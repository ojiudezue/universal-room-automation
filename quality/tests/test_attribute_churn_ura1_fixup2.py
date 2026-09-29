"""URA-ATTRIBUTE-CHURN-1 fix-up 2 (2026-09-29) — phase-gated churn
tests with stamp advance.

Fix-up 1 replaced `idle_duration`/`timeout`/`last_evidence_at` with
static timestamp anchors but published them UNCONDITIONALLY. Two
reviewers converged on a HIGH: coordinator.py:3603-3604 bumps
`_last_motion_time = now` every refresh while any sensor is active,
and coordinator.py:3638-3640 bumps `_last_occupied_time = now` every
countdown tick. So `_last_motion_time + timeout` (fix-up 1's
`timeout_at`) and `_last_occupied_time` (fix-up 1's
`last_occupied_at`) still ticked in exactly those phases.

Fix-up 2 gates each publication to the phase where the underlying
stamp is FROZEN:

  OccupiedBinarySensor:
    `timeout_at`       only when `occupancy_source == "timeout"`
                       (countdown phase; motion time frozen —
                       coordinator.py:3631-3641)
    `last_occupied_at` only while vacant (`not is_on`;
                       `_last_occupied_time` is frozen at the last
                       countdown tick before expiry — the value that
                       actually answers "when was this room last
                       occupied?")

  HVACOccupiedBinarySensor:
    `last_evidence_at` dropped entirely (still); coordinator method
                       `get_last_hvac_evidence_time()` retained for
                       HVAC consumers.

  SafetyActiveCooldownsSensor:
    `age_seconds`, `max_remaining_seconds` dropped; `cooldown_until`
    renamed to `window_until` (upper-bound suppression window; per-
    severity windows are shorter per safety.py:864-869 but the dedup
    cache keys omit severity).

Behavioural anchors (MEDIUM-1/2/3):

  * OccupiedBinarySensor actively-sensing phase — hold `is_on=True`
    steady, `occupancy_source != "timeout"`, ADVANCE
    `coord._last_motion_time` by +2.5 s between two reads. Assert
    dict equal. Under fix-up 1 unconditional-publish, `timeout_at`
    was `_last_motion_time + timeout` and would diff; under fix-up
    2's gate it is `None` in this phase (the gate is behavioural,
    not string-shape).

  * OccupiedBinarySensor countdown phase — hold `is_on=True`,
    `occupancy_source == "timeout"`, ADVANCE
    `coord._last_occupied_time` by +2.5 s. Assert dict equal. Under
    fix-up 1, `last_occupied_at` was `_last_occupied_time.isoformat()`
    and would diff; under fix-up 2 it is `None` while occupied.

  * HVACOccupiedBinarySensor full path (zone_manager wired) —
    advance `coord.get_last_hvac_evidence_time` return between two
    reads. Assert dict equal.

  * SafetyActiveCooldownsSensor — fixed `_last_alert`, patch
    `dt_util.utcnow` T0 / T0+15 s. Assert dict equal.

Each behavioural test is paired with a mutation-drill hint in its
docstring — reverting the specific fix-up 2 gate produces a failing
diff.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("homeassistant.helpers.storage")

from custom_components.universal_room_automation import binary_sensor as bs  # noqa: E402
from custom_components.universal_room_automation import sensor as sen  # noqa: E402


_UTC = timezone.utc
T0 = datetime(2026, 9, 29, 10, 0, 0, tzinfo=_UTC)
T_ADVANCE = timedelta(seconds=2.5)


# ---------------------------------------------------------------------------
# OccupiedBinarySensor — phase-gated behavioural anchors
# ---------------------------------------------------------------------------
def _make_occupied(*, is_on: bool, source: str):
    """Build an OccupiedBinarySensor via object.__new__ with a mock
    coordinator wired to the phase specified. `source` matches the
    values that coordinator.py:3616-3624 / 3641 / 3651 emit."""
    ent = object.__new__(bs.OccupiedBinarySensor)
    coord = MagicMock()
    coord._last_motion_time = T0
    coord._occupancy_timeout = 300
    coord._became_occupied_time = T0
    coord._last_occupied_state = is_on
    coord._occupancy_first_detected = T0
    coord._failsafe_fired = False
    coord._last_trigger_source = "motion"
    coord._last_lux_zone = "bright"
    coord._fan_transition_suppressed_count = 0
    coord._last_occupied_time = T0
    coord.data = {
        "timeout_remaining": 300 if is_on else 0,
        "occupancy_source": source,
        "ble_persons": [],
    }
    coord.entry.data = {"room_name": "living_room"}
    coord.entry.options = {}
    coord.automation = None
    ent.coordinator = coord
    ent.hass = MagicMock()
    ent.hass.data = {bs.DOMAIN: {}}
    type(ent).is_on = property(lambda self, _v=is_on: _v)
    return ent, coord


def test_occupied_actively_sensing_frozen_across_last_motion_stamp_advance():
    """MEDIUM-1 (actively-sensing phase): the CORE regression case
    fix-up 2 exists to close. `is_on=True`, `occupancy_source ==
    "motion"` (per coordinator.py:3616). We advance
    `coord._last_motion_time` by +2.5 s between reads (mirroring
    coordinator.py:3604 `self._last_motion_time = now` on every
    refresh while any sensor is active).

    Under fix-up 1 unconditional-publish this diffed (`timeout_at =
    _last_motion_time + 300 s` moved). Under fix-up 2's gate
    (`timeout_at` published ONLY when source == "timeout"),
    `timeout_at` is `None` in this phase => dict equal.

    Mutation drill: remove the `if _src == "timeout":` gate on
    `_timeout_at` in binary_sensor.py OccupiedBinarySensor and this
    test goes RED (proven by the drill recorded in the commit
    message)."""
    ent, coord = _make_occupied(is_on=True, source="motion")
    with patch.object(bs.dt_util, "utcnow", return_value=T0):
        a1 = dict(ent.extra_state_attributes)
    coord._last_motion_time = T0 + T_ADVANCE
    with patch.object(bs.dt_util, "utcnow", return_value=T0 + T_ADVANCE):
        a2 = dict(ent.extra_state_attributes)
    diffs = {k: (a1.get(k), a2.get(k)) for k in set(a1) | set(a2)
             if a1.get(k) != a2.get(k)}
    assert diffs == {}, (
        f"OccupiedBinarySensor emitted a stamp-derived value while "
        f"actively sensing ({diffs}) — the fix-up 1 unconditional-"
        f"publish HIGH would still be live"
    )
    # Positive: gate closed => timeout_at absent as a value.
    assert a1["timeout_at"] is None
    # Also: last_occupied_at gate closed while occupied.
    assert a1["last_occupied_at"] is None


def test_occupied_countdown_frozen_across_last_occupied_stamp_advance():
    """MEDIUM-1 (countdown phase). `is_on=True`, `occupancy_source
    == "timeout"` (per coordinator.py:3641). Coordinator.py:3638-3640
    keeps setting `_last_occupied_time = now` every countdown tick
    while `STATE_OCCUPIED` is still True — so we advance that stamp
    by +2.5 s between reads.

    Under fix-up 1's unconditional `last_occupied_at =
    _last_occupied_time.isoformat()`, this diffed. Under fix-up 2's
    `not self.is_on` gate the value is `None` while occupied.

    `_last_motion_time` is frozen in the countdown branch, so
    `timeout_at` is a legitimate static instant to publish; that
    value MUST match between reads (proves the gate is on the right
    field and the value doesn't slip)."""
    ent, coord = _make_occupied(is_on=True, source="timeout")
    with patch.object(bs.dt_util, "utcnow", return_value=T0):
        a1 = dict(ent.extra_state_attributes)
    coord._last_occupied_time = T0 + T_ADVANCE
    with patch.object(bs.dt_util, "utcnow", return_value=T0 + T_ADVANCE):
        a2 = dict(ent.extra_state_attributes)
    diffs = {k: (a1.get(k), a2.get(k)) for k in set(a1) | set(a2)
             if a1.get(k) != a2.get(k)}
    assert diffs == {}, (
        f"OccupiedBinarySensor emitted a stamp-derived value during "
        f"countdown ({diffs})"
    )
    # Positive: timeout_at exposed in countdown phase (the meaningful
    # branch); last_occupied_at gated off while occupied.
    assert a1["timeout_at"] == (T0 + timedelta(seconds=300)).isoformat()
    assert a1["last_occupied_at"] is None


def test_occupied_vacant_frozen_last_occupied_at_stable():
    """Vacant phase — `_last_occupied_time` is frozen (final
    countdown tick before expiry, per coordinator.py:3640 last-
    write). `last_occupied_at` publishes that frozen instant; the
    dict must be equal across a 15 s wall-clock advance even with
    the coordinator's `_last_motion_time` also advanced (defensive:
    prove nothing else time-derived leaks in)."""
    ent, coord = _make_occupied(is_on=False, source="none")
    with patch.object(bs.dt_util, "utcnow", return_value=T0):
        a1 = dict(ent.extra_state_attributes)
    coord._last_motion_time = T0 + timedelta(seconds=15)  # would tick
    with patch.object(bs.dt_util, "utcnow", return_value=T0 + timedelta(seconds=15)):
        a2 = dict(ent.extra_state_attributes)
    assert a1 == a2, f"vacant-phase attrs diffed: {a1} vs {a2}"
    # Positive: last_occupied_at is the frozen final-tick instant.
    assert a1["last_occupied_at"] == T0.isoformat()
    # timeout_at gated off (source is not "timeout").
    assert a1["timeout_at"] is None


# ---------------------------------------------------------------------------
# HVACOccupiedBinarySensor — MEDIUM-2 full-path behavioural anchor
# ---------------------------------------------------------------------------
def _wire_hvac_full_path():
    """Build HVACOccupiedBinarySensor + wire hass.data so the full
    `extra_state_attributes` body runs (zone_manager present,
    hvac_occupied_diag returns a fixed dict, `_display_hold` returns
    a fixed (hold, rule) tuple). Under fix-up 2 `last_evidence_at`
    is not written at all, so the returned dict is time-invariant
    across an advance of `coord.get_last_hvac_evidence_time`."""
    ent = object.__new__(bs.HVACOccupiedBinarySensor)
    coord = MagicMock()
    coord.entry.data = {"room_name": "living_room"}
    coord.entry.options = {}
    # Two consecutive calls must be able to return different stamps
    # (this is exactly what would produce the pre-fix churn).
    ev_holder = {"t": T0}
    coord.get_last_hvac_evidence_time = lambda: ev_holder["t"]
    coord.is_hvac_evidence_active = lambda: True
    ent.coordinator = coord
    ent.hass = MagicMock()

    fixed_diag = {
        "output": True, "armed": True, "source": "held",
        "tail_expires_at": (T0 + timedelta(minutes=10)).isoformat(),
        "rule": "day", "episode_start": T0.isoformat(),
        "armed_at": T0.isoformat(), "arm_span_s": 60, "arm_class": "held",
        "pending": False, "exempt_reason": None, "dwell_s": 90,
        "released_at": None, "episode_active_s": 200, "cold": False,
        "release_at": (T0 + timedelta(minutes=10)).isoformat(),
    }
    zm = SimpleNamespace(
        zones={},
        hvac_occupied_diag=lambda name: fixed_diag,
        _display_hold=lambda room_type, house_state, override_day=None,
        override_night=None, room_name=None: (120, "evidence"),
        is_zone_hvac_established=lambda zid: True,
    )
    hvac = SimpleNamespace(_zone_manager=zm, _house_state="home_day")
    manager = MagicMock()
    manager.coordinators = {"hvac": hvac, "presence": None}
    ent.hass.data = {bs.DOMAIN: {"coordinator_manager": manager}}
    return ent, ev_holder


def test_hvac_occupied_full_path_frozen_across_evidence_advance():
    """MEDIUM-2. Under fix-up 1's unconditional
    `attrs["last_evidence_at"] = _ev.isoformat()`, advancing the
    coordinator's evidence stamp diffed the dict every tick. Fix-up
    2 dropped the write entirely; the emitted dict is stable across
    the advance.

    Mutation drill: re-add
    ``attrs["last_evidence_at"] = _ev.isoformat() if hasattr(_ev,
    "isoformat") else None`` inside the try block => this test goes
    RED (proven in the commit message)."""
    ent, ev_holder = _wire_hvac_full_path()
    a1 = dict(ent.extra_state_attributes)
    ev_holder["t"] = T0 + T_ADVANCE
    a2 = dict(ent.extra_state_attributes)
    diffs = {k: (a1.get(k), a2.get(k)) for k in set(a1) | set(a2)
             if a1.get(k) != a2.get(k)}
    assert diffs == {}, (
        f"HVACOccupiedBinarySensor (full path) diffed across an "
        f"evidence-stamp advance: {diffs}"
    )
    assert "last_evidence_at" not in a1


# ---------------------------------------------------------------------------
# SafetyActiveCooldownsSensor — MEDIUM-3 behavioural anchor
# ---------------------------------------------------------------------------
def test_safety_active_cooldowns_attrs_stable_across_clock_advance():
    """MEDIUM-3. Fixed `_last_alert`, patch `dt_util.utcnow` T0 vs
    T0+15 s. Under fix-up 1 renaming `remaining` -> `cooldown_until`
    the payload was already static; fix-up 2 renames to
    `window_until` (Review LOW-3 — upper-bound semantics). This test
    is the BEHAVIOURAL anchor per Review MEDIUM-3 (source-grep
    subdict-symbol scan in test_attribute_churn_ura1.py is retained
    only as a secondary guard).

    Mutation drill: reintroduce `"age_seconds": (dt_util.utcnow() -
    last_time).total_seconds()` into the sub-dict => two reads
    differ."""
    ent = object.__new__(sen.SafetyActiveCooldownsSensor)
    ent.hass = MagicMock()

    class _Dedup:
        pass

    dedup = _Dedup()
    dedup._last_alert = {
        "smoke:kitchen": T0 - timedelta(minutes=10),
    }

    class _Safety:
        pass

    safety = _Safety()
    safety._deduplicator = dedup

    manager = MagicMock()
    manager.coordinators = {"safety": safety}
    ent.hass.data = {sen.DOMAIN: {"coordinator_manager": manager}}

    with patch.object(sen.dt_util, "utcnow", return_value=T0):
        a1 = dict(ent.extra_state_attributes)
    with patch.object(sen.dt_util, "utcnow", return_value=T0 + timedelta(seconds=15)):
        a2 = dict(ent.extra_state_attributes)
    assert a1 == a2, (
        f"SafetyActiveCooldownsSensor attrs diffed across a 15 s "
        f"clock advance with a fixed _last_alert: {a1} vs {a2}"
    )
    cooldowns = a1["cooldowns"]
    assert "smoke:kitchen" in cooldowns
    entry = cooldowns["smoke:kitchen"]
    assert set(entry.keys()) == {"last_alert", "window_until"}, (
        f"unexpected keys in cooldowns sub-dict: {sorted(entry.keys())}"
    )
    # `window_until` = last_alert + 3600 s (upper-bound suppression
    # window; per-severity windows are shorter per safety.py:864-869
    # but the dedup cache keys omit severity).
    assert entry["window_until"] == (
        T0 - timedelta(minutes=10) + timedelta(seconds=3600)
    ).isoformat()
