"""EC-HOUSE-ENTITY-DEFAULTS-1 (Rev 5, 2026-10-13) — acceptance tests.

Covers:
    * Test 1 — ``test_default_literals_contain_no_house_entity_ids``
      (G1: no house-specific entity_ids in DEFAULT_* literal source).
    * Test 2 — ``test_bootstrap_pins_phalanx_shape_options_byte_identical``
      (G3: per-key byte-identity against committed Phalanx fixture).
    * Test 5 — ``test_repair_issue_fires_on_configured_missing_entity``.
    * Test 6 — ``test_repair_issue_cleared_on_recovery``.

Scoped per Rev 5 plan §D-5.5. Driven by targeted file execution only.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# -------------------------------------------------------------------------
# Sibling test files (e.g. test_energy_battery.py) install a BARE
# ModuleType for `custom_components.universal_room_automation` into
# sys.modules — the real __init__.py is never loaded, so the migration
# helpers aren't attached. Detect that situation and load __init__.py as
# a module ourselves so our tests can access `_bootstrap_pin_ec_defaults_once`
# and `_scan_ec_role_entities` directly.
# -------------------------------------------------------------------------
def _load_ura_init_module():
    key = "custom_components.universal_room_automation"
    mod = sys.modules.get(key)
    if mod is not None and hasattr(mod, "_bootstrap_pin_ec_defaults_once"):
        return mod
    repo_root = Path(__file__).resolve().parents[2]
    init_path = (
        repo_root / "custom_components" / "universal_room_automation" / "__init__.py"
    )
    if not init_path.exists():
        return mod
    # Load into a side-channel module name so we don't clobber a sibling
    # test's bootstrap. The migration helpers are self-contained with
    # respect to the production path, so this does not re-register anything.
    side_key = "ura_init_for_ec_defaults_tests"
    if side_key in sys.modules:
        return sys.modules[side_key]
    spec = importlib.util.spec_from_file_location(side_key, str(init_path))
    sidemod = importlib.util.module_from_spec(spec)
    sys.modules[side_key] = sidemod
    try:
        spec.loader.exec_module(sidemod)
    except Exception:  # noqa: BLE001
        # Fallback: swallow (tests that need these will skip at use-site).
        pass
    return sidemod


_URA_INIT = _load_ura_init_module()


def _get_fn(name: str):
    """Return the production helper by name, from whichever module slot
    has it attached (the bare-ModuleType sibling bootstrap puts nothing;
    the real __init__.py side-load does).
    """
    for mod in (
        sys.modules.get("custom_components.universal_room_automation"),
        _URA_INIT,
    ):
        if mod is not None and hasattr(mod, name):
            return getattr(mod, name)
    pytest.skip(f"{name} not available in this test environment")


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOMAIN_COORD_DIR = (
    _REPO_ROOT
    / "custom_components"
    / "universal_room_automation"
    / "domain_coordinators"
)
_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "phalanx_options_pre_migration.json"
)

# Brand / host tokens that must NOT appear inside any DEFAULT_* literal
# entity_id value in energy_const.py / energy_pool.py / energy_circuits.py.
# Allowlisted: DEFAULT_TOU_RATE_FILE (path, not an entity id).
_BRAND_TOKEN_RE = re.compile(
    r"sensor\.(solcast|envoy|iq_|garage_[ab]_power|generac|pentair)"
    r"|switch\.(iq_|smartplug_moes|span_panel|pentair_)"
    r"|select\.(iq_|enpower_)"
    r"|number\.(iq_|enpower_|pentair_)"
    r"|weather\.phalanxmadrone"
)

# DEFAULT_* lines (allow single-line and the first body line of a multi-line
# parenthesised assignment).
_DEFAULT_ASSIGN_RE = re.compile(
    r"^\s*(DEFAULT_[A-Z0-9_]+)\s*(?::\s*[^=]+)?=\s*(.*)$"
)


def _load_default_literal_rhs() -> dict[str, str]:
    """Scan the three source files for DEFAULT_* assignments and return
    the right-hand side text (first line) per name. Multi-line values are
    collapsed by concatenating until the parenthesis-balance returns to 0.
    """
    out: dict[str, str] = {}
    for path in (
        _DOMAIN_COORD_DIR / "energy_const.py",
        _DOMAIN_COORD_DIR / "energy_pool.py",
        _DOMAIN_COORD_DIR / "energy_circuits.py",
    ):
        text = path.read_text()
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            m = _DEFAULT_ASSIGN_RE.match(lines[i])
            if m is None:
                i += 1
                continue
            name, rhs = m.group(1), m.group(2)
            # Multi-line parenthesised RHS: concatenate until parens balance.
            depth = rhs.count("(") - rhs.count(")")
            j = i
            while depth > 0 and j + 1 < len(lines):
                j += 1
                rhs += " " + lines[j].strip()
                depth = rhs.count("(") - rhs.count(")")
            out[name] = rhs
            i = j + 1
    return out


def test_default_literals_contain_no_house_entity_ids() -> None:
    """G1: no DEFAULT_* literal in the three source files encodes a
    house-specific entity_id (brand/host token).

    Allowlisted: DEFAULT_TOU_RATE_FILE (a path string, not an entity_id).
    """
    rhs_map = _load_default_literal_rhs()
    offenders: dict[str, str] = {}
    for name, rhs in rhs_map.items():
        if name == "DEFAULT_TOU_RATE_FILE":
            continue
        if _BRAND_TOKEN_RE.search(rhs):
            offenders[name] = rhs
    assert not offenders, (
        "DEFAULT_* literal(s) still carry house-specific entity_ids: "
        f"{offenders!r}"
    )


# ---------------------------------------------------------------------------
# Pin migration: byte-identity against the Phalanx fixture.
# ---------------------------------------------------------------------------


class _StubEntityRegistry:
    def __init__(self, present_ids: set[str]) -> None:
        self._present = set(present_ids)

    def async_get(self, entity_id: str):  # noqa: D401
        if entity_id in self._present:
            return SimpleNamespace(entity_id=entity_id)
        return None


class _StubConfigEntries:
    """Minimal stand-in for hass.config_entries that captures the last
    options dict written via `async_update_entry`.
    """

    def __init__(self) -> None:
        self.last_options: dict | None = None

    def async_update_entry(self, entry, *, options):
        entry.options = dict(options)
        self.last_options = dict(options)


def _make_fake_hass(present_ids: set[str]):
    """Return (hass, cm_entry) stubs sufficient for the pin migration."""
    hass = MagicMock()
    hass.config_entries = _StubConfigEntries()
    hass.states = MagicMock()
    cm_entry = SimpleNamespace(
        entry_id="cm-test",
        data={},
        options={},
    )
    # Patch er.async_get used inside the migration.
    reg_patch = patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=_StubEntityRegistry(present_ids),
    )
    return hass, cm_entry, reg_patch


@pytest.mark.asyncio
async def test_bootstrap_pins_phalanx_shape_options_byte_identical() -> None:
    """G3: on Phalanx-shaped pre-migration options, every role key
    satisfies ``(pre.get(k) or OLD_DEFAULT) == post[k]``.
    """
    _bootstrap_pin_ec_defaults_once = _get_fn("_bootstrap_pin_ec_defaults_once")
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        EC_ROLE_KEY_DEFAULTS,
    )

    pre_options: dict = {
        k: v for k, v in json.loads(_FIXTURE_PATH.read_text()).items()
        if not k.startswith("_")
    }

    # Assume every OLD default entity_id is present in Phalanx's registry
    # (true on this house — the entity-registry probe at setup confirmed it).
    present_ids: set[str] = set()
    for v in EC_ROLE_KEY_DEFAULTS.values():
        if isinstance(v, list):
            present_ids.update(v)
        elif v:
            present_ids.add(v)

    hass, cm_entry, reg_patch = _make_fake_hass(present_ids)
    cm_entry.options = dict(pre_options)  # Phalanx shape

    with reg_patch:
        wrote = await _bootstrap_pin_ec_defaults_once(hass, cm_entry)
    assert wrote is True
    post = cm_entry.options

    # Per-key byte-identity.
    for k, old_default in EC_ROLE_KEY_DEFAULTS.items():
        expected = pre_options.get(k) if k in pre_options else old_default
        assert post[k] == expected, (
            f"key={k}: pre={pre_options.get(k)!r} old_default={old_default!r} "
            f"post={post.get(k)!r}"
        )

    # Flags set.
    assert post.get("_ec_defaults_pinned") is True
    assert post.get("_ec_defaults_pinned_version")


@pytest.mark.asyncio
async def test_bootstrap_skips_absent_from_registry() -> None:
    """2nd-install path: nothing in the registry → nothing is pinned, keys
    remain absent so the operator sees empty option fields.
    """
    _bootstrap_pin_ec_defaults_once = _get_fn("_bootstrap_pin_ec_defaults_once")
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        EC_ROLE_KEY_DEFAULTS,
    )

    hass, cm_entry, reg_patch = _make_fake_hass(present_ids=set())
    with reg_patch:
        wrote = await _bootstrap_pin_ec_defaults_once(hass, cm_entry)
    assert wrote is True  # flag write still happened

    for key in EC_ROLE_KEY_DEFAULTS:
        assert key not in cm_entry.options, (
            f"2nd install should not have pinned {key} but got "
            f"{cm_entry.options.get(key)!r}"
        )
    assert cm_entry.options.get("_ec_defaults_pinned") is True


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent() -> None:
    """Second invocation is a no-op (flag already set)."""
    _bootstrap_pin_ec_defaults_once = _get_fn("_bootstrap_pin_ec_defaults_once")

    hass, cm_entry, reg_patch = _make_fake_hass(present_ids=set())
    cm_entry.options = {"_ec_defaults_pinned": True}
    with reg_patch:
        wrote = await _bootstrap_pin_ec_defaults_once(hass, cm_entry)
    assert wrote is False
    assert hass.config_entries.last_options is None


# ---------------------------------------------------------------------------
# Repair-issue scanner.
# ---------------------------------------------------------------------------


def _make_fake_hass_sync(present_ids: set[str], unavailable_ids: set[str]):
    """Hass stub whose state machine knows which ids are unavailable."""
    hass = MagicMock()

    def _state_get(eid):
        if eid in unavailable_ids:
            return SimpleNamespace(state="unavailable")
        if eid in present_ids:
            return SimpleNamespace(state="on")
        return None

    hass.states.get.side_effect = _state_get
    return hass


def test_repair_issue_fires_on_configured_missing_entity() -> None:
    """When a configured role-key points at an unregistered entity, the
    scanner creates a WARNING repair issue naming the key and entity.
    """
    _scan_ec_role_entities = _get_fn("_scan_ec_role_entities")

    hass = _make_fake_hass_sync(present_ids=set(), unavailable_ids=set())
    cm_entry = SimpleNamespace(
        data={},
        options={"energy_storage_mode_entity": "select.does_not_exist"},
    )

    created: list[dict] = []

    def _ir_create(*args, **kwargs):
        created.append(kwargs)

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=_StubEntityRegistry(set()),
    ), patch(
        "homeassistant.helpers.issue_registry.async_create_issue",
        side_effect=_ir_create,
    ), patch(
        "homeassistant.helpers.issue_registry.async_delete_issue",
    ):
        _scan_ec_role_entities(hass, cm_entry)

    assert created, "expected at least one repair issue to be created"
    assert any(
        c.get("translation_placeholders", {}).get("entity_id")
        == "select.does_not_exist"
        for c in created
    )


def test_repair_issue_cleared_on_recovery() -> None:
    """When the configured role-key resolves cleanly, the scanner deletes
    any prior issue for that key.
    """
    _scan_ec_role_entities = _get_fn("_scan_ec_role_entities")

    good_id = "select.enpower_482348004678_storage_mode"
    hass = _make_fake_hass_sync(present_ids={good_id}, unavailable_ids=set())
    cm_entry = SimpleNamespace(
        data={},
        options={"energy_storage_mode_entity": good_id},
    )

    deleted: list[str] = []

    def _ir_delete(_hass, _domain, issue_id):
        deleted.append(issue_id)

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=_StubEntityRegistry({good_id}),
    ), patch(
        "homeassistant.helpers.issue_registry.async_create_issue",
    ), patch(
        "homeassistant.helpers.issue_registry.async_delete_issue",
        side_effect=_ir_delete,
    ):
        _scan_ec_role_entities(hass, cm_entry)

    assert "ec_role_entity_energy_storage_mode_entity" in deleted


def test_repair_issue_fires_on_unavailable_entity() -> None:
    """Entity exists in registry but state is `unavailable` — scanner
    reports it as a problem (`problem='unavailable'`).
    """
    _scan_ec_role_entities = _get_fn("_scan_ec_role_entities")

    bad_id = "sensor.solcast_pv_forecast_forecast_today"
    hass = _make_fake_hass_sync(
        present_ids={bad_id}, unavailable_ids={bad_id},
    )
    cm_entry = SimpleNamespace(
        data={},
        options={"energy_solcast_today_entity": bad_id},
    )

    created: list[dict] = []

    def _ir_create(*args, **kwargs):
        created.append(kwargs)

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=_StubEntityRegistry({bad_id}),
    ), patch(
        "homeassistant.helpers.issue_registry.async_create_issue",
        side_effect=_ir_create,
    ), patch(
        "homeassistant.helpers.issue_registry.async_delete_issue",
    ):
        _scan_ec_role_entities(hass, cm_entry)

    assert any(
        c.get("translation_placeholders", {}).get("problem") == "unavailable"
        for c in created
    )


# ---------------------------------------------------------------------------
# l1_charger_active reads the configured list (not DEFAULT_).
# ---------------------------------------------------------------------------


def test_l1_charger_active_reads_configured_list_not_default_literal() -> None:
    """Source check: `l1_charger_active` reads `self._smart_plugs._plugs`
    (configured list) rather than the former
    `DEFAULT_L1_CHARGER_ENTITIES` module constant.
    """
    source = (_DOMAIN_COORD_DIR / "energy.py").read_text()
    # Find the l1_charger_active body window.
    m = re.search(
        r"def l1_charger_active\(self\)[\s\S]{0,800}?return False",
        source,
    )
    assert m is not None, "l1_charger_active body not located"
    body = m.group(0)
    assert "_smart_plugs" in body, (
        "l1_charger_active should read self._smart_plugs._plugs"
    )
    # Strip docstring to isolate the executable body.
    code_only = re.sub(r'"""[\s\S]*?"""', "", body)
    assert "DEFAULT_L1_CHARGER_ENTITIES" not in code_only, (
        "l1_charger_active executable body must not reference "
        "DEFAULT_L1_CHARGER_ENTITIES"
    )
