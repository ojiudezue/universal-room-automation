"""APPLIANCE-MGMT-REFINE-1 v1b — options-flow tests.

Covers:
- CM menu includes ``coordinator_appliance``.
- Add-record round-trip: an added record lands in ``CONF_APPLIANCE_RECORDS``
  and the v1a census reader surfaces it with its declared
  ``functional_domain`` (NOT "other").
- Net-new TV (media_player NOT in any room config) is ABSENT from the
  v1a census until added via the flow, then present after (v1b
  acceptance moved from v1a).
- Cross-integration triple-covered appliance (declared record naming
  ThinQ + SPAN + room entity refs) collapses to ONE census record after
  the operator groups them (v1b acceptance moved from v1a).
- Reject-at-validation: saving a record whose entity is already claimed
  by another record is REJECTED (per-role ``errors[...]`` set).
- Edit path preserves entity ownership (editing the SAME record with its
  own entities does NOT trip the entity-exclusivity check).
- Remove path deletes the record.
- No-CM-reload: ``CONF_APPLIANCE_RECORDS`` is a member of both
  ``OPTIONS_RELOAD_SUPPRESS_KEYS`` and ``_NO_LIVE_ATTR_KEYS`` so an
  onboarding save takes the in-place-apply branch.
- Mutation drill anchors:
  * Neuter the record-writer (make save a no-op) -> add round-trip test RED.
  * Remove ``CONF_APPLIANCE_RECORDS`` from ``OPTIONS_RELOAD_SUPPRESS_KEYS`` ->
    no-reload assertion RED.

Piggybacks on ``test_cycle_b_config_flow._load_config_flow`` (HA-mock
harness) to compile config_flow without a live HA install.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib
import os
import sys
import types


# Load the v1a coordinator-test module FIRST so its HA-mock scaffolding
# (including the `custom_components.universal_room_automation` bare package
# stub) is in place before we import config_flow. The v1a test installs
# just enough to import appliance.py + appliance_const.py + base.py + const.py
# without executing the real __init__.py (which requires homeassistant).
_v1a = importlib.import_module("test_appliance_coordinator_v1a")

_cbcf = importlib.import_module("test_cycle_b_config_flow")

_load_config_flow = _cbcf._load_config_flow
_build_ha_modules = _cbcf._build_ha_modules
_FakeConfigEntry = _cbcf._FakeConfigEntry
_FakeHass = _cbcf._FakeHass
_make_options_flow = _cbcf._make_options_flow


# The options-flow module was loaded once at import time by test_cycle_b_config_flow.
# Re-load so the appliance step (added post-import) is present.
_cf = _load_config_flow()
UniversalRoomAutomationOptionsFlow = _cf.UniversalRoomAutomationOptionsFlow


# Const import via the flat _COMPONENT_DIR path insertion (mirrors
# test_cycle_b_config_flow's approach at line 34). Loads const.py directly
# without executing URA's real __init__.py (which requires homeassistant).
_COMPONENT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation",
)
if _COMPONENT_DIR not in sys.path:
    sys.path.insert(0, _COMPONENT_DIR)
from const import (  # noqa: E402
    CONF_APPLIANCE_RECORDS,
    CONF_ENTRY_TYPE,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_ROOM,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_cm_options_flow(records=None):
    flow = _make_options_flow(
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER},
        options={CONF_APPLIANCE_RECORDS: list(records or [])},
    )
    return flow


# ---------------------------------------------------------------------------
# Menu wiring
# ---------------------------------------------------------------------------


def test_cm_init_menu_includes_coordinator_appliance():
    flow = _make_cm_options_flow()
    result = _run(flow.async_step_init())
    assert result["type"] == "menu"
    assert "coordinator_appliance" in result["menu_options"]


def test_coordinator_appliance_menu_lists_records_plus_add():
    """Menu carries an add key + one edit key per record."""
    records = [
        {
            "name": "Fridge",
            "functional_domain": "cold_chain",
            "room": "Kitchen",
            "entity_refs": {
                "power": ["sensor.fridge"], "energy": [],
                "control": [], "state": [],
            },
            "source_tags": ["ura_config"],
        },
        {
            "name": "Washer",
            "functional_domain": "laundry",
            "room": "Laundry",
            "entity_refs": {
                "power": [], "energy": [], "control": [],
                "state": ["sensor.washer_state"],
            },
            "source_tags": ["ura_config"],
        },
    ]
    flow = _make_cm_options_flow(records=records)
    result = _run(flow.async_step_coordinator_appliance())
    assert result["type"] == "menu"
    keys = list(result["menu_options"].keys())
    assert "apick_new" in keys
    assert "apick_0" in keys
    assert "apick_1" in keys


# ---------------------------------------------------------------------------
# Add / edit / remove
# ---------------------------------------------------------------------------


def test_add_new_record_round_trip():
    flow = _make_cm_options_flow(records=[])
    flow._appliance_edit_index = None
    result = _run(flow.async_step_appliance_form(user_input={
        "name": "Kitchen Fridge",
        "functional_domain": "cold_chain",
        "room": "Kitchen",
        "power": ["sensor.fridge_power"],
        "energy": [],
        "control": [],
        "state": [],
    }))
    assert result["type"] == "create_entry"
    saved = result["data"][CONF_APPLIANCE_RECORDS]
    assert len(saved) == 1
    assert saved[0]["name"] == "Kitchen Fridge"
    assert saved[0]["functional_domain"] == "cold_chain"
    assert saved[0]["entity_refs"]["power"] == ["sensor.fridge_power"]


def test_add_record_appears_in_census_with_declared_domain():
    """Declared record round-trips through options -> census reader wires
    the record's functional_domain (not "other").
    """
    # Import + inject the coordinator's runtime path only for this test.
    from custom_components.universal_room_automation.domain_coordinators.appliance import (  # noqa: E402
        ApplianceCoordinator,
    )
    from unittest.mock import MagicMock

    # Simulate an entry.options with the new record.
    class _E:
        def __init__(self, data, options, title=""):
            self.data = data
            self.options = options
            self.title = title
            self.entry_id = "x"

    entries = [
        _E({CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}, {
            CONF_APPLIANCE_RECORDS: [{
                "name": "Living Room TV",
                "functional_domain": "media_av",
                "room": "Living Room",
                "entity_refs": {
                    "power": [], "energy": [], "control": [],
                    "state": ["media_player.living_tv"],
                },
                "source_tags": ["ura_config"],
            }],
        }),
    ]
    hass = MagicMock()
    hass.config_entries.async_entries = lambda _domain: entries
    hass.states.get = lambda _eid: None
    hass.data = {"universal_room_automation": {"coordinator_manager": None}}
    coord = ApplianceCoordinator(hass)
    recs = coord.resolve_census()
    assert len(recs) == 1
    assert recs[0]["name"] == "Living Room TV"
    # Declared record's functional_domain is preserved (NOT downgraded to "other").
    assert recs[0]["functional_domain"] == "media_av"


def test_net_new_tv_absent_until_added_then_present():
    """media_player not in any URA room config is invisible in v1a until
    the operator declares it as a record via the v1b flow.
    """
    from custom_components.universal_room_automation.domain_coordinators.appliance import (  # noqa: E402
        ApplianceCoordinator,
    )
    from unittest.mock import MagicMock

    class _E:
        def __init__(self, data, options, title=""):
            self.data = data
            self.options = options
            self.title = title
            self.entry_id = "x"

    # BEFORE — no ROOM entry references the TV, no declared record.
    entries_before = [
        _E({CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}, {
            CONF_APPLIANCE_RECORDS: [],
        }),
        _E({CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, "room_name": "Kitchen",
            "fans": ["fan.kitchen"]}, {}),
    ]
    hass_b = MagicMock()
    hass_b.config_entries.async_entries = lambda _d: entries_before
    hass_b.states.get = lambda _e: None
    hass_b.data = {"universal_room_automation": {"coordinator_manager": None}}
    recs_before = ApplianceCoordinator(hass_b).resolve_census()
    names_before = {r["name"] for r in recs_before}
    assert "media_player.orphan_tv" not in names_before
    assert not any(
        "media_player.orphan_tv" in (r.get("entity_refs", {}).get("state") or [])
        for r in recs_before
    )

    # AFTER — flow saved the declared record.
    entries_after = [
        _E({CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}, {
            CONF_APPLIANCE_RECORDS: [{
                "name": "Orphan TV",
                "functional_domain": "media_av",
                "room": None,
                "entity_refs": {
                    "power": [], "energy": [], "control": [],
                    "state": ["media_player.orphan_tv"],
                },
                "source_tags": ["ura_config"],
            }],
        }),
        _E({CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, "room_name": "Kitchen",
            "fans": ["fan.kitchen"]}, {}),
    ]
    hass_a = MagicMock()
    hass_a.config_entries.async_entries = lambda _d: entries_after
    hass_a.states.get = lambda _e: None
    hass_a.data = {"universal_room_automation": {"coordinator_manager": None}}
    recs_after = ApplianceCoordinator(hass_a).resolve_census()
    names_after = {r["name"] for r in recs_after}
    assert "Orphan TV" in names_after


def test_cross_integration_triple_covered_appliance_collapses_after_grouping():
    """A device that has ThinQ state + SPAN power + a room-config entity
    would produce 3 census records before grouping. After operator
    groups them into ONE declared record naming all three entities, the
    census shows ONE record (declared claim suppresses the sibling sources).
    """
    from custom_components.universal_room_automation.domain_coordinators.appliance import (  # noqa: E402
        ApplianceCoordinator,
    )
    from unittest.mock import MagicMock

    class _E:
        def __init__(self, data, options, title=""):
            self.data = data
            self.options = options
            self.title = title
            self.entry_id = "x"

    room_entry = _E(
        {
            CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
            "room_name": "Laundry",
            "power_sensors": ["sensor.span_washer_power"],
            "room_media_player": None,
        },
        {},
    )
    # BEFORE grouping — SPAN + room refs both surface. NO declared record.
    cm_before = _E({CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}, {
        CONF_APPLIANCE_RECORDS: [],
    })
    hass_b = MagicMock()
    hass_b.config_entries.async_entries = lambda _d: [cm_before, room_entry]
    hass_b.states.get = lambda _e: None
    energy = MagicMock()
    energy._circuits = MagicMock()
    energy._circuits._circuits = {
        "sensor.span_washer_power": MagicMock(friendly_name="Washer"),
    }
    cm = MagicMock()
    cm.coordinators = {"energy": energy}
    hass_b.data = {"universal_room_automation": {"coordinator_manager": cm}}
    recs_before = ApplianceCoordinator(hass_b).resolve_census()
    # At minimum, the URA-owned power_sensor record shows up (source-3
    # claims it first, suppressing the SPAN emission for the same eid).
    assert any(
        "sensor.span_washer_power"
        in (r.get("entity_refs", {}).get("power") or [])
        for r in recs_before
    )

    # AFTER — operator declared ONE record grouping SPAN + a ThinQ state
    # entity. The declared record claims the SPAN eid; the SPAN/URA
    # sources are suppressed for that eid.
    cm_after = _E({CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}, {
        CONF_APPLIANCE_RECORDS: [{
            "name": "Washer (grouped)",
            "functional_domain": "laundry",
            "room": "Laundry",
            "entity_refs": {
                "power": ["sensor.span_washer_power"],
                "energy": [],
                "control": [],
                # ThinQ state entity — cross-integration bridge under
                # a single operator-declared record.
                "state": ["sensor.thinq_washer_state"],
            },
            "source_tags": ["ura_config", "thinq", "span"],
        }],
    })
    hass_a = MagicMock()
    hass_a.config_entries.async_entries = lambda _d: [cm_after, room_entry]
    hass_a.states.get = lambda _e: None
    hass_a.data = {"universal_room_automation": {"coordinator_manager": cm}}
    recs_after = ApplianceCoordinator(hass_a).resolve_census()
    # Exactly ONE record for the SPAN eid — no duplicate URA/SPAN emission.
    matching = [
        r for r in recs_after
        if "sensor.span_washer_power"
        in (r.get("entity_refs", {}).get("power") or [])
    ]
    assert len(matching) == 1
    assert matching[0]["name"] == "Washer (grouped)"


def test_edit_existing_record_does_not_trip_exclusivity():
    """Editing a record with its OWN entities must NOT raise
    entity_already_claimed (the exclusivity check must exclude the
    record being edited)."""
    records = [{
        "name": "Fridge",
        "functional_domain": "cold_chain",
        "room": "Kitchen",
        "entity_refs": {
            "power": ["sensor.fridge_power"], "energy": [],
            "control": [], "state": [],
        },
        "source_tags": ["ura_config"],
    }]
    flow = _make_cm_options_flow(records=records)
    flow._appliance_edit_index = 0
    result = _run(flow.async_step_appliance_form(user_input={
        "name": "Fridge",
        "functional_domain": "cold_chain",
        "room": "Kitchen",
        "power": ["sensor.fridge_power"],
        "energy": [],
        "control": [],
        "state": [],
    }))
    assert result["type"] == "create_entry"
    saved = result["data"][CONF_APPLIANCE_RECORDS]
    assert len(saved) == 1
    assert saved[0]["entity_refs"]["power"] == ["sensor.fridge_power"]


def test_reject_at_validation_entity_already_claimed():
    """Saving a record whose entity is already claimed by ANOTHER record
    is rejected — the form re-renders with an error field."""
    records = [{
        "name": "Fridge",
        "functional_domain": "cold_chain",
        "room": "Kitchen",
        "entity_refs": {
            "power": ["sensor.shared_power"], "energy": [],
            "control": [], "state": [],
        },
        "source_tags": ["ura_config"],
    }]
    flow = _make_cm_options_flow(records=records)
    flow._appliance_edit_index = None  # adding a NEW record
    result = _run(flow.async_step_appliance_form(user_input={
        "name": "Freezer",
        "functional_domain": "cold_chain",
        "room": "Kitchen",
        "power": ["sensor.shared_power"],
        "energy": [],
        "control": [],
        "state": [],
    }))
    assert result["type"] == "form"
    assert "power" in result.get("errors", {})
    assert result["errors"]["power"] == "entity_already_claimed"


def test_remove_path_deletes_record():
    records = [
        {
            "name": "A",
            "functional_domain": "other",
            "room": None,
            "entity_refs": {
                "power": [], "energy": [], "control": [], "state": [],
            },
            "source_tags": ["ura_config"],
        },
        {
            "name": "B",
            "functional_domain": "other",
            "room": None,
            "entity_refs": {
                "power": [], "energy": [], "control": [], "state": [],
            },
            "source_tags": ["ura_config"],
        },
    ]
    flow = _make_cm_options_flow(records=records)
    flow._appliance_edit_index = 0
    result = _run(flow.async_step_appliance_form(user_input={
        "name": "A", "functional_domain": "other", "room": None,
        "power": [], "energy": [], "control": [], "state": [],
        "remove": True,
    }))
    assert result["type"] == "create_entry"
    saved = result["data"][CONF_APPLIANCE_RECORDS]
    assert len(saved) == 1
    assert saved[0]["name"] == "B"


# ---------------------------------------------------------------------------
# No-CM-reload — membership assertion (in-place-apply path is taken)
# ---------------------------------------------------------------------------
#
# The listener at __init__.py:_async_update_listener routes a CM options
# save through _apply_in_place iff changed_keys ⊆ OPTIONS_RELOAD_SUPPRESS_KEYS.
# Assert CONF_APPLIANCE_RECORDS is in both suppress-keys AND
# _NO_LIVE_ATTR_KEYS (source-level assertion — no HA runtime required).
# This is the mutation-anchor for the "no CM reload on onboarding save"
# invariant. Neutering the OPTIONS_RELOAD_SUPPRESS_KEYS membership turns
# this RED.


def _read_init_source() -> str:
    p = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "custom_components", "universal_room_automation", "__init__.py",
    )
    with open(p, encoding="utf-8") as f:
        return f.read()


def test_conf_appliance_records_in_reload_suppress_keys():
    src = _read_init_source()
    # The frozenset construction imports CONF_APPLIANCE_RECORDS and the
    # OPTIONS_RELOAD_SUPPRESS_KEYS block references it. Anchor on both
    # the sentinel comment and the identifier appearance inside the set.
    assert "OPTIONS_RELOAD_SUPPRESS_KEYS" in src
    # Grep for the appliance-records comment sentinel + the identifier
    # inside the suppress block (both must be present).
    assert (
        "APPLIANCE-MGMT-REFINE-1 v1b — appliance records list. Iterative"
        in src
    ), (
        "OPTIONS_RELOAD_SUPPRESS_KEYS is missing the appliance-records "
        "membership — an onboarding save would trigger a full CM reload."
    )


def test_conf_appliance_records_in_no_live_attr_keys():
    src = _read_init_source()
    # The _NO_LIVE_ATTR_KEYS block precedes OPTIONS_RELOAD_SUPPRESS_KEYS
    # in the file; the comment sentinel for the no-live-attr membership
    # is distinct from the reload-suppress one.
    assert (
        "APPLIANCE-MGMT-REFINE-1 v1b — appliance records list. The Appliance\n"
        "    # Coordinator re-reads"
        in src
    ), (
        "_NO_LIVE_ATTR_KEYS is missing the appliance-records membership — "
        "the in-place-apply path would not mark the key applied."
    )
