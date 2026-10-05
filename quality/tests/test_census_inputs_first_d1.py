"""PLANNING_census_inputs_first D1 (R2.2 / R3.* / R4.*) — build tests.

Drives production modules (no local re-impl). Covers:
  * `_extract_camera_stem` composition (`_PERSON_SUFFIXES + (_PERSON_COUNT_SUFFIX,)`)
    — strips `_person_occupancy`, `_person_count`, `_2`, `_person_count_2`.
  * `DOOR_STEM_DEDUP_S` knob replaces the historical 5 s inline literal.
  * `_last_resolved` prune horizon >= DOOR_STEM_DEDUP_S + ENTRY_WINDOW_SECONDS.
  * Door-group dedup (set) vs per-stem (unset — today's behaviour).
  * `_get_interior_cameras_near` fallback = full interior list when
    `CONF_DOOR_INTERIOR_NEIGHBOURS` unset (R3.1 CRITICAL-1).
  * Newest-first exit-bias in direction loop (R2.2 item 4(d)).
  * `peak_person_count` sampler window + door-group MAX (not sum).
  * `log_entry_exit_event` accepts `peak_person_count` kwarg.
  * Schema: fresh CREATE AND ALTER both land `peak_person_count`.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

import sys as _sys
import types as _types

# transit_validator depends on these HA event helpers; stub if missing.
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

from custom_components.universal_room_automation.const import (
    DOOR_STEM_DEDUP_S,
    EGRESS_ENTRY_WINDOW_SECONDS,
    EGRESS_EXIT_WINDOW_SECONDS,
)
from custom_components.universal_room_automation.camera_census import (
    CameraIntegrationManager,
)
from custom_components.universal_room_automation.transit_validator import (
    EgressDirectionTracker,
)


# ---------------------------------------------------------------------------
# _extract_camera_stem — composition over _PERSON_SUFFIXES + _PERSON_COUNT_SUFFIX
# ---------------------------------------------------------------------------

def test_extract_camera_stem_strips_person_occupancy():
    assert CameraIntegrationManager._extract_camera_stem(
        "binary_sensor.foo_person_occupancy"
    ) == "foo"


def test_extract_camera_stem_strips_person_occupancy_2_suffix():
    """R3.3 caller #1 — Frigate-2 `_2` legs no longer return None."""
    assert CameraIntegrationManager._extract_camera_stem(
        "binary_sensor.foo_person_occupancy_2"
    ) == "foo"


def test_extract_camera_stem_strips_plain_person_count():
    """R4.1 (N-HIGH-1) regression — `_person_count` must be stripped."""
    assert CameraIntegrationManager._extract_camera_stem(
        "sensor.foo_person_count"
    ) == "foo"


def test_extract_camera_stem_strips_person_count_2():
    assert CameraIntegrationManager._extract_camera_stem(
        "sensor.foo_person_count_2"
    ) == "foo"


def test_extract_camera_stem_strips_person_detected():
    assert CameraIntegrationManager._extract_camera_stem(
        "binary_sensor.foo_person_detected"
    ) == "foo"


def test_extract_camera_stem_unmatched_returns_none():
    assert CameraIntegrationManager._extract_camera_stem(
        "sensor.foo_total_power"
    ) is None


# ---------------------------------------------------------------------------
# EgressDirectionTracker fixtures
# ---------------------------------------------------------------------------

def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_tracker(door_groups=None, neighbours=None, interior=None):
    hass = make_hass()
    tracker = EgressDirectionTracker(hass)
    tracker._interior_entities = list(interior or [])
    tracker._door_group_by_stem = dict(door_groups or {})
    tracker._interior_neighbours_by_group = dict(neighbours or {})
    return tracker, hass


# ---------------------------------------------------------------------------
# DOOR_STEM_DEDUP_S knob (R2.2 item 2 / R3.9)
# ---------------------------------------------------------------------------

def test_door_stem_dedup_s_default_is_30s():
    """Replaces inline 5 s literal."""
    assert DOOR_STEM_DEDUP_S == 30


def test_dedup_covers_person_occupancy_2_sibling_within_window():
    """R3.3 caller #1 — before the fix, `_2` legs returned stem=None → dedup
    skipped. Post-fix: two legs on the same stem inside the window → the
    second resolve is skipped by the direction-keyed dedup head."""
    tracker, hass = _make_tracker()
    hass.data["custom_components.universal_room_automation"] = {}

    database = MagicMock()
    database.log_entry_exit_event = AsyncMock()
    hass.data = {}
    from custom_components.universal_room_automation.const import DOMAIN
    hass.data[DOMAIN] = {"database": database}

    t0 = datetime(2026, 10, 5, 14, 24, 0)
    _run_async(tracker._resolve_direction("binary_sensor.foo_person_occupancy", t0))
    # Second leg on `_2` sibling within DOOR_STEM_DEDUP_S:
    _run_async(tracker._resolve_direction(
        "binary_sensor.foo_person_occupancy_2",
        t0 + timedelta(seconds=10),
    ))
    # Direction-keyed dedup (Review B3): no interior events → direction
    # is "ambiguous" both times → key "foo|ambiguous" recorded at t0 and
    # the second leg (10 s later) is dedupped (not overwritten).
    assert tracker._last_resolved.get("foo|ambiguous") == t0


def test_dedup_window_knob_blocks_at_29s_passes_at_31s():
    tracker, hass = _make_tracker()
    from custom_components.universal_room_automation.const import DOMAIN
    hass.data[DOMAIN] = {}

    t0 = datetime(2026, 10, 5, 14, 24, 0)
    _run_async(tracker._resolve_direction("binary_sensor.foo_person_occupancy", t0))
    # 29 s later: SKIP (within DOOR_STEM_DEDUP_S=30)
    _run_async(tracker._resolve_direction(
        "binary_sensor.foo_person_occupancy", t0 + timedelta(seconds=29),
    ))
    # last_resolved stayed at t0 (second call skipped before overwrite)
    assert tracker._last_resolved["foo|ambiguous"] == t0

    # 31 s later: PROCESS (outside window) — key advances
    _run_async(tracker._resolve_direction(
        "binary_sensor.foo_person_occupancy", t0 + timedelta(seconds=31),
    ))
    assert tracker._last_resolved["foo|ambiguous"] == t0 + timedelta(seconds=31)


# ---------------------------------------------------------------------------
# Direction-keyed dedup (Review B3): opposite directions NEVER collapse
# ---------------------------------------------------------------------------

def test_direction_keyed_dedup_does_not_swallow_opposite_direction():
    """Review B3: exit at t0 then entry at t0+20 (within 30 s dedup) MUST
    NOT be swallowed — the direction suffix on the key separates them."""
    tracker, hass = _make_tracker(interior=["interior_cam_1"])
    from custom_components.universal_room_automation.const import DOMAIN
    hass.data[DOMAIN] = {}
    hass.bus = MagicMock()

    t0 = datetime(2026, 10, 5, 14, 24, 0)
    # Leg 1: interior fire BEFORE egress → EXIT
    tracker._recent_interior_events["interior_cam_1"] = [t0 - timedelta(seconds=5)]
    _run_async(tracker._resolve_direction(
        "binary_sensor.cam_door_a_person_occupancy", t0,
    ))
    # Leg 2 (20 s later, within DOOR_STEM_DEDUP_S=30): interior fire AFTER
    # egress → ENTRY. Direction-keyed dedup must let it through.
    t1 = t0 + timedelta(seconds=20)
    tracker._recent_interior_events["interior_cam_1"] = [t1 + timedelta(seconds=3)]
    _run_async(tracker._resolve_direction(
        "binary_sensor.cam_door_a_person_occupancy", t1,
    ))
    # Both direction keys should be present.
    assert "cam_door_a|exit" in tracker._last_resolved
    assert "cam_door_a|entry" in tracker._last_resolved
    # Both bus fires happened (opposite directions never dedupped).
    assert hass.bus.async_fire.call_count == 2


def test_direction_keyed_dedup_same_direction_still_collapses():
    """Review B3: same stem + SAME direction inside the window still
    collapses (prevents double-counting a chattering sensor)."""
    tracker, hass = _make_tracker(interior=["interior_cam_1"])
    from custom_components.universal_room_automation.const import DOMAIN
    hass.data[DOMAIN] = {}
    hass.bus = MagicMock()

    t0 = datetime(2026, 10, 5, 14, 24, 0)
    tracker._recent_interior_events["interior_cam_1"] = [t0 + timedelta(seconds=3)]
    _run_async(tracker._resolve_direction(
        "binary_sensor.cam_door_a_person_occupancy", t0,
    ))
    tracker._recent_interior_events["interior_cam_1"] = [
        t0 + timedelta(seconds=13),
    ]
    _run_async(tracker._resolve_direction(
        "binary_sensor.cam_door_a_person_occupancy",
        t0 + timedelta(seconds=10),
    ))
    assert tracker._last_resolved["cam_door_a|entry"] == t0
    # Only one bus fire — the second ENTRY was dedupped.
    assert hass.bus.async_fire.call_count == 1


# ---------------------------------------------------------------------------
# Door-group dedup (R2.2 item 4(b))
# ---------------------------------------------------------------------------

def test_door_group_dedup_collapses_cross_camera_legs_within_window():
    tracker, hass = _make_tracker(
        door_groups={"cam_door_a": "door_a", "cam_door_b": "door_a"},
    )
    from custom_components.universal_room_automation.const import DOMAIN
    hass.data[DOMAIN] = {}

    t0 = datetime(2026, 10, 5, 14, 24, 0)
    _run_async(tracker._resolve_direction(
        "binary_sensor.cam_door_a_person_occupancy", t0,
    ))
    # cross-camera leg 10 s later within same group → DEDUPED (group key)
    _run_async(tracker._resolve_direction(
        "binary_sensor.cam_door_b_person_occupancy",
        t0 + timedelta(seconds=10),
    ))
    # Direction-keyed (Review B3): both legs produced direction=ambiguous
    # (no interior cams) → one group-scoped key recorded at t0.
    assert "group:door_a|ambiguous" in tracker._last_resolved
    assert tracker._last_resolved["group:door_a|ambiguous"] == t0


def test_unset_door_groups_falls_back_to_per_stem_dedup():
    """R4.6: unset → per-stem dedup → today's byte-identical behaviour.
    Two different stems within the window must NOT dedup each other."""
    tracker, hass = _make_tracker(door_groups={})
    from custom_components.universal_room_automation.const import DOMAIN
    hass.data[DOMAIN] = {}

    t0 = datetime(2026, 10, 5, 14, 24, 0)
    _run_async(tracker._resolve_direction(
        "binary_sensor.cam_door_a_person_occupancy", t0,
    ))
    _run_async(tracker._resolve_direction(
        "binary_sensor.cam_door_b_person_occupancy",
        t0 + timedelta(seconds=5),
    ))
    assert "cam_door_a|ambiguous" in tracker._last_resolved
    assert "cam_door_b|ambiguous" in tracker._last_resolved
    assert "group:door_a|ambiguous" not in tracker._last_resolved


# ---------------------------------------------------------------------------
# _get_interior_cameras_near fallback (R3.1 CRITICAL-1)
# ---------------------------------------------------------------------------

def test_interior_cameras_near_unset_falls_back_to_all_interior():
    tracker, _ = _make_tracker(
        door_groups={},  # unset
        neighbours={},
        interior=["interior_cam_1", "interior_cam_2"],
    )
    out = tracker._get_interior_cameras_near(
        "binary_sensor.cam_door_a_person_occupancy"
    )
    assert out == ["interior_cam_1", "interior_cam_2"]


def test_interior_cameras_near_configured_narrows_set():
    tracker, _ = _make_tracker(
        door_groups={"cam_door_a": "door_a"},
        neighbours={"door_a": ["interior_cam_1"]},
        interior=["interior_cam_1", "interior_cam_2"],
    )
    out = tracker._get_interior_cameras_near(
        "binary_sensor.cam_door_a_person_occupancy"
    )
    assert out == ["interior_cam_1"]


def test_interior_cameras_near_empty_configured_honours_opt_out():
    """Operator explicitly maps group → [] (deliberate opt-out)."""
    tracker, _ = _make_tracker(
        door_groups={"cam_door_a": "door_a"},
        neighbours={"door_a": []},
        interior=["interior_cam_1"],
    )
    assert tracker._get_interior_cameras_near(
        "binary_sensor.cam_door_a_person_occupancy"
    ) == []


# ---------------------------------------------------------------------------
# Direction loop (Review A-HIGH): per-camera first-match + across-cameras
# closest-in-time wins. Single-camera t-12/t+8 must stay EXIT (develop
# forward-iteration preserved). Cross-camera noisy-vs-close must pick the
# closer camera.
# ---------------------------------------------------------------------------

def test_resolve_direction_single_camera_prefers_older_exit_match():
    """Review A-HIGH repro: ONE neighbour cam, interior fires at t-12
    (EXIT window) and t+8 (ENTRY window). Develop's forward iteration
    hit t-12 first → EXIT; the reversed() variant wrongly flipped it to
    ENTRY. Fix: per-camera forward iteration → stays EXIT."""
    tracker, hass = _make_tracker(interior=["interior_cam_1"])
    from custom_components.universal_room_automation.const import DOMAIN
    hass.data[DOMAIN] = {}
    hass.bus = MagicMock()

    t0 = datetime(2026, 10, 5, 14, 24, 0)
    tracker._recent_interior_events["interior_cam_1"] = [
        t0 - timedelta(seconds=12),  # EXIT candidate
        t0 + timedelta(seconds=8),   # ENTRY candidate
    ]
    _run_async(tracker._resolve_direction(
        "binary_sensor.cam_door_a_person_occupancy", t0,
    ))
    args = hass.bus.async_fire.call_args.args
    assert args[0] == "ura_person_egress_event"
    assert args[1]["direction"] == "exit", (
        f"single-camera t-12/t+8 must stay EXIT (got {args[1]['direction']})"
    )


def test_resolve_direction_cross_camera_closest_in_time_wins():
    """Review A-HIGH repro: noisy camera 'cam_interior_noisy' fires at
    t-25 (EXIT window edge); 'cam_interior_close' fires at t+3 (closest).
    The old outer-first-camera bias would pick the noisy one → EXIT; the
    fix picks whichever camera's match has the smallest |delta|."""
    tracker, hass = _make_tracker(
        interior=["cam_interior_noisy", "cam_interior_close"],
    )
    from custom_components.universal_room_automation.const import DOMAIN
    hass.data[DOMAIN] = {}
    hass.bus = MagicMock()

    t0 = datetime(2026, 10, 5, 14, 24, 0)
    tracker._recent_interior_events["cam_interior_noisy"] = [
        t0 - timedelta(seconds=25),
    ]
    tracker._recent_interior_events["cam_interior_close"] = [
        t0 + timedelta(seconds=3),
    ]
    _run_async(tracker._resolve_direction(
        "binary_sensor.cam_door_a_person_occupancy", t0,
    ))
    args = hass.bus.async_fire.call_args.args
    assert args[1]["direction"] == "entry", (
        f"closest-in-time (t+3) must beat the noisier t-25 cam "
        f"(got {args[1]['direction']})"
    )


# ---------------------------------------------------------------------------
# _last_resolved prune horizon (R4.2 N-HIGH-2)
# ---------------------------------------------------------------------------

def test_last_resolved_prune_covers_dedup_plus_resolve_delay():
    """Horizon = max(60, DOOR_STEM_DEDUP_S + ENTRY_WINDOW_SECONDS). With
    defaults = max(60, 30+45) = 75. An entry 70 s old must survive the
    prune (dedup head still consults it) — a 90 s old entry must not."""
    tracker, _ = _make_tracker()
    import custom_components.universal_room_automation.transit_validator as _tv
    now = _tv.dt_util.now()
    tracker._last_resolved["survives"] = now - timedelta(seconds=70)
    tracker._last_resolved["drops"] = now - timedelta(seconds=200)
    # entity_id just needs to exist in _recent_egress_events for prune to run
    tracker._recent_egress_events["x"] = []
    tracker._prune_event_list(tracker._recent_egress_events, "x")
    assert "survives" in tracker._last_resolved
    assert "drops" not in tracker._last_resolved


# ---------------------------------------------------------------------------
# peak_person_count sampler (R3.6 / R4.5)
# ---------------------------------------------------------------------------

def test_peak_count_sampler_window_bounds():
    tracker, _ = _make_tracker()
    t = datetime(2026, 10, 5, 14, 24, 0)
    tracker._peak_count_buffer["foo"] = __import__("collections").deque([
        (t - timedelta(seconds=200), 7),   # out: too old
        (t - timedelta(seconds=10), 4),    # in
        (t + timedelta(seconds=30), 3),    # in
        (t + timedelta(seconds=200), 9),   # out: too new
    ])
    assert tracker._sample_peak_person_count("foo", t) == 4


def test_peak_count_sampler_door_group_takes_max_not_sum():
    """R4.5: two cameras in one group both see a 4-person arrival →
    peak = 4, not 8."""
    tracker, _ = _make_tracker(
        door_groups={"cam_a": "door_a", "cam_b": "door_a"},
    )
    t = datetime(2026, 10, 5, 14, 24, 0)
    from collections import deque
    tracker._peak_count_buffer["cam_a"] = deque([(t, 4)])
    tracker._peak_count_buffer["cam_b"] = deque([(t + timedelta(seconds=2), 4)])
    assert tracker._sample_peak_person_count("cam_a", t) == 4  # MAX, not SUM


def test_peak_count_sampler_returns_none_when_no_sample_in_window():
    tracker, _ = _make_tracker()
    t = datetime(2026, 10, 5, 14, 24, 0)
    tracker._peak_count_buffer["foo"] = __import__("collections").deque([
        (t - timedelta(seconds=600), 2),
    ])
    assert tracker._sample_peak_person_count("foo", t) is None


# ---------------------------------------------------------------------------
# Database — log_entry_exit_event + fresh CREATE + ALTER migration
# ---------------------------------------------------------------------------

def test_log_entry_exit_event_accepts_peak_person_count_kwarg():
    """R3.6 writer signature carries the new kwarg (default None)."""
    import inspect
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    sig = inspect.signature(UniversalRoomDatabase.log_entry_exit_event)
    assert "peak_person_count" in sig.parameters
    assert sig.parameters["peak_person_count"].default is None


def test_fresh_create_table_includes_peak_person_count_column():
    """R4.5: fresh CREATE at database.py:928 ships the column so new
    installs (Wigton) match the migrated-install schema."""
    repo_root = Path(__file__).resolve().parents[2]
    db_src = (repo_root / "custom_components/universal_room_automation/database.py").read_text()
    # The fresh CREATE must contain the column name as part of the
    # person_entry_exit_events DDL block.
    create_block = db_src.split("CREATE TABLE IF NOT EXISTS person_entry_exit_events", 1)[1]
    create_block = create_block.split(")", 1)[0]
    assert "peak_person_count" in create_block


def test_alter_migration_added_for_person_entry_exit_events():
    """R4.5: ALTER TABLE migration present (idempotent, mirrors
    database.py precedent at :972/:1819/:1957/:2012/:2057)."""
    repo_root = Path(__file__).resolve().parents[2]
    db_src = (repo_root / "custom_components/universal_room_automation/database.py").read_text()
    assert "ALTER TABLE person_entry_exit_events" in db_src
    assert "ADD COLUMN peak_person_count INTEGER" in db_src


# ---------------------------------------------------------------------------
# R3.11 generic fixtures use — assert no household-specific names in tests
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Review C new behavioral tests
# ---------------------------------------------------------------------------

def test_peak_count_sampler_seeds_with_last_pre_window_sample():
    """Review LOW: a step-and-hold count sensor that stepped BEFORE the
    window and did NOT re-fire during the window still represents the
    multiplicity. The sampler must seed with the last pre-window sample."""
    tracker, _ = _make_tracker()
    t = datetime(2026, 10, 5, 14, 24, 0)
    from collections import deque
    tracker._peak_count_buffer["foo"] = deque([
        (t - timedelta(seconds=45), 3),   # pre-window SEED (within horizon)
        # no in-window samples (step-held)
    ])
    assert tracker._sample_peak_person_count("foo", t) == 3


def test_peak_count_sampler_group_max_different_values_takes_six():
    """Review C: group-max with different per-camera values (cam_a=6,
    cam_b=4) → MAX = 6, not sum (10) and not min (4)."""
    tracker, _ = _make_tracker(
        door_groups={"cam_a": "door_a", "cam_b": "door_a"},
    )
    t = datetime(2026, 10, 5, 14, 24, 0)
    from collections import deque
    tracker._peak_count_buffer["cam_a"] = deque([(t, 6)])
    tracker._peak_count_buffer["cam_b"] = deque([(t + timedelta(seconds=2), 4)])
    assert tracker._sample_peak_person_count("cam_a", t) == 6


def test_on_peak_count_change_appends_prunes_and_ignores_bad_values():
    """Review C: _on_peak_count_change appends int samples, prunes >horizon,
    and ignores non-int / negative / missing-state."""
    tracker, _ = _make_tracker()
    tracker._count_sensor_to_stem["sensor.cam_a_person_count"] = "cam_a"

    def _ev(state_value, entity_id="sensor.cam_a_person_count"):
        new = MagicMock()
        new.entity_id = entity_id
        new.state = state_value
        ev = MagicMock()
        ev.data = {"new_state": new}
        return ev

    # Valid int → appended
    tracker._on_peak_count_change(_ev("3"))
    assert len(tracker._peak_count_buffer["cam_a"]) == 1
    # Non-int → ignored
    tracker._on_peak_count_change(_ev("unknown"))
    assert len(tracker._peak_count_buffer["cam_a"]) == 1
    # Negative → ignored
    tracker._on_peak_count_change(_ev("-1"))
    assert len(tracker._peak_count_buffer["cam_a"]) == 1
    # Unknown stem → ignored
    tracker._on_peak_count_change(_ev("2", entity_id="sensor.other_person_count"))
    assert "other" not in tracker._peak_count_buffer


def test_load_door_config_reads_integration_config_entry():
    """Review C: `_load_door_config` reads CONF_DOOR_GROUPS and
    CONF_DOOR_INTERIOR_NEIGHBOURS from the integration-type entry's
    merged data+options (not a hand-string lookup)."""
    from custom_components.universal_room_automation.const import (
        CONF_DOOR_GROUPS,
        CONF_DOOR_INTERIOR_NEIGHBOURS,
        CONF_ENTRY_TYPE,
        ENTRY_TYPE_INTEGRATION,
    )

    tracker, hass = _make_tracker()
    entry = MagicMock()
    entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION}
    entry.options = {
        CONF_DOOR_GROUPS: {"cam_a": "door_a", "cam_b": "door_a"},
        CONF_DOOR_INTERIOR_NEIGHBOURS: {"door_a": ["interior_1"]},
    }
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[entry])

    tracker._load_door_config()
    assert tracker._door_group_by_stem == {"cam_a": "door_a", "cam_b": "door_a"}
    assert tracker._interior_neighbours_by_group == {"door_a": ["interior_1"]}


def test_db_log_entry_exit_event_falls_back_to_six_columns_when_absent():
    """Review B2: when the ALTER-TABLE migration couldn't land the column,
    log_entry_exit_event must INSERT the 6-column shape (no
    peak_person_count) so rows still land."""
    import asyncio as _aio
    from unittest.mock import AsyncMock, MagicMock

    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )

    db = UniversalRoomDatabase.__new__(UniversalRoomDatabase)
    db._peak_person_count_absent = True

    executed_sql: list[str] = []

    class _FakeDb:
        async def execute(self, sql, params=None):
            executed_sql.append(sql)
        async def commit(self):
            pass

    class _CtxMgr:
        async def __aenter__(self):
            return _FakeDb()
        async def __aexit__(self, *a):
            return False

    db._db = lambda: _CtxMgr()  # type: ignore[assignment]

    _aio.new_event_loop().run_until_complete(
        db.log_entry_exit_event(
            person_id="p",
            event_type="egress",
            direction="entry",
            egress_camera="cam",
            confidence=0.9,
            peak_person_count=3,
        )
    )
    assert any(
        "egress_camera, confidence)" in sql.replace("\n", " ").replace("  ", " ")
        for sql in executed_sql
    ), f"Expected 6-column INSERT in: {executed_sql!r}"
    assert all(
        "peak_person_count" not in sql for sql in executed_sql
    )


def test_strings_json_carries_door_groups_labels_and_helper_text():
    """Review C: labels + helper text present (both strings.json and the
    translation copy); label-style-guide (plain language, no nerd words)."""
    repo_root = Path(__file__).resolve().parents[2]
    for rel in (
        "custom_components/universal_room_automation/strings.json",
        "custom_components/universal_room_automation/translations/en.json",
    ):
        txt = (repo_root / rel).read_text()
        assert '"door_groups": "Group door cameras"' in txt
        assert '"door_interior_neighbours": "Rooms next to each door"' in txt
        assert '"main_entry_door": "Main entry door"' in txt
        # Helper text (data_description) presence check
        assert "Map each door camera's name to a group" in txt
        assert "For each door group, list the indoor cameras" in txt
        assert "Name of the main door group" in txt
        # Label-style-guide: no "hysteresis", "debounce", etc. in the
        # three helper lines we added.
        for banned in ("hysteresis", "debounce", "provenance", "substrate"):
            assert banned.lower() not in txt.lower().split("door_groups", 1)[-1][:4000]


def test_options_flow_strips_empty_new_keys_before_save():
    """Review B1: on save, empty values for the three new keys are dropped
    so they don't trigger the None!={} fall-through reload."""
    repo_root = Path(__file__).resolve().parents[2]
    src = (repo_root / "custom_components/universal_room_automation/config_flow.py").read_text()
    # The save handler must contain the drop-empties logic.
    assert "cleaned.pop(_k, None)" in src
    assert "CONF_DOOR_GROUPS, CONF_DOOR_INTERIOR_NEIGHBOURS" in src
    assert 'cleaned.get(CONF_MAIN_ENTRY_DOOR) in ("", None)' in src
    # And must use `suggested_value` (not `default`) for the three keys
    # so unselected fields don't bake defaults into user_input.
    assert "suggested_value" in src
    # Validator helper exists.
    assert "_validate_door_interior_neighbours" in src


def test_validate_door_interior_neighbours_rejects_bad_shapes():
    """Review MED: validator rejects non-dict, missing-dot entities, and
    returns a plain-language error."""
    from custom_components.universal_room_automation.config_flow import (
        UniversalRoomAutomationOptionsFlow,
    )
    v = UniversalRoomAutomationOptionsFlow._validate_door_interior_neighbours
    assert v({}) == ({}, None)
    cleaned, err = v({"door_a": ["camera.foo"]})
    assert err is None and cleaned == {"door_a": ["camera.foo"]}
    _, err = v("not a dict")
    assert err and "mapping" in err.lower()
    _, err = v({"door_a": "notalist"})
    assert err and "list" in err.lower()
    _, err = v({"door_a": ["noDotHere"]})
    assert err and "entity id" in err.lower()
    # Interior-whitelist constraint for non-camera.* entries
    _, err = v({"door_a": ["binary_sensor.unknown"]}, interior_entities=set())
    assert err and "known interior" in err.lower()
    cleaned, err = v(
        {"door_a": ["binary_sensor.known_sensor"]},
        interior_entities={"binary_sensor.known_sensor"},
    )
    assert err is None and cleaned == {"door_a": ["binary_sensor.known_sensor"]}


def test_tests_use_generic_fixtures_not_household_names():
    """R3.11 / MED-3: cycle tests use `cam_door_a` / `interior_cam_1`,
    not household entity IDs. We check the FUNCTION bodies (strip the
    banned-list literal so it doesn't match itself)."""
    me = Path(__file__).read_text()
    # Strip ourselves: everything from this function's def onward is docs
    # about the policy, not fixture code.
    me = me.split("def test_tests_use_generic_fixtures_not_household_names", 1)[0]
    banned = ["front" + "_door_aerial", "madrone" + "_g6_entry",
              "doorbell" + "_lite", "foyer" + "_fisheye",
              "family" + "_room"]
    for b in banned:
        assert b not in me, (
            f"test fixture leaked household-specific entity: {b}"
        )
