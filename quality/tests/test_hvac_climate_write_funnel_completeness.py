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

# DYNAMIC_DOMAIN_ALLOWLIST is imported from production (single source of
# truth in hvac_const.py) — a hand copy would silently drift on additions.
def _load_allowlist():
    import sys
    _q = Path(__file__).resolve().parents[1]
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))
    from custom_components.universal_room_automation.domain_coordinators import (
        hvac_const,
    )
    return frozenset(hvac_const.DYNAMIC_DOMAIN_ALLOWLIST)


_ALLOWLIST = _load_allowlist()


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


def _required_kw_only(funnel_name: str) -> set[str]:
    """Read the required keyword-only args off the live funnel definition
    (so the check stays correct if the signature changes)."""
    import inspect
    from custom_components.universal_room_automation.domain_coordinators import (
        hvac_setpoint,
    )
    fn = getattr(hvac_setpoint, funnel_name)
    sig = inspect.signature(fn)
    return {
        name for name, p in sig.parameters.items()
        if p.kind is inspect.Parameter.KEYWORD_ONLY
        and p.default is inspect.Parameter.empty
    }


def test_every_production_funnel_call_supplies_required_kwargs():
    """AST completeness: every PRODUCTION call of the three emit funnels
    supplies every currently-required keyword-only argument.

    Reads the required set from the function definitions (via inspect on
    hvac_setpoint), so if the signature changes the test tracks
    automatically. Scope: production code under
    ``custom_components/universal_room_automation/`` — test files are
    intentionally excluded (the F3 TypeError discriminator lives in the
    tests). Per-site drill: remove ``site=`` from any production call →
    this test goes RED.
    """
    funnels = {
        name: _required_kw_only(name)
        for name in ("emit_set_hvac_mode", "emit_set_preset_mode",
                     "emit_set_temperature",
                     # HVAC Batch C (CPR U1): the fourth funnel.
                     "emit_set_activity_setpoint")
    }
    violations: list[str] = []
    n_calls = 0
    for path in _iter_py_files():
        # Skip the funnel definitions themselves.
        if path.name == FUNNEL_FILE:
            continue
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            continue
        rel = str(path.relative_to(URA_DIR))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            fname = (
                func.id if isinstance(func, ast.Name)
                else (func.attr if isinstance(func, ast.Attribute) else "")
            )
            if fname not in funnels:
                continue
            n_calls += 1
            supplied = {kw.arg for kw in node.keywords if kw.arg}
            missing = funnels[fname] - supplied
            if missing:
                violations.append(
                    f"{rel}:{node.lineno}: {fname} missing required "
                    f"kwarg(s) {sorted(missing)}"
                )
    assert n_calls > 0, (
        "sanity: expected to find production funnel call sites"
    )
    assert not violations, (
        "production funnel call sites missing required kwargs:\n"
        + "\n".join(violations)
    )


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


# --------------------------------------------------------------------------
# HVAC Batch C (CPR) REV 3.1 F3 + REV 3.2 clarification: the brand service
# literal lives ONLY in the thermostat adapter. Forbidden: a services call
# whose domain is the LITERAL "ha_carrier" outside hvac_strategy.py, and the
# literal "ha_carrier" anywhere in hvac_setpoint.py (the funnel takes the
# domain from its caller). A NON-literal domain (Name / attribute) is
# allowed — that is how the funnel itself calls `async_call(service_domain,
# ...)`.
# --------------------------------------------------------------------------

_BRAND_LITERAL = "ha_carrier"
_ADAPTER_FILE = "hvac_strategy.py"


def _brand_literal_violations(sources: dict[str, str]) -> list[str]:
    """`sources` = {file name: source text}. Returns violations."""
    out: list[str] = []
    for name, text in sources.items():
        tree = ast.parse(text, filename=name)
        if name == FUNNEL_FILE:
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == _BRAND_LITERAL:
                    out.append(f"{name}:{node.lineno}: brand literal in the funnel")
            continue
        if name == _ADAPTER_FILE:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_services_call(
                node.func, ("async_call", "call"),
            ):
                dom = _domain_arg(node)
                if isinstance(dom, ast.Constant) and dom.value == _BRAND_LITERAL:
                    out.append(f"{name}:{node.lineno}: brand service call outside the adapter")
    return out


def test_brand_service_literal_only_in_adapter():
    sources = {p.name: p.read_text() for p in _iter_py_files()}
    v = _brand_literal_violations(sources)
    assert not v, "\n".join(v)


def test_lint_accepts_variable_service_domain():
    """Lint-of-the-lint (REV 3.2): a Name-typed domain passes."""
    src = "async def f(hass, service_domain):\n    await hass.services.async_call(service_domain, 'x', {})\n"
    assert _brand_literal_violations({"some_caller.py": src}) == []
    assert _brand_literal_violations({FUNNEL_FILE: src}) == []


def test_lint_rejects_literal_brand_call_and_funnel_literal():
    """Lint-of-the-lint: the planted shapes ARE caught."""
    call = "async def f(hass):\n    await hass.services.async_call('ha_carrier', 'x', {})\n"
    assert _brand_literal_violations({"some_caller.py": call})
    assert _brand_literal_violations({_ADAPTER_FILE: call}) == []
    assert _brand_literal_violations({FUNNEL_FILE: "X = 'ha_carrier'\n"})
