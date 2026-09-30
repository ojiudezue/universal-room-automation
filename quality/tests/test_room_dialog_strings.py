"""Meta-test: every ROOM config-flow / options-flow field has a clean label + helper.

Card ROOM-DIALOGS-USABILITY-SWEEP-1 (2026-09-29).

For every schema key that appears in each ROOM step of `config_flow.py`
(vol.Optional / vol.Required inside the step function's body), and for every
field entry already present in strings.json / translations/en.json for that
step, we assert:

* a `data.<key>` label exists in BOTH strings.json and translations/en.json
* the label is not the raw key and contains no underscore
* a `data_description.<key>` helper exists in BOTH files
* the helper is <= 220 characters

Menu-only steps (no user-input schema) are skipped -- they carry no
`data`/`data_description` block and none is expected.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

_COMPONENT = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "universal_room_automation"
)
_STRINGS = _COMPONENT / "strings.json"
_EN = _COMPONENT / "translations" / "en.json"
_CONFIG_FLOW = _COMPONENT / "config_flow.py"

# Room-entry-reachable steps (see config_flow.py: async_step_init room branch
# + async_step_room_setup wizard chain). Menu-only steps are included so the
# enumerator can note they carry no schema.
ROOM_CONFIG_STEPS = [
    "room_setup",
    "room_class",
    "sensors",
    "devices",
    "sensors_confirm",
    "devices_confirm",
    "room_summary",  # menu / summary
    "night_light_detail",
    "cover_behavior",
    "automation_behavior",
    "init_automation_chaining",  # menu
    "init_chain_occupancy",
    "init_chain_light",
    "init_chain_house_state",
    "init_chain_coordinator",
    "init_ai_rules",  # menu
    "init_ai_rule_add",
    "climate",
    "fan_speeds",
    "sleep_protection",
    "energy",
    "notifications",
]

ROOM_OPTIONS_STEPS = [
    "basic_setup",
    "sensors",
    "devices",
    "options_lighting",
    "options_covers",
    "automation_chaining",  # menu
    "chain_occupancy",
    "chain_light",
    "chain_house_state",
    "chain_coordinator",
    "ai_rules",  # menu
    "ai_rule_add",
    "ai_rule_list",
    "ai_rule_delete",
    "climate",
    "sleep_protection",
    "music_following",
    "energy",
    "notifications",
]

MAX_HELPER_LEN = 220


def _load(p: Path) -> dict:
    return json.loads(p.read_text())


def _extract_step_schema_keys() -> dict[str, dict[str, set[str]]]:
    """AST-scan config_flow.py.

    Returns: {"config": {step_id: {keys}}, "options": {step_id: {keys}}}
    """
    tree = ast.parse(_CONFIG_FLOW.read_text())

    # Locate the ConfigFlow class and the OptionsFlow class.
    config_class = None
    options_class = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if node.name.endswith("ConfigFlow"):
                config_class = node
            elif node.name.endswith("OptionsFlow"):
                options_class = node

    assert config_class is not None, "ConfigFlow class not found"
    assert options_class is not None, "OptionsFlow class not found"

    def _keys_in_function(fn: ast.AsyncFunctionDef | ast.FunctionDef) -> set[str]:
        """Find vol.Optional(CONF_X) / vol.Required(CONF_X) constants used as
        dict keys. We look at Call nodes whose func is vol.Optional/Required and
        take the first positional arg's value.
        """
        keys: set[str] = set()
        # Build a map: name -> constant string, from module-level and class-level
        # ast.Assign we could see. Simpler: extract via regex on the source of
        # the function body.
        src = ast.get_source_segment(_CONFIG_FLOW.read_text(), fn) or ""
        # Match vol.Optional(CONF_X, ...) or vol.Required(CONF_X, ...)
        # Also handle direct string keys like vol.Optional("wet_room", ...)
        for m in re.finditer(
            r"vol\.(?:Optional|Required)\(\s*(?:CONF_[A-Z0-9_]+|\"([a-z0-9_]+)\"|'([a-z0-9_]+)')",
            src,
        ):
            lit = m.group(1) or m.group(2)
            if lit:
                keys.add(lit)
        # Constant names referenced -- resolve them via const module.
        return keys

    # Load const module string values.
    const_src = (_COMPONENT / "const.py").read_text()
    const_map: dict[str, str] = {}
    for m in re.finditer(
        r"^(CONF_[A-Z0-9_]+)\s*=\s*[\"']([^\"']+)[\"']",
        const_src,
        re.MULTILINE,
    ):
        const_map[m.group(1)] = m.group(2)
    # Some CONF_* live in config_flow.py itself.
    for m in re.finditer(
        r"^(CONF_[A-Z0-9_]+)\s*=\s*[\"']([^\"']+)[\"']",
        _CONFIG_FLOW.read_text(),
        re.MULTILINE,
    ):
        const_map.setdefault(m.group(1), m.group(2))

    def _resolve_keys(fn) -> set[str]:
        src = ast.get_source_segment(_CONFIG_FLOW.read_text(), fn) or ""
        keys: set[str] = set()
        # vol.Optional(CONF_X, ...): <value>  -- capture value's opening token
        # to skip `section(...)` grouping keys (HA renders those via a
        # `sections.<key>` block, not a `data.<key>` label).
        pat = re.compile(
            r"vol\.(?:Optional|Required)\(\s*"
            r"(?:(CONF_[A-Z0-9_]+)|[\"']([a-z0-9_]+)[\"'])"
            r"[^\)]*\)\s*:\s*([A-Za-z_][A-Za-z0-9_]*)"
        )
        for m in pat.finditer(src):
            cname, lit, wrapper = m.group(1), m.group(2), m.group(3)
            if wrapper in ("section", "_ha_section"):
                continue
            if cname:
                if cname in const_map:
                    keys.add(const_map[cname])
            elif lit:
                keys.add(lit)
        return keys

    result = {"config": {}, "options": {}}
    for fn in config_class.body:
        if isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if fn.name.startswith("async_step_"):
                sid = fn.name[len("async_step_"):]
                result["config"][sid] = _resolve_keys(fn)
    for fn in options_class.body:
        if isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if fn.name.startswith("async_step_"):
                sid = fn.name[len("async_step_"):]
                result["options"][sid] = _resolve_keys(fn)
    return result


def _cases():
    strings = _load(_STRINGS)
    en = _load(_EN)
    schema = _extract_step_schema_keys()
    seen: list[tuple[str, str, str]] = []
    for section, step_ids in (
        ("config", ROOM_CONFIG_STEPS),
        ("options", ROOM_OPTIONS_STEPS),
    ):
        for sid in step_ids:
            code_keys = schema.get(section, {}).get(sid, set())
            s_step = strings.get(section, {}).get("step", {}).get(sid, {})
            s_data = s_step.get("data", {}) or {}
            s_dd = s_step.get("data_description", {}) or {}
            union = code_keys | set(s_data.keys()) | set(s_dd.keys())
            for k in sorted(union):
                seen.append((section, sid, k))
    return seen


CASES = _cases()


@pytest.mark.parametrize("section,step_id,key", CASES)
def test_room_field_has_clean_label_and_helper(section, step_id, key):
    strings = _load(_STRINGS)
    en = _load(_EN)

    for src_name, blob in (("strings.json", strings), ("en.json", en)):
        step = blob.get(section, {}).get("step", {}).get(step_id, {})
        assert step, f"{src_name}: room {section} step '{step_id}' missing"
        data = step.get("data", {}) or {}
        dd = step.get("data_description", {}) or {}

        label = data.get(key)
        assert label, f"{src_name}: {section}.{step_id}.data missing label for '{key}'"
        assert label != key, (
            f"{src_name}: {section}.{step_id}.{key} label equals raw key"
        )
        assert "_" not in label, (
            f"{src_name}: {section}.{step_id}.{key} label {label!r} contains '_' "
            "(raw key leaked into UI)"
        )

        helper = dd.get(key)
        assert helper, (
            f"{src_name}: {section}.{step_id}.data_description missing helper for '{key}'"
        )
        assert len(helper) <= MAX_HELPER_LEN, (
            f"{src_name}: {section}.{step_id}.{key} helper is {len(helper)} chars "
            f"(>{MAX_HELPER_LEN}); shorten."
        )
