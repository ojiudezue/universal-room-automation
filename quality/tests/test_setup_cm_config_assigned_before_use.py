"""v5.103.38 hotfix regression: in async_setup_entry, cm_config must be
assigned before any read. v5.103.37 called coordinators_to_register(cm_config)
before cm_config existed -> UnboundLocalError -> Coordinator Manager never
started (every domain coordinator down)."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation" / "__init__.py"


def _setup_fn():
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry":
            return node
    raise AssertionError("async_setup_entry not found")


def _lines(fn, name, ctx):
    return sorted(
        n.lineno for n in ast.walk(fn)
        if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ctx)
    )


def test_cm_config_first_store_precedes_first_load():
    fn = _setup_fn()
    stores = _lines(fn, "cm_config", ast.Store)
    loads = _lines(fn, "cm_config", ast.Load)
    assert stores and loads
    assert stores[0] < loads[0], (stores[0], loads[0])


def test_to_register_computed_after_cm_config_built():
    fn = _setup_fn()
    calls = [
        n.lineno for n in ast.walk(fn)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "coordinators_to_register"
    ]
    full_builds = [
        n.lineno for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "cm_config" for t in n.targets)
        and isinstance(n.value, ast.Dict) and n.value.keys and n.value.keys[0] is None
    ]
    assert calls and full_builds
    assert min(full_builds) < min(calls), (full_builds, calls)
