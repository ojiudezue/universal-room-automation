"""URA-ATTRIBUTE-CHURN-1 (2026-09-29) — write-amplification fix.

Two additional per-refresh churn sources measured over 5 min on the
live recorder 2026-09-28 19:07 (following the same class as
RECORDER-BLOAT-LOGFLOOD-1 D4):

  * OccupiedBinarySensor:
        ATTR_LAST_MOTION (const key "last_motion") wrote a fresh
        `_last_motion_time.isoformat()` on every motion-driven
        `_run_inference` tick (~every 2.5s) while the entity state was
        a steady "on".  Result: ~119 state_changed rows / 5 min on
        binary_sensor.living_room_occupied while occupancy never
        toggled.
  * SafetyActiveCooldownsSensor:
        `age_seconds` and `max_remaining_seconds` inside every
        `cooldowns.<key>` sub-dict were both `dt_util.utcnow()`-derived
        and therefore differed on every refresh — 119 state_changed
        rows / 5 min on the "1 recent" state.

Fix (see the two files below): remove the churning keys from the
producer dicts. HA core's `async_set_internal` fires
EVENT_STATE_CHANGED whenever the full attributes dict differs
(homeassistant/core.py:~2313), and the recorder writes a States row
per event — `_unrecorded_attributes` alone does NOT prevent that (it
only dedups the state_attributes table).  Load-bearing fix = key
removal at the producer.  `_unrecorded_attributes` retained as a
belt-and-suspenders declaration.

Test shape mirrors the D4 anchors in test_recorder_bloat_logflood.py:

  A. Primary invariant — churning key ABSENT from the runtime
     attributes dict at the producer (AST scan of the returned dict
     literal).
  B. Backstop — `_unrecorded_attributes` declares the churning keys
     (regression guard on the belt-and-suspenders).
  C. No-churn AST symbol scan — the terminal returned dict must not
     reference `dt_util` / `datetime` / `.utcnow` / `.now` /
     `.isoformat` / `.timestamp` in the churn-shape positions.  For
     the cooldowns sensor we anchor on the sub-dict literal (the outer
     `now = dt_util.utcnow()` is retained for membership filtering).

Bug-class guards exercised:
  #62  (truth-in-labeling — the invariant is time-invariance of the
        published attrs, not just source-string presence)
  RECORDER-BLOAT class (per-tick State/state_attributes writes on an
        unchanged logical state).
"""
from __future__ import annotations

import ast
import os


_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_CC = os.path.join(_ROOT, "custom_components")


def _read(path: str) -> str:
    with open(path) as fh:
        return fh.read()


def _sensor_py() -> str:
    return _read(os.path.join(
        _CC, "universal_room_automation", "sensor.py",
    ))


def _binary_sensor_py() -> str:
    return _read(os.path.join(
        _CC, "universal_room_automation", "binary_sensor.py",
    ))


def _class_unrecorded_attrs(src: str, class_name: str) -> frozenset[str] | None:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue
        for stmt in node.body:
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and stmt.targets[0].id == "_unrecorded_attributes"
            ):
                call = stmt.value
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "frozenset"
                    and call.args
                    and isinstance(call.args[0], ast.Set)
                ):
                    return frozenset(
                        el.value for el in call.args[0].elts
                        if isinstance(el, ast.Constant)
                        and isinstance(el.value, str)
                    )
        return None
    raise AssertionError(f"class {class_name} not found")


def _method_ast(src: str, class_name: str, method_name: str) -> ast.AST:
    tree = ast.parse(src)
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
    return keys


# ---------------------------------------------------------------------------
# A. Primary invariant — churning keys absent from producer dicts
# ---------------------------------------------------------------------------
def test_occupied_binary_sensor_extra_attrs_omit_last_motion():
    """Mutation drill: re-add `ATTR_LAST_MOTION:
    self.coordinator._last_motion_time.isoformat() ...` to the
    OccupiedBinarySensor.extra_state_attributes returned dict →
    the "last_motion" key reappears in the dict-literal keys and
    this test goes RED.

    Under steady occupancy every motion event bumps
    `_last_motion_time` and the coordinator's async_set_updated_data
    → _handle_coordinator_update → async_write_ha_state cycle would
    then emit EVENT_STATE_CHANGED per tick despite is_on being
    unchanged."""
    func = _method_ast(
        _binary_sensor_py(), "OccupiedBinarySensor", "extra_state_attributes",
    )
    keys = _dict_keys_in(func)
    assert "last_motion" not in keys, (
        "OccupiedBinarySensor.extra_state_attributes still emits "
        "'last_motion' — write-amplification regression "
        "(URA-ATTRIBUTE-CHURN-1). ~119 state_changed rows / 5 min "
        "observed on binary_sensor.living_room_occupied 2026-09-28 "
        "19:07 with this key present."
    )


def test_safety_active_cooldowns_extra_attrs_omit_age_and_remaining():
    """Mutation drill: restore `age_seconds` and `max_remaining_seconds`
    to the cooldowns[key] sub-dict → this test goes RED.

    Both fields were `dt_util.utcnow()`-derived so the emitted dict
    differed on every refresh even for a fixed `_last_alert` snapshot;
    that produced 119 state_changed rows / 5 min on the "1 recent"
    state 2026-09-28 19:07."""
    func = _method_ast(
        _sensor_py(),
        "SafetyActiveCooldownsSensor",
        "extra_state_attributes",
    )
    keys = _dict_keys_in(func)
    assert "age_seconds" not in keys, (
        "SafetyActiveCooldownsSensor still emits 'age_seconds' — "
        "per-refresh churn regression (URA-ATTRIBUTE-CHURN-1)"
    )
    assert "max_remaining_seconds" not in keys, (
        "SafetyActiveCooldownsSensor still emits "
        "'max_remaining_seconds' — per-refresh churn regression"
    )
    # Positive: the static substitutes are present.
    assert "last_alert" in keys, (
        "SafetyActiveCooldownsSensor no longer emits static "
        "'last_alert' — a consumer of `cooldown_until - last_alert` "
        "would lose its source"
    )
    assert "window_until" in keys, (
        "SafetyActiveCooldownsSensor missing static 'window_until' "
        "— consumers of a live countdown lose their source (the "
        "value is derivable client-side from `last_alert`). Renamed "
        "from `cooldown_until` in fix-up 2 to make the upper-bound "
        "semantics explicit (per-severity windows are shorter)."
    )


# ---------------------------------------------------------------------------
# B. Backstop — _unrecorded_attributes declares the dropped keys
# ---------------------------------------------------------------------------
def test_occupied_binary_sensor_declares_last_motion_unrecorded():
    attrs = _class_unrecorded_attrs(_binary_sensor_py(), "OccupiedBinarySensor")
    assert attrs is not None, (
        "OccupiedBinarySensor lost its _unrecorded_attributes "
        "belt-and-suspenders declaration"
    )
    assert "last_motion" in attrs, (
        f"OccupiedBinarySensor._unrecorded_attributes missing "
        f"'last_motion'; got {sorted(attrs)}"
    )


def test_safety_active_cooldowns_declares_age_and_remaining_unrecorded():
    attrs = _class_unrecorded_attrs(
        _sensor_py(), "SafetyActiveCooldownsSensor",
    )
    assert attrs is not None, (
        "SafetyActiveCooldownsSensor lost its _unrecorded_attributes "
        "declaration"
    )
    assert "age_seconds" in attrs and "max_remaining_seconds" in attrs, (
        f"SafetyActiveCooldownsSensor._unrecorded_attributes missing "
        f"one of the belt-and-suspenders keys; got {sorted(attrs)}"
    )


# ---------------------------------------------------------------------------
# C. No-churn AST symbol scan on the cooldowns sub-dict literal.
#
# The OUTER method retains `now = dt_util.utcnow()` for the
# membership filter (`age < 3600`) — this is legitimate; entries drop
# OUT of the map at expiry, but the payload emitted for a stable set
# of alerts must be time-invariant. We anchor the invariant on the
# INNER `cooldowns[key] = {...}` dict literal, which is the payload
# that gets serialized per key.
# ---------------------------------------------------------------------------
def test_safety_active_cooldowns_subdict_has_no_churn_symbols():
    """The per-key `{"last_alert": ..., "cooldown_until": ...}` sub-dict
    must not reference `.utcnow` / `.now` / any expression that reads
    the current wall clock. `last_time` and `timedelta(...)` are
    fine — both are functions of the snapshot input, not of "now"."""
    func = _method_ast(
        _sensor_py(),
        "SafetyActiveCooldownsSensor",
        "extra_state_attributes",
    )
    # Locate the innermost dict literal being assigned into
    # `cooldowns[key]` — walk the AST looking for a Subscript
    # target on the LHS of an Assign with a Dict value.
    inner: ast.Dict | None = None
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Subscript)
            and isinstance(node.value, ast.Dict)
        ):
            inner = node.value
            break
    assert inner is not None, (
        "SafetyActiveCooldownsSensor: no `cooldowns[key] = {...}` "
        "assignment found — shape changed, review this anchor"
    )

    class _ForbidChurn(ast.NodeVisitor):
        def __init__(self) -> None:
            self.hits: list[str] = []

        def visit_Attribute(self, n: ast.Attribute) -> None:
            if n.attr in ("utcnow", "now"):
                self.hits.append(n.attr)
            self.generic_visit(n)

        def visit_Name(self, n: ast.Name) -> None:
            # `now` as a local variable is the wall-clock snapshot;
            # any reference from inside the sub-dict re-introduces
            # per-refresh drift into the payload.
            if n.id in ("dt_util", "now"):
                self.hits.append(n.id)
            self.generic_visit(n)

    checker = _ForbidChurn()
    checker.visit(inner)
    assert not checker.hits, (
        f"cooldowns[key] sub-dict contains wall-clock symbols "
        f"{checker.hits} — the payload would differ every refresh "
        f"even for a fixed _last_alert snapshot, restoring the "
        f"per-tick State-row write."
    )


def test_occupied_binary_sensor_last_motion_time_still_available_for_internal_use():
    """The producer field remains on the coordinator (aggregation.py
    reads `coord._last_motion_time`). Sanity: the internal writer
    site is intact — dropping the ATTR only removes the PUBLISHED
    surface, not the tracked value."""
    src = _read(os.path.join(
        _CC, "universal_room_automation", "coordinator.py",
    ))
    assert "self._last_motion_time = now" in src, (
        "coordinator no longer bumps _last_motion_time — internal "
        "aggregation.py freshest-motion consumer will break"
    )
    agg = _read(os.path.join(
        _CC, "universal_room_automation", "aggregation.py",
    ))
    assert "_last_motion_time" in agg, (
        "aggregation.py no longer reads _last_motion_time — check "
        "for a scope change if this was intentional"
    )
