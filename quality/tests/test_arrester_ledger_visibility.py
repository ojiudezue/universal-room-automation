"""ARRESTER-LEDGER-INVISIBLE-1 — arrester decisions must reach the DURABLE ledger.

THE SCAR THIS GUARDS. The arrester recorded its decisions only as `_LOGGER.info`
lines while URA's log keeps WARNING and above, so every arrest was erased as it
was written. That was not cosmetic: on 2026-08-20 a live override could not be
confirmed OR ruled out afterwards, and on 2026-09-16 three separate
investigations stalled in one night because a thermostat write that demonstrably
happened could not be attributed to anything.

THE TESTS DISCRIMINATE. A guard that logged everything, or nothing, would pass a
naive "a row appeared" assertion. So we assert BOTH directions:
  * a real override writes a row, with the fields a reader needs to attribute it
  * a NON-override state change writes NO row
and separately that the write is fail-open — observability must never be able to
prevent an arrest.
"""
from __future__ import annotations

import ast
import pathlib

import pytest


SRC = pathlib.Path(__file__).resolve().parents[2].joinpath(
    "custom_components", "universal_room_automation", "domain_coordinators",
    "hvac_override.py"
)


def _fn(name: str):
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node, tree
    raise AssertionError(f"{name} not found in hvac_override.py")


def test_ledger_helper_exists_and_is_fail_open():
    """The helper must swallow every exception.

    If a ledger write could raise, observability would be able to PREVENT an
    arrest — strictly worse than the invisibility it replaces.
    """
    node, _ = _fn("_arrest_ledger")
    handlers = [n for n in ast.walk(node) if isinstance(n, ast.ExceptHandler)]
    assert handlers, "_arrest_ledger must wrap its work in try/except (fail-open)"
    # The except must be broad — a narrow catch would still let the arrester die.
    assert any(
        h.type is None or (isinstance(h.type, ast.Name) and h.type.id == "Exception")
        for h in handlers
    ), "_arrest_ledger's except must be broad enough to never propagate"


def test_ledger_helper_never_blocks_the_decision_path():
    """It must fire-and-forget, not await — an arrest must not wait on logging."""
    node, _ = _fn("_arrest_ledger")
    assert not [n for n in ast.walk(node) if isinstance(n, ast.Await)], (
        "_arrest_ledger must not await; it should hand off via async_create_task "
        "so a slow DB write cannot delay a corrective thermostat action"
    )
    src = ast.get_source_segment(SRC.read_text(), node) or ""
    assert "async_create_task" in src


def _ledger_calls():
    """Return the _arrest_ledger call nodes inside _handle_climate_change.

    AST rather than string search, because a substring test cannot tell the
    GOVERNED call from the PASSIVE one — both mention `_arrest_ledger` and
    `override_detected`. The first version of this file made exactly that
    mistake: deleting the governed call left these tests green because the
    passive call still matched. Mutation testing caught it.
    """
    node, _ = _fn("_handle_climate_change")
    calls = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            fn = n.func
            if isinstance(fn, ast.Attribute) and fn.attr == "_arrest_ledger":
                calls.append(n)
    return calls


def _mode_of(call):
    """Extract details={"mode": X} from a ledger call, or None."""
    for kw in call.keywords:
        if kw.arg == "details" and isinstance(kw.value, ast.Dict):
            for k, v in zip(kw.value.keys, kw.value.values):
                if getattr(k, "value", None) == "mode":
                    return getattr(v, "value", None)
    return None


def test_both_detection_sites_write_distinct_ledger_rows():
    """THE POSITIVE DIRECTION, pinned per-site so neither can cover for the other."""
    calls = _ledger_calls()
    modes = sorted(m for m in (_mode_of(c) for c in calls) if m)
    assert modes == ["governed", "passive"], (
        f"expected exactly one governed and one passive ledger call, got {modes}. "
        "Deleting either site must fail this test — that is what makes it an anchor."
    )


def test_governed_row_carries_the_attribution_fields():
    """A row that cannot attribute the event is as useless as no row.

    The 2026-09-16 investigation needed exactly these: which zone, which entity,
    and what the preset/setpoints moved from and to. Asserted against the
    GOVERNED call specifically, not against the function text.
    """
    governed = [c for c in _ledger_calls() if _mode_of(c) == "governed"]
    assert len(governed) == 1, "the governed detection site must write exactly one row"
    call = governed[0]
    kwargs = {kw.arg for kw in call.keywords}
    for field in ("zone_id", "entity_id", "action", "description", "details"):
        assert field in kwargs, f"governed ledger row is missing kwarg: {field}"
    detail_keys = set()
    for kw in call.keywords:
        if kw.arg == "details" and isinstance(kw.value, ast.Dict):
            detail_keys = {getattr(k, "value", None) for k in kw.value.keys}
    for field in ("old_preset", "new_preset", "old_high", "new_high"):
        assert field in detail_keys, (
            f"governed ledger row cannot attribute the change without {field}"
        )


def test_passive_mode_detection_also_records_and_is_distinguishable():
    """Passive mode DETECTS without reverting — it must still be recorded, and a
    reader must be able to tell it apart from a real arrest."""
    modes = [_mode_of(c) for c in _ledger_calls()]
    assert "passive" in modes, "passive detection must be recorded"
    assert "governed" in modes, (
        "governed arrests must be distinguishable from passive detections — "
        "otherwise the ledger cannot answer 'did URA actually act?'"
    )


def test_non_override_path_writes_no_row():
    """THE NEGATIVE DIRECTION, and the one that makes this suite discriminate.

    `_handle_climate_change` returns early when `is_override` is false. The
    ledger call must sit AFTER that early return, so an ordinary state change
    (a preset range adjustment, URA's own write) produces no row. A ledger that
    fires on every tick would drown the signal it exists to provide.
    """
    text = SRC.read_text()
    node, _ = _fn("_handle_climate_change")
    src = ast.get_source_segment(text, node) or ""
    guard = src.index("if not is_override:")
    first_ledger = src.index("_arrest_ledger(")
    assert first_ledger > guard, (
        "the ledger write must come AFTER the `if not is_override: return` "
        "guard, or every non-override state change would be logged as an arrest"
    )
