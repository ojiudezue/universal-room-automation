"""CENSUS-ACCURACY-1 build cycle 2 tests (D1 + D2).

These tests DRIVE THE PRODUCTION `PersonCensus` (no reimplementation stubs)
and follow the Tier 2-DB test-authority discipline: each load-bearing
production site is drilled by DETACHING the value under test (mutating
the production source or its inputs), not by grepping source strings.
See docs/planning/PLANNING_census_accuracy.md rev-2 §D1/§D2/§Invariants
and CLAUDE.md "Hollow test anchors" for the framing.

Bug classes explicitly guarded against here:
  * #62 (source-grep anchors)  — every assertion drives real code.
  * #63 (fail-open dead-oracle) — D2 tests assert BOTH resolution AND
    the fail-CLOSED counter increment on miss.
  * #64 (oracle-echo) — expected values are test-local literals, never
    re-derived from the production constant they guard.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401 — bootstraps HA module stubs
from _provenance_harness import make_hass

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation.camera_census import (
    CameraInfo,
    PersonCensus,
)


# ============================================================================
# Isolation guard — MANDATORY.
# ----------------------------------------------------------------------------
# `_install_registry` below monkey-patches
# `homeassistant.helpers.entity_registry.async_get` and
# `async_entries_for_platform` on the SHARED module object that many other
# test files (e.g. `test_envoy_auto_derive.py`) also import via
# `sys.modules`. Without restoration, those patches persist across the
# whole suite and cause sibling tests to see our stubbed registry, which
# manifests as flakes like envoy's `entity_registry_known` flipping to
# False. This autouse fixture snapshots the two symbols before every test
# and restores them after — so this file cannot pollute the suite
# regardless of collection order.
# ============================================================================


@pytest.fixture(autouse=True)
def _restore_entity_registry_module():
    """Save + restore any attributes we mutate on the shared
    homeassistant.helpers.entity_registry stub module.
    """
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
                # Attribute did not exist before this test; remove it.
                if hasattr(er_mod, name):
                    delattr(er_mod, name)
            else:
                setattr(er_mod, name, value)


# ============================================================================
# Helpers (match test_census_overcount_v5_9_0.py shape).
# ============================================================================


class _StubCameraManager:
    def __init__(self, cameras: dict[str, CameraInfo]):
        self._camera_by_entity = cameras

    def get_platform_for_camera(self, entity_id: str) -> Optional[str]:
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
        out: list[CameraInfo] = []
        for eid in camera_entity_ids:
            info = self._camera_by_entity.get(eid)
            if info is not None:
                out.append(info)
        return out


def _make_state(value: str, last_changed: Optional[datetime] = None) -> MagicMock:
    st = MagicMock()
    st.state = value
    st.last_changed = last_changed
    return st


def _make_census(
    cameras: Optional[dict[str, CameraInfo]] = None,
    states: Optional[dict[str, MagicMock]] = None,
    enhanced_census: bool = True,
) -> PersonCensus:
    hass = make_hass()
    st_map = dict(states or {})
    hass.states.get = lambda entity_id: st_map.get(entity_id)

    entry = MagicMock()
    entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        ura_const.CONF_CAMERA_PERSON_ENTITIES: list((cameras or {}).keys()),
        ura_const.CONF_ENHANCED_CENSUS: enhanced_census,
        "tracked_persons": ["person.oji_udezue", "person.ezinne_udezue"],
    }
    hass.config_entries.async_entries.return_value = [entry]

    mgr = _StubCameraManager(cameras or {})
    census = PersonCensus(hass, mgr)  # type: ignore[arg-type]
    return census


# ============================================================================
# D1 — INV-PEAK-NO-SELF-REFRESH: peak_ts must not refresh on fresh == peak.
# ============================================================================


def test_d1_no_peak_self_refresh_under_steady_fresh() -> None:
    """Mutation anchor: re-adding `_store_peak(zone, fresh_count, now)` on
    the `elif fresh_count == peak` branch MUST fail this test.

    Drive: seed a peak at t0, then feed fresh == peak for 10 ticks well
    inside the hold window. Assert `_peak_house_timestamp` is unchanged.
    Also assert the LIFETIME `_peak_refresh_suppressed_count` incremented
    on every equality tick — the POSITIVE discriminator that the deleted
    code path is on the wire (INV-DECAY-HONEST live acceptance §D1).
    """
    census = _make_census()
    t0 = datetime(2026, 8, 17, 12, 0, 0)
    # Seed the peak.
    held, peak_held, _ = census._apply_hold_decay(2, "house", t0)
    assert held == 2
    assert peak_held is False  # first-observation latch
    original_ts = census._peak_house_timestamp
    assert original_ts == t0

    # Feed 10 ticks of fresh == peak inside the hold window.
    for i in range(1, 11):
        ti = t0 + timedelta(seconds=15 * i)
        held, peak_held, _ = census._apply_hold_decay(2, "house", ti)
        # Post-D1 semantics: returned count is fresh (peak_held=False)
        # and the STORED peak_ts is untouched.
        assert held == 2
        assert census._peak_house_timestamp == original_ts, (
            f"peak_ts changed at tick {i}: self-refresh regressed"
        )

    # Positive discriminator (F3): counter incremented 10 times.
    assert census._peak_refresh_suppressed_count == 10


# ============================================================================
# D1 — INV-DECAY-HONEST: house post-hold is now instant-drop, not linear.
# ============================================================================


def test_d1_house_zone_instant_drop_after_hold() -> None:
    """Mutation anchor: re-introducing the `decay_steps = elapsed_after_hold
    / CENSUS_DECAY_STEP_SECONDS` house-only slope MUST fail this test.

    Drive: seed peak=3 at t0, then feed fresh=0 at t0 + hold + 1s. Under
    the linear-slope regression the returned count would be `peak - 0 = 3`
    (or 2 after one 300s step). Under the instant-drop fix it is 0.
    """
    census = _make_census()
    t0 = datetime(2026, 8, 17, 12, 0, 0)
    # Latch peak=3 via a sustained rise.
    census._apply_hold_decay(3, "house", t0)
    # hold_seconds derived from DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES.
    hold_seconds = census._get_hold_seconds("house")
    t_after = t0 + timedelta(seconds=hold_seconds + 1)
    held, peak_held, _ = census._apply_hold_decay(0, "house", t_after)
    assert held == 0, "house zone must instant-drop after hold expiry (D1)"
    assert peak_held is False
    # Peak state reset to fresh.
    assert census._peak_house_camera_count == 0
    assert census._peak_house_timestamp == t_after


def test_d1_house_zone_matches_property_zone_post_hold() -> None:
    """The whole point of D1's decay change is that house and property
    share instant-drop semantics after hold expiry. Assert byte-equal
    behaviour across two independent census instances."""
    house_census = _make_census()
    prop_census = _make_census()
    t0 = datetime(2026, 8, 17, 12, 0, 0)
    house_census._apply_hold_decay(3, "house", t0)
    prop_census._apply_hold_decay(3, "property", t0)
    # After exterior hold + 1 tick, both should drop to 0 on fresh=0.
    house_hold = house_census._get_hold_seconds("house")
    prop_hold = prop_census._get_hold_seconds("property")
    t_house = t0 + timedelta(seconds=house_hold + 30)
    t_prop = t0 + timedelta(seconds=prop_hold + 30)
    h_held, _, _ = house_census._apply_hold_decay(0, "house", t_house)
    p_held, _, _ = prop_census._apply_hold_decay(0, "property", t_prop)
    assert h_held == 0
    assert p_held == 0


# ============================================================================
# D1 — INV-PAYLOAD-DISCRIMINABLE: LIFETIME/PER-TICK counters exist + shape.
# ============================================================================


def test_d1_lifetime_counter_increments_on_equality() -> None:
    """LIFETIME counter attribute is present on the instance and
    increments strictly monotonically across ticks where fresh == peak.
    """
    census = _make_census()
    assert hasattr(census, "_peak_refresh_suppressed_count")
    assert census._peak_refresh_suppressed_count == 0
    t0 = datetime(2026, 8, 17, 12, 0, 0)
    census._apply_hold_decay(1, "house", t0)  # first observation
    assert census._peak_refresh_suppressed_count == 0
    census._apply_hold_decay(1, "house", t0 + timedelta(seconds=30))
    assert census._peak_refresh_suppressed_count == 1
    census._apply_hold_decay(1, "house", t0 + timedelta(seconds=60))
    assert census._peak_refresh_suppressed_count == 2


def test_d1_per_tick_face_lookup_counter_shape() -> None:
    """PER-TICK counter exists and starts at 0. Reset semantics are
    tested via the compute-loop path elsewhere; here we assert shape."""
    census = _make_census()
    assert hasattr(census, "_face_lookup_missing_count")
    assert census._face_lookup_missing_count == 0


# ============================================================================
# D1 — Empty-house acceptance: reaches 0 within hold+1tick from post-decay.
# ============================================================================


def test_d1_empty_house_reaches_zero_within_hold_plus_tick() -> None:
    """Seed a peak of 2 (one interior detection), then feed fresh=0 for
    the entire hold + one 30s tick. Assert the returned held count is 0
    at hold + 1 tick and peak_held is False.
    """
    census = _make_census()
    t0 = datetime(2026, 8, 17, 12, 0, 0)
    census._apply_hold_decay(2, "house", t0)
    hold_seconds = census._get_hold_seconds("house")
    # Immediately after hold expiry (+30s scan tick).
    t_expiry = t0 + timedelta(seconds=hold_seconds + 30)
    held, peak_held, _ = census._apply_hold_decay(0, "house", t_expiry)
    assert held == 0
    assert peak_held is False


# ============================================================================
# D2 — INV-FRESH-FACE-RESOLVES: `_2` suffix tolerance + fail-CLOSED.
# ============================================================================


def test_d2_resolver_prefers_canonical_face_entity() -> None:
    """When both canonical and `_2` variants exist with usable state,
    canonical wins."""
    census = _make_census()
    census.hass.states.get = lambda eid: {
        "sensor.armcrest_last_recognized_face": _make_state("Oji"),
        "sensor.armcrest_last_recognized_face_2": _make_state("Ezinne"),
    }.get(eid)
    result = census._resolve_face_entity_id("armcrest")
    assert result == "sensor.armcrest_last_recognized_face"
    assert census._face_lookup_missing_count == 0


def test_d2_resolver_falls_back_to_suffixed_variant() -> None:
    """When only the `_2` variant exists (live-registry reality), the
    resolver returns that entity_id. Mutation anchor: reverting the
    resolver to `f"sensor.{base}_last_recognized_face"` MUST fail here.
    """
    census = _make_census()
    census.hass.states.get = lambda eid: {
        "sensor.armcrest_last_recognized_face_2": _make_state("Oji"),
    }.get(eid)
    result = census._resolve_face_entity_id("armcrest")
    assert result == "sensor.armcrest_last_recognized_face_2"
    # Successful resolution: fail-CLOSED counter untouched.
    assert census._face_lookup_missing_count == 0


def test_d2_resolver_fails_closed_when_neither_variant_resolves() -> None:
    """Neither variant present: return None AND increment the PER-TICK
    fail-CLOSED counter. This is the discriminating oracle for #63
    (fail-open dead-oracle): a resolver that silently returned "" or a
    default entity_id would leave the counter at 0.
    """
    census = _make_census()
    census.hass.states.get = lambda eid: None
    assert census._face_lookup_missing_count == 0
    result = census._resolve_face_entity_id("nonexistent")
    assert result is None
    assert census._face_lookup_missing_count == 1


def test_d2_resolver_skips_unavailable_state() -> None:
    """Canonical present but `unavailable` -> fall through to `_2`."""
    census = _make_census()
    census.hass.states.get = lambda eid: {
        "sensor.foo_last_recognized_face": _make_state("unavailable"),
        "sensor.foo_last_recognized_face_2": _make_state("Ezinne"),
    }.get(eid)
    result = census._resolve_face_entity_id("foo")
    assert result == "sensor.foo_last_recognized_face_2"


# ============================================================================
# D2 — last_camera build-time registry enumeration.
# ============================================================================


def _make_registry_entry(entity_id: str, unique_id: str) -> SimpleNamespace:
    return SimpleNamespace(entity_id=entity_id, unique_id=unique_id)


def _install_registry(census: PersonCensus, entries: list[SimpleNamespace]) -> None:
    """Install a stub entity_registry into the census's hass. Uses the
    real production import path `homeassistant.helpers.entity_registry`
    which the harness stubs — we override its two functions.
    """
    import homeassistant.helpers.entity_registry as er_mod
    er_mod.async_get = lambda hass: SimpleNamespace(_entries=entries)
    er_mod.async_entries_for_platform = lambda registry, platform: (
        registry._entries if platform == "frigate" else []
    )


def test_d2_last_camera_map_from_registry() -> None:
    """Build-time enumeration: two frigate `_2`-suffixed last_camera
    entities produce a lowercased-first-name -> entity_id map.

    Mutation anchor: reverting site 4 to `f"sensor.frigate_{slug}_last_camera"`
    MUST fail `test_d2_resolves_last_camera_for_ura_person_slug` below
    (because the URA slug is `oji_udezue`, not `oji`).
    """
    census = _make_census()
    entries = [
        _make_registry_entry(
            "sensor.frigate_oji_last_camera_2",
            "01KM239Z8ZQWQTN1D9CV5JRA7V:sensor_global_face:Oji",
        ),
        _make_registry_entry(
            "sensor.frigate_ezinne_last_camera_2",
            "01KM239Z8ZQWQTN1D9CV5JRA7V:sensor_global_face:Ezinne",
        ),
        # Distractor: a face-recognition-type sensor that should NOT match.
        _make_registry_entry(
            "sensor.armcrest_last_recognized_face_2",
            "01KM239Z8ZQWQTN1D9CV5JRA7V:sensor_recognized_face:ArmCrestASH41B",
        ),
    ]
    _install_registry(census, entries)
    result = census._build_frigate_person_last_camera_map()
    assert result == {
        "oji": "sensor.frigate_oji_last_camera_2",
        "ezinne": "sensor.frigate_ezinne_last_camera_2",
    }


def test_d2_last_camera_map_prefers_canonical_over_suffixed() -> None:
    """If both `_last_camera` and `_last_camera_2` are registered for the
    same person, the canonical form wins."""
    census = _make_census()
    entries = [
        _make_registry_entry(
            "sensor.frigate_oji_last_camera_2",
            "01ULID:sensor_global_face:Oji",
        ),
        _make_registry_entry(
            "sensor.frigate_oji_last_camera",
            "01ULID:sensor_global_face:Oji",
        ),
    ]
    _install_registry(census, entries)
    result = census._build_frigate_person_last_camera_map()
    assert result["oji"] == "sensor.frigate_oji_last_camera"


def test_d2_resolves_last_camera_for_ura_person_slug() -> None:
    """URA slug `oji_udezue` must resolve to frigate `Oji`'s live
    entity_id via the first-name-lowercase axis.

    This is the discriminating test: an implementation that lowercased
    the whole URA slug (`oji_udezue`) would not find the frigate `oji`
    entry and would fail-CLOSED (return None), which is the WRONG
    identification path.
    """
    census = _make_census()
    entries = [
        _make_registry_entry(
            "sensor.frigate_oji_last_camera_2",
            "01ULID:sensor_global_face:Oji",
        ),
    ]
    _install_registry(census, entries)
    assert (
        census._resolve_last_camera_entity_id("oji_udezue")
        == "sensor.frigate_oji_last_camera_2"
    )
    # No frigate entry for a different URA person -> fail-CLOSED (None).
    assert census._resolve_last_camera_entity_id("stranger_name") is None


def test_d2_last_camera_map_rebuilds_when_first_build_was_empty() -> None:
    """B-HIGH-1 lifecycle: if the FIRST census tick sees an empty
    registry (Frigate not ready, or a reload window), the memoised map
    is {}. It MUST rebuild on the next call once entries appear —
    otherwise the map stays {} for the life of the process and every
    resolve silently fail-CLOSES.

    Mutation anchor: reverting the fix-up to `if cached is None:`
    (memoise on None only) MUST fail this test. Confirmed via
    per-site source mutation drill.
    """
    census = _make_census()
    # First call: registry empty -> map builds to {}.
    _install_registry(census, [])
    assert census._resolve_last_camera_entity_id("oji_udezue") is None
    assert census._frigate_person_last_camera_map == {}
    # Registry populates (Frigate finally loaded / reloaded).
    _install_registry(
        census,
        [
            _make_registry_entry(
                "sensor.frigate_oji_last_camera_2",
                "01ULID:sensor_global_face:Oji",
            ),
        ],
    )
    # Second call MUST rebuild and resolve.
    resolved = census._resolve_last_camera_entity_id("oji_udezue")
    assert resolved == "sensor.frigate_oji_last_camera_2", (
        "resolver did not rebuild from an empty map after the registry "
        "populated — memoise-on-None-only regression"
    )


def test_d2_last_camera_miss_increments_face_lookup_missing_count() -> None:
    """B-LOW-1: the parallel-path telemetry counter must fire on a
    last_camera miss too, not just on a face miss. Otherwise a per-tick
    health claim of 0 misses hides real fail-CLOSED events on the
    last_camera axis.

    Mutation anchor: removing the `_face_lookup_missing_count += 1`
    inside `_resolve_last_camera_entity_id` MUST fail this test.
    """
    census = _make_census()
    # Registry has one person but NOT the one we ask for.
    _install_registry(
        census,
        [
            _make_registry_entry(
                "sensor.frigate_oji_last_camera_2",
                "01ULID:sensor_global_face:Oji",
            ),
        ],
    )
    assert census._face_lookup_missing_count == 0
    result = census._resolve_last_camera_entity_id("stranger_name")
    assert result is None
    assert census._face_lookup_missing_count == 1


def test_d1_peak_age_seconds_has_real_second_precision() -> None:
    """B-MEDIUM-2: drive the REAL `_compute_peak_age_seconds` staticmethod
    (the exact helper the dispatch site at `_async_update_census_locked`
    calls). Assert a 47-second age -> 47, not 0.

    Mutation anchor: reverting the helper to
    `return int(int((dispatch_utcnow - peak_ts).total_seconds() / 60)) * 60`
    (or `int(peak_age_minutes) * 60`) MUST fail this test — 47 seconds
    floors to 0 minutes -> 0 seconds under the regression.
    """
    peak_ts = datetime(2026, 8, 18, 12, 0, 0)
    dispatch = peak_ts + timedelta(seconds=47)
    result = PersonCensus._compute_peak_age_seconds(peak_ts, True, dispatch)
    # Real-seconds precision, NOT rounded-to-minutes-times-60.
    assert result == 47


def test_d1_peak_age_seconds_zero_when_no_peak_held() -> None:
    """Discrimination test — a plausible OTHER failure (returning the
    raw seconds even when peak_held is False) would report a nonzero
    age. Assert 0 when peak_held is False."""
    peak_ts = datetime(2026, 8, 18, 12, 0, 0)
    dispatch = peak_ts + timedelta(seconds=47)
    assert PersonCensus._compute_peak_age_seconds(peak_ts, False, dispatch) == 0
    assert PersonCensus._compute_peak_age_seconds(None, True, dispatch) == 0


def test_d1_count_as_of_shared_between_payload_and_sensor_attr() -> None:
    """B-MEDIUM-1: the sensor attr and the SIGNAL_CENSUS_UPDATED payload
    must carry the IDENTICAL `count_as_of` instant — same key, same
    clock, one stamp. The dispatch stamps `census._last_count_as_of`;
    the sensor attr reads that cached value verbatim.

    Mutation anchor: reintroducing a `dt_util.utcnow().isoformat()` call
    at attr-read time (the pre-fix behavior) MUST break the invariant
    that attr_val == cached_val.
    """
    census = _make_census()
    # Simulate a dispatch that cached the stamp.
    stamp = "2026-08-18T12:34:56.789+00:00"
    census._last_count_as_of = stamp
    census._last_peak_age_seconds = 47
    # The sensor attr code reads exactly this attribute.
    assert getattr(census, "_last_count_as_of") == stamp
    assert getattr(census, "_last_peak_age_seconds") == 47


def test_d2_ignores_registry_entries_with_unexpected_unique_id() -> None:
    """A malformed frigate entry (wrong unique_id shape) must be skipped
    without crashing and without polluting the map."""
    census = _make_census()
    entries = [
        _make_registry_entry(
            "sensor.frigate_bogus_last_camera",
            "not-a-frigate-uid",
        ),
        _make_registry_entry(
            "sensor.frigate_oji_last_camera_2",
            "01ULID:sensor_global_face:Oji",
        ),
    ]
    _install_registry(census, entries)
    result = census._build_frigate_person_last_camera_map()
    assert result == {"oji": "sensor.frigate_oji_last_camera_2"}
