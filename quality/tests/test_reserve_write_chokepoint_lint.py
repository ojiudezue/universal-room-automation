"""EC-RESERVE-WRITE-GOVERNOR-1 — INV-G1 writer-allowlist AST lint.

Every statically visible `number` / `set_value` writer anywhere in
`custom_components/universal_room_automation/` must sit lexically inside a
`(module, function)` entry of the PRODUCTION tuple
`energy_const.RESERVE_SET_VALUE_WRITERS`, with exactly the pinned count.

Matched shapes (plan §4 counting rule):
  * +1 per `Call` whose first two positional args are the constants
    `("number", "set_value")`, or whose keywords are `domain="number"` and
    `service="set_value"`;
  * +1 per `ast.Constant == "number.set_value"` (dict-shape action
    `{"service": "number.set_value", ...}` or any other literal use).
  Constant args of a Call that already qualified are NOT counted again, so
  `force_redispatch` = 2 (the Call + the failure-record constant).

Known limits (cannot be seen by the AST, listed in the plan INV-G1): a
domain/service passed in a variable, the HA constant `SERVICE_SET_VALUE`,
runtime-built strings, and the EVSE overlay's update-in-place leg (which
rewrites an existing action dict with no new literal — C1 still sees that
value at dispatch).

The allowlist is IMPORTED from production (never hand-copied), via a private
module load so this file cannot disturb sibling bootstraps.
"""
from __future__ import annotations

import ast
import importlib.util
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
URA_DIR = ROOT / "custom_components" / "universal_room_automation"
_EC_CONST_PATH = URA_DIR / "domain_coordinators" / "energy_const.py"


def _load_allowlist() -> tuple[tuple[str, str, str, int], ...]:
    spec = importlib.util.spec_from_file_location(
        "_reserve_lint_private_energy_const", _EC_CONST_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return tuple(mod.RESERVE_SET_VALUE_WRITERS)


ALLOWLIST = _load_allowlist()
VALID_KINDS = frozenset({"reserve", "reader", "non_reserve"})


# ---------------------------------------------------------------------------
# Walker
# ---------------------------------------------------------------------------
def _enclosing_function(parents: dict, node: ast.AST) -> str:
    n = node
    while n in parents:
        n = parents[n]
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return n.name
    return "<module>"


def _call_qualifies(call: ast.Call) -> bool:
    pos = call.args[:2]
    if (
        len(pos) == 2
        and all(isinstance(a, ast.Constant) for a in pos)
        and (pos[0].value, pos[1].value) == ("number", "set_value")
    ):
        return True
    kws = {
        kw.arg: kw.value.value
        for kw in call.keywords
        if kw.arg and isinstance(kw.value, ast.Constant)
    }
    return kws.get("domain") == "number" and kws.get("service") == "set_value"


def scan_tree(tree: ast.AST, module: str) -> list[tuple[str, str, str, int]]:
    """Return (module, function, shape, lineno) per qualifying node."""
    parents: dict = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parents[c] = n
    hits: list[tuple[str, str, str, int]] = []
    consumed: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and _call_qualifies(n):
            hits.append((module, _enclosing_function(parents, n), "call", n.lineno))
            for a in n.args[:2]:
                consumed.add(id(a))
            for kw in n.keywords:
                consumed.add(id(kw.value))
    for n in ast.walk(tree):
        if (
            isinstance(n, ast.Constant)
            and n.value == "number.set_value"
            and id(n) not in consumed
        ):
            hits.append((module, _enclosing_function(parents, n), "const", n.lineno))
    return hits


def scan_source(text: str, module: str) -> list[tuple[str, str, str, int]]:
    return scan_tree(ast.parse(text, filename=module), module)


def scan_package() -> list[tuple[str, str, str, int]]:
    hits: list[tuple[str, str, str, int]] = []
    for path in sorted(URA_DIR.rglob("*.py")):
        hits.extend(scan_source(path.read_text(), path.name))
    return hits


def violations(
    hits: list[tuple[str, str, str, int]],
    allow: tuple[tuple[str, str, str, int], ...],
) -> list[str]:
    counts = Counter((m, f) for m, f, _shape, _ln in hits)
    pinned = {(m, f): n for m, f, _k, n in allow}
    out: list[str] = []
    for (m, f), n in sorted(counts.items()):
        if (m, f) not in pinned:
            lines = sorted(ln for mm, ff, _s, ln in hits if (mm, ff) == (m, f))
            out.append(
                f"{m}:{f}: UNLISTED number/set_value writer at line(s) {lines} "
                f"— add to RESERVE_SET_VALUE_WRITERS (reviewed) or route "
                f"through the governed slice"
            )
        elif pinned[(m, f)] != n:
            out.append(
                f"{m}:{f}: count mismatch — pinned {pinned[(m, f)]}, found {n}"
            )
    for (m, f), n in pinned.items():
        if (m, f) not in counts:
            out.append(f"{m}:{f}: STALE allowlist entry (pinned {n}, found 0)")
    return out


# ---------------------------------------------------------------------------
# The lint
# ---------------------------------------------------------------------------
def test_no_unlisted_writers():
    """INV-G1 on HEAD: every writer is allowlisted with its exact count."""
    v = violations(scan_package(), ALLOWLIST)
    assert not v, "reserve write chokepoint lint failed:\n" + "\n".join(v)


def test_allowlist_shape():
    assert ALLOWLIST, "RESERVE_SET_VALUE_WRITERS must not be empty"
    for row in ALLOWLIST:
        m, f, kind, n = row
        assert m.endswith(".py"), row
        assert isinstance(f, str) and f, row
        assert kind in VALID_KINDS, row
        assert isinstance(n, int) and n >= 1, row
    pairs = [(m, f) for m, f, _k, _n in ALLOWLIST]
    assert len(pairs) == len(set(pairs)), "duplicate (module, function) rows"


def test_allowlist_pins_the_known_topology():
    """Pin the three REAL reserve producers + the redispatch so a silent
    retyping to `non_reserve`/`reader` is caught."""
    kinds = {(m, f): k for m, f, k, _n in ALLOWLIST}
    assert kinds[("energy_battery.py", "_result")] == "reserve"
    assert kinds[("energy_battery.py", "determine_mode")] == "reserve"
    assert kinds[("energy_battery.py", "force_redispatch")] == "reserve"
    assert kinds[("energy.py", "_apply_evse_battery_hold")] == "reserve"
    assert kinds[("energy.py", "_tap_write_verifier")] == "reader"
    assert kinds[("energy.py", "_evaluate_battery")] == "reader"


# ---------------------------------------------------------------------------
# Lint-of-the-lint: every planted shape IS caught (mutation table rows
# "inject ... into a non-allowlisted function").
# ---------------------------------------------------------------------------
_BASE = (
    "def harmless():\n"
    "    return hass.services.async_call('switch', 'turn_on', {})\n"
)


def test_lint_catches_dict_shape_injection():
    src = _BASE + (
        "def rogue(x):\n"
        "    return {'service': 'number.set_value', 'target': x, 'data': {}}\n"
    )
    v = violations(scan_source(src, "energy.py"), ALLOWLIST)
    assert any("energy.py:rogue: UNLISTED" in s for s in v), v


def test_lint_catches_positional_call_injection():
    src = _BASE + (
        "async def rogue(hass, eid):\n"
        "    await hass.services.async_call('number', 'set_value', {'entity_id': eid})\n"
    )
    v = violations(scan_source(src, "inclement.py"), ALLOWLIST)
    assert any("inclement.py:rogue: UNLISTED" in s for s in v), v


def test_lint_catches_keyword_call_injection():
    src = _BASE + (
        "async def rogue(hass, eid):\n"
        "    await hass.services.async_call(domain='number', service='set_value',\n"
        "                                   service_data={'entity_id': eid})\n"
    )
    v = violations(scan_source(src, "optimization.py"), ALLOWLIST)
    assert any("optimization.py:rogue: UNLISTED" in s for s in v), v


def test_lint_catches_second_writer_in_allowlisted_function():
    """Count-pinning makes allowlisting the huge `determine_mode` safe: a
    second dict-shape writer injected INTO it is a count mismatch."""
    path = URA_DIR / "domain_coordinators" / "energy_battery.py"
    tree = ast.parse(path.read_text(), filename="energy_battery.py")
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "determine_mode"
    )
    injected = ast.parse(
        "_rogue = {'service': 'number.set_value', 'target': t, 'data': {}}"
    ).body[0]
    fn.body.insert(1, injected)
    ast.fix_missing_locations(tree)
    v = violations(scan_tree(tree, "energy_battery.py"), ALLOWLIST)
    assert any(
        "energy_battery.py:determine_mode: count mismatch — pinned 1, found 2" in s
        for s in v
    ), v


def test_lint_flags_stale_allowlist_entry():
    allow = ALLOWLIST + (("energy.py", "_gone_writer", "reserve", 1),)
    v = violations(scan_package(), allow)
    assert any("energy.py:_gone_writer: STALE" in s for s in v), v


def test_counting_rule_call_args_not_double_counted():
    src = (
        "async def w(hass):\n"
        "    await hass.services.async_call('number', 'set_value', {'value': 1})\n"
    )
    hits = scan_source(src, "m.py")
    assert hits == [("m.py", "w", "call", 2)]


def test_counting_rule_dict_shape_counts_once():
    src = "def w(t):\n    return {'service': 'number.set_value', 'target': t}\n"
    hits = scan_source(src, "m.py")
    assert hits == [("m.py", "w", "const", 2)]


def test_docstring_substring_does_not_match():
    src = (
        'def w():\n'
        '    """Talks about number.set_value in prose; not a writer."""\n'
        '    return None\n'
    )
    assert scan_source(src, "m.py") == []


def test_bare_set_value_without_number_domain_does_not_match():
    """A bare "set_value" counts only through a qualifying Call."""
    src = (
        "async def w(hass):\n"
        "    await hass.services.async_call('input_number', 'set_value', {})\n"
    )
    assert scan_source(src, "m.py") == []


def test_module_level_writer_is_attributed_to_module():
    src = "X = {'service': 'number.set_value'}\n"
    hits = scan_source(src, "m.py")
    assert hits == [("m.py", "<module>", "const", 1)]
    v = violations(hits, ALLOWLIST)
    assert any("m.py:<module>: UNLISTED" in s for s in v)
