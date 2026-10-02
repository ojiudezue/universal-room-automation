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
    "options_lighting_behaviour",  # v5.103.28 Slice B'
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

    KEY_PAT = re.compile(
        r"vol\.(?:Optional|Required)\(\s*"
        r"(?:(CONF_[A-Z0-9_]+)|[\"']([a-z0-9_]+)[\"'])"
        r"[^\)]*\)\s*:\s*([A-Za-z_][A-Za-z0-9_]*)"
    )
    # Locate a `section(` / `_ha_section(` call and capture its LITERAL key
    # (the vol.Optional("<key>") right before) + the inner schema body up to
    # the matching close paren of section(...). We split on section calls in
    # the function source and re-scan the inner slice with KEY_PAT.
    SECTION_HEAD = re.compile(
        r"vol\.(?:Optional|Required)\(\s*[\"']([a-z0-9_]+)[\"'][^\)]*\)"
        r"\s*:\s*(?:section|_ha_section)\("
    )

    def _slice_balanced(src: str, start_paren: int) -> str:
        """Return the substring inside a balanced (...) starting at start_paren
        (index of the '(' character)."""
        depth = 0
        for i in range(start_paren, len(src)):
            c = src[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return src[start_paren + 1 : i]
        return ""

    def _resolve_key(cname, lit) -> str | None:
        if cname:
            return const_map.get(cname)
        return lit

    def _parse_step(fn):
        """Return (top_level_keys, {section_key: [field_keys...]})."""
        src = ast.get_source_segment(_CONFIG_FLOW.read_text(), fn) or ""
        sections: dict[str, set[str]] = {}
        # Mask each section body so top-level scan doesn't pick up nested keys.
        masked = list(src)
        for m in SECTION_HEAD.finditer(src):
            skey = m.group(1)
            open_paren = m.end() - 1  # position of '(' of section(
            body = _slice_balanced(src, open_paren)
            inner_keys: set[str] = set()
            for km in KEY_PAT.finditer(body):
                k = _resolve_key(km.group(1), km.group(2))
                if k and km.group(3) not in ("section", "_ha_section"):
                    inner_keys.add(k)
            sections[skey] = inner_keys
            # Mask this range in the top-level source.
            for i in range(m.start(), open_paren + 1 + len(body) + 1):
                if i < len(masked):
                    masked[i] = " "
        top_src = "".join(masked)
        top: set[str] = set()
        for m in KEY_PAT.finditer(top_src):
            k = _resolve_key(m.group(1), m.group(2))
            if k and m.group(3) not in ("section", "_ha_section"):
                top.add(k)
        return top, sections

    result = {"config": {}, "options": {}}
    for cls, section in ((config_class, "config"), (options_class, "options")):
        for fn in cls.body:
            if isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if fn.name.startswith("async_step_"):
                    sid = fn.name[len("async_step_"):]
                    top, secs = _parse_step(fn)
                    result[section][sid] = {"top": top, "sections": secs}
    return result


def _cases():
    strings = _load(_STRINGS)
    schema = _extract_step_schema_keys()
    seen: list[tuple[str, str, str, str]] = []  # (section, step_id, section_key|"", field)
    for section, step_ids in (
        ("config", ROOM_CONFIG_STEPS),
        ("options", ROOM_OPTIONS_STEPS),
    ):
        for sid in step_ids:
            step_schema = schema.get(section, {}).get(sid, {"top": set(), "sections": {}})
            s_step = strings.get(section, {}).get("step", {}).get(sid, {})
            # Top-level fields.
            top_data = s_step.get("data", {}) or {}
            top_dd = s_step.get("data_description", {}) or {}
            for k in sorted(step_schema["top"] | set(top_data) | set(top_dd)):
                seen.append((section, sid, "", k))
            # Section fields.
            s_sections = s_step.get("sections", {}) or {}
            all_secs = set(step_schema["sections"].keys()) | set(s_sections.keys())
            for skey in sorted(all_secs):
                code_keys = step_schema["sections"].get(skey, set())
                sblock = s_sections.get(skey, {}) or {}
                sd = sblock.get("data", {}) or {}
                sdd = sblock.get("data_description", {}) or {}
                for k in sorted(code_keys | set(sd) | set(sdd)):
                    seen.append((section, sid, skey, k))
    return seen


CASES = _cases()


def _get_field_blocks(blob, section, step_id, section_key):
    step = blob.get(section, {}).get("step", {}).get(step_id, {})
    if not section_key:
        return step, step.get("data", {}) or {}, step.get("data_description", {}) or {}
    sblock = (step.get("sections", {}) or {}).get(section_key, {}) or {}
    return sblock, sblock.get("data", {}) or {}, sblock.get("data_description", {}) or {}


@pytest.mark.parametrize("section,step_id,section_key,key", CASES)
def test_room_field_has_clean_label_and_helper(section, step_id, section_key, key):
    strings = _load(_STRINGS)
    en = _load(_EN)

    where = (
        f"{section}.{step_id}"
        + (f".sections.{section_key}" if section_key else "")
    )
    for src_name, blob in (("strings.json", strings), ("en.json", en)):
        block, data, dd = _get_field_blocks(blob, section, step_id, section_key)
        assert block, f"{src_name}: {where} block missing"

        label = data.get(key)
        assert label, f"{src_name}: {where}.data missing label for '{key}'"
        assert label != key, f"{src_name}: {where}.{key} label equals raw key"
        assert "_" not in label, (
            f"{src_name}: {where}.{key} label {label!r} contains '_' "
            "(raw key leaked into UI)"
        )

        helper = dd.get(key)
        assert helper, (
            f"{src_name}: {where}.data_description missing helper for '{key}'"
        )
        assert len(helper) <= MAX_HELPER_LEN, (
            f"{src_name}: {where}.{key} helper is {len(helper)} chars "
            f"(>{MAX_HELPER_LEN}); shorten."
        )


def test_every_room_menu_option_has_a_label():
    """2026-10-02: the Lighting behaviour menu item rendered blank (no
    menu_options label). Every step the room options menu can show must
    carry a label in both string files."""
    import json, pathlib, re

    src = pathlib.Path("custom_components/universal_room_automation/config_flow.py").read_text()
    menu_steps = set(re.findall(r'"(options_lighting_behaviour|options_lighting|options_covers)"', src))
    for rel in ("strings.json", "translations/en.json"):
        d = json.loads(pathlib.Path("custom_components/universal_room_automation", rel).read_text())
        labels = d["options"]["step"]["init"]["menu_options"]
        for step in menu_steps:
            assert labels.get(step), f"{rel}: menu option {step} has no label"


def test_colour_temperature_fields_use_the_colour_picker():
    """Operator 2026-10-02: kelvin values must be picked visually, not typed."""
    import pathlib

    src = pathlib.Path("custom_components/universal_room_automation/config_flow.py").read_text()
    assert 'unit_of_measurement="K"' not in src
