"""Zone Manager Page-1 picker renders as a one-tap MENU (MENU-ZONE-PICKER-1, v5.100.4).

History: v4.7.5 D1 changed the picker from a DROPDOWN to a
SelectSelectorMode.LIST form (vertical menu + Submit). v5.100.4 replaces that
LIST form with a TRUE one-tap `async_show_menu`: selecting a zone navigates
immediately (no Submit). Because the zone set is dynamic and HA routes a menu
selection to `async_step_<key>`, each zone gets a prefixed key
(`_ZONE_PICK_PREFIX`) dispatched via `UniversalRoomAutomationOptionsFlow.__getattr__`.

Source-level AST guards (the picker cannot be behaviorally instantiated without
a full HA runtime): verify the method uses `async_show_menu`, no longer builds a
SelectSelector, and that the dispatch shim exists.
"""

import ast
import os


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_CONFIG_FLOW = os.path.join(
    _REPO_ROOT, "custom_components", "universal_room_automation", "config_flow.py"
)


def _tree():
    with open(_CONFIG_FLOW) as f:
        return ast.parse(f.read()), open(_CONFIG_FLOW).read()


def _method_source(name: str) -> str:
    tree, _ = _tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"Method {name!r} not found in config_flow.py")


def test_manage_zones_renders_async_show_menu():
    src = _method_source("async_step_manage_zones")
    assert "async_show_menu" in src, (
        "MENU-ZONE-PICKER-1: async_step_manage_zones must render a one-tap "
        "async_show_menu (was it reverted to a SelectSelector form?)."
    )
    assert "menu_options" in src and "_zone_menu_map" in src


def test_manage_zones_no_longer_builds_selectselector():
    # Check the CODE (not the docstring, which references the history). The
    # method must no longer build a form; a real SelectSelector call node or
    # an async_show_form call would both fail this.
    import ast as _ast
    tree, _ = _tree()
    method = next(
        n for n in _ast.walk(tree)
        if isinstance(n, _ast.AsyncFunctionDef) and n.name == "async_step_manage_zones"
    )
    calls = {
        _ast.unparse(n.func) for n in _ast.walk(method) if isinstance(n, _ast.Call)
    }
    assert not any("async_show_form" in c for c in calls), \
        "picker must not call async_show_form anymore (one-tap menu)"
    assert not any("SelectSelector" in c for c in calls), \
        "picker must not build a SelectSelector anymore (one-tap menu)"


def test_zone_pick_dispatch_shim_exists():
    _, whole = _tree()
    assert "_ZONE_PICK_PREFIX" in whole, "menu-key prefix constant missing"
    # the __getattr__ dispatch shim that resolves async_step_<prefix><i>
    getattr_src = _method_source_sync("__getattr__")
    assert "_ZONE_PICK_PREFIX" in getattr_src
    assert "async_step_zone_config_menu" in getattr_src
    assert "raise AttributeError" in getattr_src, (
        "__getattr__ must raise AttributeError for non-matching names so normal "
        "attribute lookup / hasattr / lazily-set attrs are preserved."
    )


def _method_source_sync(name: str) -> str:
    tree, _ = _tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"Method {name!r} not found in config_flow.py")
