"""D2 — Migration mint-guard tests (Zone-prune hotfix + fix-up).

Anchors real production ``_migrate_zone_names_to_entries`` and its
module-level helpers ``_is_phantom_compound`` / ``_live_hvac_display_names``
in ``custom_components/universal_room_automation/__init__.py``.

Fix-up "Fix 2" test-authority upgrades:
  * D2 helpers extracted to module-level so tests can drive them
    without triggering the URA package's HA-heavy __init__ import.
  * Import-and-call smoke test loads the helper block via exec with
    the DOMAIN constant stubbed — no HA runtime required.
  * Helper-driven positive + negative tests for `_is_phantom_compound`
    and CM-vs-legacy-slot resolution in `_live_hvac_display_names`.
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


_INIT_PY = (
    Path(__file__).parent.parent.parent
    / "custom_components" / "universal_room_automation" / "__init__.py"
)


def _load_d2_helpers():
    """Extract + exec the D2 helper block from __init__.py with DOMAIN
    stubbed. No HA runtime needed."""
    if "_ura_d2_helpers" in sys.modules:
        return sys.modules["_ura_d2_helpers"]
    src = _INIT_PY.read_text()
    start_marker = "def _is_phantom_compound("
    end_marker = "PLATFORMS: list[Platform]"
    s_idx = src.index(start_marker)
    e_idx = src.index(end_marker)
    helper_src = src[s_idx:e_idx]

    mod = types.ModuleType("_ura_d2_helpers")
    import logging
    mod._LOGGER = logging.getLogger("_ura_d2_test")
    mod.DOMAIN = "universal_room_automation"
    exec("from typing import Any", mod.__dict__)
    exec(helper_src, mod.__dict__)
    sys.modules["_ura_d2_helpers"] = mod
    return mod


def test_d2_helpers_load_and_import_paths_resolve():
    """Fix 2 import smoke test — D2 helpers callable without HA runtime."""
    mod = _load_d2_helpers()
    assert hasattr(mod, "_is_phantom_compound")
    assert hasattr(mod, "_live_hvac_display_names")
    ok, parts = mod._is_phantom_compound(
        "Entertainment + Master Suite",
        {"entertainment", "master suite"},
    )
    assert ok is True
    assert set(p.lower() for p in parts) == {"entertainment", "master suite"}


def test_is_phantom_compound_negative_single_name():
    """Legitimate single-name zone MUST NOT be flagged as phantom."""
    mod = _load_d2_helpers()
    ok, parts = mod._is_phantom_compound(
        "Garage", {"entertainment", "master suite"},
    )
    assert ok is False
    assert parts == []


def test_is_phantom_compound_negative_compound_with_unknown_part():
    """Compound with unknown part MUST NOT be flagged."""
    mod = _load_d2_helpers()
    ok, parts = mod._is_phantom_compound(
        "Entertainment + Novel",
        {"entertainment", "master suite"},
    )
    assert ok is False
    assert parts == ["Entertainment", "Novel"]


def test_live_hvac_display_names_empty_when_no_coordinator():
    mod = _load_d2_helpers()
    class _Hass:
        def __init__(self):
            self.data = {}
    assert mod._live_hvac_display_names(_Hass()) == set()


def test_live_hvac_display_names_reads_via_coordinator_manager():
    """A-HIGH-1 / B-HIGH-1: helper MUST read from CM.coordinators["hvac"]
    (production canonical), not just the legacy hass.data slot."""
    mod = _load_d2_helpers()
    fake_zs = SimpleNamespace(zone_name="AliasMerged")
    fake_zm = SimpleNamespace(zones={"zone_1": fake_zs})
    fake_hvac = SimpleNamespace(zone_manager=fake_zm)
    fake_cm = SimpleNamespace(coordinators={"hvac": fake_hvac})

    class _Hass:
        def __init__(self):
            self.data = {"universal_room_automation": {"coordinator_manager": fake_cm}}
    assert "aliasmerged" in mod._live_hvac_display_names(_Hass())


def test_live_hvac_display_names_falls_back_to_legacy_slot():
    """Legacy `hass.data[DOMAIN]["hvac_coordinator"]` remains a
    best-effort fallback (tests + very-early boot)."""
    mod = _load_d2_helpers()
    fake_zs = SimpleNamespace(zone_name="LegacyMerged")
    fake_zm = SimpleNamespace(zones={"zone_1": fake_zs})
    fake_hvac = SimpleNamespace(zone_manager=fake_zm)

    class _Hass:
        def __init__(self):
            self.data = {"universal_room_automation": {"hvac_coordinator": fake_hvac}}
    assert "legacymerged" in mod._live_hvac_display_names(_Hass())


def test_mint_guard_present_in_source():
    """Source-anchor: D2 mint-guard predicates + WARNING must be
    physically in ``_migrate_zone_names_to_entries``."""
    src = _INIT_PY.read_text()
    fn_marker = "async def _migrate_zone_names_to_entries("
    idx = src.index(fn_marker)
    end = src.index("\nasync def _migrate_room_cameras_to_integration", idx)
    region = src[idx:end]
    assert "Zone-prune hotfix D2" in region
    assert "_is_phantom_compound" in region
    assert "live_hvac_display_names" in region
    assert "refusing to mint phantom zone" in region


# Per-test HA gate for the legacy full-flow behavioral tests below.
def _require_ha():
    try:
        import homeassistant.config_entries as _ha  # noqa: F401
    except ImportError:
        pytest.skip("homeassistant not installed — D2 behavioral test skipped")


class _FakeEntry:
    def __init__(self, data, options=None, entry_id="e"):
        self.data = data
        self.options = options or {}
        self.entry_id = entry_id


class _FakeFlow:
    def __init__(self):
        self.calls = []

    async def async_init(self, domain, context=None, data=None):
        self.calls.append({"domain": domain, "context": context, "data": data})
        return {"type": "create_entry"}


class _FakeConfigEntries:
    def __init__(self, entries):
        self._entries = entries
        self.flow = _FakeFlow()

    def async_entries(self, domain):  # noqa: ARG002
        return list(self._entries)


class _FakeHass:
    def __init__(self, entries, hvac_coord=None):
        _require_ha()
        self.config_entries = _FakeConfigEntries(entries)
        from custom_components.universal_room_automation.const import DOMAIN
        self.data = {DOMAIN: {}}
        if hvac_coord is not None:
            self.data[DOMAIN]["hvac_coordinator"] = hvac_coord


def _room_entry(entry_id, zone_name):
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM, CONF_ZONE,
    )
    return _FakeEntry(
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ZONE: zone_name},
        entry_id=entry_id,
    )


def _zone_entry(entry_id, zone_name):
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE, ENTRY_TYPE_ZONE, CONF_ZONE_NAME,
    )
    return _FakeEntry(
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE, CONF_ZONE_NAME: zone_name},
        entry_id=entry_id,
    )


def _integration_entry():
    return _FakeEntry(data={}, entry_id="integration_e")


def test_compound_of_existing_zones_skipped():
    _require_ha()
    from custom_components.universal_room_automation import (
        _migrate_zone_names_to_entries,
    )
    entries = [
        _zone_entry("z_a", "Entertainment"),
        _zone_entry("z_b", "Master Suite"),
        _room_entry("r1", "Entertainment + Master Suite"),
    ]
    integ = _integration_entry()
    hass = _FakeHass(entries)

    n = asyncio.run(_migrate_zone_names_to_entries(hass, integ))
    assert n == 0
    assert hass.config_entries.flow.calls == []


def test_novel_name_still_minted():
    _require_ha()
    from custom_components.universal_room_automation import (
        _migrate_zone_names_to_entries,
    )
    entries = [
        _room_entry("r1", "Garage"),
    ]
    integ = _integration_entry()
    hass = _FakeHass(entries)

    n = asyncio.run(_migrate_zone_names_to_entries(hass, integ))
    assert n == 1
    assert len(hass.config_entries.flow.calls) == 1


def test_live_hvac_display_name_skipped_when_coordinator_up():
    _require_ha()
    from custom_components.universal_room_automation import (
        _migrate_zone_names_to_entries,
    )
    fake_zs = SimpleNamespace(zone_name="AliasMerged")
    fake_zm = SimpleNamespace(zones={"zone_1": fake_zs})
    fake_hvac = SimpleNamespace(zone_manager=fake_zm)

    entries = [
        _room_entry("r1", "AliasMerged"),
    ]
    integ = _integration_entry()
    hass = _FakeHass(entries, hvac_coord=fake_hvac)

    n = asyncio.run(_migrate_zone_names_to_entries(hass, integ))
    assert n == 0
    assert hass.config_entries.flow.calls == []
