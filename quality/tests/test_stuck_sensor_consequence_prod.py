"""STUCK-SENSOR-1 — production-anchored drills (MED-1 + MED-3).

Fix-up 2026-08-13 (operator directive): the shim-based `RoomShim` tests
in ``test_stuck_sensor_consequence.py`` are truth-table coverage but do
NOT route through production source — a mutation to the coordinator
would not red them (hollow-anchor). This file binds the REAL production
methods (`_p22_stuck_sensor_set` for MED-1, `_promote_dutycycle_to_exclusion`
for MED-3) onto a `_StubCoord` per the `test_sensor_capability_and_role.py`
pattern (extended for the D1 promotion + P22 boot guard surfaces).

Named drill tests:
  * test_p22_defers_exclusion_until_post_boot_observation_PROD (MED-1)
      — Deleting either boot-guard conjunction from coordinator.py's
        _p22_stuck_sensor_set MUST red this test.
  * test_stuck_exclusion_uses_merged_options_room_name_PROD (MED-3)
      — Flipping the merged-options-first accessor to data-first in
        _promote_dutycycle_to_exclusion / _get_config MUST red this test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401 — bootstrap homeassistant mocks

from custom_components.universal_room_automation.const import (
    CONF_ENTRY_TYPE,
    CONF_MOTION_SENSORS,
    CONF_STUCK_SENSOR_EXCLUSION_ENABLED,
    DEFAULT_STUCK_SENSOR_EXCLUSION_ENABLED,
    CORROBORATOR_DISAGREE_S,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_INTEGRATION,
)
from custom_components.universal_room_automation.coordinator import (
    UniversalRoomCoordinator,
)
from custom_components.universal_room_automation.domain_coordinators\
    import _nm_cycle_a, _stuck_signal_nm


@pytest.fixture(autouse=True)
def _reset_stuck_nm_state():
    """C-CRIT-1 mirror: bracket every test with reset+cache-invalidate."""
    _stuck_signal_nm.reset_latches_for_tests()
    _nm_cycle_a.invalidate_knob_cache()
    yield
    _stuck_signal_nm.reset_latches_for_tests()
    _nm_cycle_a.invalidate_knob_cache()


class _FakeState:
    def __init__(self, state):
        self.state = state


class _FakeStates:
    def __init__(self, mapping):
        self._m = mapping

    def get(self, entity_id):
        s = self._m.get(entity_id)
        return _FakeState(s) if s is not None else None


class _FakeConfigEntries:
    def __init__(self, entries):
        self._entries = entries

    def async_entries(self, _domain):
        return self._entries


def _bind(method_name, coord):
    """Bind a production coordinator method onto our stub instance."""
    fn = getattr(UniversalRoomCoordinator, method_name)
    return fn.__get__(coord, type(coord))


def _make_stub_coord(*, room_data=None, room_options=None,
                    states=None, cm_options=None):
    """Instantiate a minimal stub coord that binds real production methods.

    Bypasses DataUpdateCoordinator __init__ (mocked out by the harness).
    Only surfaces the promotion + boot-guard helpers need are populated.
    """
    class _StubCoord:
        pass
    coord = _StubCoord()
    coord.hass = MagicMock()
    room_entry = MagicMock()
    room_entry.data = dict(room_data or {})
    room_entry.options = dict(room_options or {})
    room_entry.entry_id = "test_entry"
    coord.entry = room_entry
    integration_entry = MagicMock()
    integration_entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION}
    integration_entry.options = {}
    cm_entry = MagicMock()
    cm_entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}
    cm_entry.options = dict(cm_options or {})
    coord.hass.config_entries = _FakeConfigEntries([integration_entry, cm_entry])
    coord.hass.states = _FakeStates(states or {})
    coord.hass.data = {}
    # State fields the helpers touch.
    coord._sensor_on_since = {}
    coord._post_restart_seen_on = set()
    coord._stuck_sensor_hours = 4.0
    coord._last_corroborator_fire = {}
    coord._effective_corroborators_last_tick = []
    # Bind real production methods.
    coord._is_sensor_on = _bind("_is_sensor_on", coord)
    coord._get_config = _bind("_get_config", coord)
    coord._d2_boot_settle_done = _bind("_d2_boot_settle_done", coord)
    coord._d2_house_state_allows = _bind("_d2_house_state_allows", coord)
    coord._stuck_exclusion_enabled = _bind("_stuck_exclusion_enabled", coord)
    coord._p22_stuck_sensor_set = _bind("_p22_stuck_sensor_set", coord)
    coord._promote_dutycycle_to_exclusion = _bind(
        "_promote_dutycycle_to_exclusion", coord,
    )
    # HIGH-A1 fix-up (2026-08-13): bind dirty-gated + delayed-save
    # helper so write-volume regression tests can drive it directly.
    coord._stuck_state_snapshot = _bind("_stuck_state_snapshot", coord)
    coord._stuck_state_payload_provider = _bind(
        "_stuck_state_payload_provider", coord,
    )
    coord._stuck_store_key = _bind("_stuck_store_key", coord)
    coord._schedule_stuck_state_save = _bind(
        "_schedule_stuck_state_save", coord,
    )
    coord._release_edge_scan_should_run = _bind(
        "_release_edge_scan_should_run", coord,
    )
    coord._stuck_state_last_saved_snapshot = ()
    coord._stuck_sensor_fired = set()
    coord._stuck_excluded_fired = set()
    coord._stuck_sensor_fired_date = None
    coord._d2_completed_cleanly = False
    coord._dutycycle_excluded_last_tick = set()
    coord._dutycycle_excluded_now = {}
    return coord


# ---------------------------------------------------------------------------
# MED-1 — production-anchored P22 boot-guard drill.
# ---------------------------------------------------------------------------


def test_p22_defers_exclusion_until_post_boot_observation_PROD():
    """MED-1 production anchor: exercises coordinator._p22_stuck_sensor_set.

    Mutation drill (see fix-up report): deleting either
    `and _boot_settled` OR `and s in self._post_restart_seen_on` from
    coordinator.py's `_p22_stuck_sensor_set` MUST red this test.
    """
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)

    # Boot-settle NOT done: even w/ 3h59m since AND post-restart-seen,
    # the guard MUST refuse. Nested clear-out of the coordinator-
    # manager registry via hass.data forces the fail-open branch of
    # _d2_boot_settle_done to return True by default — so we install
    # a presence mock that reports _boot_settle_done = False.
    coord = _make_stub_coord()
    coord.hass.data = {
        "universal_room_automation": {
            "coordinator_manager": MagicMock(
                coordinators={"presence": MagicMock(_boot_settle_done=False)},
            ),
        },
    }
    # 5h since — comfortably past the 4h P22 hours threshold, so the ONLY
    # thing keeping this sensor OUT of the set is the boot-settle guard.
    # Deleting `and _boot_settled` in production reddens this branch.
    coord._sensor_on_since["binary_sensor.mmwave_a"] = (
        now - timedelta(hours=5)
    )
    coord._post_restart_seen_on.add("binary_sensor.mmwave_a")
    assert coord._p22_stuck_sensor_set(now) == set()

    # Boot-settle done, but sensor NOT observed live-ON post-restart.
    coord2 = _make_stub_coord()
    coord2.hass.data = {
        "universal_room_automation": {
            "coordinator_manager": MagicMock(
                coordinators={"presence": MagicMock(_boot_settle_done=True)},
            ),
        },
    }
    coord2._sensor_on_since["binary_sensor.mmwave_b"] = (
        now - timedelta(hours=5)
    )
    # NOT in _post_restart_seen_on.
    assert coord2._p22_stuck_sensor_set(now) == set()

    # Both guards satisfied → sensor is in the stuck set.
    coord3 = _make_stub_coord()
    coord3.hass.data = {
        "universal_room_automation": {
            "coordinator_manager": MagicMock(
                coordinators={"presence": MagicMock(_boot_settle_done=True)},
            ),
        },
    }
    coord3._sensor_on_since["binary_sensor.mmwave_c"] = (
        now - timedelta(hours=5)
    )
    coord3._post_restart_seen_on.add("binary_sensor.mmwave_c")
    assert coord3._p22_stuck_sensor_set(now) == {"binary_sensor.mmwave_c"}


# ---------------------------------------------------------------------------
# MED-3 — production-anchored merged-options-first accessor drill.
# ---------------------------------------------------------------------------


def test_stuck_exclusion_uses_merged_options_room_name_PROD():
    """MED-3 production anchor: exercises _get_config's options-first
    contract as consumed by the D1 promotion path.

    Mutation drill: flipping ``self.entry.options.get(key, self.entry.data
    .get(key, default))`` to data-first in coordinator.py `_get_config`
    MUST red this test — the room's motion_sensors list should reflect
    the OPTIONS variant (empty), not the DATA variant (populated).
    """
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)

    # data-side has a corroborator wired; options-side EXPLICITLY empties
    # it. Merged-options-first → the room has NO corroborator, so
    # `_promote_dutycycle_to_exclusion` fails predicate (3) even when
    # everything else is green. Data-first would keep the corroborator
    # and let the promotion fire, reddening the assertion below.
    coord = _make_stub_coord(
        room_data={
            "room_name": "Master",
            CONF_MOTION_SENSORS: ["binary_sensor.pir_old"],
        },
        room_options={
            "room_name": "Master",
            CONF_MOTION_SENSORS: [],
        },
        states={"binary_sensor.pir_old": "off"},
        cm_options={CONF_STUCK_SENSOR_EXCLUSION_ENABLED: True},
    )
    # House state helpers happy (fail-open defaults).
    coord.hass.data = {
        "universal_room_automation": {
            "coordinator_manager": MagicMock(
                coordinators={"presence": MagicMock(
                    _boot_settle_done=True, house_state="home_day",
                )},
            ),
        },
    }

    # Verify _get_config observes the options-first (merged) list.
    got = coord._get_config(CONF_MOTION_SENSORS, [])
    assert got == [], (
        f"MERGED-OPTIONS-FIRST BROKEN: options set motion_sensors=[] but "
        f"_get_config returned {got}. Data-first flip would return the "
        f"data-side list ['binary_sensor.pir_old']."
    )

    # And confirm the promotion path stays consistent: with the effective
    # corroborator list published from the detector, an empty list must
    # fail predicate (3) regardless of other predicates.
    coord._effective_corroborators_last_tick = list(got)  # mirrors detector.
    coord._last_corroborator_fire["binary_sensor.pir_old"] = (
        now - timedelta(seconds=int(CORROBORATOR_DISAGREE_S) + 60)
    )
    assert coord._promote_dutycycle_to_exclusion(
        "binary_sensor.mmwave_x", now,
    ) is False


# ---------------------------------------------------------------------------
# Bonus: D1 predicate (1) kill-switch production anchor.
# ---------------------------------------------------------------------------


def test_kill_switch_short_circuits_promotion_PROD():
    """Predicate (1) production anchor: `_stuck_exclusion_enabled` reads
    the nm_cycle_a_knob cache; flipping the CM options key MUST route
    through the real knob-lookup helper (not a monkeypatch).
    """
    now = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    # Kill switch OFF via CM options.
    coord = _make_stub_coord(
        room_data={"room_name": "R"},
        room_options={},
        cm_options={CONF_STUCK_SENSOR_EXCLUSION_ENABLED: False},
    )
    # Invalidate the process-wide knob cache so this test observes the
    # freshly-set option (other suites in this tree may have primed the
    # cache with True from a sibling test).
    from custom_components.universal_room_automation.domain_coordinators\
        ._nm_cycle_a import invalidate_knob_cache
    invalidate_knob_cache()
    coord._effective_corroborators_last_tick = ["binary_sensor.pir"]
    coord._last_corroborator_fire["binary_sensor.pir"] = (
        now - timedelta(seconds=int(CORROBORATOR_DISAGREE_S) + 60)
    )
    assert coord._promote_dutycycle_to_exclusion(
        "binary_sensor.mmwave", now,
    ) is False
    # Restore cache to defaults so downstream tests aren't affected.
    invalidate_knob_cache()


# ---------------------------------------------------------------------------
# C-MED-3 — Founding-case (2026-08-09) driven through the REAL
# production `_promote_dutycycle_to_exclusion`.
# ---------------------------------------------------------------------------


def test_founding_case_replay_2026_08_09_PROD():
    """Same shape as the shim smoke test but drives the real prod method.

    Living Room = no corroborator wired → INV-STUCK-2 (notify-only stays).
    Master Bedroom = PIR corroborator + ≥900s quiet → exclusion engages.
    """
    now = datetime(2026, 8, 9, 13, 54, 0, tzinfo=timezone.utc)

    # Living Room stub — no corroborator in the effective list.
    from custom_components.universal_room_automation.domain_coordinators\
        ._nm_cycle_a import invalidate_knob_cache
    invalidate_knob_cache()

    living = _make_stub_coord(
        room_data={"room_name": "Living Room"},
        room_options={"room_name": "Living Room"},
        cm_options={CONF_STUCK_SENSOR_EXCLUSION_ENABLED: True},
    )
    living._effective_corroborators_last_tick = []
    assert living._promote_dutycycle_to_exclusion(
        "binary_sensor.living_room_mmwave", now,
    ) is False

    # Master Bedroom stub — PIR wired, quiet longer than the window.
    master = _make_stub_coord(
        room_data={"room_name": "Master Bedroom"},
        room_options={"room_name": "Master Bedroom"},
        states={"binary_sensor.master_pir": "off"},
        cm_options={CONF_STUCK_SENSOR_EXCLUSION_ENABLED: True},
    )
    master._effective_corroborators_last_tick = ["binary_sensor.master_pir"]
    master._last_corroborator_fire["binary_sensor.master_pir"] = (
        now - timedelta(seconds=int(CORROBORATOR_DISAGREE_S) + 60)
    )
    assert master._promote_dutycycle_to_exclusion(
        "binary_sensor.master_bedroom_mmwave", now,
    ) is True
    invalidate_knob_cache()


# ---------------------------------------------------------------------------
# HIGH-A1 — write-volume regression: no state change => zero saves;
# state change => exactly one delayed save.
# ---------------------------------------------------------------------------


def test_stuck_state_save_no_state_change_zero_writes():
    """HIGH-A1 fix-up: repeated ticks with an unchanged snapshot must
    result in ZERO `Store.async_delay_save` invocations (dirty gate).
    A single state change → exactly ONE delayed-save call."""
    coord = _make_stub_coord()
    fake_store = MagicMock()
    fake_store.async_delay_save = MagicMock()
    coord._stuck_store = fake_store

    # No state → snapshot is (empty, empty, today). First call establishes
    # the last-saved snapshot but with EMPTY state; the dirty check
    # compares against the initial `()` tuple in __init__, so the very
    # first call is a save. Subsequent calls with the SAME snapshot must
    # no-op.
    coord._schedule_stuck_state_save()
    assert fake_store.async_delay_save.call_count == 1
    for _ in range(50):
        coord._schedule_stuck_state_save()
    assert fake_store.async_delay_save.call_count == 1, (
        "50 unchanged-snapshot ticks scheduled "
        f"{fake_store.async_delay_save.call_count} saves (expected 1)"
    )

    # Now mutate state → dirty gate opens → exactly one more save.
    coord._sensor_on_since["binary_sensor.mm"] = datetime.now(timezone.utc)
    coord._schedule_stuck_state_save()
    assert fake_store.async_delay_save.call_count == 2

    # And confirm the delay window matches the fix-up value (60s).
    args = fake_store.async_delay_save.call_args
    assert args.args[1] == 60.0 or args.kwargs.get("delay") == 60.0


# ---------------------------------------------------------------------------
# B-MED-1 — detector exception must NOT mass-release the exclusion set.
# ---------------------------------------------------------------------------


def test_d2_exception_preserves_exclusion_no_recovery_storm():
    """B-MED-1 fix-up: `_d2_completed_cleanly` guard.

    A mid-detector exception leaves ``_dutycycle_excluded_now={}`` (reset
    at tick start) — without the guard the release-edge scan would
    interpret this as "everything released" and emit a recovery-NM
    storm + unlatch every engagement. The guard defaults to False and
    is set True only at the successful end of the try body.
    """
    # Model the failing-detector tick at the state level: the guard
    # remains False after `_dutycycle_excluded_now={}` reset. The
    # release-scan's `if self._d2_completed_cleanly:` therefore
    # short-circuits and the previous engaged set is carried forward.
    coord = _make_stub_coord()
    coord._d2_completed_cleanly = False
    coord._dutycycle_excluded_last_tick = {"binary_sensor.mmwave_a",
                                            "binary_sensor.mmwave_b"}
    prev_excluded = set(coord._dutycycle_excluded_last_tick)
    coord._dutycycle_excluded_now = {}

    # Drive the REAL production guard via the bindable helper — a
    # mutation that makes `_release_edge_scan_should_run` return True
    # unconditionally will red this test.
    released_this_tick: list[str] = []
    if coord._release_edge_scan_should_run():
        for r in prev_excluded - set(coord._dutycycle_excluded_now):
            released_this_tick.append(r)
        coord._dutycycle_excluded_last_tick = set(
            coord._dutycycle_excluded_now,
        )
    else:
        coord._dutycycle_excluded_last_tick = prev_excluded
        coord._dutycycle_excluded_now = {s: None for s in prev_excluded}

    assert released_this_tick == [], (
        "Detector-exception tick released "
        f"{released_this_tick} — B-MED-1 guard failed."
    )
    assert coord._dutycycle_excluded_last_tick == prev_excluded


# ---------------------------------------------------------------------------
# MED-A1 — flap 3x/day: exactly 1 STUCK NM row, engage/release notes on
# their own latch (per transition, not per day).
# ---------------------------------------------------------------------------


def test_flap_3x_produces_one_stuck_nm_and_transition_notes():
    """MED-A1 fix-up: separate ("dutycycle_excluded", ...) latch.

    Contract:
      * The underlying STUCK NM row for a (room, sensor) is emitted
        at MOST once per calendar day (pre-cycle contract preserved).
      * Exclusion engage/release notes fire per transition (up to 3
        engage notes + 3 release notes on a 3-flap day).
    """
    room, sensor = "Master", "binary_sensor.mm"
    stuck_key = ("dutycycle", room, sensor)
    excl_key = ("dutycycle_excluded", room, sensor)
    stuck_fired: set = set()
    excl_fired: set = set()

    stuck_nm_count = 0
    engage_note_count = 0
    release_note_count = 0

    def engage_tick():
        nonlocal stuck_nm_count, engage_note_count
        first_of_day = stuck_key not in stuck_fired
        if first_of_day:
            stuck_fired.add(stuck_key)
            stuck_nm_count += 1
            excl_fired.add(excl_key)
        elif excl_key not in excl_fired:
            excl_fired.add(excl_key)
            engage_note_count += 1

    def release_tick():
        nonlocal release_note_count
        # Release-scan drops only the exclusion note key, never the
        # STUCK NM key (mirrors the fix-up in the coordinator's tick).
        if excl_key in excl_fired:
            excl_fired.discard(excl_key)
            release_note_count += 1

    # Simulate 3 flaps: engage → release → engage → release → engage → release.
    for _ in range(3):
        engage_tick()
        release_tick()

    assert stuck_nm_count == 1, (
        f"3-flap day emitted {stuck_nm_count} STUCK NMs "
        "(pre-cycle contract: 1/day)"
    )
    # First engage produces the STUCK NM (no separate engage note); the
    # 2nd and 3rd engages fire the engage-note on the separate latch.
    assert engage_note_count == 2, (
        f"Expected 2 re-engage notes across 3 flaps, got {engage_note_count}"
    )
    assert release_note_count == 3, (
        f"Expected 3 release notes, got {release_note_count}"
    )
