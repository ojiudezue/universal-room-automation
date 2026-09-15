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
- Stable record identity: records are keyed by uuid ``id``, not list
  index. A stale menu-key from a concurrent flow session cannot
  edit/delete the wrong record (A-HIGH-1/2 + B-LOW-1/2).
- No-CM-reload: LISTENER BEHAVIORAL test (not comment grep) — a
  records-only save on the real ``_async_update_listener`` produces
  zero ``async_create_task`` calls; a mixed change does reload.
- Mutation drill anchors:
  * Neuter the record-writer (save CONF_APPLIANCE_RECORDS -> some
    other key) -> census-linkage test RED.
  * Remove ``CONF_APPLIANCE_RECORDS`` from ``OPTIONS_RELOAD_SUPPRESS_KEYS`` ->
    the records-only reload-suppress test goes RED.

Piggybacks on ``test_cycle_b_config_flow._load_config_flow`` (HA-mock
harness) to compile config_flow without a live HA install.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys


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


class _CensusEntry:
    """Fake ConfigEntry mirroring the shape ApplianceCoordinator reads."""

    def __init__(self, data, options, title=""):
        self.data = data
        self.options = options
        self.title = title
        self.entry_id = "cm-test"


def _build_census_hass(cm_options: dict, extra_entries=None, span=None):
    """Build a MagicMock hass with a CM entry carrying ``cm_options`` +
    any additional URA config entries (e.g. ROOM entries)."""
    from unittest.mock import MagicMock

    cm = _CensusEntry({CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}, cm_options)
    entries = [cm] + list(extra_entries or [])
    hass = MagicMock()
    hass.config_entries.async_entries = lambda _d: entries
    hass.states.get = lambda _e: None
    coordinator_manager = None
    if span is not None:
        energy = MagicMock()
        energy._circuits = MagicMock()
        energy._circuits._circuits = span
        coordinator_manager = MagicMock()
        coordinator_manager.coordinators = {"energy": energy}
    hass.data = {"universal_room_automation": {
        "coordinator_manager": coordinator_manager,
    }}
    return hass


# ---------------------------------------------------------------------------
# Menu wiring
# ---------------------------------------------------------------------------


def test_cm_init_menu_includes_coordinator_appliance():
    flow = _make_cm_options_flow()
    result = _run(flow.async_step_init())
    assert result["type"] == "menu"
    assert "coordinator_appliance" in result["menu_options"]


def test_coordinator_appliance_menu_lists_records_plus_add():
    """Menu carries an add key + one edit key per record, keyed by
    stable record id (uuid), not list index."""
    records = [
        {
            "id": "aaaaaaaa",
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
            "id": "bbbbbbbb",
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
    assert "apick_aaaaaaaa" in keys
    assert "apick_bbbbbbbb" in keys
    # Map exposes menu-key -> record `id`, not list index.
    assert flow._appliance_menu_map["apick_aaaaaaaa"] == "aaaaaaaa"
    assert flow._appliance_menu_map["apick_bbbbbbbb"] == "bbbbbbbb"


# ---------------------------------------------------------------------------
# Add / edit / remove
# ---------------------------------------------------------------------------


def test_add_new_record_round_trip():
    flow = _make_cm_options_flow(records=[])
    flow._appliance_edit_id = None
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
    # Stable identity: create mints a non-empty uuid `id` string.
    assert isinstance(saved[0].get("id"), str) and saved[0]["id"]


# ---------------------------------------------------------------------------
# Flow -> census linkage (A-HIGH-3 fix-up — chain the REAL writer through
# to ApplianceCoordinator.resolve_census, not a hand-forged record dict).
# ---------------------------------------------------------------------------


def _run_flow_and_get_saved(records_before, user_input, edit_id=None):
    flow = _make_cm_options_flow(records=records_before)
    flow._appliance_edit_id = edit_id
    result = _run(flow.async_step_appliance_form(user_input=user_input))
    assert result["type"] == "create_entry", result
    return result["data"][CONF_APPLIANCE_RECORDS]


def test_add_record_appears_in_census_with_declared_domain():
    """Flow -> census linkage: run the REAL writer, feed its saved list
    into the CM entry.options, and assert resolve_census() surfaces the
    record with its declared functional_domain.
    """
    from custom_components.universal_room_automation.domain_coordinators.appliance import (  # noqa: E402
        ApplianceCoordinator,
    )

    saved = _run_flow_and_get_saved(
        records_before=[],
        user_input={
            "name": "Living Room TV",
            "functional_domain": "media_av",
            "room": "Living Room",
            "power": [],
            "energy": [],
            "control": [],
            "state": ["media_player.living_tv"],
        },
    )
    hass = _build_census_hass({CONF_APPLIANCE_RECORDS: saved})
    recs = ApplianceCoordinator(hass).resolve_census()
    assert any(
        r["name"] == "Living Room TV" and r["functional_domain"] == "media_av"
        for r in recs
    )


def test_net_new_tv_absent_until_added_then_present():
    """A media_player not referenced by any URA room config is invisible
    until the operator declares it via the flow. Drive the REAL flow to
    add it, then chain through resolve_census().
    """
    from custom_components.universal_room_automation.domain_coordinators.appliance import (  # noqa: E402
        ApplianceCoordinator,
    )

    room_entry = _CensusEntry(
        {CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, "room_name": "Kitchen",
         "fans": ["fan.kitchen"]}, {},
    )

    # BEFORE — no declared record.
    hass_b = _build_census_hass(
        {CONF_APPLIANCE_RECORDS: []}, extra_entries=[room_entry],
    )
    recs_before = ApplianceCoordinator(hass_b).resolve_census()
    assert not any(
        "media_player.orphan_tv" in (r.get("entity_refs", {}).get("state") or [])
        for r in recs_before
    )

    # Drive the flow to add the TV.
    saved = _run_flow_and_get_saved(
        records_before=[],
        user_input={
            "name": "Orphan TV",
            "functional_domain": "media_av",
            "room": "",
            "power": [],
            "energy": [],
            "control": [],
            "state": ["media_player.orphan_tv"],
        },
    )
    hass_a = _build_census_hass(
        {CONF_APPLIANCE_RECORDS: saved}, extra_entries=[room_entry],
    )
    recs_after = ApplianceCoordinator(hass_a).resolve_census()
    assert any(r["name"] == "Orphan TV" for r in recs_after)


def test_cross_integration_triple_covered_appliance_collapses_after_grouping():
    """Operator groups a SPAN power sensor + a ThinQ state entity under
    ONE declared record. After the flow saves, the census yields ONE
    record for the SPAN eid (the declared claim suppresses the SPAN
    source emission).

    NOTE (A-HIGH-3 fix-up): the previous version of this test asserted
    ``source_tags == ["ura_config","thinq","span"]`` — an impossible
    outcome because the flow hard-writes ``source_tags=["ura_config"]``
    and offers no source-tag field. Rewritten to assert what the flow
    ACTUALLY yields: ONE census record naming both entities after
    grouping.
    """
    from custom_components.universal_room_automation.domain_coordinators.appliance import (  # noqa: E402
        ApplianceCoordinator,
    )
    from unittest.mock import MagicMock

    room_entry = _CensusEntry(
        {
            CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
            "room_name": "Laundry",
            "power_sensors": ["sensor.span_washer_power"],
            "room_media_player": None,
        },
        {},
    )
    span_circuits = {
        "sensor.span_washer_power": MagicMock(friendly_name="Washer"),
    }

    # BEFORE grouping — no declared record; SPAN/URA sources compete.
    hass_b = _build_census_hass(
        {CONF_APPLIANCE_RECORDS: []},
        extra_entries=[room_entry],
        span=span_circuits,
    )
    recs_before = ApplianceCoordinator(hass_b).resolve_census()
    assert any(
        "sensor.span_washer_power"
        in (r.get("entity_refs", {}).get("power") or [])
        for r in recs_before
    )

    # Drive the flow to group SPAN + ThinQ under ONE declared record.
    saved = _run_flow_and_get_saved(
        records_before=[],
        user_input={
            "name": "Washer (grouped)",
            "functional_domain": "laundry",
            "room": "Laundry",
            "power": ["sensor.span_washer_power"],
            "energy": [],
            "control": [],
            "state": ["sensor.thinq_washer_state"],
        },
    )
    hass_a = _build_census_hass(
        {CONF_APPLIANCE_RECORDS: saved},
        extra_entries=[room_entry],
        span=span_circuits,
    )
    recs_after = ApplianceCoordinator(hass_a).resolve_census()
    matching = [
        r for r in recs_after
        if "sensor.span_washer_power"
        in (r.get("entity_refs", {}).get("power") or [])
    ]
    assert len(matching) == 1
    assert matching[0]["name"] == "Washer (grouped)"
    # source_tags is what the FLOW yields, not what the operator claimed.
    assert matching[0]["source_tags"] == ["ura_config"]


def test_edit_existing_record_does_not_trip_exclusivity():
    """Editing a record with its OWN entities must NOT raise
    entity_already_claimed (the exclusivity check must exclude the
    record being edited).
    """
    records = [{
        "id": "recA",
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
    flow._appliance_edit_id = "recA"
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
    # Edit preserves the stable id.
    assert saved[0]["id"] == "recA"


def test_reject_at_validation_entity_already_claimed():
    """Saving a record whose entity is already claimed by ANOTHER record
    is rejected — the form re-renders with an error field."""
    records = [{
        "id": "recA",
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
    flow._appliance_edit_id = None  # adding a NEW record
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
            "id": "recA",
            "name": "A",
            "functional_domain": "other",
            "room": None,
            "entity_refs": {
                "power": ["sensor.a"], "energy": [], "control": [], "state": [],
            },
            "source_tags": ["ura_config"],
        },
        {
            "id": "recB",
            "name": "B",
            "functional_domain": "other",
            "room": None,
            "entity_refs": {
                "power": ["sensor.b"], "energy": [], "control": [], "state": [],
            },
            "source_tags": ["ura_config"],
        },
    ]
    flow = _make_cm_options_flow(records=records)
    flow._appliance_edit_id = "recA"
    result = _run(flow.async_step_appliance_form(user_input={
        "name": "A", "functional_domain": "other", "room": None,
        "power": ["sensor.a"], "energy": [], "control": [], "state": [],
        "remove": True,
    }))
    assert result["type"] == "create_entry"
    saved = result["data"][CONF_APPLIANCE_RECORDS]
    assert len(saved) == 1
    assert saved[0]["name"] == "B"


# ---------------------------------------------------------------------------
# Stable identity — stale-menu wrong-record vector (A-HIGH-1/2 + B-LOW-1/2)
# ---------------------------------------------------------------------------


def test_stale_menu_from_removed_middle_record_does_not_edit_wrong_record():
    """Two tabs open. Tab-1 renders picker for [A,B,C]; Tab-2 removes B.
    Tab-1's still-visible menu-key for C (previously index=2, now
    logically shifted) must NOT resolve to whatever new record sits at
    index=2 — it must resolve BY ID to C (or, if C is gone too,
    re-render the picker).
    """
    records = [
        {"id": "A", "name": "A", "functional_domain": "other", "room": None,
         "entity_refs": {"power": ["sensor.a"], "energy": [], "control": [], "state": []},
         "source_tags": ["ura_config"]},
        {"id": "B", "name": "B", "functional_domain": "other", "room": None,
         "entity_refs": {"power": ["sensor.b"], "energy": [], "control": [], "state": []},
         "source_tags": ["ura_config"]},
        {"id": "C", "name": "C", "functional_domain": "other", "room": None,
         "entity_refs": {"power": ["sensor.c"], "energy": [], "control": [], "state": []},
         "source_tags": ["ura_config"]},
    ]
    flow = _make_cm_options_flow(records=records)
    # Render the picker — this seeds `_appliance_menu_map`.
    _run(flow.async_step_coordinator_appliance())
    stale_menu = dict(flow._appliance_menu_map)
    assert "apick_C" in stale_menu

    # Tab-2 removes B; the entry.options list mutates behind Tab-1's back.
    flow._config_entry.options = {
        CONF_APPLIANCE_RECORDS: [r for r in records if r["id"] != "B"],
    }

    # Tab-1 now uses its cached menu-key for C. The pick handler looks
    # up the id from the (still-valid) menu map — for C it resolves to
    # id="C", which IS still present after B's removal, so we edit C
    # (its own entities) — no wrong-record mutation.
    picker = flow.__getattr__(f"async_step_apick_C")
    _run(picker())
    assert flow._appliance_edit_id == "C"
    result = _run(flow.async_step_appliance_form(user_input={
        "name": "C-renamed",
        "functional_domain": "other",
        "room": None,
        "power": ["sensor.c"], "energy": [], "control": [], "state": [],
    }))
    assert result["type"] == "create_entry"
    saved = result["data"][CONF_APPLIANCE_RECORDS]
    names = [r["name"] for r in saved]
    assert names == ["A", "C-renamed"], names
    # And critically: A was NOT mutated (would happen under index-keying
    # if Tab-1's cached key had shifted).
    a_row = next(r for r in saved if r["id"] == "A")
    assert a_row["name"] == "A"
    assert a_row["entity_refs"]["power"] == ["sensor.a"]


def test_stale_menu_id_gone_rerenders_picker_not_wrong_record():
    """Tab-1 renders picker for [A,B,C]; Tab-2 removes C entirely.
    Tab-1's cached menu-key for C must NOT delete/edit A or B — the
    by-id lookup misses, and the form re-renders the picker.
    """
    records = [
        {"id": "A", "name": "A", "functional_domain": "other", "room": None,
         "entity_refs": {"power": ["sensor.a"], "energy": [], "control": [], "state": []},
         "source_tags": ["ura_config"]},
        {"id": "B", "name": "B", "functional_domain": "other", "room": None,
         "entity_refs": {"power": ["sensor.b"], "energy": [], "control": [], "state": []},
         "source_tags": ["ura_config"]},
        {"id": "C", "name": "C", "functional_domain": "other", "room": None,
         "entity_refs": {"power": ["sensor.c"], "energy": [], "control": [], "state": []},
         "source_tags": ["ura_config"]},
    ]
    flow = _make_cm_options_flow(records=records)
    _run(flow.async_step_coordinator_appliance())
    # Tab-2 removes C entirely.
    flow._config_entry.options = {
        CONF_APPLIANCE_RECORDS: [r for r in records if r["id"] != "C"],
    }
    # Simulate Tab-1 arriving at appliance_form with edit_id=C AND a
    # remove submission — the form must NOT delete A or B.
    flow._appliance_edit_id = "C"
    result = _run(flow.async_step_appliance_form(user_input={
        "remove": True,
        "name": "irrelevant",
        "functional_domain": "other", "room": None,
        "power": [], "energy": [], "control": [], "state": [],
    }))
    # By-id miss re-renders the picker instead of firing the delete.
    assert result["type"] == "menu"
    # The stored list is unchanged.
    assert [r["id"] for r in flow._config_entry.options[CONF_APPLIANCE_RECORDS]] == ["A", "B"]


# ---------------------------------------------------------------------------
# A-LOW-1: reject a record with a name but ZERO entities.
# ---------------------------------------------------------------------------


def test_reject_record_with_no_entities():
    flow = _make_cm_options_flow(records=[])
    flow._appliance_edit_id = None
    result = _run(flow.async_step_appliance_form(user_input={
        "name": "Empty",
        "functional_domain": "other",
        "room": None,
        "power": [], "energy": [], "control": [], "state": [],
    }))
    assert result["type"] == "form"
    assert result["errors"].get("base") == "no_entities"


# ---------------------------------------------------------------------------
# Reload-suppress — BEHAVIORAL against the real listener (A-HIGH-4 / B-HIGH-1)
# ---------------------------------------------------------------------------
#
# Re-uses the ``listener_ns`` + ``_FakeHass`` + ``_FakeEntry`` harness
# in test_cm_reload_suppression.py so this test drives the SAME code
# path as the D3 listener suite. The mutation drill — delete
# CONF_APPLIANCE_RECORDS from OPTIONS_RELOAD_SUPPRESS_KEYS — makes the
# records-only assertion RED.


_reload_suite = importlib.import_module("test_cm_reload_suppression")


def test_records_only_save_does_not_reload_cm():
    ns = _reload_suite._load_init_listener_helpers()
    hass = _reload_suite._FakeHass(hvac=_reload_suite._FakeHvac())
    entry = _reload_suite._FakeEntry(
        "cm1", {CONF_APPLIANCE_RECORDS: []},
    )
    ns["_seed_cm_last_applied_options"](hass, entry)
    # Iterative onboarding save — records list grows by one.
    entry.options = {CONF_APPLIANCE_RECORDS: [
        {"id": "x", "name": "Fridge", "functional_domain": "cold_chain",
         "room": None,
         "entity_refs": {"power": ["sensor.f"], "energy": [], "control": [], "state": []},
         "source_tags": ["ura_config"]},
    ]}
    asyncio.new_event_loop().run_until_complete(
        ns["_async_update_listener"](hass, entry)
    )
    # allowlisted-only change: NO reload.
    assert hass.async_create_task.call_count == 0


def test_records_plus_non_allowlisted_key_does_reload_cm():
    ns = _reload_suite._load_init_listener_helpers()
    hass = _reload_suite._FakeHass(hvac=_reload_suite._FakeHvac())
    entry = _reload_suite._FakeEntry(
        "cm1", {CONF_APPLIANCE_RECORDS: [], "presence_enabled": True},
    )
    ns["_seed_cm_last_applied_options"](hass, entry)
    # Mixed change: one allowlisted + one non-allowlisted.
    entry.options = {
        CONF_APPLIANCE_RECORDS: [
            {"id": "x", "name": "Fridge", "functional_domain": "cold_chain",
             "room": None,
             "entity_refs": {"power": ["sensor.f"], "energy": [], "control": [], "state": []},
             "source_tags": ["ura_config"]},
        ],
        "presence_enabled": False,
    }
    asyncio.new_event_loop().run_until_complete(
        ns["_async_update_listener"](hass, entry)
    )
    # Non-allowlisted change dominates: exactly one reload dispatched.
    assert hass.async_create_task.call_count == 1
