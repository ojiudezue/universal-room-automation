"""Tests for the DPM cleanup + room-form label de-jargoning cycle.

Covers the four test buckets called out in PLANNING_dpm_cleanup_and_room_label_pass.md:
  (a) AST denylist-enforcement over strings.json labels
  (b) strings.json vs translations/en.json VALUE parity for keys this cycle
      touched (closes the v5.10.0 parity-gap lesson — assert values equal,
      not just keys)
  (c) Removed-imports/args regression guard: config_flow module imports
      cleanly and the DPM schema renders its 4 remaining fields (via AST
      inspection to avoid the heavy HA import needed for a full flow invoke).
  (d) No-key-rename guard: every translation key present in the pre-cycle
      strings.json baseline is still present in the current strings.json.
      Only the 17 vestigial DPM bucket keys + the sleep_section wrapper
      are permitted to be removed.

Scope note: the plan's D2.1 appendix (full old→new label table) was left
as a placeholder — this cycle applied only the 10 concrete D2.4 samples
plus the number.py _attr_name renames confirmed by the operator. The
denylist test still runs over ALL room-facing labels so any future
label addition that reintroduces "hysteresis"/"debounce"/etc. is caught.
"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CC_ROOT = _REPO_ROOT / "custom_components" / "universal_room_automation"
_STRINGS_JSON = _CC_ROOT / "strings.json"
_EN_JSON = _CC_ROOT / "translations" / "en.json"
_CONFIG_FLOW_PY = _CC_ROOT / "config_flow.py"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def strings_data() -> dict:
    return json.loads(_STRINGS_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def en_data() -> dict:
    return json.loads(_EN_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def config_flow_tree() -> ast.Module:
    return ast.parse(_CONFIG_FLOW_PY.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# (a) AST denylist enforcement over strings.json labels
# ---------------------------------------------------------------------------

# Denylist per plan D2.6: these words are internal jargon and must not
# appear in any user-facing LABEL. They may appear in data_description
# (that's where glosses live), so this test walks `.data` blocks only.
_LABEL_DENYLIST = (
    "hysteresis",
    "debounce",
    "provenance",
    "substrate",
    "failsafe",
    # "tier" -> matches too aggressively (e.g. "tiered"); use targeted
    # substring rather than word-boundary to keep the test simple.
)

# `occ ` abbreviation as a whole token (with trailing space) — flag its
# use as a shorthand in labels. Won't match "occupancy" or "occupied".
_LABEL_DENYLIST_TOKEN = ("occ ",)

# Room-facing step allowlist: the plan's Part 2 scope. Only these step
# ids get the denylist check (avoids sweeping unrelated integration /
# energy / zone / hvac-coordinator steps that share strings.json).
_ROOM_FACING_STEPS = frozenset({
    "room_setup",
    "sensors",
    "devices",
    "night_light_detail",
    "cover_behavior",
    "automation_behavior",
    "init_automation_chaining",
    "init_ai_rules",
    "init_ai_rule_add",
    "climate",
    "fan_speeds",
    "sleep_protection",
    "basic_setup",
    "notifications",
})


def _iter_labels(step_dict: dict, step_id: str):
    """Yield (step_id, field_key, label) for each entry in step.data."""
    data_block = step_dict.get("data")
    if not isinstance(data_block, dict):
        return
    for field_key, label in data_block.items():
        if isinstance(label, str):
            yield step_id, field_key, label


def _walk_room_facing_labels(strings: dict):
    """Yield labels from every room-facing step in config.step and options.step."""
    for section in ("config", "options"):
        steps = strings.get(section, {}).get("step", {})
        for step_id, step_dict in steps.items():
            if step_id in _ROOM_FACING_STEPS and isinstance(step_dict, dict):
                yield from _iter_labels(step_dict, step_id)


class TestDenylistOverLabels:
    """Plan D2.6: no room-facing `strings.json` label may contain any
    token from the denylist. `data_description` entries are exempt."""

    def test_no_denylist_word_in_room_facing_labels_strings(self, strings_data):
        violations = []
        for step_id, field_key, label in _walk_room_facing_labels(strings_data):
            low = label.lower()
            for banned in _LABEL_DENYLIST:
                if banned in low:
                    violations.append((step_id, field_key, banned, label))
            for banned in _LABEL_DENYLIST_TOKEN:
                if banned in low:
                    violations.append((step_id, field_key, banned.strip(), label))
        assert not violations, (
            "Denylist words leaked into room-facing labels (strings.json): "
            f"{violations}"
        )

    def test_no_denylist_word_in_room_facing_labels_en(self, en_data):
        violations = []
        for step_id, field_key, label in _walk_room_facing_labels(en_data):
            low = label.lower()
            for banned in _LABEL_DENYLIST:
                if banned in low:
                    violations.append((step_id, field_key, banned, label))
            for banned in _LABEL_DENYLIST_TOKEN:
                if banned in low:
                    violations.append((step_id, field_key, banned.strip(), label))
        assert not violations, (
            "Denylist words leaked into room-facing labels (translations/en.json): "
            f"{violations}"
        )


# ---------------------------------------------------------------------------
# (b) strings.json vs en.json VALUE parity for keys this cycle touched
# ---------------------------------------------------------------------------

# Explicit list of the labels + data_description entries edited during
# this cycle. Assert both files carry byte-identical values so a future
# edit to one but not the other is caught (v5.10.0 lesson — the shipped
# parity test only compares KEYS).
_CYCLE_TOUCHED_KEYS = (
    # step, section (data|data_description), field_key
    # -- Sensors (config + options)
    ("sensors", "data", "presence_sensors"),
    ("sensors", "data", "occupancy_sensors"),
    ("sensors", "data_description", "presence_sensors"),
    ("sensors", "data_description", "occupancy_sensors"),
    ("sensors", "data_description", "scanner_areas"),
    ("sensors", "data_description", "is_egress_window"),
    # -- Room setup helper
    ("room_setup", "data_description", "occupancy_debounce"),
    # -- Climate hvac_coordination_enabled helper
    ("climate", "data_description", "hvac_coordination_enabled"),
    # -- HVAC-coordinator-settings label + dpm adjustment (touched via
    #    denylist sweep; parent step is coordinator_hvac_settings, not
    #    a room step)
    ("coordinator_hvac_settings", "data", "hvac_zone_entry_dwell"),
    # -- Sleep protection D2.4 #10
    ("sleep_protection", "data", "sleep_bypass_motion_count"),
    ("sleep_protection", "data_description", "sleep_bypass_motion_count"),
    # -- Zone DPM step (Part 1 rewrite of the description + 4-field surface)
    ("zone_dynamic_preset", "data", "zone_dynamic_preset_enabled"),
    ("zone_dynamic_preset", "data", "zone_dynamic_preset_offset"),
    ("zone_dynamic_preset", "data", "zone_dynamic_preset_reset_offset_guest"),
    ("zone_dynamic_preset", "data", "zone_dynamic_preset_sleep_enabled"),
    ("zone_dynamic_preset", "data_description", "zone_dynamic_preset_enabled"),
    ("zone_dynamic_preset", "data_description", "zone_dynamic_preset_offset"),
    # -- HVAC DPM Adjustment labels
    ("hvac_dynamic_preset", "data", "dynamic_preset_dwell_minutes"),
    ("hvac_dynamic_preset", "data", "dynamic_preset_hysteresis_f"),
    # -- Appendix A PROPOSED (rows 18-40) + Part 1 wording (row 40)
    ("room_setup", "data", "shared_space_warning"),
    ("sensors", "data", "disable_camera_presence"),
    ("sensors", "data", "door_type"),
    ("devices", "data", "light_capabilities"),
    ("devices", "data", "humidity_fans"),
    ("devices", "data", "auto_switches"),
    ("devices", "data", "manual_switches"),
    ("cover_behavior", "data", "entry_cover_action"),
    ("cover_behavior", "data", "exit_cover_action"),
    ("cover_behavior", "data", "open_timing_mode"),
    ("cover_behavior", "data", "close_timing_mode"),
    ("cover_behavior", "data", "cover_hvac_managed"),
    ("automation_behavior", "data", "illuminance_dark_threshold"),
    ("automation_behavior", "data", "light_transition_seconds_on"),
    ("automation_behavior", "data", "light_transition_seconds_off"),
    ("climate", "data", "humidity_fan_presence_runtime_base_s"),
    ("climate", "data", "humidity_fan_presence_runtime_per_min_s"),
    ("climate", "data", "humidity_fan_presence_runtime_cap_s"),
    ("climate", "data", "humidity_fan_timeout"),
    ("climate", "data", "humidity_fan_max_runtime"),
    ("sleep_protection", "data", "fan_sleep_policy"),
    ("basic_setup", "data", "room_guest_occupancy_threshold_min"),
)


def _lookup(root: dict, section: str, step: str, sub: str, field: str):
    """Return the value at root[<section>].step[<step>][<sub>][<field>], or None."""
    try:
        return root[section]["step"][step][sub][field]
    except (KeyError, TypeError):
        return None


class TestStringsEnValueParity:
    """v5.10.0 lesson: shipped parity test compares keys, not values.
    This test compares VALUES for the specific keys this cycle touched."""

    @pytest.mark.parametrize(
        "step,sub,field",
        _CYCLE_TOUCHED_KEYS,
        ids=lambda x: x,
    )
    def test_strings_en_value_parity_config_scope(
        self, strings_data, en_data, step, sub, field,
    ):
        # Look up in both config.step and options.step; at least one
        # scope must exist in both files with equal values.
        found_any = False
        for section in ("config", "options"):
            s_val = _lookup(strings_data, section, step, sub, field)
            e_val = _lookup(en_data, section, step, sub, field)
            if s_val is None and e_val is None:
                continue
            found_any = True
            assert s_val == e_val, (
                f"strings.json vs translations/en.json divergence at "
                f"{section}.step.{step}.{sub}.{field}: "
                f"strings={s_val!r} en={e_val!r}"
            )
        assert found_any, (
            f"Cycle-touched key not found in either strings.json or en.json: "
            f"step={step} sub={sub} field={field}"
        )

    def test_zone_dpm_description_parity(self, strings_data, en_data):
        s_desc = strings_data["options"]["step"]["zone_dynamic_preset"]["description"]
        e_desc = en_data["options"]["step"]["zone_dynamic_preset"]["description"]
        assert s_desc == e_desc


# ---------------------------------------------------------------------------
# (c) Removed-imports / args regression guard
# ---------------------------------------------------------------------------


class TestPart1SchemaSurface:
    """Regression guard: the DPM schema renders its 4 remaining fields
    and the 17 vestigial keys are not imported / passed / referenced in
    the render call site."""

    def test_config_flow_module_parses(self, config_flow_tree):
        # AST parse succeeded — module is importable at the syntax layer.
        assert isinstance(config_flow_tree, ast.Module)

    def test_seventeen_vestigial_confs_not_imported_at_dpm_render(self):
        src = _CONFIG_FLOW_PY.read_text(encoding="utf-8")
        # Locate the async_step_zone_dynamic_preset method body.
        idx = src.find("async def async_step_zone_dynamic_preset(")
        assert idx > 0, "async_step_zone_dynamic_preset must exist"
        body = src[idx:idx + 6000]
        vestigial = (
            "CONF_ZONE_DYNAMIC_PRESET_CUSTOMIZE_BUCKETS",
            "CONF_ZONE_DYNAMIC_PRESET_COOL_HOME_LOW",
            "CONF_ZONE_DYNAMIC_PRESET_COOL_HOME_HIGH",
            "CONF_ZONE_DYNAMIC_PRESET_MILD_HOME_LOW",
            "CONF_ZONE_DYNAMIC_PRESET_MILD_HOME_HIGH",
            "CONF_ZONE_DYNAMIC_PRESET_HOT_HOME_LOW",
            "CONF_ZONE_DYNAMIC_PRESET_HOT_HOME_HIGH",
            "CONF_ZONE_DYNAMIC_PRESET_EXTREME_HOME_LOW",
            "CONF_ZONE_DYNAMIC_PRESET_EXTREME_HOME_HIGH",
            "CONF_ZONE_DYNAMIC_PRESET_COOL_SLEEP_LOW",
            "CONF_ZONE_DYNAMIC_PRESET_COOL_SLEEP_HIGH",
            "CONF_ZONE_DYNAMIC_PRESET_MILD_SLEEP_LOW",
            "CONF_ZONE_DYNAMIC_PRESET_MILD_SLEEP_HIGH",
            "CONF_ZONE_DYNAMIC_PRESET_HOT_SLEEP_LOW",
            "CONF_ZONE_DYNAMIC_PRESET_HOT_SLEEP_HIGH",
            "CONF_ZONE_DYNAMIC_PRESET_EXTREME_SLEEP_LOW",
            "CONF_ZONE_DYNAMIC_PRESET_EXTREME_SLEEP_HIGH",
        )
        leaked = [name for name in vestigial if name in body]
        assert not leaked, (
            "v5.11.x DPM cleanup: async_step_zone_dynamic_preset must "
            f"not reference the 17 vestigial CONF constants; found: {leaked}"
        )

    def test_dpm_schema_signature_is_4_named_params(self, config_flow_tree):
        # Find _build_dynamic_preset_schema.
        target = None
        for node in ast.walk(config_flow_tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_build_dynamic_preset_schema":
                target = node
                break
        assert target is not None, "_build_dynamic_preset_schema must exist"
        # No *args after the strip.
        assert target.args.vararg is None, (
            "v5.11.x DPM cleanup: _build_dynamic_preset_schema must not "
            "take *conf_keys anymore (4 named keyword-only params instead)"
        )
        # 4 keyword-only args with the expected names.
        kwonly_names = [a.arg for a in target.args.kwonlyargs]
        assert kwonly_names == [
            "conf_enabled",
            "conf_offset",
            "conf_reset_guest",
            "conf_sleep_enabled",
        ], (
            f"v5.11.x DPM cleanup: unexpected kwonly args {kwonly_names!r}"
        )

    def test_dpm_strings_data_block_has_only_4_fields(self, strings_data):
        data = strings_data["options"]["step"]["zone_dynamic_preset"]["data"]
        assert set(data.keys()) == {
            "zone_dynamic_preset_enabled",
            "zone_dynamic_preset_offset",
            "zone_dynamic_preset_reset_offset_guest",
            "zone_dynamic_preset_sleep_enabled",
        }

    def test_dpm_en_data_block_has_only_4_fields(self, en_data):
        data = en_data["options"]["step"]["zone_dynamic_preset"]["data"]
        assert set(data.keys()) == {
            "zone_dynamic_preset_enabled",
            "zone_dynamic_preset_offset",
            "zone_dynamic_preset_reset_offset_guest",
            "zone_dynamic_preset_sleep_enabled",
        }

    def test_dpm_no_sections_block_remains(self, strings_data, en_data):
        s_step = strings_data["options"]["step"]["zone_dynamic_preset"]
        e_step = en_data["options"]["step"]["zone_dynamic_preset"]
        # sections block is either absent or empty; sleep_section must not
        # be present under either surface.
        for name, block in (("strings.json", s_step), ("translations/en.json", e_step)):
            sections = block.get("sections", {})
            assert "sleep_section" not in sections, (
                f"v5.11.x DPM cleanup: sleep_section must be stripped from {name}"
            )
            assert "customize_buckets_section" not in sections, (
                f"v4.7.18 D1: customize_buckets_section must be stripped from {name}"
            )


# ---------------------------------------------------------------------------
# (d) No-key-rename guard: snapshot-compare against git HEAD strings.json
# ---------------------------------------------------------------------------


def _load_head_strings_keys() -> set[str] | None:
    """Read the pre-cycle strings.json from `git show HEAD:...` and return
    the flat set of `config.step.<step>.data.<field>` + `options.step...`
    key paths.

    Returns None if git or the file are unavailable (test skips)."""
    try:
        raw = subprocess.check_output(
            ["git", "show", f"HEAD:custom_components/universal_room_automation/strings.json"],
            cwd=str(_REPO_ROOT),
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    keys: set[str] = set()
    for section in ("config", "options"):
        steps = data.get(section, {}).get("step", {})
        for step_id, step_dict in steps.items():
            if not isinstance(step_dict, dict):
                continue
            for sub in ("data", "data_description"):
                block = step_dict.get(sub)
                if isinstance(block, dict):
                    for field_key in block:
                        keys.add(f"{section}.step.{step_id}.{sub}.{field_key}")
            sections_block = step_dict.get("sections")
            if isinstance(sections_block, dict):
                for section_key in sections_block:
                    keys.add(f"{section}.step.{step_id}.sections.{section_key}")
    return keys


def _current_strings_keys(strings: dict) -> set[str]:
    keys: set[str] = set()
    for section in ("config", "options"):
        steps = strings.get(section, {}).get("step", {})
        for step_id, step_dict in steps.items():
            if not isinstance(step_dict, dict):
                continue
            for sub in ("data", "data_description"):
                block = step_dict.get(sub)
                if isinstance(block, dict):
                    for field_key in block:
                        keys.add(f"{section}.step.{step_id}.{sub}.{field_key}")
            sections_block = step_dict.get("sections")
            if isinstance(sections_block, dict):
                for section_key in sections_block:
                    keys.add(f"{section}.step.{step_id}.sections.{section_key}")
    return keys


# The allow-list of keys this cycle is permitted to REMOVE from the
# pre-cycle baseline. Only the 17 vestigial DPM bucket cells + the
# sleep_section wrapper live here; everything else is preserved.
_ALLOWED_REMOVED_KEYS = frozenset(
    f"options.step.zone_dynamic_preset.{sub}.{field}"
    for sub, fields in {
        "data": (
            "zone_dynamic_preset_cool_home_low",
            "zone_dynamic_preset_cool_home_high",
            "zone_dynamic_preset_mild_home_low",
            "zone_dynamic_preset_mild_home_high",
            "zone_dynamic_preset_hot_home_low",
            "zone_dynamic_preset_hot_home_high",
            "zone_dynamic_preset_extreme_home_low",
            "zone_dynamic_preset_extreme_home_high",
            "zone_dynamic_preset_cool_sleep_low",
            "zone_dynamic_preset_cool_sleep_high",
            "zone_dynamic_preset_mild_sleep_low",
            "zone_dynamic_preset_mild_sleep_high",
            "zone_dynamic_preset_hot_sleep_low",
            "zone_dynamic_preset_hot_sleep_high",
            "zone_dynamic_preset_extreme_sleep_low",
            "zone_dynamic_preset_extreme_sleep_high",
        ),
        "data_description": (
            "zone_dynamic_preset_cool_home_low",
            "zone_dynamic_preset_cool_home_high",
            "zone_dynamic_preset_mild_home_low",
            "zone_dynamic_preset_mild_home_high",
            "zone_dynamic_preset_hot_home_low",
            "zone_dynamic_preset_hot_home_high",
            "zone_dynamic_preset_extreme_home_low",
            "zone_dynamic_preset_extreme_home_high",
            "zone_dynamic_preset_cool_sleep_low",
            "zone_dynamic_preset_cool_sleep_high",
            "zone_dynamic_preset_mild_sleep_low",
            "zone_dynamic_preset_mild_sleep_high",
            "zone_dynamic_preset_hot_sleep_low",
            "zone_dynamic_preset_hot_sleep_high",
            "zone_dynamic_preset_extreme_sleep_low",
            "zone_dynamic_preset_extreme_sleep_high",
        ),
        "sections": ("sleep_section",),
    }.items()
    for field in fields
)


class TestNoKeyRenameGuard:
    """Snapshot-compare current strings.json against git HEAD to catch any
    accidental translation-KEY rename. Only the 17 vestigial DPM keys +
    the sleep_section wrapper are permitted to disappear."""

    def test_no_key_removed_beyond_allowlist(self, strings_data):
        head_keys = _load_head_strings_keys()
        if head_keys is None:
            pytest.skip("git HEAD strings.json unavailable; skipping snapshot compare")
        cur_keys = _current_strings_keys(strings_data)
        removed = head_keys - cur_keys - _ALLOWED_REMOVED_KEYS
        assert not removed, (
            "v5.11.x DPM cleanup / label pass: translation keys were "
            f"removed beyond the allow-list. Renamed / dropped keys: "
            f"{sorted(removed)}"
        )
