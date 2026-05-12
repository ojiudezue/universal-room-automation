"""v4.5.17 — Bayesian eval dt_util import fix (Phase 2).

v4.5.16 Phase 1 surfaced the silent failure mode: every Bayesian
accuracy eval since the feature was added (v4.0.0-B2) has died with
`NameError: name 'dt_util' is not defined` at `__init__.py:1171`. The
closure uses `dt_util.now()` / `dt_util.utcnow()` but never imports it.
Module-level imports also don't include `dt_util`, only function-local
imports elsewhere (e.g., `__init__.py:2375`).

v4.5.17 adds the missing function-local import inside the closure body.
One-line fix. Same pattern as the existing line 2375.

Tests below pin:
1. The import statement is present inside `_bayesian_accuracy_eval`
2. `dt_util.now()` and `dt_util.utcnow()` remain in the closure body
   (catches accidental rewrite that breaks the binding)
3. The import is INSIDE the try-block so the WARNING log still fires
   if HA's util layout ever changes (defensive)
"""

import ast

import pytest


@pytest.fixture(scope="module")
def init_src() -> str:
    with open("custom_components/universal_room_automation/__init__.py") as f:
        return f.read()


def _find_closure_body(src: str) -> str:
    """Return the text of the `_bayesian_accuracy_eval` async-def body.

    Closure is ~80 lines; anchor on the registration call to bound the
    end so we capture the whole body including its `except` block.
    """
    start = src.find("async def _bayesian_accuracy_eval")
    assert start >= 0, "Closure _bayesian_accuracy_eval not found"
    end = src.find("async_track_time_change(", start)
    assert end > start, "Closure body end (registration call) not found"
    return src[start:end]


def test_closure_imports_dt_util(init_src: str):
    """Phase 2 fix: dt_util MUST be imported inside the closure body."""
    body = _find_closure_body(init_src)
    assert "from homeassistant.util import dt as dt_util" in body, (
        "v4.5.17 Phase 2 fix is missing: the closure must import "
        "dt_util function-locally. Without this, every eval fails with "
        "NameError (see v4.5.16 Phase 1 diagnostic for evidence)."
    )


def test_closure_uses_dt_util_now_and_utcnow(init_src: str):
    """Pin the function calls so an accidental refactor (e.g., swap to
    `datetime.now()`) still has visible coupling to the import.
    """
    body = _find_closure_body(init_src)
    assert "dt_util.now()" in body, (
        "Closure must reference dt_util.now() to compute local-time bin "
        "boundary. If you swapped to datetime.now(timezone), update this "
        "test and ensure the import is consistent."
    )
    assert "dt_util.utcnow()" in body, (
        "Closure must reference dt_util.utcnow() for UTC ISO timestamp."
    )


def test_dt_util_import_inside_try_block(init_src: str):
    """Defensive: the import should be inside the try-block so any
    future HA util layout change still surfaces via the v4.5.16 WARNING
    log, not as another silent NameError.
    """
    body = _find_closure_body(init_src)
    # Find the try block boundaries
    try_idx = body.find("try:")
    except_idx = body.find("except Exception as exc:")
    assert try_idx >= 0 and except_idx > try_idx, (
        "Could not locate try/except boundary in closure"
    )
    try_block = body[try_idx:except_idx]
    assert "from homeassistant.util import dt as dt_util" in try_block, (
        "v4.5.17: the dt_util import should be INSIDE the try-block. "
        "If HA's util layout ever changes, the WARNING log surfaces it. "
        "Outside the try-block, an import failure would be silent again."
    )


def test_closure_remains_a_valid_async_def(init_src: str):
    """Catch any AST-level breakage from the v4.5.17 edit."""
    tree = ast.parse(init_src)
    found = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_bayesian_accuracy_eval"
        ):
            found = True
            # Verify the function body is non-trivial. The closure
            # is structured as: docstring + try-block. Two top-level
            # statements is the expected shape; truncation would show 1.
            assert len(node.body) >= 2, (
                f"_bayesian_accuracy_eval has only {len(node.body)} "
                "top-level statements — looks truncated"
            )
            break
    assert found, "_bayesian_accuracy_eval not found as an AsyncFunctionDef"


def test_v4516_phase1_warning_log_still_in_place(init_src: str):
    """The v4.5.16 Phase 1 diagnostic must remain — without it, future
    silent failures would re-hide. Tier 1 regression guard.
    """
    assert "exc_info=True" in init_src, (
        "v4.5.16 Phase 1 diagnostic (exc_info=True on the exception "
        "warning) must remain. Without it, the next silent failure "
        "mode is invisible."
    )
    # And the WARNING level must still be in the eval failure path
    fail_idx = init_src.find("Bayesian accuracy eval failed")
    assert fail_idx >= 0
    window = init_src[max(0, fail_idx - 300):fail_idx + 100]
    assert "_LOGGER.warning" in window, (
        "Bayesian eval failure log must remain at WARNING level "
        "(not reverted to debug)."
    )
