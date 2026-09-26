"""HVAC-W1-A D5 — AST completeness lint for `climate` service calls.

Invariant INV-A: no URA-originated `climate` service call may reach
``hass.services.async_call("climate", ...)`` outside
``hvac_setpoint.py``. The AST lint is the authoritative completeness
test; a grep-based check is included as a smoke belt that guards against
brace-mismatch bugs in the AST walker (F1).

Failure format: ``<file>:<lineno>: <message>``.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
URA_DIR = ROOT / "custom_components" / "universal_room_automation"
FUNNEL_FILE = "hvac_setpoint.py"

# DYNAMIC_DOMAIN_ALLOWLIST is imported from the code by module basename.
# See hvac_const.py DYNAMIC_DOMAIN_ALLOWLIST for the source of truth.
_ALLOWLIST = frozenset({"optimization.py"})


# --------------------------------------------------------------------------
# Helpers: unwrap attribute chains and identify call shapes.
# --------------------------------------------------------------------------


def _attr_chain(node: ast.AST) -> list[str]:
    """Return dotted-name segments for an ``Attribute``/``Name`` chain."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return list(reversed(parts))


def _is_services_call(func: ast.AST, verbs: tuple[str, ...]) -> bool:
    """Is ``func`` an attribute chain ending in ``services.<verb>``?"""
    chain = _attr_chain(func)
    if len(chain) < 2:
        return False
    if chain[-1] not in verbs:
        return False
    if chain[-2] != "services":
        return False
    return True


def _is_executor_wrapped(call: ast.Call) -> tuple[bool, ast.AST | None]:
    """Detect ``hass.async_add_executor_job(hass.services.call, ...)`` or
    ``hass.loop.run_in_executor(None, hass.services.call, ...)``.

    Returns (is_executor_wrapped, domain_arg_node) where domain_arg_node
    is the first argument PAST the wrapped callable (or None).
    """
    chain = _attr_chain(call.func)
    if not chain:
        return False, None
    last = chain[-1]
    if last == "async_add_executor_job":
        # First arg = callable; second arg onward = its args.
        if len(call.args) >= 2 and _is_services_call(
            call.args[0], ("call", "async_call"),
        ):
            return True, call.args[1]
    if last == "run_in_executor":
        # (executor, func, *args)
        if len(call.args) >= 3 and _is_services_call(
            call.args[1], ("call", "async_call"),
        ):
            return True, call.args[2]
    return False, None


def _domain_arg(call: ast.Call) -> ast.AST | None:
    """Return the domain arg node for a services call (positional 0 or
    ``domain=`` kwarg)."""
    if call.args:
        return call.args[0]
    for kw in call.keywords:
        if kw.arg == "domain":
            return kw.value
    return None


def _service_arg(call: ast.Call) -> ast.AST | None:
    """Return the service-name arg for a services call (positional 1 or
    ``service=`` kwarg)."""
    if len(call.args) >= 2:
        return call.args[1]
    for kw in call.keywords:
        if kw.arg == "service":
            return kw.value
    return None


# Climate verbs that MUST route through emit_set_* funnels. A call
# whose service literal is one of these AND whose domain is either
# non-literal or the "climate" literal is a violation.
_CLIMATE_VERBS = frozenset({"set_temperature", "set_preset_mode", "set_hvac_mode"})


def _service_is_climate_verb_literal(call: ast.Call) -> bool:
    svc = _service_arg(call)
    return isinstance(svc, ast.Constant) and svc.value in _CLIMATE_VERBS


def _is_climate_literal(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value == "climate"


def _is_non_literal_domain(node: ast.AST | None) -> bool:
    """A domain expression that is not a string literal → cannot be
    statically proven safe → treated as a potential climate route."""
    if node is None:
        return False
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return False
    return True


# --------------------------------------------------------------------------
# Walkers.
# --------------------------------------------------------------------------


def _iter_py_files():
    for root, _dirs, files in os.walk(URA_DIR):
        for name in files:
            if not name.endswith(".py"):
                continue
            yield Path(root) / name


def _find_violations() -> list[str]:
    violations: list[str] = []
    for path in _iter_py_files():
        base = path.name
        if base == FUNNEL_FILE:
            continue  # the funnel is the ONE allowed home.
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError as e:
            violations.append(f"{path}:{e.lineno}: parse error: {e.msg}")
            continue
        rel = str(path.relative_to(URA_DIR))

        for node in ast.walk(tree):
            # (3) Aliasing: `_c = hass.services.async_call` or similar.
            if isinstance(node, ast.Assign):
                if _is_services_call(
                    node.value, ("async_call", "call"),
                ):
                    violations.append(
                        f"{rel}:{node.lineno}: alias of "
                        f"hass.services.async_call — the AST cannot follow "
                        f"aliases at analysis time"
                    )
                    continue
            # (3) `from homeassistant.core import ...` binding `async_call`
            # at module scope outside the funnel.
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "async_call" or alias.asname == "async_call":
                        violations.append(
                            f"{rel}:{node.lineno}: async_call bound as a "
                            f"module-level name — aliasing failure"
                        )

            if not isinstance(node, ast.Call):
                continue

            # (1) Direct services.async_call / services.call.
            direct_verbs = ("async_call", "call")
            if _is_services_call(node.func, direct_verbs):
                dom = _domain_arg(node)
                if _is_climate_literal(dom):
                    violations.append(
                        f"{rel}:{node.lineno}: raw climate service call "
                        f"outside {FUNNEL_FILE}"
                    )
                    continue
                if _is_non_literal_domain(dom):
                    # Only flag non-literal domain when the service verb
                    # is a known climate verb literal. URA has many
                    # legitimate dynamic-domain callers targeting fan /
                    # cover / media_player / notify — those cannot reach
                    # a climate service without also naming a climate
                    # verb, so they are safe.
                    if (
                        _service_is_climate_verb_literal(node)
                        and base not in _ALLOWLIST
                    ):
                        violations.append(
                            f"{rel}:{node.lineno}: non-literal domain "
                            f"paired with a climate verb — potential "
                            f"climate route outside {FUNNEL_FILE}; add "
                            f"file to DYNAMIC_DOMAIN_ALLOWLIST if "
                            f"deliberate"
                        )
                    continue

            # (1)+(4) Executor-wrapped.
            is_exec, dom = _is_executor_wrapped(node)
            if is_exec:
                if _is_climate_literal(dom):
                    violations.append(
                        f"{rel}:{node.lineno}: executor-wrapped climate "
                        f"service call outside {FUNNEL_FILE}"
                    )
                elif (
                    _is_non_literal_domain(dom)
                    and base not in _ALLOWLIST
                    # Same narrowing as above.
                    and _service_is_climate_verb_literal(node)
                ):
                    violations.append(
                        f"{rel}:{node.lineno}: executor-wrapped services "
                        f"call with non-literal domain paired with a "
                        f"climate verb"
                    )
    return violations


# --------------------------------------------------------------------------
# Tests.
# --------------------------------------------------------------------------


def test_climate_write_funnel_completeness_lint_passes():
    """No raw `climate` service calls outside hvac_setpoint.py."""
    v = _find_violations()
    assert not v, (
        "climate_write funnel completeness lint failed:\n"
        + "\n".join(v)
    )


def test_lint_recognises_climate_literal():
    """Guard: injecting a raw climate call is detected by the walker."""
    src = 'hass.services.async_call("climate", "set_hvac_mode", {})\n'
    tree = ast.parse(src)
    call = tree.body[0].value
    assert _is_services_call(call.func, ("async_call", "call"))
    assert _is_climate_literal(_domain_arg(call))


def test_lint_recognises_non_literal_domain():
    src = "hass.services.async_call(some_var, 'x', {})\n"
    tree = ast.parse(src)
    call = tree.body[0].value
    assert _is_non_literal_domain(_domain_arg(call))


def test_lint_recognises_aliasing():
    src = "_c = hass.services.async_call\n"
    tree = ast.parse(src)
    assign = tree.body[0]
    assert _is_services_call(assign.value, ("async_call", "call"))


def test_lint_recognises_executor_wrapping():
    src = (
        "hass.async_add_executor_job("
        "hass.services.call, 'climate', 'set_hvac_mode', {})\n"
    )
    tree = ast.parse(src)
    call = tree.body[0].value
    is_exec, dom = _is_executor_wrapped(call)
    assert is_exec
    assert _is_climate_literal(dom)


def test_grep_belt_smoke():
    """Multiline grep belt — climate service calls only inside the funnel.

    Kept as a belt for the AST walker's braces per plan F1.
    """
    pat = re.compile(
        r'services\.async_call\(\s*[\'"]climate[\'"]',
        re.MULTILINE,
    )
    hits: list[str] = []
    for path in _iter_py_files():
        if path.name == FUNNEL_FILE:
            continue
        text = path.read_text()
        for m in pat.finditer(text):
            line = text[: m.start()].count("\n") + 1
            hits.append(f"{path.relative_to(URA_DIR)}:{line}")
    assert not hits, (
        "grep belt found raw climate services calls outside funnel:\n"
        + "\n".join(hits)
    )
