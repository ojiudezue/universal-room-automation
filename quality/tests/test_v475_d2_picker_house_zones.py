"""v4.7.5 D2 — Picker shows RAW house zones, never canonical merged labels.

Pre-v4.7.5, two house zones sharing a thermostat (Entertainment + Master
Suite) could be exposed to the user as a single canonical "Entertainment +
Master Suite" entry via `iter_canonical_hvac_zones`. v4.7.5 D2 locks the
contract that `async_step_manage_zones`:
  1. Reads RAW zones from `entry.options["zones"]`.
  2. Never imports/calls `iter_canonical_hvac_zones` (AST regression guard).
  3. Adds a "(shared thermostat)" suffix to each label whose thermostat
     appears in 2+ house zones (quick-glance cue; full banner is on
     zone_config_menu via D4).
"""

import ast
import os


_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_CONFIG_FLOW = os.path.join(
    _REPO_ROOT, "custom_components", "universal_room_automation", "config_flow.py"
)


def _method_source(qualname: str) -> str:
    with open(_CONFIG_FLOW) as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == qualname:
            return ast.unparse(node)
    raise AssertionError(f"Method {qualname!r} not found in config_flow.py")


def test_v475_d2_picker_does_not_call_iter_canonical():
    """async_step_manage_zones MUST NOT import or call iter_canonical_hvac_zones.

    Docstrings/comments that MENTION the symbol are fine — the AST check below
    walks the parsed method body and rejects only actual `Call`/`ImportFrom`/
    `Attribute` references to the name.
    """
    with open(_CONFIG_FLOW) as f:
        tree = ast.parse(f.read())
    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_step_manage_zones":
            target = node
            break
    assert target is not None
    for sub in ast.walk(target):
        # Real call: a Name or Attribute named iter_canonical_hvac_zones
        if isinstance(sub, ast.Name) and sub.id == "iter_canonical_hvac_zones":
            raise AssertionError(
                "v4.7.5 D2: async_step_manage_zones references "
                "iter_canonical_hvac_zones as a Name node (live identifier). "
                "Mentioning it in a docstring is OK; calling it is not."
            )
        if isinstance(sub, ast.Attribute) and sub.attr == "iter_canonical_hvac_zones":
            raise AssertionError(
                "v4.7.5 D2: async_step_manage_zones references "
                "iter_canonical_hvac_zones as an attribute access. "
                "The picker MUST NOT call canonical merge."
            )
        if isinstance(sub, ast.ImportFrom):
            for alias in sub.names:
                if alias.name == "iter_canonical_hvac_zones":
                    raise AssertionError(
                        "v4.7.5 D2: async_step_manage_zones imports "
                        "iter_canonical_hvac_zones. Forbidden by D3."
                    )


def test_v475_d2_picker_emits_shared_thermostat_suffix():
    """Method body must contain the '(shared thermostat)' suffix literal."""
    src = _method_source("async_step_manage_zones")
    assert "shared thermostat" in src, (
        "v4.7.5 D2: async_step_manage_zones must render a "
        "'(shared thermostat)' suffix on zones whose thermostat is shared."
    )


def test_v475_d2_picker_reads_raw_zones_dict():
    """Source must show the picker reading from entry.options/data, not a
    canonical helper. Asserts at least one `merged.get("zones"` pattern."""
    src = _method_source("async_step_manage_zones")
    # The picker uses a `merged = {**entry.data, **entry.options}` pattern,
    # then `merged.get("zones", {})`. Either form is acceptable.
    assert 'merged.get("zones"' in src or "merged.get('zones'" in src, (
        "v4.7.5 D2: async_step_manage_zones must read raw zones via "
        "`merged.get('zones', {})` rather than any canonical helper."
    )
