"""Guard against config-flow label drift between strings.json and translations/en.json.

Root cause (v5.6.0): the bathroom-exhaust cycle updated `strings.json` (the dev
source) with the renamed "Climate & Fans" step + new field labels, but never
synced `translations/en.json` — which is what Home Assistant actually serves to
the config-flow UI. Result: the live form showed the old title and raw
snake_case field keys instead of friendly labels.

This test asserts, for every config/options step in strings.json, that en.json
carries the same title and at least the same `data` / `data_description` keys.
For the English base language, en.json should mirror strings.json; a missing
key here means a user would see a raw key in the UI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"
_STRINGS = _COMPONENT / "strings.json"
_EN = _COMPONENT / "translations" / "en.json"


def _load(p: Path) -> dict:
    return json.loads(p.read_text())


def _step_field_cases():
    strings = _load(_STRINGS)
    cases = []
    for flow in ("config", "options"):
        for step_id, step in strings.get(flow, {}).get("step", {}).items():
            cases.append((flow, step_id, step))
    return cases


@pytest.mark.parametrize(
    "flow,step_id,strings_step",
    _step_field_cases(),
    ids=[f"{f}.{s}" for f, s, _ in _step_field_cases()],
)
def test_en_translation_matches_strings_step(flow, step_id, strings_step):
    en = _load(_EN)
    en_step = en.get(flow, {}).get("step", {}).get(step_id)
    assert en_step is not None, (
        f"translations/en.json is missing the '{flow}.{step_id}' step that exists "
        f"in strings.json — HA would fall back to raw keys in the UI."
    )

    # Title must match (this is what surfaced the 'Climate & HVAC' vs 'Climate & Fans' miss).
    if "title" in strings_step:
        assert en_step.get("title") == strings_step["title"], (
            f"{flow}.{step_id} title drift: strings.json={strings_step['title']!r} "
            f"en.json={en_step.get('title')!r}"
        )

    # Every field label/help present in strings must exist in en (else raw key shows).
    for sub in ("data", "data_description"):
        missing = set(strings_step.get(sub, {})) - set(en_step.get(sub, {}))
        assert not missing, (
            f"{flow}.{step_id}.{sub}: translations/en.json is missing keys {sorted(missing)} "
            f"— sync them from strings.json or the UI shows raw snake_case keys."
        )

    # Menu-item labels (options-flow menus) must match too. A step rename that
    # updates the step title but forgets the menu_options label leaves a stale
    # menu entry (the v5.6.1 "Climate & HVAC" menu-item miss).
    s_menu = strings_step.get("menu_options", {})
    e_menu = en_step.get("menu_options", {})
    for key, label in s_menu.items():
        assert key in e_menu, (
            f"{flow}.{step_id}.menu_options is missing key {key!r} in translations/en.json."
        )
        assert e_menu[key] == label, (
            f"{flow}.{step_id}.menu_options[{key!r}] drift: "
            f"strings.json={label!r} en.json={e_menu.get(key)!r}"
        )

    # `sections` parity. When config_flow.py wraps fields inside a HA
    # `section(...)`, the field labels must live under `sections.<key>.data`
    # (not the step's top-level `data`), or HA renders both the section
    # header and its fields as raw snake_case keys. We assert:
    #   - every section key in strings.json exists in en.json
    #   - each section's `name` matches
    #   - each section's `data` / `data_description` keys are a subset in en.json
    s_sections = strings_step.get("sections", {})
    e_sections = en_step.get("sections", {})
    for sec_key, s_sec in s_sections.items():
        assert sec_key in e_sections, (
            f"{flow}.{step_id}.sections is missing key {sec_key!r} in translations/en.json "
            f"— the section header would render as raw snake_case in the UI."
        )
        e_sec = e_sections[sec_key]
        # Two valid shapes for a section value:
        #   - str: shorthand for {"name": "<string>"} (existing convention in
        #     hvac_baseline_presets, hvac_dynamic_preset, etc.)
        #   - dict: full {"name": ..., "data": {...}, "data_description": {...}}
        if isinstance(s_sec, str):
            assert e_sec == s_sec, (
                f"{flow}.{step_id}.sections.{sec_key} drift: "
                f"strings.json={s_sec!r} en.json={e_sec!r}"
            )
            continue
        # dict form
        if "name" in s_sec:
            e_name = e_sec.get("name") if isinstance(e_sec, dict) else e_sec
            assert e_name == s_sec["name"], (
                f"{flow}.{step_id}.sections.{sec_key}.name drift: "
                f"strings.json={s_sec['name']!r} en.json={e_name!r}"
            )
        if not isinstance(e_sec, dict):
            raise AssertionError(
                f"{flow}.{step_id}.sections.{sec_key}: strings.json has dict-form section "
                f"but translations/en.json has {type(e_sec).__name__} — cannot carry data labels."
            )
        for sub in ("data", "data_description"):
            missing = set(s_sec.get(sub, {})) - set(e_sec.get(sub, {}))
            assert not missing, (
                f"{flow}.{step_id}.sections.{sec_key}.{sub}: translations/en.json "
                f"is missing keys {sorted(missing)} — sync them from strings.json or "
                f"the UI shows raw snake_case keys."
            )
