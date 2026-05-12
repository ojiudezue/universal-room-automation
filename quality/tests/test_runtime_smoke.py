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

import asyncio
import pytest

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

from runtime_harness import build_smoke_hass  # noqa: E402


# =============================================================================
# HVAC Coordinator — the one that crashed in v4.5.11
# =============================================================================


@pytest.fixture
def smoke_hass():
    """3-zone canonical install stub."""
    return build_smoke_hass(zones_count=3)


@pytest.mark.asyncio
async def test_hvac_coordinator_async_setup_does_not_raise(smoke_hass):
    """v4.5.11.2 regression: HVAC coord async_setup must complete
    without raising. This is the smoke test that would have caught
    the UnboundLocalError on `DOMAIN` at hvac.py:356 in <1 second.

    Specifically guards against:
    - Bug Class #34 (function-local import shadows module-level)
    - Any AttributeError or ImportError from a code path that's
      reached by async_setup but not by source-grep tests
    """
    from custom_components.universal_room_automation.domain_coordinators.hvac import (
        HVACCoordinator,
    )

    coord = HVACCoordinator(smoke_hass)

    # Sanity: construction itself shouldn't raise (no I/O in __init__).
    assert coord is not None
    assert coord.coordinator_id == "hvac"

    # The smoke check: async_setup() must execute its body without
    # an exception escaping. We do NOT assert on outcome (no zones
    # discovered, no real entities — the stub hass is intentionally
    # bare). We only assert "no crash".
    #
    # NOTE: HVAC's async_setup wires up event listeners, queries
    # config entries, builds zone manager state, etc. With a stub
    # hass and no real climate entities, much of that returns empty.
    # That's fine — we're testing for crashes, not behavior.
    try:
        await asyncio.wait_for(coord.async_setup(), timeout=10.0)
    except asyncio.TimeoutError:
        pytest.fail(
            "HVAC coord async_setup did not complete in 10s — possible "
            "deadlock or infinite loop in the setup path"
        )
    except Exception as e:
        pytest.fail(
            f"HVAC coord async_setup raised {type(e).__name__}: {e}\n"
            f"This indicates a runtime bug in the setup path — source-grep "
            f"tests cannot catch this class of issue. See Bug Class #34 "
            f"in QUALITY_CONTEXT.md for the v4.5.11.2 case."
        )

    # Cleanup: cancel any background tasks the coord spawned
    for task in smoke_hass._stub_tasks:
        if not task.done():
            task.cancel()


@pytest.mark.asyncio
async def test_hvac_coordinator_async_setup_with_zero_zones(smoke_hass):
    """Edge case: install with no AC zones configured.

    URA must handle this gracefully — no zones means no AC ramp-down,
    but the coord should still start and the integration should remain
    usable. v4.5.11's _discover_ac_zones helper specifically iterates
    config_entries; if it had a divide-by-zero or empty-list crash,
    this test catches it.
    """
    from custom_components.universal_room_automation.domain_coordinators.hvac import (
        HVACCoordinator,
    )
    # Wipe out zones
    hass_no_zones = build_smoke_hass(zones_count=0)
    coord = HVACCoordinator(hass_no_zones)
    try:
        await asyncio.wait_for(coord.async_setup(), timeout=10.0)
    except Exception as e:
        pytest.fail(
            f"HVAC coord async_setup raised {type(e).__name__} with zero "
            f"zones: {e}. The coord must handle the no-AC-zones case "
            f"gracefully."
        )
    for task in hass_no_zones._stub_tasks:
        if not task.done():
            task.cancel()


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
async def test_database_init_creates_v4511_tables(tmp_path):
    """v4.5.11 D4 regression: UniversalRoomDatabase.init_db must
    create the ac_reset_state and ac_ramp_events tables on a fresh
    database file. If init_db raises (CREATE TABLE syntax error,
    schema constraint failure), this test catches it.
    """
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    from runtime_harness import StubHass

    # Build a stub hass pointing at a temp config dir
    hass = StubHass(config_dir=str(tmp_path))
    db = UniversalRoomDatabase(hass)

    # Start write worker (URA's pattern)
    await db.start_write_worker()
    try:
        ok = await db.init_db()
        assert ok, "init_db returned False — see logs for failed_tables list"

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
        # Best-effort cleanup
        if db._write_task and not db._write_task.done():
            db._write_task.cancel()
