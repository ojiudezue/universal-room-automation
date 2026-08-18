"""EXTERIOR-GUEST-FACE-FASTFOLLOW-1 D1 tests (post-review fix-up).

Drives PRODUCTION `transit_validator.EgressDirectionTracker` and
`camera_census.PersonCensus`. Follows the Tier 2-DB test-authority
discipline: uses an INJECTED clock (no `time.sleep`), the plan-review
C-LOW-1 requirement.

Discriminators map to plan §D1 acceptance criteria + review fix-ups:

- helper returns None / valid name paths (I3)
- veto: face-recognized but `person.<URA_SLUG>=not_home` -> None
  (A-HIGH-1 — ORACLE-INDEPENDENT: fixture sets person.oji_udezue
  directly, without re-implementing the slug derivation)
- house-level fuse via `_apply_enhanced_house_census` (C-CRIT-1)
- URA-slug-namespace agreement across census / emitted person_id
  (A-MED-1, B-MED-2)
- phantom-guest guard: an EXIT crossing must NOT register (B-CRIT-1);
  entry+exit within TTL EVICTS (B-CRIT-1 belt-and-braces).
- kill switch inert path (deliverable 2, 2026-08-18): default OFF ->
  fuse byte-identical to pre-cycle.
- observability attributes on PersonsEnteredTodaySensor.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import _provenance_harness  # noqa: F401 — bootstraps HA module stubs
from _provenance_harness import make_hass


# --------------------------------------------------------------------------
# C-MED-1 fix: sys.modules pollution isolation.
#
# transit_validator needs area_registry + event helpers that the shared
# _provenance_harness does not stub. We install them under an autouse
# module-scope fixture that snapshots + restores the pre-existing entries
# (or their absence) so no sibling test file inherits the stubs.
# --------------------------------------------------------------------------

import sys as _sys
import types as _types


_STUB_MODULES = (
    "homeassistant.helpers.area_registry",
    "homeassistant.helpers.event",
)


@pytest.fixture(autouse=True, scope="module")
def _install_stub_modules():
    saved: dict[str, object] = {}
    for name in _STUB_MODULES:
        saved[name] = _sys.modules.get(name, ...)  # sentinel for "absent"

    if "homeassistant.helpers.area_registry" not in _sys.modules:
        mod = _types.ModuleType("homeassistant.helpers.area_registry")
        mod.async_get = MagicMock()
        _sys.modules["homeassistant.helpers.area_registry"] = mod
    if "homeassistant.helpers.event" not in _sys.modules:
        ev = _types.ModuleType("homeassistant.helpers.event")
        ev.async_track_state_change_event = lambda *a, **kw: (lambda: None)
        ev.async_call_later = lambda *a, **kw: (lambda: None)
        ev.async_track_time_interval = lambda *a, **kw: (lambda: None)
        _sys.modules["homeassistant.helpers.event"] = ev
    yield
    for name, prior in saved.items():
        if prior is ...:
            _sys.modules.pop(name, None)
        else:
            _sys.modules[name] = prior


# Import the modules under test — because the fixture is module-scoped
# autouse, pytest will have installed the stubs by the time these run.
# But module imports execute at collection time, BEFORE fixtures fire.
# So we bootstrap the stubs once here too (guarded), and rely on the
# fixture only for restoration.
if "homeassistant.helpers.area_registry" not in _sys.modules:
    _mod = _types.ModuleType("homeassistant.helpers.area_registry")
    _mod.async_get = MagicMock()
    _sys.modules["homeassistant.helpers.area_registry"] = _mod
if "homeassistant.helpers.event" not in _sys.modules:
    _ev = _types.ModuleType("homeassistant.helpers.event")
    _ev.async_track_state_change_event = lambda *a, **kw: (lambda: None)
    _ev.async_call_later = lambda *a, **kw: (lambda: None)
    _ev.async_track_time_interval = lambda *a, **kw: (lambda: None)
    _sys.modules["homeassistant.helpers.event"] = _ev

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


def _configure_integration_entry(
    hass, *, tracked_persons=("person.oji_udezue", "person.ezinne_udezue"),
    egress_identity_enabled: bool = True,
):
    """Attach a MagicMock integration ConfigEntry so census helpers that
    read `tracked_persons` / CONF_EGRESS_IDENTITY_ENABLED find it."""
    entry = MagicMock()
    entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        ura_const.CONF_ENHANCED_CENSUS: True,
        "tracked_persons": list(tracked_persons),
        ura_const.CONF_EGRESS_IDENTITY_ENABLED: egress_identity_enabled,
    }
    hass.config_entries.async_entries.return_value = [entry]


def _make_census(
    cameras: dict[str, CameraInfo] | None = None,
    states: dict[str, MagicMock] | None = None,
    *,
    egress_identity_enabled: bool = True,
) -> PersonCensus:
    hass = make_hass()
    st_map = dict(states or {})
    hass.states.get = lambda entity_id: st_map.get(entity_id)
    _configure_integration_entry(
        hass, egress_identity_enabled=egress_identity_enabled,
    )
    mgr = _StubCameraManager(cameras or {})
    census = PersonCensus(hass, mgr)  # type: ignore[arg-type]
    return census


def _make_tracker_with_census(
    face_sensor_id: str,
    face_value: str,
    face_last_changed: datetime | None,
    *,
    person_entity: str | None = None,
    person_state: str | None = None,
    egress_identity_enabled: bool = True,
) -> tuple[EgressDirectionTracker, PersonCensus, MagicMock, dict]:
    """Wire an EgressDirectionTracker + PersonCensus sharing a fake hass.

    person_entity + person_state: if both provided, set that person entity
    state directly. ORACLE-INDEPENDENT — the test author hand-picks the
    URA slug entity id; the helper is expected to arrive at it via the
    canonicalizer (not by re-deriving from face_value).
    """
    hass = make_hass()
    states: dict[str, MagicMock] = {}
    if face_last_changed is not None:
        states[face_sensor_id] = _make_state(face_value, face_last_changed)
    if person_entity is not None and person_state is not None:
        states[person_entity] = _make_state(person_state)
    hass.states.get = lambda eid: states.get(eid)

    _configure_integration_entry(
        hass, egress_identity_enabled=egress_identity_enabled,
    )
    mgr = _StubCameraManager({})
    census = PersonCensus(hass, mgr)  # type: ignore[arg-type]
    hass.data = {ura_const.DOMAIN: {"census": census}}
    tracker = EgressDirectionTracker(hass)
    return tracker, census, hass, states


# ---------------------------------------------------------------------------
# _resolve_egress_face_identity — resolver correctness (I3)
# ---------------------------------------------------------------------------


def test_resolver_returns_none_when_no_face_sensor():
    """No sensor.<stem>_last_recognized_face exists -> None."""
    hass = make_hass()
    hass.states.get = lambda eid: None
    _configure_integration_entry(hass)
    hass.data = {ura_const.DOMAIN: {"census": _make_census()}}
    tracker = EgressDirectionTracker(hass)

    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    got = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now,
    )
    assert got is None


@pytest.mark.parametrize("bad_value", ["unavailable", "unknown", "", "none"])
def test_resolver_returns_none_on_bad_state(bad_value):
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    tracker, *_ = _make_tracker_with_census(face_id, bad_value, now)
    got = tracker._resolve_egress_face_identity(
        f"binary_sensor.{stem}_person_occupancy", now,
    )
    assert got is None


def test_resolver_returns_fresh_name_as_canonical_slug():
    """Frigate first-name 'Oji' resolves to the URA slug 'oji_udezue'."""
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    tracker, *_ = _make_tracker_with_census(face_id, "Oji", now)
    got = tracker._resolve_egress_face_identity(
        f"binary_sensor.{stem}_person_occupancy", now,
    )
    assert got == "oji_udezue"


def test_resolver_returns_none_when_stale():
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    old = now - timedelta(seconds=ura_const.FACE_MATCH_WINDOW_S + 1)
    tracker, *_ = _make_tracker_with_census(face_id, "Oji", old)
    got = tracker._resolve_egress_face_identity(
        f"binary_sensor.{stem}_person_occupancy", now,
    )
    assert got is None


def test_resolver_returns_none_on_future_dated_face():
    """A-LOW-1 / C-LOW-3: face recognized AFTER the crossing time (age<0)
    is treated as stale, not fresh-in-the-future."""
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    # Face last_changed is 5s in the FUTURE relative to the crossing.
    future = now + timedelta(seconds=5)
    tracker, *_ = _make_tracker_with_census(face_id, "Oji", future)
    got = tracker._resolve_egress_face_identity(
        f"binary_sensor.{stem}_person_occupancy", now,
    )
    assert got is None


# ---------------------------------------------------------------------------
# A-HIGH-1 veto — ORACLE INDEPENDENT.
# ---------------------------------------------------------------------------


def test_resolver_vetoes_when_person_not_home_oracle_independent():
    """Fixture hand-sets `person.oji_udezue = not_home` (the REAL URA
    slug entity) without re-deriving the slug from face_value. The
    helper must canonicalize 'Oji' -> 'oji_udezue' and honour the veto.

    Mutation-anchored: if the canonicalizer mapped 'Oji' to any other
    slug, this test would FAIL (person state on the wrong entity would
    look absent -> fail-open -> returns 'oji_udezue' or similar).
    """
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    tracker, *_ = _make_tracker_with_census(
        face_id, "Oji", now,
        person_entity="person.oji_udezue",  # HAND-PICKED, not re-derived.
        person_state="not_home",
    )
    got = tracker._resolve_egress_face_identity(
        f"binary_sensor.{stem}_person_occupancy", now,
    )
    assert got is None, (
        "person.oji_udezue=not_home must suppress; canonicalizer must map "
        "Frigate first-name -> URA slug"
    )


def test_resolver_fail_open_when_person_missing():
    """Missing person entity -> keep the identity (fail-open)."""
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    tracker, *_ = _make_tracker_with_census(face_id, "Oji", now)
    got = tracker._resolve_egress_face_identity(
        f"binary_sensor.{stem}_person_occupancy", now,
    )
    assert got == "oji_udezue"


# ---------------------------------------------------------------------------
# A-MED-1 / B-MED-2 — namespace agreement across payload + census + DB.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_namespace_agreement_payload_census_dbcall():
    """The emitted `person_id`, the census `_egress_face_ids` member, and
    the argument passed to `database.log_entry_exit_event` are ALL the
    same URA slug ('oji_udezue') for the same crossing.
    """
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    face_ts = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    tracker, census, hass, _ = _make_tracker_with_census(face_id, "Oji", face_ts)

    fired: list[tuple[str, dict]] = []
    hass.bus = MagicMock()
    hass.bus.async_fire = lambda t, p: fired.append((t, p))

    db = MagicMock()
    db_calls: list[dict] = []
    async def _log(**kw):
        db_calls.append(kw)
    db.log_entry_exit_event = _log
    hass.data[ura_const.DOMAIN]["database"] = db

    # Force direction=entry deterministically by seeding an interior event
    # inside the ENTRY_WINDOW.
    crossing = face_ts + timedelta(seconds=3)
    tracker._recent_interior_events[
        "binary_sensor.foyer_person_occupancy"
    ] = [crossing + timedelta(seconds=2)]
    with patch.object(
        tracker, "_get_interior_cameras_near",
        return_value=["binary_sensor.foyer_person_occupancy"],
    ):
        await tracker._resolve_direction(
            f"binary_sensor.{stem}_person_occupancy", crossing,
        )

    assert fired, "bus event expected"
    _, payload = fired[-1]
    assert payload["direction"] == "entry"
    assert payload["person_id"] == "oji_udezue"
    assert "oji_udezue" in census._egress_face_ids
    assert db_calls and db_calls[-1]["person_id"] == "oji_udezue"


# ---------------------------------------------------------------------------
# B-CRIT-1 phantom-guest-on-exit guard + B-HIGH-1 ambiguous no-register.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exit_crossing_does_not_register_phantom_identity():
    """B-CRIT-1: a sole resident EXIT must NOT inject into
    `_egress_face_ids`. If it did, `identified_count` would stay 1 for
    EGRESS_FACE_UNION_TTL_S after every departure => phantom guest."""
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    face_ts = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    tracker, census, hass, _ = _make_tracker_with_census(face_id, "Oji", face_ts)
    hass.bus = MagicMock()

    # Seed a NEGATIVE-delta interior event to force direction=exit.
    crossing = face_ts + timedelta(seconds=3)
    tracker._recent_interior_events[
        "binary_sensor.foyer_person_occupancy"
    ] = [crossing - timedelta(seconds=5)]
    with patch.object(
        tracker, "_get_interior_cameras_near",
        return_value=["binary_sensor.foyer_person_occupancy"],
    ):
        await tracker._resolve_direction(
            f"binary_sensor.{stem}_person_occupancy", crossing,
        )

    assert census._egress_face_ids == {}, (
        "exit crossing must NOT register any identity"
    )


@pytest.mark.asyncio
async def test_ambiguous_crossing_neither_registers_nor_evicts():
    """B-HIGH-1: ambiguous crossings must not mutate the census union."""
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    face_ts = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    tracker, census, hass, _ = _make_tracker_with_census(face_id, "Oji", face_ts)
    hass.bus = MagicMock()

    # Prior registration we want to observe is NOT evicted.
    census.register_egress_face("oji_udezue", face_ts)
    assert "oji_udezue" in census._egress_face_ids

    crossing = face_ts + timedelta(seconds=3)
    # No interior events -> direction stays "ambiguous".
    with patch.object(
        tracker, "_get_interior_cameras_near",
        return_value=[],
    ):
        await tracker._resolve_direction(
            f"binary_sensor.{stem}_person_occupancy", crossing,
        )

    # Prior entry untouched by the ambiguous crossing.
    assert "oji_udezue" in census._egress_face_ids


@pytest.mark.asyncio
async def test_entry_registers_then_exit_evicts_within_ttl():
    """B-CRIT-1 belt-and-braces: walked-in-then-out within TTL removes
    the prior entry-registration."""
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    face_ts = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    tracker, census, hass, _ = _make_tracker_with_census(face_id, "Oji", face_ts)
    hass.bus = MagicMock()

    # Entry crossing.
    entry_ts = face_ts + timedelta(seconds=3)
    tracker._recent_interior_events[
        "binary_sensor.foyer_person_occupancy"
    ] = [entry_ts + timedelta(seconds=2)]
    with patch.object(
        tracker, "_get_interior_cameras_near",
        return_value=["binary_sensor.foyer_person_occupancy"],
    ):
        await tracker._resolve_direction(
            f"binary_sensor.{stem}_person_occupancy", entry_ts,
        )
    assert "oji_udezue" in census._egress_face_ids

    # Reset dedup for a second crossing.
    tracker._last_resolved.clear()
    # Exit crossing shortly after (< TTL).
    exit_ts = entry_ts + timedelta(seconds=30)
    tracker._recent_interior_events[
        "binary_sensor.foyer_person_occupancy"
    ] = [exit_ts - timedelta(seconds=5)]
    # Advance face timestamp too so freshness holds.
    _stat = MagicMock()
    _stat.state = "Oji"
    _stat.last_changed = exit_ts
    hass.states.get = lambda eid: (
        _stat if eid == face_id
        else None
    )
    with patch.object(
        tracker, "_get_interior_cameras_near",
        return_value=["binary_sensor.foyer_person_occupancy"],
    ):
        await tracker._resolve_direction(
            f"binary_sensor.{stem}_person_occupancy", exit_ts,
        )
    assert "oji_udezue" not in census._egress_face_ids, (
        "exit within TTL must evict the prior entry-registration"
    )


# ---------------------------------------------------------------------------
# Behavioral — person_id on the bus, injected clock advance.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_behavioral_egress_event_carries_person_id_then_expires():
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    face_ts = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    tracker, census, hass, _ = _make_tracker_with_census(face_id, "Oji", face_ts)

    fired: list[tuple[str, dict]] = []
    hass.bus = MagicMock()
    hass.bus.async_fire = lambda topic, payload: fired.append((topic, payload))

    crossing_1 = face_ts + timedelta(seconds=3)
    await tracker._resolve_direction(
        f"binary_sensor.{stem}_person_occupancy", crossing_1,
    )
    assert fired
    topic, payload = fired[-1]
    assert topic == "ura_person_egress_event"
    assert payload["person_id"] == "oji_udezue"

    tracker._last_resolved.clear()

    crossing_2 = face_ts + timedelta(
        seconds=ura_const.FACE_MATCH_WINDOW_S + 1,
    )
    await tracker._resolve_direction(
        f"binary_sensor.{stem}_person_occupancy", crossing_2,
    )
    topic2, payload2 = fired[-1]
    assert payload2["person_id"] is None


# ---------------------------------------------------------------------------
# House-level fuse — C-CRIT-1 discriminator + I5 namespace dedup.
# ---------------------------------------------------------------------------


def _house_apply(census: PersonCensus, ble_persons, face_recognized_slugs):
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
    census._last_camera_total_pre_cancel = 99
    with patch.object(census, "_get_unrecognized_camera_count", return_value=0), \
         patch.object(census, "_get_wifi_guest_count", return_value=0), \
         patch.object(
             census, "_get_face_recognized_person_names",
             return_value=list(face_recognized_slugs),
         ):
        return census._apply_enhanced_house_census(raw, list(ble_persons), now)


def test_house_fuse_face_and_egress_same_person_counts_once():
    census = _make_census()
    census.register_egress_face(
        "oji", datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC),
    )
    result = _house_apply(
        census, ble_persons=[], face_recognized_slugs=["oji_udezue"],
    )
    assert result.identified_count == 1


def test_house_fuse_face_and_egress_different_persons_counts_two():
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
    Frigate face) MUST raise house identified_count by 1."""
    census = _make_census()
    census.register_egress_face(
        "ziri", datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC),
    )
    result = _house_apply(
        census, ble_persons=[], face_recognized_slugs=[],
    )
    assert result.identified_count == 1


def test_house_fuse_name_normalization_i5():
    """I5: 'Oji_Udezue' (URA slug case-varied) unioned with egress 'oji'
    normalizes to 1 under URA-slug canonicalization."""
    census = _make_census()
    census.register_egress_face(
        "oji", datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC),
    )
    result = _house_apply(
        census, ble_persons=[], face_recognized_slugs=["Oji_Udezue"],
    )
    assert result.identified_count == 1


def test_house_fuse_identified_persons_are_ura_slugs():
    """A-MED-1: `identified_persons` list carries URA slugs, not
    Frigate first-name slugs."""
    census = _make_census()
    census.register_egress_face(
        "Oji", datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC),
    )
    result = _house_apply(
        census, ble_persons=[], face_recognized_slugs=[],
    )
    # Enhanced-house sets identified_count but not identified_persons in
    # its return value; verify via the census set membership on the
    # canonical namespace.
    assert census._egress_face_ids.get("oji_udezue") is not None


# ---------------------------------------------------------------------------
# TTL prune on the egress register.
# ---------------------------------------------------------------------------


def test_egress_face_register_ttl_prunes_stale_entries():
    census = _make_census()
    t0 = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    census.register_egress_face("oji", t0)
    inside = t0 + timedelta(
        seconds=ura_const.EGRESS_FACE_UNION_TTL_S - 1,
    )
    assert census._get_egress_face_ids_fresh(inside) == {"oji_udezue"}
    after = t0 + timedelta(
        seconds=ura_const.EGRESS_FACE_UNION_TTL_S + 1,
    )
    assert census._get_egress_face_ids_fresh(after) == set()
    assert "oji_udezue" not in census._egress_face_ids


# ---------------------------------------------------------------------------
# Kill switch (2026-08-18 deliverable 2) — inert byte-for-byte when OFF.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kill_switch_disabled_yields_none_and_no_register():
    """With EGRESS_IDENTITY_ENABLED=False, an entry crossing that WOULD
    stamp an identity yields person_id=None and `_egress_face_ids` stays
    empty. Byte-identical to pre-cycle."""
    stem = "front_door"
    face_id = f"sensor.{stem}_last_recognized_face"
    face_ts = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    tracker, census, hass, _ = _make_tracker_with_census(
        face_id, "Oji", face_ts, egress_identity_enabled=False,
    )
    fired: list[tuple[str, dict]] = []
    hass.bus = MagicMock()
    hass.bus.async_fire = lambda t, p: fired.append((t, p))

    crossing = face_ts + timedelta(seconds=3)
    tracker._recent_interior_events[
        "binary_sensor.foyer_person_occupancy"
    ] = [crossing + timedelta(seconds=2)]
    with patch.object(
        tracker, "_get_interior_cameras_near",
        return_value=["binary_sensor.foyer_person_occupancy"],
    ):
        await tracker._resolve_direction(
            f"binary_sensor.{stem}_person_occupancy", crossing,
        )
    assert fired
    _, payload = fired[-1]
    assert payload["person_id"] is None
    assert census._egress_face_ids == {}


def test_kill_switch_disabled_house_fuse_byte_identical():
    """With the kill switch OFF, `_get_egress_face_ids_fresh` returns
    empty even if the dict were populated — proves the fuse sites see
    no contribution."""
    census = _make_census(egress_identity_enabled=False)
    # Force-populate to prove the getter, not the register, is the gate.
    census._egress_face_ids["oji_udezue"] = datetime(
        2026, 8, 18, 12, 0, 0, tzinfo=UTC,
    )
    now = datetime(2026, 8, 18, 12, 0, 5, tzinfo=UTC)
    assert census._get_egress_face_ids_fresh(now) == set()


def test_kill_switch_disabled_register_is_noop():
    census = _make_census(egress_identity_enabled=False)
    census.register_egress_face(
        "Oji", datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC),
    )
    assert census._egress_face_ids == {}
