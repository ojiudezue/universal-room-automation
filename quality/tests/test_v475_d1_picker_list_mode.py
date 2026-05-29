"""v4.7.5 D1 — Zone Manager Page 1 picker renders as LIST not DROPDOWN.

The picker (`async_step_manage_zones`) is the user's first touch in Zone
Manager → Configure. Pre-v4.7.5 it rendered as a SelectSelectorMode.DROPDOWN
which truncates labels and feels cramped at 5+ zones. v4.7.5 D1 changes the
mode to SelectSelectorMode.LIST (vertical menu).

This is a source-level guard: parse `async_step_manage_zones` and verify the
schema-build site references `SelectSelectorMode.LIST`, not `.DROPDOWN`.
"""

import ast
import os


_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_CONFIG_FLOW = os.path.join(
    _REPO_ROOT, "custom_components", "universal_room_automation", "config_flow.py"
)


def _find_method_source(tree: ast.Module, qualname: str) -> str:
    """Return the source of the AsyncFunctionDef whose name == qualname."""
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == qualname:
            return ast.unparse(node)
    raise AssertionError(f"Method {qualname!r} not found in config_flow.py")


def test_v475_d1_manage_zones_uses_list_mode():
    """async_step_manage_zones must reference SelectSelectorMode.LIST, not DROPDOWN."""
    with open(_CONFIG_FLOW) as f:
        tree = ast.parse(f.read())
    src = _find_method_source(tree, "async_step_manage_zones")
    assert "SelectSelectorMode.LIST" in src, (
        "v4.7.5 D1: async_step_manage_zones must use SelectSelectorMode.LIST "
        "for the vertical menu UI. Was it reverted to .DROPDOWN?"
    )
    assert "SelectSelectorMode.DROPDOWN" not in src, (
        "v4.7.5 D1: async_step_manage_zones still references "
        "SelectSelectorMode.DROPDOWN — the picker is meant to be LIST only."
    )
