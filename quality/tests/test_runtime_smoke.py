"""Runtime smoke tests — does each domain coordinator's async_setup
execute end-to-end without exception?

These catch RUNTIME bugs (UnboundLocalError, AttributeError, scope
errors, missing import resolution at execution time) that source-grep
and AST tests cannot see. The v4.5.11.2 UnboundLocalError that took
HA down for hours would have been caught by `test_hvac_coord_setup`
below in <1 second.

**This is the missing tier.** Source-grep tests verify structure;
AST tests verify shape; smoke tests verify the code actually executes.

When a coordinator's `async_setup` body changes — especially when
adding code that reads from `hass.data`, `hass.config_entries`,
`hass.services`, or any framework-level resource — the relevant smoke
test in this file MUST pass before deploy.

To add a new coordinator smoke test:
1. Add an import + fixture that constructs the coordinator
2. Add a test that awaits `coordinator.async_setup()` and asserts no
   exception was raised
3. If the coordinator touches a hass facility we haven't stubbed yet,
   extend `runtime_harness.StubHass` to cover it
"""

from __future__ import annotations

import contextlib
import sys
import os

import asyncio

import pytest
import pytest_asyncio

# Smoke tests load the actual URA integration code, which imports
# homeassistant.*. Skip cleanly when HA isn't installed (e.g., dev env
# without `pytest-homeassistant-custom-component`). To enable smoke
# tests: `pip install pytest-homeassistant-custom-component` or
# `pip install homeassistant`. See quality/requirements_test.txt.
ha_available = pytest.importorskip(
    "homeassistant.config_entries",
    reason=(
        "homeassistant package not installed — smoke tests skipped. "
        "Install via: pip install pytest-homeassistant-custom-component "
        "(see quality/requirements_test.txt for the canonical version pin)."
    ),
)

from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
    async_test_home_assistant,
)

from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_ENTRY_TYPE,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_ZONE_MANAGER,
)

# TEST-HARNESS D4b: migrated off runtime_harness.StubHass onto the REAL
# Home Assistant ``hass`` fixture (pytest_homeassistant_custom_component).
# The hand-built StubBus.async_listen() had no ``event_filter`` kwarg, so the
# HVAC setup path that real HA accepts raised TypeError inside the stub --
# a fake-drift failure, not a production defect.

_CANONICAL_ZONES = {
    "Back Hallway": {
        "zone_thermostat": "climate.back_hallway_zone_3",
        "zone_rooms": [],
    },
    "Entertainment": {
        "zone_thermostat": "climate.entertainment_zone_1",
        "zone_rooms": [],
    },
    "Upstairs": {
        "zone_thermostat": "climate.upstairs_zone_2",
        "zone_rooms": [],
    },
}


def _install_canonical_entries(hass, zones_count: int = 3) -> None:
    """Register the canonical CM + ZM config entries on a REAL hass."""
    zones = dict(list(_CANONICAL_ZONES.items())[:zones_count])
    MockConfigEntry(
        domain=DOMAIN,
        entry_id="coordinator_manager_entry",
        title="coordinator_manager_entry",
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER},
        options={},
    ).add_to_hass(hass)
    MockConfigEntry(
        domain=DOMAIN,
        entry_id="zone_manager_entry",
        title="zone_manager_entry",
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_ZONE_MANAGER},
        options={"zones": zones},
    ).add_to_hass(hass)


async def _setup_hvac_and_teardown(hass):
    from custom_components.universal_room_automation.domain_coordinators.hvac import (
        HVACCoordinator,
    )

    coord = HVACCoordinator(hass)
    assert coord.coordinator_id == "hvac"
    try:
        await asyncio.wait_for(coord.async_setup(), timeout=10.0)
    finally:
        await coord.async_teardown()
        await hass.async_block_till_done()
    return coord


# ---------------------------------------------------------------------------
# TEST-HARNESS D4b: REAL-HA fixture + clean-interpreter guard.
#
# phcc's own ``hass`` fixture only resolves under ``asyncio_mode=auto``; this
# suite runs ``strict``, so the same phcc factory (``async_test_home_assistant``)
# is wrapped in a ``pytest_asyncio`` fixture; teardown mirrors phcc's.
#
# In a full-suite run, ~200 fake-HA test modules mutate the REAL
# ``homeassistant.*`` modules at IMPORT time (e.g. ``er.async_get = ...``,
# ``ha_core.HomeAssistant = MagicMock``), before any test runs. A real hass
# then cannot even be constructed. Fixing those donors is D7. Until then: if
# construction fails in-process, the test is skipped with an explicit reason
# AND recorded, and the file's last test re-runs the whole file in a CLEAN
# interpreter and asserts it passes there with zero such skips -- so the
# behaviour is still executed (never silently dropped).
# ---------------------------------------------------------------------------
_D4B_CLEAN_ENV = "URA_D4B_CLEAN_INTERPRETER"
_D4B_POISON_SKIPS: list[str] = []
_D4B_SKIP_PREFIX = "D4B-REAL-HA-POISONED"


@pytest_asyncio.fixture
async def hass(tmp_path, request):
    stack = contextlib.AsyncExitStack()
    try:
        hass = await stack.enter_async_context(
            async_test_home_assistant(config_dir=str(tmp_path))
        )
    except Exception as exc:  # noqa: BLE001 -- poisoned in-process HA
        await stack.aclose()
        if os.environ.get(_D4B_CLEAN_ENV):
            raise  # in the clean interpreter this is a real failure
        _D4B_POISON_SKIPS.append(request.node.nodeid)
        pytest.skip(
            f"{_D4B_SKIP_PREFIX}: real HA could not be constructed in-process "
            f"({type(exc).__name__}: {exc}); an earlier test module mutated "
            f"homeassistant.* at import (D7 donor). Executed instead by "
            f"test_zz_d4b_real_ha_clean_interpreter."
        )
    try:
        yield hass
        await hass.async_block_till_done()
        await hass.async_stop(force=True)
    finally:
        await stack.aclose()



@pytest_asyncio.fixture
async def smoke_hass(hass):
    """3-zone canonical install on a REAL hass."""
    _install_canonical_entries(hass, zones_count=3)
    return hass


@pytest.mark.asyncio
async def test_hvac_coordinator_async_setup_does_not_raise(smoke_hass):
    """v4.5.11.2 regression: HVAC coord async_setup must complete
    without raising on a REAL hass (Bug Class #34 guard). Behavioural
    anchor: the 3 configured thermostat zones must be discovered."""
    coord = await _setup_hvac_and_teardown(smoke_hass)
    zm = coord._zone_manager
    assert sorted(zm.zones) == ["zone_1", "zone_2", "zone_3"]


@pytest.mark.asyncio
async def test_hvac_coordinator_async_setup_with_zero_zones(hass):
    """Edge case: install with no AC zones configured -- setup must still
    complete, and zero zones are discovered."""
    _install_canonical_entries(hass, zones_count=0)
    coord = await _setup_hvac_and_teardown(hass)
    assert len(coord._zone_manager.zones) == 0


# =============================================================================
# Per-platform smoke — would catch button.py setup_entry crashes
# =============================================================================


@pytest.mark.asyncio
async def test_button_platform_setup_does_not_raise(smoke_hass):
    """v4.5.11.x regression: button.py async_setup_entry iterates
    `_discover_ac_zones(hass)` and builds 3 buttons per zone. If any
    of that path crashed (e.g., a missing key in zone_spec, an import
    error in `_make_ac_ramp_button`), this test catches it.
    """
    from custom_components.universal_room_automation.button import (
        async_setup_entry,
    )

    # Find the CM entry (button.py only builds AC ramp buttons for that type)
    cm_entry = None
    for e in smoke_hass.config_entries.async_entries():
        if e.title == "coordinator_manager_entry":
            cm_entry = e
            break
    assert cm_entry is not None

    added_entities: list = []

    def _async_add_entities(entities, _update_before_add=False):
        added_entities.extend(entities)

    try:
        await async_setup_entry(smoke_hass, cm_entry, _async_add_entities)
    except Exception as e:
        pytest.fail(
            f"button.py async_setup_entry raised {type(e).__name__}: {e}"
        )

    # 2 always-added (NMAcknowledge + ClearBayesianBeliefs) + 3 zones × 3 buttons
    # = 11 entities. Less = some path crashed silently.
    assert len(added_entities) >= 11, (
        f"Expected at least 11 entities (2 fixed + 9 AC ramp), got "
        f"{len(added_entities)}. Some _make_ac_ramp_button invocation "
        f"may have silently failed."
    )


@pytest.mark.asyncio
async def test_number_platform_setup_does_not_raise(smoke_hass):
    """v4.5.11.x regression: number.py async_setup_entry builds the
    7 house-wide v4.5.10 numbers, the 6 v4.5.11 house-wide numbers,
    and 1 per-zone kWh threshold per AC zone.

    Catches: import resolution issues in factory invocations,
    class-build errors, _discover_ac_zones key mismatches.
    """
    from custom_components.universal_room_automation.number import (
        async_setup_entry,
    )

    cm_entry = None
    for e in smoke_hass.config_entries.async_entries():
        if e.title == "coordinator_manager_entry":
            cm_entry = e
            break
    assert cm_entry is not None

    added_entities: list = []

    def _async_add_entities(entities, _update_before_add=False):
        added_entities.extend(entities)

    try:
        await async_setup_entry(smoke_hass, cm_entry, _async_add_entities)
    except Exception as e:
        pytest.fail(
            f"number.py async_setup_entry raised {type(e).__name__}: {e}"
        )

    # Expected counts (rough — exact depends on what's in CM):
    # 7 entry-flow numbers (ZoneEntryDwell + 4 OffPeakDrain + PeakBuffer +
    # ArbitrageChargeLeadTime + EVBatteryDrainSOC) +
    # 7 v4.5.10 HVAC tunables + 6 v4.5.11 house-wide + 3 per-zone =
    # 23 minimum.
    assert len(added_entities) >= 19, (
        f"Expected at least 19 Number entities, got "
        f"{len(added_entities)}. The platform setup may have silently "
        f"failed in one of the factory iterations."
    )


@pytest.mark.asyncio
async def test_switch_platform_setup_does_not_raise(smoke_hass):
    """v4.5.11.x regression: switch.py async_setup_entry builds the
    HVAC and CM switches including the v4.5.11 master AC Ramp-Down
    switch. Catches: master switch constructor errors, _get_arrester
    init issues.
    """
    from custom_components.universal_room_automation.switch import (
        async_setup_entry,
    )

    cm_entry = None
    for e in smoke_hass.config_entries.async_entries():
        if e.title == "coordinator_manager_entry":
            cm_entry = e
            break
    assert cm_entry is not None

    added_entities: list = []

    def _async_add_entities(entities, _update_before_add=False):
        added_entities.extend(entities)

    try:
        await async_setup_entry(smoke_hass, cm_entry, _async_add_entities)
    except Exception as e:
        pytest.fail(
            f"switch.py async_setup_entry raised {type(e).__name__}: {e}"
        )

    # Lots of CM-level switches; at minimum the v4.5.11 master should be there
    assert any(
        getattr(e, "_attr_unique_id", "").endswith("_hvac_ac_ramp_master")
        for e in added_entities
    ), "v4.5.11 master AC Ramp-Down switch not registered"


# =============================================================================
# Database smoke — does init_db create the v4.5.11 tables?
# =============================================================================


@pytest.mark.asyncio
async def test_database_init_creates_v4511_tables(hass, tmp_path):
    """v4.5.11 D4 regression: UniversalRoomDatabase.initialize must
    create the ac_reset_state and ac_ramp_events tables on a fresh
    database file. If init_db raises (CREATE TABLE syntax error,
    schema constraint failure), this test catches it.
    """
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    # Real hass; its config dir is already tmp_path (see ``hass`` fixture).
    assert hass.config.config_dir == str(tmp_path)
    db = UniversalRoomDatabase(hass)

    # Production order (__init__.py:2648-2649): initialize() FIRST, then
    # start the write worker. (The old test started the worker first; on a
    # real hass the background task starts eagerly and its connection can
    # hold the fresh file locked while initialize() sets PRAGMAs.) The
    # production entry point is ``initialize()``; ``init_db`` never existed.
    try:
        ok = await db.initialize()
        assert ok, "initialize() returned False — see logs for failed_tables list"
        await db.start_write_worker()

        # Confirm v4.5.11 tables exist
        async with db._db_read() as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('ac_reset_state', 'ac_ramp_events')"
            )
            rows = await cursor.fetchall()
            names = {r[0] for r in rows}
            assert "ac_reset_state" in names, (
                "ac_reset_state table not created — Bug Class #4 "
                "(domain mismatch) or CREATE TABLE syntax error"
            )
            assert "ac_ramp_events" in names, (
                "ac_ramp_events table not created"
            )
    finally:
        await db.stop_write_worker()


@pytest.mark.asyncio
async def test_number_platform_registers_inclement_blind_floor(smoke_hass):
    """EC storm/blind Stage A D-A5 wire-in: the CM number platform setup
    registers exactly one `InclementBlindFullHoldFloorNumber` (Live (e):
    missing entity = platform wiring broken)."""
    from custom_components.universal_room_automation.number import (
        InclementBlindFullHoldFloorNumber,
        async_setup_entry,
    )

    cm_entry = next(
        e for e in smoke_hass.config_entries.async_entries()
        if e.title == "coordinator_manager_entry"
    )
    added: list = []
    await async_setup_entry(
        smoke_hass, cm_entry, lambda ents, _u=False: added.extend(ents),
    )
    # Exact type: the Stage B pre-onset slider subclasses this entity.
    found = [e for e in added if type(e) is InclementBlindFullHoldFloorNumber]
    assert len(found) == 1
    assert found[0].native_value == 60


@pytest.mark.asyncio
async def test_number_platform_registers_inclement_preonset_floor(smoke_hass):
    """EC storm Stage B D-B6 wire-in: the CM number platform registers
    exactly one `InclementPreonsetFloorNumber` (default 80)."""
    from custom_components.universal_room_automation.number import (
        InclementPreonsetFloorNumber,
        async_setup_entry,
    )

    cm_entry = next(
        e for e in smoke_hass.config_entries.async_entries()
        if e.title == "coordinator_manager_entry"
    )
    added: list = []
    await async_setup_entry(
        smoke_hass, cm_entry, lambda ents, _u=False: added.extend(ents),
    )
    found = [e for e in added if type(e) is InclementPreonsetFloorNumber]
    assert len(found) == 1
    assert found[0].native_value == 80


@pytest.mark.asyncio
async def test_platforms_register_nm_panel_entities(smoke_hass):
    """Halo S1b D-S1b-4 wire-in: the CM switch platform registers exactly one
    NMPanelChannelSwitch (default OFF) and the number platform exactly one
    NMPanelLeaseTtlNumber (default 30 min)."""
    from custom_components.universal_room_automation import number as number_mod
    from custom_components.universal_room_automation import switch as switch_mod
    from custom_components.universal_room_automation.nm_panel_entities import (
        NMPanelChannelSwitch,
        NMPanelLeaseTtlNumber,
    )

    cm_entry = next(
        e for e in smoke_hass.config_entries.async_entries()
        if e.title == "coordinator_manager_entry"
    )
    added: list = []
    await switch_mod.async_setup_entry(
        smoke_hass, cm_entry, lambda ents, _u=False: added.extend(ents),
    )
    await number_mod.async_setup_entry(
        smoke_hass, cm_entry, lambda ents, _u=False: added.extend(ents),
    )
    switches = [e for e in added if type(e) is NMPanelChannelSwitch]
    numbers = [e for e in added if type(e) is NMPanelLeaseTtlNumber]
    assert len(switches) == 1 and switches[0].is_on is False
    assert len(numbers) == 1 and numbers[0].native_value == 30

def test_zz_d4b_real_ha_clean_interpreter():
    """Runs LAST in this file. If any real-HA test was skipped because the
    in-process HA was poisoned, re-run this whole file in a clean interpreter
    and require it to pass with no poison skips."""
    if os.environ.get(_D4B_CLEAN_ENV) or not _D4B_POISON_SKIPS:
        return  # nothing skipped in-process (or we ARE the clean run)
    import subprocess
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env[_D4B_CLEAN_ENV] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(repo, "quality")] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    r = subprocess.run(
        [sys.executable, "-m", "pytest", os.path.abspath(__file__), "-q",
         "-p", "no:cacheprovider", "-rs"],
        cwd=repo, env=env, capture_output=True, text=True, timeout=600,
    )
    out = r.stdout + r.stderr
    print("D4B clean-interpreter run:", r.returncode, out.strip().splitlines()[-1:])
    assert r.returncode == 0, f"clean-interpreter run failed:\n{out[-4000:]}"
    assert _D4B_SKIP_PREFIX not in out, out[-4000:]
