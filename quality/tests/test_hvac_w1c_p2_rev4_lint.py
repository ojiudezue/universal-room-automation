"""HVAC W1-C P2 option C — structural lints (plan REV 4.1-C.11, M11; C.1
reader enumeration).

INV-E2' (structural half): inside ``domain_coordinators/hvac*.py`` the only
``select`` / ``button`` / ``number`` service call is the ONE call inside
``hvac_setpoint.emit_select_comfort``. Scope is ``hvac*.py`` ONLY: the energy
coordinator legitimately calls ``number.set_value`` (EVSE / TOU) and must
never trip this lint. Branch D (number entities) is parked — a
``number.set_value`` anywhere in HVAC scope is a violation.

These are lints (structure), not behavioural anchors; the behaviour lives in
``test_hvac_w1c_p2_ecobee_rev4.py``.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DC = ROOT / "custom_components" / "universal_room_automation" / "domain_coordinators"

BANNED_DOMAINS = frozenset({"select", "button", "number"})
BANNED_SERVICES = frozenset({"select_option", "press", "set_value"})
# (file, enclosing function) -> the ONE allowed site.
ALLOWED = {("hvac_setpoint.py", "emit_select_comfort")}


def _hvac_files() -> dict[str, str]:
    return {p.name: p.read_text() for p in sorted(DC.glob("hvac*.py"))}


def _is_services_call(node: ast.Call) -> bool:
    f = node.func
    return isinstance(f, ast.Attribute) and f.attr in ("async_call", "call")


def _violations(files: dict[str, str]) -> tuple[list[str], int]:
    """(violations, allowed-site count)."""
    out: list[str] = []
    allowed_hits = 0
    for name, src in files.items():
        tree = ast.parse(src)
        parents: dict[int, ast.AST] = {}
        for p in ast.walk(tree):
            for c in ast.iter_child_nodes(p):
                parents[id(c)] = p

        def _enclosing_fn(n: ast.AST) -> str | None:
            cur = parents.get(id(n))
            while cur is not None:
                if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return cur.name
                cur = parents.get(id(cur))
            return None

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_services_call(node):
                continue
            args = node.args
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            dom_n = args[0] if args else kw.get("domain")
            svc_n = args[1] if len(args) > 1 else kw.get("service")
            dom = dom_n.value if isinstance(dom_n, ast.Constant) else None
            svc = svc_n.value if isinstance(svc_n, ast.Constant) else None
            if dom not in BANNED_DOMAINS and svc not in BANNED_SERVICES:
                continue
            if (name, _enclosing_fn(node)) in ALLOWED and (dom, svc) == ("select", "select_option"):
                allowed_hits += 1
                continue
            out.append(f"{name}:{node.lineno}: {dom}.{svc} outside emit_select_comfort")
    return out, allowed_hits


def test_m11_no_select_button_number_service_in_hvac_scope():
    viol, hits = _violations(_hvac_files())
    assert viol == []
    assert hits == 1, "emit_select_comfort must hold exactly ONE select_option call"


def test_m11_scope_is_hvac_files_only_and_energy_would_trip_it():
    """The scope is hvac*.py; the energy coordinator's legitimate
    `number.set_value` calls would be violations if it were scanned."""
    names = set(_hvac_files())
    assert names and all(n.startswith("hvac") for n in names)
    energy = {p.name: p.read_text() for p in sorted(DC.glob("energy*.py"))}
    viol, _ = _violations(energy)
    assert viol, "expected energy's number.set_value calls to be out of scope, not absent"


def test_m11_lint_catches_planted_calls():
    planted = {
        "hvac_x.py": (
            "async def f(hass):\n"
            "    await hass.services.async_call('select', 'select_option', {})\n"
            "    await hass.services.async_call('button', 'press', {})\n"
            "    await hass.services.async_call('number', 'set_value', {})\n"
            "    await hass.services.async_call(dom, 'press', {})\n"
        ),
        "hvac_setpoint.py": (
            "async def emit_select_comfort(hass):\n"
            "    await hass.services.async_call('select', 'select_option', {})\n"
            "async def other(hass):\n"
            "    await hass.services.async_call('select', 'select_option', {})\n"
        ),
    }
    viol, hits = _violations(planted)
    assert len(viol) == 5
    assert hits == 1


def test_m11_lint_catches_keyword_argument_calls():
    """C-LOW: `async_call(domain=..., service=...)` (and a mixed form) is
    read like the positional form."""
    planted = {
        "hvac_y.py": (
            "async def f(hass):\n"
            "    await hass.services.async_call(domain='select', service='select_option')\n"
            "    await hass.services.async_call('number', service='set_value')\n"
            "    await hass.services.async_call(service='press', domain=d)\n"
            "    await hass.services.async_call(domain='climate', service='set_temperature')\n"
        ),
    }
    viol, hits = _violations(planted)
    assert [v.split(":")[1] for v in viol] == ["2", "3", "4"]
    assert hits == 0


# --------------------------------------------------------------------------
# C.1: every reader of `EcobeeHomeKitStrategy._held` is enumerated.
# --------------------------------------------------------------------------

HELD_READERS = frozenset({
    "preset_of",              # C.3 projection (+ lazy settle)
    "hold_needs_reassert",    # C.4 truth table
    "reference_setpoints",    # C.5 arrester reference
    "hold_preset",            # Branch-S / Branch-R no-op
    "_hold_range",            # Branch R stamp
    "_hold_select",           # Branch S stamp
    "_restore_held",          # B-L4 rollback
    "set_preset_range",       # C.4 upgrade / downgrade
    "export_state",           # shutdown / periodic snapshot
    "rehydrate_state",        # boot restore + legacy migration
    "flush_entity",           # profile switch + prune seam
})


def _held_readers() -> set[str]:
    src = (DC / "hvac_strategy.py").read_text()
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "EcobeeHomeKitStrategy")
    out = set()
    for fn in cls.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(fn):
            if (
                isinstance(n, ast.Attribute) and n.attr == "_held"
                and isinstance(n.value, ast.Name) and n.value.id == "self"
                and fn.name != "__init__"
            ):
                out.add(fn.name)
    return out


def test_rev4_1_held_readers_enumerated():
    assert _held_readers() == HELD_READERS
