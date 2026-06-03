"""Regression test for v4.7.18.2 — boot warning log-once guard.

Bug class: cosmetic log-spam from per-entity fan-out.

PROBLEM:
    `ZoneSensorBase._check_coordinators` (aggregation.py) emits a
    `_LOGGER.warning("Zone '%s': No room coordinators found after %ds ...")`
    when the 60s retry window expires. Each zone sensor ENTITY runs its own
    retry timer, so for a zone whose room coordinators never register, every
    one of its ~20 entities emits the same warning simultaneously at t=60s.

FIX:
    Per-entity `_coordinator_warning_logged` bool initialized in
    `ZoneSensorBase.__init__`, reset on `async_added_to_hass`, and checked
    before logging — so each entity emits the warning at most once per add
    lifecycle. Retry/discovery behavior is unchanged.

TEST STRATEGY:
    AST/source assertion (NOT behavioral). Justification: exercising the
    behavior would require mocking the periodic-time-interval scheduler,
    a fake entity-lifecycle registration, and a log-capture handler — heavy
    machinery for a 15-LoC cosmetic fix. The risk we're guarding against is
    "someone deletes the guard during a future refactor," which AST assertions
    catch reliably. The guard is small, declarative, and has no branchy
    runtime behavior worth simulating.
"""

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
AGGREGATION_PATH = (
    REPO_ROOT
    / "custom_components"
    / "universal_room_automation"
    / "aggregation.py"
)


@pytest.fixture(scope="module")
def aggregation_tree():
    """Parse aggregation.py once per module."""
    source = AGGREGATION_PATH.read_text()
    return ast.parse(source), source


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"Class {name!r} not found in aggregation.py")


def _find_method(cls: ast.ClassDef, name: str) -> ast.FunctionDef:
    for node in cls.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError(f"Method {name!r} not found in {cls.name}")


def test_init_sets_log_once_guard(aggregation_tree):
    """ZoneSensorBase.__init__ must initialize _coordinator_warning_logged=False."""
    tree, _ = aggregation_tree
    cls = _find_class(tree, "ZoneSensorBase")
    init = _find_method(cls, "__init__")

    found = False
    for node in ast.walk(init):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and target.attr == "_coordinator_warning_logged"
            ):
                # Confirm it's initialized to False (a literal, not derived).
                assert isinstance(node.value, ast.Constant) and node.value.value is False, (
                    "_coordinator_warning_logged must be initialized to literal False "
                    "in ZoneSensorBase.__init__"
                )
                found = True
    assert found, (
        "ZoneSensorBase.__init__ must initialize "
        "self._coordinator_warning_logged for v4.7.18.2 boot-warning log-once guard"
    )


def test_async_added_resets_log_once_guard(aggregation_tree):
    """async_added_to_hass must reset _coordinator_warning_logged on (re-)add.

    Lifecycle reset matters because an entity may be removed and re-added
    (e.g. config-entry reload). A fresh add should get its single warning.
    """
    tree, _ = aggregation_tree
    cls = _find_class(tree, "ZoneSensorBase")
    method = _find_method(cls, "async_added_to_hass")

    found = False
    for node in ast.walk(method):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and target.attr == "_coordinator_warning_logged"
                and isinstance(node.value, ast.Constant)
                and node.value.value is False
            ):
                found = True
    assert found, (
        "ZoneSensorBase.async_added_to_hass must reset "
        "self._coordinator_warning_logged = False so a re-added entity can "
        "emit its single warning"
    )


def test_warning_is_guarded_by_log_once_flag(aggregation_tree):
    """The 'No room coordinators found after' warning must be inside a guard
    that checks `not self._coordinator_warning_logged` and sets it True after
    emitting. Otherwise every zone entity emits the same line per restart."""
    _, source = aggregation_tree

    # Locate the warning call in source — the literal string is unique.
    warning_marker = "No room coordinators found after"
    assert warning_marker in source, (
        "Expected warning literal not found — was the warning relocated?"
    )

    # Parse the warning's enclosing function and confirm structural guard.
    tree = ast.parse(source)
    cls = _find_class(tree, "ZoneSensorBase")
    method = _find_method(cls, "async_added_to_hass")

    warning_call = None
    enclosing_if = None
    sets_flag_after = False

    for node in ast.walk(method):
        if not isinstance(node, ast.If):
            continue
        # Look for `if not self._coordinator_warning_logged:`
        test = node.test
        is_guard = (
            isinstance(test, ast.UnaryOp)
            and isinstance(test.op, ast.Not)
            and isinstance(test.operand, ast.Attribute)
            and isinstance(test.operand.value, ast.Name)
            and test.operand.value.id == "self"
            and test.operand.attr == "_coordinator_warning_logged"
        )
        if not is_guard:
            continue

        # Inside this guard, look for _LOGGER.warning(...) containing the marker
        # and an assignment self._coordinator_warning_logged = True.
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                func = inner.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "warning"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "_LOGGER"
                ):
                    # Check if any argument string contains the marker
                    for arg in inner.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            if warning_marker in arg.value:
                                warning_call = inner
                                enclosing_if = node
            if isinstance(inner, ast.Assign):
                for target in inner.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and target.attr == "_coordinator_warning_logged"
                        and isinstance(inner.value, ast.Constant)
                        and inner.value.value is True
                    ):
                        sets_flag_after = True

    assert warning_call is not None and enclosing_if is not None, (
        "The 'No room coordinators found after' warning must be inside "
        "`if not self._coordinator_warning_logged:` guard"
    )
    assert sets_flag_after, (
        "After emitting the warning, the guard block must set "
        "self._coordinator_warning_logged = True so subsequent invocations "
        "do not re-emit"
    )
