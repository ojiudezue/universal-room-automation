"""ROOM-NAME-DESYNC-1 — D1 write-through + D2 boot migration + D3 invariant tests.

Planning doc: docs/planning/PLANNING_room_rename_writethrough.md

Drives the REAL options-flow save methods (not a monkeypatched shortcut)
against a fake ConfigEntry whose `async_update_entry` mutates the entry
in place, so we can assert `entry.data`, `entry.options`, and
`entry.title` all agree after a rename.

Named per §D1 acceptance criteria:
  - test_room_rename_updates_data_options_and_title
  - test_room_zone_reassign_updates_data_and_options
  - test_zone_rename_update_branch_updates_data
  - test_zone_rename_create_branch_updates_data
  - test_room_rename_single_listener_invocation
  - test_room_rename_uses_async_abort_not_create_entry

§D2:
  - test_migration_syncs_desynced_room_name
  - test_migration_syncs_desynced_zone_assignment
  - test_migration_syncs_legacy_zone_entry_name
  - test_migration_noop_when_in_sync
  - test_migration_idempotent_second_run

§D3 falsifier drill (documented mutation reviewer C re-runs):
  - test_falsifier_drill_reverting_writethrough_reddens_this_test
    (a targeted assert that neutering the write-through in a mocked
    handler reddens the D1 test path).
"""

from __future__ import annotations

import os
import sys
import pytest
from unittest.mock import MagicMock, AsyncMock

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_COMPONENT_DIR = os.path.join(_REPO_ROOT, "custom_components", "universal_room_automation")

# Reuse the isolated config_flow loader from the cycle-b test infra so we
# don't re-implement the HA mock tree here (institutional context: this
# is the established pattern for direct config_flow unit tests).
sys.path.insert(0, os.path.dirname(__file__))
from test_cycle_b_config_flow import (  # noqa: E402
    _cf,
    _FakeConfigEntry,
    _FakeHass,
    _make_options_flow as _base_make_options_flow,
    CONF_ROOM_NAME,
    CONF_ENTRY_TYPE,
    ENTRY_TYPE_ROOM,
)


def _make_options_flow(*a, **kw):
    flow = _base_make_options_flow(*a, **kw)
    _attach_flow_stubs(flow)
    return flow

# Const values we need beyond what test_cycle_b re-exports.
sys.path.insert(0, _COMPONENT_DIR)
from const import (  # noqa: E402
    CONF_ZONE,
    CONF_ZONE_NAME,
    CONF_ZONE_DESCRIPTION,
    CONF_ZONE_ROOMS,
    CONF_ZONE_IS_OUTDOOR,
    ENTRY_TYPE_ZONE,
)

UniversalRoomAutomationOptionsFlow = _cf.UniversalRoomAutomationOptionsFlow


def _attach_flow_stubs(flow):
    """Attach `async_abort` + `async_show_form` on flow instances.

    The FakeOptionsFlow base in test_cycle_b_config_flow doesn't expose
    `async_abort` (it wasn't needed before the D1 write-through). Our
    D1 code path terminates via `async_abort` per the plan's C1 recipe,
    so we bolt the stub on the instance directly.
    """
    if not hasattr(flow, "async_abort"):
        flow.async_abort = lambda **kw: {"type": "abort", **kw}
    if not hasattr(flow, "async_show_form"):
        flow.async_show_form = lambda **kw: {"type": "form", **kw}


# The zone-rename branches import `homeassistant.helpers.device_registry`
# at call time. Other tests in the suite install partial `homeassistant`
# stubs in sys.modules and don't necessarily include device_registry,
# so we FORCE our shim into place at each test's setup rather than
# only-if-absent (would flake under test-order pollution — observed in
# the full-suite run before the fix).
import types as _types  # noqa: E402


def _ensure_device_registry_shim():
    if (
        "homeassistant.helpers.device_registry" in sys.modules
        and hasattr(
            sys.modules["homeassistant.helpers.device_registry"],
            "async_get",
        )
    ):
        return
    _ha_dr = _types.ModuleType("homeassistant.helpers.device_registry")

    def _fake_dr_async_get(hass):
        m = MagicMock()
        m.async_get_device = MagicMock(return_value=None)
        m.async_remove_device = MagicMock(return_value=None)
        return m

    _ha_dr.async_get = _fake_dr_async_get
    if "homeassistant" not in sys.modules:
        sys.modules["homeassistant"] = _types.ModuleType("homeassistant")
    if "homeassistant.helpers" not in sys.modules:
        sys.modules["homeassistant.helpers"] = _types.ModuleType(
            "homeassistant.helpers"
        )
    sys.modules["homeassistant.helpers"].device_registry = _ha_dr
    sys.modules["homeassistant.helpers.device_registry"] = _ha_dr


_ensure_device_registry_shim()


# ---------------------------------------------------------------------------
# Fixtures — a hass whose async_update_entry actually mutates the entry.
# ---------------------------------------------------------------------------


def _hass_with_mutating_update():
    """Return a _FakeHass wired so async_update_entry mutates entries in place.

    This is the crucial fidelity bit — HA's real
    `config_entries.async_update_entry(entry, data=..., options=...,
    title=...)` mutates the entry, so any test that asserts the entry
    reflects the new values must model that.
    """
    hass = _FakeHass()

    update_calls = []

    def _mutating_update(entry, data=None, options=None, title=None, **kw):
        update_calls.append({
            "entry_id": entry.entry_id,
            "data": None if data is None else dict(data),
            "options": None if options is None else dict(options),
            "title": title,
        })
        if data is not None:
            entry.data = dict(data)
        if options is not None:
            entry.options = dict(options)
        if title is not None:
            entry.title = title
        # Fire any registered update listeners exactly once per call
        # (mirrors HA's ConfigEntries.async_update_entry semantics — the
        # listener spy in TestD3ListenerSpy relies on this).
        for cb in getattr(entry, "_update_listeners", []):
            try:
                cb(hass, entry)
            except Exception:
                pass
        return True

    hass.config_entries.async_update_entry = MagicMock(side_effect=_mutating_update)
    hass.config_entries.async_get_entry = MagicMock(return_value=None)
    hass._update_calls = update_calls
    return hass


def _register_update_listener(entry, cb):
    """Attach a fake update-listener list to a _FakeConfigEntry.

    Mirrors `ConfigEntry.add_update_listener` — enough to drive the C1
    single-listener-invocation spy in TestD3ListenerSpy.
    """
    if not hasattr(entry, "_update_listeners"):
        entry._update_listeners = []
    entry._update_listeners.append(cb)


# ===========================================================================
# D1 site 1 — Room rename / zone reassign via async_step_basic_setup
# ===========================================================================


class TestD1RoomRenameWriteThrough:
    """§D1 site 1 — config_flow.py:9112-9128."""

    @pytest.mark.asyncio
    async def test_room_rename_updates_data_options_and_title(self):
        hass = _hass_with_mutating_update()
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "OldRoom"},
            options={CONF_ROOM_NAME: "OldRoom"},
            hass=hass,
        )
        result = await flow.async_step_basic_setup(
            user_input={CONF_ROOM_NAME: "NewRoom"}
        )

        assert flow._config_entry.data[CONF_ROOM_NAME] == "NewRoom"
        assert flow._config_entry.options[CONF_ROOM_NAME] == "NewRoom"
        assert flow._config_entry.title == "NewRoom"
        assert result.get("type") == "abort"
        # M1 invariant: title is present in the async_update_entry call.
        assert hass._update_calls, "async_update_entry not invoked"
        call = hass._update_calls[0]
        assert call["title"] == "NewRoom"
        assert call["data"][CONF_ROOM_NAME] == "NewRoom"
        assert call["options"][CONF_ROOM_NAME] == "NewRoom"

    @pytest.mark.asyncio
    async def test_room_zone_reassign_updates_data_and_options(self):
        hass = _hass_with_mutating_update()
        flow = _make_options_flow(
            data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_ROOM_NAME: "Room1",
                CONF_ZONE: "ZoneA",
            },
            options={CONF_ZONE: "ZoneA"},
            hass=hass,
        )
        await flow.async_step_basic_setup(
            user_input={CONF_ROOM_NAME: "Room1", CONF_ZONE: "ZoneB"}
        )
        # BOTH data and options agree on the new zone assignment — this
        # is the aggregation.py:502 data-first-fallback bug fix.
        assert flow._config_entry.data[CONF_ZONE] == "ZoneB"
        assert flow._config_entry.options[CONF_ZONE] == "ZoneB"

    @pytest.mark.asyncio
    async def test_room_rename_single_listener_invocation(self):
        """C1 invariant: SINGLE combined write, not two sequential writes."""
        hass = _hass_with_mutating_update()
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "OldRoom"},
            options={},
            hass=hass,
        )
        await flow.async_step_basic_setup(
            user_input={CONF_ROOM_NAME: "NewRoom"}
        )
        # Exactly one async_update_entry call per save (would-be double-
        # emit sentinel: async_create_entry on an OptionsFlow implicitly
        # issues a second write internally — we chose async_abort
        # instead).
        assert hass.config_entries.async_update_entry.call_count == 1

    @pytest.mark.asyncio
    async def test_room_rename_uses_async_abort_not_create_entry(self):
        hass = _hass_with_mutating_update()
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "OldRoom"},
            options={},
            hass=hass,
        )
        result = await flow.async_step_basic_setup(
            user_input={CONF_ROOM_NAME: "NewRoom"}
        )
        assert result.get("type") == "abort"
        assert result.get("reason") == "reconfigure_successful"


# ===========================================================================
# D1 sites 2 & 3 — Zone rename via async_step_zone_rooms
# ===========================================================================


class TestD1ZoneRenameWriteThrough:
    """§D1 sites 2 (7938 update-branch) & 3 (7943 create-branch)."""

    def _zone_flow(self, hass, selected_zone_entry_id, zone_entry):
        _ensure_device_registry_shim()
        flow = UniversalRoomAutomationOptionsFlow.__new__(
            UniversalRoomAutomationOptionsFlow
        )
        flow._config_entry = zone_entry
        flow._selected_zone_entry_id = selected_zone_entry_id
        flow._pending_delete_rule_id = None
        flow.hass = hass
        # Stub the ZM / zone-entry lookups: force the legacy-zone branch.
        flow._get_zm_zone_data = MagicMock(return_value=None)
        flow._get_zone_entry = MagicMock(return_value=zone_entry)
        # async_step_zone_config_menu (return value for the site-2 path).
        async def _menu():
            return {"type": "menu", "step_id": "zone_config_menu"}
        flow.async_step_zone_config_menu = _menu
        _attach_flow_stubs(flow)
        return flow

    @pytest.mark.asyncio
    async def test_zone_rename_update_branch_updates_data(self):
        hass = _hass_with_mutating_update()
        zone_entry = _FakeConfigEntry(
            data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE,
                CONF_ZONE_NAME: "OldZone",
            },
            options={CONF_ZONE_NAME: "OldZone"},
            entry_id="zone_entry_1",
        )
        flow = self._zone_flow(hass, "zone_entry_1", zone_entry)
        await flow.async_step_zone_rooms(
            user_input={
                CONF_ZONE_NAME: "NewZone",
                CONF_ZONE_DESCRIPTION: "",
                CONF_ZONE_ROOMS: [],
            }
        )
        assert zone_entry.data[CONF_ZONE_NAME] == "NewZone"
        assert zone_entry.options[CONF_ZONE_NAME] == "NewZone"
        assert zone_entry.title == "NewZone"

    @pytest.mark.asyncio
    async def test_zone_rename_create_branch_updates_data(self):
        """§D1 site 3 — else-branch fires when _selected_zone_entry_id is falsy."""
        hass = _hass_with_mutating_update()
        zone_entry = _FakeConfigEntry(
            data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE,
                CONF_ZONE_NAME: "OldZone",
            },
            options={CONF_ZONE_NAME: "OldZone"},
            entry_id="zone_entry_1",
        )
        # _selected_zone_entry_id = None + _get_zm_zone_data returns None
        # forces the site-3 else-branch.
        flow = self._zone_flow(hass, None, zone_entry)
        result = await flow.async_step_zone_rooms(
            user_input={
                CONF_ZONE_NAME: "NewZone",
                CONF_ZONE_DESCRIPTION: "",
                CONF_ZONE_ROOMS: [],
            }
        )
        assert zone_entry.data[CONF_ZONE_NAME] == "NewZone"
        assert zone_entry.options[CONF_ZONE_NAME] == "NewZone"
        assert zone_entry.title == "NewZone"
        assert result.get("type") == "abort"


# ===========================================================================
# D2 — Boot migration
# ===========================================================================


def _load_migration_helpers():
    """Import the D2/D3b helpers from __init__.py directly (bypasses HA)."""
    # The helpers are pure-python top-level functions that use
    # `hass.config_entries.async_update_entry` — safe to import via a
    # thin isolation wrapper. But __init__.py imports heavy HA modules.
    # For unit-testing D2 we replicate the helper inline against the
    # SAME contract; the D1 site-1 test already proves the write-through
    # semantics end-to-end.
    #
    # This mirrors the production helper at __init__.py:
    # `_migrate_room_zone_name_writethrough`.
    from const import (  # noqa: PLC0415
        CONF_ROOM_NAME as _CRN,
        CONF_ZONE_NAME as _CZN,
        CONF_ZONE as _CZ,
        CONF_ENTRY_TYPE as _CET,
        ENTRY_TYPE_ROOM as _ETR,
        ENTRY_TYPE_ZONE as _ETZ,
    )
    _KEYS = (_CRN, _CZN, _CZ)

    # Production helper source of truth — load it from __init__.py so
    # tests exercise the SAME function that runs at boot. We isolate via
    # a namespace exec (no HA imports side-effect the runtime).
    import importlib.util  # noqa: PLC0415
    init_path = os.path.join(_COMPONENT_DIR, "__init__.py")
    with open(init_path, "r") as fh:
        source = fh.read()
    # Extract just the helper we need. Simpler than mocking the whole
    # heavy init module (which pulls coordinator, database, etc.).
    start = source.index("def _migrate_room_zone_name_writethrough")
    end = source.index("\nasync def _check_and_notify_room_name_desync")
    helper_src = source[start:end]
    # Also need _ROOM_NAME_WRITETHROUGH_KEYS above it.
    keys_start = source.index("_ROOM_NAME_WRITETHROUGH_KEYS")
    keys_end = source.index("\n\n\ndef _migrate")
    keys_src = source[keys_start:keys_end]
    ns = {
        "_LOGGER": _LoggerNS(),
        "HomeAssistant": object,
        "ConfigEntry": object,
        "CONF_ROOM_NAME": _CRN,
        "CONF_ZONE_NAME": _CZN,
        "CONF_ZONE": _CZ,
        "CONF_ENTRY_TYPE": _CET,
        "ENTRY_TYPE_ROOM": _ETR,
        "ENTRY_TYPE_ZONE": _ETZ,
    }
    exec(keys_src, ns)  # noqa: S102
    exec(helper_src, ns)  # noqa: S102
    return ns["_migrate_room_zone_name_writethrough"]


class _LoggerNS:
    def info(self, *a, **kw):
        pass

    def debug(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def exception(self, *a, **kw):
        pass


class TestD2BootMigration:

    def test_migration_syncs_desynced_room_name(self):
        hass = _hass_with_mutating_update()
        entry = _FakeConfigEntry(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "OldRoom"},
            options={CONF_ROOM_NAME: "NewRoom"},
            entry_id="e1",
        )
        migrate = _load_migration_helpers()
        n = migrate(hass, entry)
        assert n == 1
        assert entry.data[CONF_ROOM_NAME] == "NewRoom"

    def test_migration_syncs_desynced_zone_assignment(self):
        hass = _hass_with_mutating_update()
        entry = _FakeConfigEntry(
            data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_ROOM_NAME: "Room1",
                CONF_ZONE: "ZoneA",
            },
            options={CONF_ZONE: "ZoneB"},
            entry_id="e1",
        )
        migrate = _load_migration_helpers()
        n = migrate(hass, entry)
        assert n == 1
        assert entry.data[CONF_ZONE] == "ZoneB"

    def test_migration_syncs_legacy_zone_entry_name(self):
        hass = _hass_with_mutating_update()
        entry = _FakeConfigEntry(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE, CONF_ZONE_NAME: "OldZone"},
            options={CONF_ZONE_NAME: "NewZone"},
            entry_id="z1",
        )
        migrate = _load_migration_helpers()
        n = migrate(hass, entry)
        assert n == 1
        assert entry.data[CONF_ZONE_NAME] == "NewZone"

    def test_migration_noop_when_in_sync(self):
        hass = _hass_with_mutating_update()
        entry = _FakeConfigEntry(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "Room"},
            options={CONF_ROOM_NAME: "Room"},
            entry_id="e1",
        )
        migrate = _load_migration_helpers()
        n = migrate(hass, entry)
        assert n == 0
        assert hass.config_entries.async_update_entry.call_count == 0

    def test_migration_idempotent_second_run(self):
        hass = _hass_with_mutating_update()
        entry = _FakeConfigEntry(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "OldRoom"},
            options={CONF_ROOM_NAME: "NewRoom"},
            entry_id="e1",
        )
        migrate = _load_migration_helpers()
        migrate(hass, entry)
        # Second run must be a full no-op.
        n = migrate(hass, entry)
        assert n == 0
        assert hass.config_entries.async_update_entry.call_count == 1

    def test_migration_skips_non_room_zone_entries(self):
        """CM / integration / ZM entries must be untouched."""
        hass = _hass_with_mutating_update()
        from const import ENTRY_TYPE_COORDINATOR_MANAGER  # noqa: PLC0415
        entry = _FakeConfigEntry(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER},
            options={CONF_ROOM_NAME: "sneaky"},
            entry_id="cm",
        )
        migrate = _load_migration_helpers()
        assert migrate(hass, entry) == 0
        assert hass.config_entries.async_update_entry.call_count == 0


# ===========================================================================
# D3 — Falsifier drill sentinels
# ===========================================================================


class TestD3FalsifierDrill:
    """Documented drills reviewer C re-runs to detect hollow anchors."""

    @pytest.mark.asyncio
    async def test_falsifier_drill_reverting_writethrough_reddens_this_test(self):
        """If a builder ever deletes the `data=merged_data` kwarg from the
        room-rename `async_update_entry` call, this test MUST turn red.

        We verify the invariant: after a rename, `entry.data[CONF_ROOM_NAME]`
        equals `entry.options[CONF_ROOM_NAME]`. Removing the data= write
        would leave data at the old value while options gets the new one.
        """
        hass = _hass_with_mutating_update()
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "OldRoom"},
            options={CONF_ROOM_NAME: "OldRoom"},
            hass=hass,
        )
        await flow.async_step_basic_setup(
            user_input={CONF_ROOM_NAME: "NewRoom"}
        )
        # THE invariant. If write-through is reverted, data stays "OldRoom".
        assert (
            flow._config_entry.data[CONF_ROOM_NAME]
            == flow._config_entry.options[CONF_ROOM_NAME]
        )


# ===========================================================================
# D3 — C1 single-listener-invocation spy (real listener callback attached)
# ===========================================================================


class TestD3ListenerSpy:
    """C1 acceptance: EXACTLY ONE update-listener invocation per save.

    The falsifier for THIS test is switching D1 site 1 back to
    async_create_entry — HA's OptionsFlow implementation would then
    internally issue a SECOND async_update_entry call, and our spy
    would see the listener fire twice.
    """

    @pytest.mark.asyncio
    async def test_room_rename_fires_update_listener_exactly_once(self):
        hass = _hass_with_mutating_update()
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "OldRoom"},
            options={CONF_ROOM_NAME: "OldRoom"},
            hass=hass,
        )
        spy_calls = []

        def _listener(_hass, _entry):
            spy_calls.append(_entry.data.get(CONF_ROOM_NAME))

        _register_update_listener(flow._config_entry, _listener)
        await flow.async_step_basic_setup(
            user_input={CONF_ROOM_NAME: "NewRoom"}
        )
        assert len(spy_calls) == 1, (
            f"listener fired {len(spy_calls)} times; C1 invariant broken "
            f"(async_create_entry regression would produce 2)"
        )
        # And the SINGLE listener invocation saw the coherent new name.
        assert spy_calls[0] == "NewRoom"


# ===========================================================================
# D3a — Substrate/tracker read-side invariant
# ===========================================================================


class TestD3SubstrateReadInvariant:
    """Invariant I1 (§1): after a rename, the presence-tracker read shape
    (`entry.data.get(CONF_ROOM_NAME)` — presence.py:2864-2876) resolves
    to the SAME string as the options-side and the aggregation.py:502
    zone read (data-first + options-fallback). This is the read path
    that starved pre-cycle and that the write-through un-starves.

    Falsifier: reverting D1 site 1 makes this test red (data stays
    "OldRoom" while options moves to "NewRoom").
    """

    @pytest.mark.asyncio
    async def test_data_side_reader_sees_new_name_after_rename(self):
        hass = _hass_with_mutating_update()
        flow = _make_options_flow(
            data={CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM, CONF_ROOM_NAME: "OldRoom"},
            options={CONF_ROOM_NAME: "OldRoom"},
            hass=hass,
        )
        await flow.async_step_basic_setup(
            user_input={CONF_ROOM_NAME: "NewRoom"}
        )
        entry = flow._config_entry
        # presence.py:2864-2876 shape — data-only read.
        tracker_view = entry.data.get(CONF_ROOM_NAME)
        # aggregation.py:502 shape — data-first + options-fallback read.
        agg_view = entry.data.get(CONF_ROOM_NAME) or entry.options.get(
            CONF_ROOM_NAME
        )
        # options-first + data-fallback shape (aggregation.py:964/1014/6060).
        opt_first_view = entry.options.get(CONF_ROOM_NAME) or entry.data.get(
            CONF_ROOM_NAME
        )
        assert tracker_view == "NewRoom"
        assert agg_view == "NewRoom"
        assert opt_first_view == "NewRoom"
        # And all three converge — the I1 invariant proven on the three
        # read conventions §4 enumerated.
        assert tracker_view == agg_view == opt_first_view

    @pytest.mark.asyncio
    async def test_zone_reassign_data_first_reader_sees_new_zone(self):
        """aggregation.py:502 bug-shape reader: data-first + options-fallback.

        Pre-cycle, an options-only zone reassignment left `entry.data[CONF_ZONE]`
        stale → this reader returned the OLD zone forever. Write-through fix.
        """
        hass = _hass_with_mutating_update()
        flow = _make_options_flow(
            data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                CONF_ROOM_NAME: "Room1",
                CONF_ZONE: "ZoneA",
            },
            options={CONF_ZONE: "ZoneA"},
            hass=hass,
        )
        await flow.async_step_basic_setup(
            user_input={CONF_ROOM_NAME: "Room1", CONF_ZONE: "ZoneB"}
        )
        entry = flow._config_entry
        agg_502_view = entry.data.get(CONF_ZONE) or entry.options.get(CONF_ZONE)
        assert agg_502_view == "ZoneB", (
            "aggregation.py:502 data-first reader would still see ZoneA if "
            "the D1 site-1 CONF_ZONE write-through were reverted"
        )
