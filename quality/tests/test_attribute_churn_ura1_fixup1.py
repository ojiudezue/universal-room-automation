"""URA-ATTRIBUTE-CHURN-1 fix-up 1 (2026-09-29) — behavioural anchors.

Orchestrator verification of the initial URA-ATTRIBUTE-CHURN-1 ship
found the fix partial. Live recorder, last 26 h, steady-state
rewrites (consecutive rows with identical state, keyed by which
attribute changed):

  binary_sensor.living_room_occupied (22,653 rewrites)
    idle_duration 12,828 | last_motion 6,020 | timeout 3,845
    fan_interference_hold_expires_at 470 | substrate_kinds 338
    tier1_provenance 309

  binary_sensor.living_room_living_room_hvac_occupied (4,193 rewrites)
    last_evidence_at 3,942 | kinds_active 355 | source 67
    hold/tail_expires_at 47

`last_motion` (initial ship) is a MINORITY of the writes.
`idle_duration` and `timeout` on OccupiedBinarySensor, and
`last_evidence_at` on HVACOccupiedBinarySensor, are the actual
dominant drivers — all three are wall-clock-derived values embedded
in `extra_state_attributes` that changed every coordinator refresh
tick even though the underlying transition set was stable.

Fix (see binary_sensor.py):

  * OccupiedBinarySensor:
      - `idle_duration` DROPPED; replaced with static
        `last_occupied_at` (ISO of `_last_occupied_time` — a
        datetime that only moves on a real occupied tick).
      - `timeout` DROPPED; replaced with static `timeout_at` (ISO
        of `_last_motion_time + _occupancy_timeout` — the wall-clock
        instant the vacancy timer would expire; static within a
        vacancy episode).

  * HVACOccupiedBinarySensor:
      - `last_evidence_at` DROPPED entirely (the underlying
        `_last_hvac_evidence_time` is bumped every motion tick in
        coordinator.py:5477; the attribute is diagnostic only, and
        real consumers call `get_last_hvac_evidence_time()` on the
        coordinator directly — hvac.py:4668, hvac_zones.py:1756,
        hvac_zones.py:1899).

Each anchor here is BEHAVIOURAL: it constructs the entity via
`object.__new__` (bypassing the ConfigEntry-heavy `__init__`), wires
a minimal mock coordinator with the private attrs the property reads,
and calls `extra_state_attributes` TWICE with `dt_util.utcnow` patched
to two different instants. The invariant is that the emitted dict is
byte-identical across the clock advance (the underlying
transition-state is unchanged; only wall-clock moved). A mutation
that re-introduces `dt_util.utcnow()` / `now`-derived math into a
value causes the two dicts to differ → the test goes RED.

The earlier AST source-grep anchors in test_attribute_churn_ura1.py
remain as a secondary guard against the churn keys being re-added by
name; these are the primary behavioural guarantee.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("homeassistant.helpers.storage")

from custom_components.universal_room_automation import binary_sensor as bs  # noqa: E402


_UTC = timezone.utc
T0 = datetime(2026, 9, 29, 10, 0, 0, tzinfo=_UTC)
T1 = datetime(2026, 9, 29, 10, 0, 15, tzinfo=_UTC)  # +15s wall-clock tick


def _make_occupied_entity(*, is_on: bool = True):
    """Build an OccupiedBinarySensor without invoking __init__.

    The property `extra_state_attributes` reads a handful of
    coordinator private attributes plus `hass.data[DOMAIN]`. Mock
    both surfaces; leave every optional lookup path (person
    coordinator, presence substrate, HVAC zone manager) at MagicMock
    default so the try/except-guarded branches take their "degraded"
    default (`{}` / `[]` / `""`) — the guards' happy path is not
    under test here; only the wall-clock-independence invariant is.
    """
    ent = object.__new__(bs.OccupiedBinarySensor)
    coord = MagicMock()
    coord._last_motion_time = T0
    coord._occupancy_timeout = 300
    coord._became_occupied_time = T0
    coord._last_occupied_state = True
    coord._occupancy_first_detected = T0
    coord._failsafe_fired = False
    coord._last_trigger_source = "motion"
    coord._last_lux_zone = "bright"
    coord._fan_transition_suppressed_count = 0
    coord._last_occupied_time = T0
    coord.data = {
        "timeout_remaining": 300,
        "occupancy_source": "motion",
        "ble_persons": [],
    }
    coord.entry.data = {"room_name": "living_room"}
    coord.entry.options = {}
    coord.automation = None
    ent.coordinator = coord
    ent.hass = MagicMock()
    ent.hass.data = {bs.DOMAIN: {}}
    # is_on is a normal @property on the class reading coordinator
    # data; the returned attr shape depends on it (idle_duration
    # branch pre-fix). Override for determinism per test.
    type(ent).is_on = property(lambda self, _v=is_on: _v)
    return ent


def _make_hvac_entity():
    """Build an HVACOccupiedBinarySensor without invoking __init__.

    The property reads `hass.data[DOMAIN]["coordinator_manager"]`.
    Leaving it unset drives the early `zm is None` return — an empty
    attrs dict. That's fine for this test: dropping `last_evidence_at`
    is proven when EVERY branch (including the degraded early-return)
    omits the key across a clock advance. The complementary path (zm
    present, `last_evidence_at` still absent) is anchored by the AST
    test in test_attribute_churn_ura1_fixup1_ast below.
    """
    ent = object.__new__(bs.HVACOccupiedBinarySensor)
    coord = MagicMock()
    coord.entry.data = {"room_name": "living_room"}
    coord.entry.options = {}
    # Real consumers still call this method — keep it callable so
    # we can prove the method is untouched even though the attr is
    # gone (see test_get_last_hvac_evidence_time_method_intact).
    coord.get_last_hvac_evidence_time = lambda: T0
    coord.is_hvac_evidence_active = lambda: True
    ent.coordinator = coord
    ent.hass = MagicMock()
    ent.hass.data = {bs.DOMAIN: {}}  # no coordinator_manager => early return
    return ent


# ---------------------------------------------------------------------------
# Behavioural — OccupiedBinarySensor
# ---------------------------------------------------------------------------
def test_occupied_extra_attrs_identical_across_clock_advance_when_occupied():
    """Steady occupied + wall-clock +15s => dict is byte-identical.

    Mutation drill: re-introduce `attrs["idle_duration"] = 0` or the
    live `attrs[ATTR_TIMEOUT] = ...timeout_remaining` — nothing
    changes on the occupied branch for the DICT since both are
    static in that state (0 and 300 respectively). This test is
    therefore the ANCHOR for the general invariant on the occupied
    branch: the DROPPED keys stay dropped and no new time-derived
    keys are introduced. The vacant-branch anchor below carries the
    real live-countdown drill weight."""
    ent = _make_occupied_entity(is_on=True)
    with patch.object(bs.dt_util, "utcnow", return_value=T0):
        a1 = dict(ent.extra_state_attributes)
    with patch.object(bs.dt_util, "utcnow", return_value=T1):
        a2 = dict(ent.extra_state_attributes)
    diffs = {k: (a1.get(k), a2.get(k)) for k in set(a1) | set(a2)
             if a1.get(k) != a2.get(k)}
    assert diffs == {}, (
        f"OccupiedBinarySensor.extra_state_attributes changed across a "
        f"15s clock advance under steady occupied state — write-"
        f"amplification regression. Diffs: {diffs}"
    )
    # Positive confirmations. Fix-up 2 gates `last_occupied_at` off
    # while occupied and `timeout_at` off when source != "timeout";
    # both are keys-present-but-None in this phase (the occupied
    # branch on a "motion" source per _make_occupied_entity). The
    # cross-clock equality above is the load-bearing invariant.
    assert "last_occupied_at" in a1 and a1["last_occupied_at"] is None
    assert "timeout_at" in a1 and a1["timeout_at"] is None
    assert "idle_duration" not in a1
    assert "timeout" not in a1
    assert "last_motion" not in a1


def test_occupied_extra_attrs_identical_across_clock_advance_when_vacant():
    """Steady VACANT + wall-clock +15s => dict is byte-identical.

    This is the load-bearing drill. Pre-fix, `idle_duration` read
    STATE_TIME_SINCE_OCCUPIED (an int seconds-since-last-occupied
    computed at the coordinator refresh from `now`) and `timeout`
    read STATE_TIMEOUT_REMAINING (`max(0, occupancy_timeout - (now
    - _last_motion_time))`). Both would tick every refresh. With
    the fix they are replaced by `last_occupied_at` and `timeout_at`
    (both static within a vacancy episode). Mutation drill: revert
    either substitution => this test goes RED on the vacant branch."""
    ent = _make_occupied_entity(is_on=False)
    ent.coordinator.data = {
        "timeout_remaining": 42,  # a live countdown would be here
        "occupancy_source": "none",
        "ble_persons": [],
    }
    with patch.object(bs.dt_util, "utcnow", return_value=T0):
        a1 = dict(ent.extra_state_attributes)
    with patch.object(bs.dt_util, "utcnow", return_value=T1):
        a2 = dict(ent.extra_state_attributes)
    diffs = {k: (a1.get(k), a2.get(k)) for k in set(a1) | set(a2)
             if a1.get(k) != a2.get(k)}
    assert diffs == {}, (
        f"OccupiedBinarySensor (vacant branch) attrs changed across "
        f"a 15s clock advance — countdown or since-time key was "
        f"re-introduced. Diffs: {diffs}"
    )
    assert "idle_duration" not in a1
    assert "timeout" not in a1
    assert "last_occupied_at" in a1
    assert "timeout_at" in a1


# ---------------------------------------------------------------------------
# Behavioural — HVACOccupiedBinarySensor
# ---------------------------------------------------------------------------
def test_hvac_occupied_extra_attrs_omit_last_evidence_at_and_are_stable():
    """The HVACOccupiedBinarySensor path with no coordinator_manager
    takes the early `zm is None` return => empty dict. That empty
    dict is trivially stable across a clock advance, and — crucially
    — does NOT contain `last_evidence_at`. The complementary path
    (zm present) is anchored by AST test test_hvac_occupied_no_
    last_evidence_at_in_source, so the two together prove the key
    is gone from BOTH branches."""
    ent = _make_hvac_entity()
    with patch.object(bs.dt_util, "utcnow", return_value=T0):
        a1 = dict(ent.extra_state_attributes)
    with patch.object(bs.dt_util, "utcnow", return_value=T1):
        a2 = dict(ent.extra_state_attributes)
    assert a1 == a2, (
        f"HVACOccupiedBinarySensor attrs changed across clock advance "
        f"even on the degraded early-return path: {a1} vs {a2}"
    )
    assert "last_evidence_at" not in a1


def test_get_last_hvac_evidence_time_method_intact():
    """The coordinator method is the load-bearing consumer surface —
    hvac.py:4668, hvac_zones.py:1756/1899 all call it directly.
    Dropping the ATTRIBUTE must not touch the METHOD. Anchor: a
    source-grep of the getter name on coordinator.py."""
    import os
    p = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..",
        "custom_components", "universal_room_automation", "coordinator.py",
    ))
    with open(p) as fh:
        src = fh.read()
    assert "def get_last_hvac_evidence_time" in src, (
        "coordinator.get_last_hvac_evidence_time was removed — "
        "HVAC consumers (hvac.py, hvac_zones.py) will break"
    )


# ---------------------------------------------------------------------------
# Secondary guard — source-grep anchors for the dropped keys.
#
# The behavioural tests above are the primary invariant. These
# source-shape checks anchor the "belt-and-suspenders"
# `_unrecorded_attributes` declaration + prove the dropped key
# strings are not present in the value-position of any returned dict
# on the touched classes.
# ---------------------------------------------------------------------------
import ast  # noqa: E402
import os  # noqa: E402

_BS_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation", "binary_sensor.py",
))


def _class_method(class_name: str, method_name: str) -> ast.AST:
    with open(_BS_PATH) as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if (
                    isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and stmt.name == method_name
                ):
                    return stmt
    raise AssertionError(f"{class_name}.{method_name} not found")


def _dict_keys_in(node: ast.AST) -> set[str]:
    keys: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
        # Also catch `attrs["x"] = ...` assignments.
        if (
            isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Subscript)
            and isinstance(n.targets[0].slice, ast.Constant)
            and isinstance(n.targets[0].slice.value, str)
        ):
            keys.add(n.targets[0].slice.value)
    return keys


def test_occupied_source_omits_idle_duration_and_timeout_keys():
    func = _class_method("OccupiedBinarySensor", "extra_state_attributes")
    keys = _dict_keys_in(func)
    assert "idle_duration" not in keys, (
        "OccupiedBinarySensor.extra_state_attributes reintroduced "
        "'idle_duration' — write-amplification regression"
    )
    assert "timeout" not in keys, (
        "OccupiedBinarySensor.extra_state_attributes reintroduced "
        "'timeout' — write-amplification regression"
    )
    # Positive substitutes:
    assert "last_occupied_at" in keys
    assert "timeout_at" in keys


def test_hvac_occupied_no_last_evidence_at_in_source():
    func = _class_method(
        "HVACOccupiedBinarySensor", "extra_state_attributes",
    )
    keys = _dict_keys_in(func)
    assert "last_evidence_at" not in keys, (
        "HVACOccupiedBinarySensor reintroduced 'last_evidence_at' — "
        "write-amplification regression (was 3,942 rewrites / 26 h)"
    )
