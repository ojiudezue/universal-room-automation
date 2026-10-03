"""ZONE-DIALOGS-CLEANUP-1 / HOUSE-DIALOGS-CLEANUP-1 slice A (D1, D3, D5).

String-only guards for the Zone Manager, House and CM menu dialogs:
every field a zone/house step renders has a readable label and a short
helper in BOTH strings.json and translations/en.json, no stale labels for
retired keys, no jargon, and every menu option is labelled.

Schema keys are pulled from the real step bodies in config_flow.py (the
first argument of each vol.Optional / vol.Required), resolved through the
CONF_* constants, so a new field without strings fails here.
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

MAX_HELPER_LEN = 220

ZONE_OPTIONS_STEPS = [
    "zone_rooms",
    "zone_media",
    "zone_hvac",
    "zone_energy",
    "zone_persons",
    "zone_cameras",
    "zone_dynamic_preset",
]
HOUSE_OPTIONS_STEPS = [
    "global_sensors",
    "energy_sensors",
    "person_tracking",
    "default_notifications",
    "camera_census",
    "perimeter_alerting",
]

# Words that must not reach the zone/house dialogs (label style guide).
BANNED = [
    "DPM", "RAW", "canonical", "hysteresis", "debounce", "provenance",
    "substrate", "failsafe", "fail-safe", "tier", "Tier", "(v",
]

_KEY_RE = re.compile(
    r"vol\.(?:Optional|Required)\(\s*(?:(CONF_[A-Z0-9_]+)|[\"']([a-z0-9_]+)[\"'])"
)


def _load(p: Path) -> dict:
    return json.loads(p.read_text())


def _const_map() -> dict[str, str]:
    out: dict[str, str] = {}
    files = [_COMPONENT / "const.py", _CONFIG_FLOW] + sorted(_COMPONENT.rglob("*.py"))
    for f in files:
        for m in re.finditer(
            r"^(CONF_[A-Z0-9_]+)\s*(?::[^=\n]+)?=\s*[\"']([^\"']+)[\"']",
            f.read_text(),
            re.MULTILINE,
        ):
            out.setdefault(m.group(1), m.group(2))
    return out


def _options_functions() -> dict[str, str]:
    src = _CONFIG_FLOW.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name.endswith("OptionsFlow"):
            return {
                fn.name: ast.get_source_segment(src, fn) or ""
                for fn in node.body
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    raise AssertionError("OptionsFlow class not found")


def _schema_keys() -> dict[str, set[str]]:
    cmap = _const_map()
    fns = _options_functions()
    result: dict[str, set[str]] = {}
    for sid in ZONE_OPTIONS_STEPS + HOUSE_OPTIONS_STEPS:
        body = fns[f"async_step_{sid}"]
        if sid == "zone_dynamic_preset":
            # Keys are passed as kwargs into _build_dynamic_preset_schema.
            keys = {
                cmap[c]
                for c in re.findall(r"conf_[a-z_]+=(CONF_[A-Z0-9_]+)", body)
            }
        else:
            keys = set()
            for m in _KEY_RE.finditer(body):
                if m.group(1):
                    assert m.group(1) in cmap, f"unresolved constant {m.group(1)}"
                    keys.add(cmap[m.group(1)])
                else:
                    keys.add(m.group(2))
        assert keys, f"no schema keys found for {sid}"
        result[sid] = keys
    return result


SCHEMA = _schema_keys()
_FIELD_CASES = [
    (sid, key)
    for sid in ZONE_OPTIONS_STEPS + HOUSE_OPTIONS_STEPS
    for key in sorted(SCHEMA[sid])
]


def _check_field(sid: str, key: str) -> None:
    for name, blob in (("strings.json", _load(_STRINGS)), ("en.json", _load(_EN))):
        step = blob["options"]["step"][sid]
        label = (step.get("data") or {}).get(key)
        assert label, f"{name}: {sid} has no label for '{key}' (raw key shows)"
        assert label != key and "_" not in label, (
            f"{name}: {sid}.{key} label {label!r} looks like a raw key"
        )
        helper = (step.get("data_description") or {}).get(key)
        assert helper, f"{name}: {sid} has no helper for '{key}'"
        assert len(helper) <= MAX_HELPER_LEN, (
            f"{name}: {sid}.{key} helper is {len(helper)} chars (>{MAX_HELPER_LEN})"
        )


@pytest.mark.parametrize(
    "sid,key",
    [c for c in _FIELD_CASES if c[0] in ZONE_OPTIONS_STEPS],
)
def test_zone_field_has_clean_label_and_helper(sid, key):
    _check_field(sid, key)


@pytest.mark.parametrize(
    "sid,key",
    [c for c in _FIELD_CASES if c[0] in HOUSE_OPTIONS_STEPS],
)
def test_house_field_has_clean_label_and_helper(sid, key):
    _check_field(sid, key)


def test_known_raw_key_bugs_are_fixed():
    """The four HIGH/MEDIUM raw-key bugs named in the plan."""
    for sid, key in (
        ("zone_rooms", "zone_is_outdoor"),
        ("person_tracking", "person_data_retention_days"),
        ("camera_census", "known_face_guests"),
        ("camera_census", "egress_identity_failsafe_strict"),
        ("camera_census", "auto_enable_person_detection"),
        ("perimeter_alerting", "perimeter_vehicle_hours_start"),
        ("perimeter_alerting", "exterior_snapshot_offset_s"),
    ):
        assert key in SCHEMA[sid], f"{key} no longer rendered by {sid}"
        _check_field(sid, key)


@pytest.mark.parametrize("sid", ZONE_OPTIONS_STEPS + HOUSE_OPTIONS_STEPS)
def test_zone_house_strings_have_no_orphan_field_labels(sid):
    """Every data/data_description key is a key the step really renders."""
    for name, blob in (("strings.json", _load(_STRINGS)), ("en.json", _load(_EN))):
        step = blob["options"]["step"][sid]
        for sub in ("data", "data_description"):
            orphans = set(step.get(sub) or {}) - SCHEMA[sid]
            assert not orphans, f"{name}: {sid}.{sub} has stale keys {sorted(orphans)}"


def test_manage_zones_has_no_dead_field_strings():
    for name, blob in (("strings.json", _load(_STRINGS)), ("en.json", _load(_EN))):
        step = blob["options"]["step"]["manage_zones"]
        assert "data" not in step and "data_description" not in step, name
        assert len(step["description"]) <= MAX_HELPER_LEN, name


def _texts(step: dict) -> list[str]:
    out = [step.get("title", ""), step.get("description", "")]
    for sub in ("data", "data_description", "menu_options"):
        out.extend((step.get(sub) or {}).values())
    return out


@pytest.mark.parametrize(
    "sid",
    ["manage_zones", "zone_config_menu"] + ZONE_OPTIONS_STEPS + HOUSE_OPTIONS_STEPS,
)
def test_no_jargon_in_zone_house_strings(sid):
    for name, blob in (("strings.json", _load(_STRINGS)), ("en.json", _load(_EN))):
        for text in _texts(blob["options"]["step"][sid]):
            for tok in BANNED:
                assert tok not in text, f"{name}: {sid} contains {tok!r}: {text!r}"


def _menu_options(step_id: str, marker: str) -> list[str]:
    """Return the menu_options list of the async_show_menu call for step_id
    that follows `marker` in config_flow.py."""
    src = _CONFIG_FLOW.read_text()
    start = src.index(marker)
    m = re.search(
        rf'step_id="{step_id}",\s*menu_options=\[(.*?)\]', src[start:], re.S
    )
    assert m, f"menu for {step_id} not found after {marker!r}"
    return re.findall(r'"([a-z_]+)"', re.sub(r"#[^\n]*", "", m.group(1)))


def test_zone_menu_options_labelled():
    opts = _menu_options("zone_config_menu", "async def async_step_zone_config_menu")
    assert "zone_dynamic_preset" in opts
    for name, blob in (("strings.json", _load(_STRINGS)), ("en.json", _load(_EN))):
        labels = blob["options"]["step"]["zone_config_menu"]["menu_options"]
        for opt in opts:
            assert labels.get(opt), f"{name}: zone menu option {opt} unlabelled"
            for tok in BANNED:
                assert tok not in labels[opt], f"{name}: {opt} label has {tok!r}"


def _cm_menu_all_options() -> list[str]:
    """Every option the dynamic CM menu can show (all coordinators added
    plus add/remove and the shared steps), read from config_flow's tables
    (CM-COORDINATORS-ADD-ONE-BY-ONE-1 made the menu dynamic)."""
    src = _CONFIG_FLOW.read_text()
    tree = ast.parse(src)
    steps: list[str] = []
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", "") == "_COORDINATOR_MENU_STEPS"):
            for v in node.value.values:
                steps.extend(e.value for e in v.elts)
    assert steps, "_COORDINATOR_MENU_STEPS not found"
    start = src.index("def _cm_menu_options(")
    body = src[start:src.index("async def async_step_add_coordinator(", start)]
    return re.findall(r'"([a-z_]+)"', body) + steps


def test_cm_menu_options_labelled():
    opts = _cm_menu_all_options()
    assert "coordinator_notifications_volume" in opts
    for name, blob in (("strings.json", _load(_STRINGS)), ("en.json", _load(_EN))):
        labels = blob["options"]["step"]["init"]["menu_options"]
        for opt in opts:
            assert labels.get(opt), f"{name}: CM menu option {opt} unlabelled"
            for tok in BANNED:
                assert tok not in labels[opt], f"{name}: {opt} label has {tok!r}"
        assert labels["coordinator_notifications_volume"].endswith("Alert noise")
        assert labels["coordinator_notifications_routing"].endswith("Who gets which alerts")


def test_cm_descriptions_cleaned():
    for name, blob in (("strings.json", _load(_STRINGS)), ("en.json", _load(_EN))):
        steps = blob["options"]["step"]
        vol_desc = steps["coordinator_notifications_volume"]["description"]
        assert "Rung-2" not in vol_desc and "NM Cycle" not in vol_desc, name
        assert "do not persist" not in vol_desc, name
        assert "DPM" not in steps["hvac_dynamic_preset"]["description"], name


def test_house_restart_notices():
    for name, blob in (("strings.json", _load(_STRINGS)), ("en.json", _load(_EN))):
        steps = blob["options"]["step"]
        for sid in ("global_sensors", "energy_sensors", "person_tracking", "default_notifications"):
            assert "Saving briefly restarts URA." in steps[sid]["description"], (name, sid)
        assert "Some changes here briefly restart URA." in steps["camera_census"]["description"], name


def test_zone_hvac_mentions_shared_thermostat():
    for name, blob in (("strings.json", _load(_STRINGS)), ("en.json", _load(_EN))):
        desc = blob["options"]["step"]["zone_hvac"]["description"]
        assert "Zones sharing this thermostat get the same settings." in desc, name


def test_person_tracking_has_no_unused_placeholders():
    body = _options_functions()["async_step_person_tracking"]
    assert "retention_info" not in body and "window_info" not in body
