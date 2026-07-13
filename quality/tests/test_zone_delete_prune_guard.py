"""D1 — HVAC prune-handler guard tests (Zone-prune hotfix + fix-up).

Anchors real production ``_handle_zm_zones_updated`` + module-level
helpers ``_compute_surviving_thermostats`` / ``_thermostat_still_claimed_helper``
in ``custom_components/universal_room_automation/domain_coordinators/hvac.py``.

Fix-up "Fix 2" test-authority upgrades:
  * Module-level helpers extracted so they are load-bearing correctness
    surface, not nested closures.
  * Import-and-call smoke test loads the D1 helper block via exec with
    the HA + const surface stubbed — no HA runtime required. This ALONE
    would have caught the A-CRIT-1 ImportError in the prior build
    (dead ``from .hvac_const import CONF_ZONE_THERMOSTAT``).
  * Behavioral tests drive the real helpers with SimpleNamespace fakes:
    incident scenario (shared thermostat spared), solo-prune negative,
    legacy-ENTRY_TYPE_ZONE inclusion (A-HIGH-2).
  * Source-anchor test guards against import-path regression.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


_HVAC_PY = (
    Path(__file__).parent.parent.parent
    / "custom_components" / "universal_room_automation"
    / "domain_coordinators" / "hvac.py"
)


def _load_d1_helpers():
    """Extract + exec the D1 helper block from hvac.py source with the
    ``..const`` relative import resolved to a fake module. Exercises the
    REAL production source — a wrong import path in the helpers turns
    this red at exec/call time, catching A-CRIT-1.
    """
    if "_ura_d1_helpers" in sys.modules:
        return sys.modules["_ura_d1_helpers"]

    src = _HVAC_PY.read_text()
    start_marker = "def _compute_surviving_thermostats("
    end_marker = "class HVACCoordinator("
    s_idx = src.index(start_marker)
    e_idx = src.index(end_marker)
    helper_src = src[s_idx:e_idx]

    pkg = types.ModuleType("_ura_d1_pkg")
    pkg.__path__ = []
    const_mod = types.ModuleType("_ura_d1_pkg.const")
    const_mod.CONF_ENTRY_TYPE = "entry_type"
    const_mod.CONF_ZONE_NAME = "zone_name"
    const_mod.CONF_ZONE_THERMOSTAT = "zone_thermostat"
    const_mod.DOMAIN = "universal_room_automation"
    const_mod.ENTRY_TYPE_ZONE = "zone"
    const_mod.ENTRY_TYPE_ZONE_MANAGER = "zone_manager"
    sub_pkg = types.ModuleType("_ura_d1_pkg.domain_coordinators")
    sub_pkg.__path__ = []
    sys.modules["_ura_d1_pkg"] = pkg
    sys.modules["_ura_d1_pkg.const"] = const_mod
    sys.modules["_ura_d1_pkg.domain_coordinators"] = sub_pkg

    hvac_stub = types.ModuleType("_ura_d1_pkg.domain_coordinators.hvac")
    hvac_stub.__package__ = "_ura_d1_pkg.domain_coordinators"
    import logging
    hvac_stub._LOGGER = logging.getLogger("_ura_d1_test")
    exec("from typing import Any", hvac_stub.__dict__)
    exec(helper_src, hvac_stub.__dict__)
    sys.modules["_ura_d1_pkg.domain_coordinators.hvac"] = hvac_stub
    sys.modules["_ura_d1_helpers"] = hvac_stub
    return hvac_stub


class _FakeEntry:
    def __init__(self, data, options=None):
        self.data = data
        self.options = options or {}


class _FakeConfigEntries:
    def __init__(self, entries):
        self._entries = entries

    def async_entries(self, domain):  # noqa: ARG002
        return list(self._entries)


class _FakeHass:
    def __init__(self, entries):
        self.config_entries = _FakeConfigEntries(entries)
        self.data = {}


def _zm_entry_with_zones(zones: dict) -> _FakeEntry:
    return _FakeEntry(
        data={"entry_type": "zone_manager"},
        options={"zones": zones},
    )


def _legacy_zone_entry(name: str, thermostat: str) -> _FakeEntry:
    return _FakeEntry(
        data={
            "entry_type": "zone",
            "zone_name": name,
            "zone_thermostat": thermostat,
        },
    )


def _zs(zone_id, zone_name, climate_entity):
    return SimpleNamespace(
        zone_id=zone_id, zone_name=zone_name, climate_entity=climate_entity,
    )


def test_d1_helpers_load_and_import_paths_resolve():
    """Fix 2c: proves the D1 helper block loads with correct import paths.
    Would have caught prior build's A-CRIT-1 dead import."""
    mod = _load_d1_helpers()
    assert hasattr(mod, "_compute_surviving_thermostats")
    assert hasattr(mod, "_thermostat_still_claimed_helper")
    hass = _FakeHass([])
    surviving, ok = mod._compute_surviving_thermostats(hass, "irrelevant")
    assert surviving == set()
    assert ok is True, (
        "Empty-entries lookup MUST return ok=True. ok=False here means an "
        "import path inside _compute_surviving_thermostats is broken."
    )


def test_incident_shared_thermostat_survives_husk_delete():
    """Fix 2a: 2026-07-12 incident scenario — 2 house zones share one
    thermostat; deleting the compound husk MUST leave the shared
    thermostat in the survivor set."""
    mod = _load_d1_helpers()
    zm_entry = _zm_entry_with_zones({
        "Entertainment": {"zone_thermostat": "climate.shared_bryant"},
        "Master Suite": {"zone_thermostat": "climate.shared_bryant"},
    })
    hass = _FakeHass([zm_entry])
    surviving, ok = mod._compute_surviving_thermostats(
        hass, "Entertainment + Master Suite",
    )
    assert ok is True
    assert "climate.shared_bryant" in surviving, (
        "2026-07-12 incident: shared thermostat MUST remain in survivor "
        "set when the husk compound-named zone is deleted"
    )
    zs = _zs("zone_1", "Entertainment + Master Suite", "climate.shared_bryant")
    assert mod._thermostat_still_claimed_helper(zs, surviving) is True


def test_solo_zone_delete_leaves_empty_survivor_set():
    """Fix 2b: solo-prune negative — last claimant deleted → NOT spared."""
    mod = _load_d1_helpers()
    zm_entry = _zm_entry_with_zones({
        "SoloZone": {"zone_thermostat": "climate.solo_bryant"},
    })
    hass = _FakeHass([zm_entry])
    surviving, ok = mod._compute_surviving_thermostats(hass, "SoloZone")
    assert ok is True
    assert "climate.solo_bryant" not in surviving
    zs = _zs("zone_2", "SoloZone", "climate.solo_bryant")
    assert mod._thermostat_still_claimed_helper(zs, surviving) is False


def test_survivor_set_includes_legacy_entry_type_zone():
    """A-HIGH-2: survivor set must fold BOTH ZM-embedded AND legacy
    ENTRY_TYPE_ZONE surfaces (plan Invariant I)."""
    mod = _load_d1_helpers()
    zm_entry = _zm_entry_with_zones({
        "ZMZone": {"zone_thermostat": "climate.zm_bryant"},
    })
    legacy = _legacy_zone_entry("LegacyZone", "climate.legacy_bryant")
    hass = _FakeHass([zm_entry, legacy])
    surviving, ok = mod._compute_surviving_thermostats(hass, "Deleted")
    assert ok is True
    assert "climate.zm_bryant" in surviving
    assert "climate.legacy_bryant" in surviving, (
        "A-HIGH-2: survivor set MUST include legacy ENTRY_TYPE_ZONE entries"
    )


def test_deleted_name_excluded_from_both_surfaces():
    mod = _load_d1_helpers()
    zm_entry = _zm_entry_with_zones({
        "DeletedZM": {"zone_thermostat": "climate.only_zm"},
    })
    legacy = _legacy_zone_entry("DeletedLegacy", "climate.only_legacy")
    hass = _FakeHass([zm_entry, legacy])

    zm_surviving, _ = mod._compute_surviving_thermostats(hass, "DeletedZM")
    assert "climate.only_zm" not in zm_surviving

    legacy_surviving, _ = mod._compute_surviving_thermostats(
        hass, "DeletedLegacy",
    )
    assert "climate.only_legacy" not in legacy_surviving


def test_guard_predicate_present_in_source():
    src = _HVAC_PY.read_text()
    handler_marker = "def _handle_zm_zones_updated(self, payload"
    idx = src.index(handler_marker)
    end = src.index("\n    def _handle_safety_hazard", idx)
    region = src[idx:end]
    assert "HVAC prune guard" in region
    assert "surviving_thermostats" in region
    assert "_thermostat_still_claimed" in region
    assert "guard_spared_ids" in region


def test_correct_import_path_for_conf_zone_thermostat():
    """A-CRIT-1 anchor: constant MUST be imported from ..const, NOT from
    .hvac_const (which does not define it — verified 2026-07-13)."""
    src = _HVAC_PY.read_text()
    assert "from ..const import" in src
    assert "from .hvac_const import CONF_ZONE_THERMOSTAT" not in src, (
        "A-CRIT-1 regression: CONF_ZONE_THERMOSTAT must NOT be imported "
        "from hvac_const (it is not defined there)"
    )
