"""D2 — Migration mint-guard tests (Zone-prune hotfix).

Anchors real production ``_migrate_zone_names_to_entries`` at
``custom_components/universal_room_automation/__init__.py:95``.

Mutation-anchored: removing the guard MUST turn
``test_compound_of_existing_zones_skipped`` red.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


_INIT_PY = (
    Path(__file__).parent.parent.parent
    / "custom_components" / "universal_room_automation" / "__init__.py"
)


def test_mint_guard_present_in_source():
    """Mutation-anchor: D2 mint-guard predicates + WARNING must be
    physically in ``_migrate_zone_names_to_entries``. Reverting turns
    this test red immediately (no HA required)."""
    src = _INIT_PY.read_text()
    fn_marker = "async def _migrate_zone_names_to_entries("
    idx = src.index(fn_marker)
    end = src.index("\nasync def _migrate_room_cameras_to_integration", idx)
    region = src[idx:end]
    assert "Zone-prune hotfix D2" in region, "D2 guard marker missing"
    assert "_is_phantom_compound" in region, "P2 compound predicate missing"
    assert "live_hvac_display_names" in region, "P1 live-HVAC predicate missing"
    assert "refusing to mint phantom zone" in region, "D2 WARNING string missing"

_ha = pytest.importorskip(
    "homeassistant.config_entries",
    reason="homeassistant not installed — D2 mint-guard tests skipped locally",
)
if not hasattr(_ha, "ConfigEntry") or not hasattr(_ha, "SOURCE_USER"):
    pytest.skip(
        "homeassistant.config_entries appears stubbed by a sibling test; "
        "D2 behavioral tests need the real package.",
        allow_module_level=True,
    )


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
    """P2 predicate: room CONF_ZONE = 'A + B' where both A and B exist
    as ZONE entries → migration MUST skip minting."""
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
    assert n == 0, "Phantom compound must not be minted"
    assert hass.config_entries.flow.calls == [], (
        "async_init must NOT be called for the phantom compound name"
    )


def test_novel_name_still_minted():
    """Negative: a novel single-word zone still mints normally."""
    from custom_components.universal_room_automation import (
        _migrate_zone_names_to_entries,
    )
    entries = [
        _room_entry("r1", "Garage"),
    ]
    integ = _integration_entry()
    hass = _FakeHass(entries)

    n = asyncio.run(_migrate_zone_names_to_entries(hass, integ))
    assert n == 1, "Novel zone must still be minted"
    assert len(hass.config_entries.flow.calls) == 1


def test_live_hvac_display_name_skipped_when_coordinator_up():
    """P1 predicate: HVAC coordinator is up and reports a merged display
    name that a stale room CONF_ZONE matches → mint MUST be skipped even
    if the name is not a " + "-compound of existing house zones."""
    from custom_components.universal_room_automation import (
        _migrate_zone_names_to_entries,
    )
    # Build a fake HVAC coordinator whose zone_manager reports a merged
    # display name that is NOT " + "-compound of any existing house zone.
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
