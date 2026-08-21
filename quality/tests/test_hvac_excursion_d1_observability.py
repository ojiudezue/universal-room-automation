"""HVAC-GOVERNED-EXCURSION-1 D1 — observability-only telemetry tests.

Purely additive columns on `ac_ramp_events` (preset_before/after,
mode_before/after, restore_ok) plus population at the two nudge lifecycle
sites. Behaviour must be byte-identical; this deliverable only MEASURES
the pre-existing ordering-race + self-disarm defects.

Tests are behavioural (round-trip through the real DB writer) and include
a WIRE-IN ANCHOR — deleting the call-site (not just the DAO parameter)
must break a specific named test. Drilled as part of the build.
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Source-grep wire-in anchors — execute in ALL environments (no HA needed),
# so they run in the local suite and CI even where the behavioural tests
# below are skipped. Deleting either call-site kwarg regresses these.
# ---------------------------------------------------------------------------


HVAC_OVERRIDE_PATH = (
    "custom_components/universal_room_automation/"
    "domain_coordinators/hvac_override.py"
)
DATABASE_PATH = "custom_components/universal_room_automation/database.py"


@pytest.fixture(scope="module")
def hvac_override_src() -> str:
    with open(HVAC_OVERRIDE_PATH) as f:
        return f.read()


@pytest.fixture(scope="module")
def database_src() -> str:
    with open(DATABASE_PATH) as f:
        return f.read()


def _slice_between(src: str, start_marker: str, end_marker: str) -> str:
    i = src.index(start_marker)
    j = src.index(end_marker, i)
    return src[i:j]


class TestDatabaseSchemaAdditions:

    def test_schema_declares_new_columns(self, database_src):
        # DDL block for ac_ramp_events must carry all 5 new columns.
        ddl = _slice_between(
            database_src,
            'CREATE TABLE IF NOT EXISTS ac_ramp_events',
            ')"""',
        )
        for col in (
            "preset_before TEXT",
            "preset_after TEXT",
            "mode_before TEXT",
            "mode_after TEXT",
            "restore_ok INTEGER",
        ):
            assert col in ddl, f"schema missing: {col}"

    def test_migration_alter_table_present_and_guarded(self, database_src):
        # Each new column must appear in an idempotent ALTER TABLE
        # migration (guarded by the "not in are_columns" check).
        for col in (
            "preset_before", "preset_after",
            "mode_before", "mode_after", "restore_ok",
        ):
            assert (
                f'"{col}"' in database_src or f"'{col}'" in database_src
            ), f"migration list missing {col}"

    def test_insert_writes_new_columns(self, database_src):
        insert = _slice_between(
            database_src,
            "INSERT INTO ac_ramp_events",
            "await db.commit()",
        )
        for col in (
            "preset_before", "preset_after",
            "mode_before", "mode_after", "restore_ok",
        ):
            assert col in insert, f"INSERT missing column {col}"


class TestNudgeStartedWireIn:

    def test_call_site_passes_preset_before_and_mode_before(
        self, hvac_override_src,
    ):
        # Isolate the _perform_soft_nudge log call and require the two
        # new kwargs. Deleting them at the call-site fails here even if
        # the DAO signature still accepts them.
        # End marker = the log call that immediately follows this
        # deliverable's block (the info log after the DB write).
        block = _slice_between(
            hvac_override_src,
            "event_type=AC_RAMP_EVENT_NUDGE_STARTED",
            "_LOGGER.info(",
        )
        assert "preset_before=" in block, (
            "nudge_started log call must pass preset_before "
            "(D1 wire-in anchor)"
        )
        assert "mode_before=" in block, (
            "nudge_started log call must pass mode_before "
            "(D1 wire-in anchor)"
        )


class TestNudgeRestoredWireIn:

    def test_call_site_passes_preset_after_mode_after_restore_ok(
        self, hvac_override_src,
    ):
        # The next method definition is our end sentinel.
        block = _slice_between(
            hvac_override_src,
            "event_type=AC_RAMP_EVENT_NUDGE_RESTORED",
            "    async def ",
        )
        for kw in ("preset_after=", "mode_after=", "restore_ok="):
            assert kw in block, (
                f"nudge_restored log call must pass {kw} "
                f"(D1 wire-in anchor)"
            )

    def test_restore_ok_uses_cached_states_get_not_await(
        self, hvac_override_src,
    ):
        # The read used to compute restore_ok must be hass.states.get
        # (sync, cached) so it cannot perturb the ordering race being
        # measured. A `hass.async_add_executor_job` or a service call
        # here would be a behavioural change.
        block = _slice_between(
            hvac_override_src,
            "HVAC-GOVERNED-EXCURSION-1 D1: post-restore telemetry",
            "await self._db.log_ac_ramp_event(",
        )
        assert "self.hass.states.get(" in block, (
            "post-restore telemetry must read via hass.states.get "
            "(cached, no-await) so it cannot perturb the race"
        )
        # No new awaits in the telemetry block itself (belt-and-braces).
        assert " await " not in block, (
            "telemetry read must not introduce awaits into the "
            "restore path"
        )


# ---------------------------------------------------------------------------
# Behavioural tests (require real HA install) — round-trip through the
# real DB writer + drive the real coordinator methods.
# ---------------------------------------------------------------------------

_HA_REAL = False
try:
    import homeassistant.util.dt as _ha_dt  # noqa: F401
    from homeassistant.helpers.storage import Store as _Store  # noqa: F401
    _HA_REAL = True
except Exception:
    _HA_REAL = False


_ha_only = pytest.mark.skipif(
    not _HA_REAL,
    reason="real homeassistant not installed; D1 behavioural test skipped",
)


# ---------------------------------------------------------------------------
# Schema / DAO round-trip
# ---------------------------------------------------------------------------


@_ha_only
@pytest.mark.asyncio
async def test_d1_schema_has_observability_columns(tmp_path):
    """Fresh DB init must contain all five new columns."""
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    from runtime_harness import StubHass

    hass = StubHass(config_dir=str(tmp_path))
    db = UniversalRoomDatabase(hass)
    await db.start_write_worker()
    try:
        assert await db.init_db()

        import aiosqlite
        async with aiosqlite.connect(db.db_file) as conn:
            cur = await conn.execute("PRAGMA table_info(ac_ramp_events)")
            cols = {row[1] for row in await cur.fetchall()}
        for expected in (
            "preset_before", "preset_after",
            "mode_before", "mode_after", "restore_ok",
        ):
            assert expected in cols, f"missing column {expected}"
    finally:
        if db._write_task and not db._write_task.done():
            db._write_task.cancel()


@_ha_only
@pytest.mark.asyncio
async def test_d1_dao_round_trips_new_columns(tmp_path):
    """log_ac_ramp_event accepts + persists the new kwargs unchanged."""
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    from runtime_harness import StubHass

    hass = StubHass(config_dir=str(tmp_path))
    db = UniversalRoomDatabase(hass)
    await db.start_write_worker()
    try:
        assert await db.init_db()

        # Row A: nudge_started with pre-write state captured.
        await db.log_ac_ramp_event(
            zone_id="zone_a",
            event_type="nudge_started",
            preset_before="sleep",
            mode_before="cool",
        )
        # Row B: nudge_restored with post-write state, restore succeeded.
        await db.log_ac_ramp_event(
            zone_id="zone_a",
            event_type="nudge_restored",
            preset_after="sleep",
            mode_after="cool",
            restore_ok=True,
        )
        # Row C: nudge_restored where post-write preset is still manual.
        await db.log_ac_ramp_event(
            zone_id="zone_b",
            event_type="nudge_restored",
            preset_after="manual",
            mode_after="cool",
            restore_ok=False,
        )
        # Row D: nudge_restored with no intent (self-disarm) -> NULL.
        await db.log_ac_ramp_event(
            zone_id="zone_c",
            event_type="nudge_restored",
            preset_after="manual",
            mode_after="cool",
            restore_ok=None,
        )
        for _ in range(30):
            if db._write_queue.empty():
                break
            await asyncio.sleep(0.05)

        import aiosqlite
        async with aiosqlite.connect(db.db_file) as conn:
            cur = await conn.execute(
                "SELECT zone_id, event_type, preset_before, preset_after, "
                "mode_before, mode_after, restore_ok "
                "FROM ac_ramp_events ORDER BY event_id"
            )
            rows = await cur.fetchall()
        by_zone = {(r[0], r[1]): r for r in rows}
        a = by_zone[("zone_a", "nudge_started")]
        assert a[2] == "sleep" and a[4] == "cool"
        b = by_zone[("zone_a", "nudge_restored")]
        assert b[3] == "sleep" and b[5] == "cool" and b[6] == 1
        c = by_zone[("zone_b", "nudge_restored")]
        assert c[3] == "manual" and c[6] == 0
        d = by_zone[("zone_c", "nudge_restored")]
        assert d[6] is None, "self-disarm intent must persist as NULL"
    finally:
        if db._write_task and not db._write_task.done():
            db._write_task.cancel()


# ---------------------------------------------------------------------------
# WIRE-IN ANCHORS — drive the real methods; fail if the call-site is
# stripped (not merely if the DAO parameter is removed).
# ---------------------------------------------------------------------------


class _CapturingDB:
    """Stand-in for URADatabase that records log_ac_ramp_event kwargs."""
    def __init__(self):
        self.calls: list[dict] = []

    async def log_ac_ramp_event(self, **kwargs):
        self.calls.append(kwargs)

    # Minimal surface that _perform_soft_nudge / _restore_after_nudge touch.
    async def get_ac_reset_state(self, zone_id):
        return {"soft_nudge_count": 0}

    async def save_ac_reset_state(self, state):
        return None

    async def save_ac_in_flight_nudge(self, *a, **kw):
        return None

    async def clear_ac_in_flight_nudge(self, *a, **kw):
        return None


def _make_state(preset: str | None, mode: str | None):
    attrs = {}
    if preset is not None:
        attrs["preset_mode"] = preset
    return SimpleNamespace(state=mode, attributes=attrs)


@_ha_only
@pytest.mark.asyncio
async def test_d1_wirein_nudge_started_populates_pre_state(monkeypatch):
    """WIRE-IN ANCHOR (nudge_started): the log call at _perform_soft_nudge
    MUST carry preset_before + mode_before pulled from hass.states.get.
    Deleting the two kwargs at the call-site (not just the DAO signature)
    causes this test to fail.
    """
    from custom_components.universal_room_automation.domain_coordinators \
        import hvac_override as ho

    # Neuter external side effects that the method reaches for.
    async def _noop(*a, **kw): return True
    monkeypatch.setattr(ho, "emit_set_temperature", _noop)

    coord = ho.HVACOverrideCoordinator.__new__(ho.HVACOverrideCoordinator)
    # Minimal attribute surface required by _perform_soft_nudge.
    captured_state = _make_state(preset="sleep", mode="cool")
    hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda eid: captured_state),
        async_create_task=lambda coro: coro.close(),
    )
    coord.hass = hass
    coord._db = _CapturingDB()
    coord._nudge_pre_preset = {}
    coord._nudge_in_flight = set()
    coord._nudge_restore_timers = {}
    coord._nudge_duration_min = 10
    coord._corrective_writes_suppressed = lambda z: False
    coord._freeze_active = lambda: False
    coord.comfort_delay_active = lambda z: False
    coord.suppress = lambda *a, **kw: None
    coord._track_zone_action = lambda *a, **kw: None

    zone = SimpleNamespace(
        zone_id="z1",
        zone_name="Test",
        climate_entity="climate.test",
        target_temp_low=68.0,
        target_temp_high=76.0,
        current_temperature=78.0,
        ramp_state="",
        nudge_kwh_rate_before=0.0,
        last_overshoot_started="",
        kwh_samples_above_threshold=0,
    )

    # Patch async_call_later to a no-op so the restore timer doesn't fire.
    monkeypatch.setattr(ho, "async_call_later", lambda *a, **kw: (lambda: None))

    await coord._perform_soft_nudge(
        zone, new_target=78.0, kwh_rate_before=1.5, triggered_by="auto",
        original_target=76.0, started_ts="2026-08-21T00:00:00", duration_s=600,
    )

    started = [c for c in coord._db.calls if c.get("event_type") == "nudge_started"]
    assert started, "nudge_started log call missing (WIRE-IN)"
    row = started[0]
    assert row.get("preset_before") == "sleep", (
        "preset_before not populated from hass.states — call-site regressed"
    )
    assert row.get("mode_before") == "cool", (
        "mode_before not populated from hass.states — call-site regressed"
    )


@_ha_only
@pytest.mark.asyncio
async def test_d1_wirein_nudge_restored_populates_post_state_and_restore_ok(
    monkeypatch,
):
    """WIRE-IN ANCHOR (nudge_restored): the log call at _restore_after_nudge
    MUST carry preset_after + mode_after + restore_ok. Deleting them at
    the call-site fails this test.

    Also asserts the semantic behaviour we want to measure:
      - intent=sleep + observed preset_after=manual -> restore_ok=False
        (the ordering-race / cloud-clobber signature).
      - intent absent (self-disarm) -> restore_ok=None.
    """
    from custom_components.universal_room_automation.domain_coordinators \
        import hvac_override as ho

    async def _noop(*a, **kw): return True
    monkeypatch.setattr(ho, "emit_set_temperature", _noop)
    monkeypatch.setattr(ho, "emit_set_preset_mode", _noop)

    coord = ho.HVACOverrideCoordinator.__new__(ho.HVACOverrideCoordinator)
    # After restore reads: preset still "manual" (defect signature).
    post_state = _make_state(preset="manual", mode="cool")
    hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda eid: post_state),
    )
    coord.hass = hass
    coord._db = _CapturingDB()
    coord._nudge_pre_preset = {"z1": "sleep"}  # intent captured
    coord._nudge_in_flight = {"z1"}
    coord._nudge_restore_timers = {}
    coord._freeze_active = lambda: False
    coord.suppress = lambda *a, **kw: None
    coord._track_zone_action = lambda *a, **kw: None

    zone = SimpleNamespace(
        zone_id="z1",
        zone_name="Test",
        climate_entity="climate.test",
        target_temp_low=68.0,
        target_temp_high=76.0,
        nudge_kwh_rate_before=1.5,
    )
    await coord._restore_after_nudge(zone, original_target=76.0)

    restored = [
        c for c in coord._db.calls if c.get("event_type") == "nudge_restored"
    ]
    assert restored, "nudge_restored log call missing (WIRE-IN)"
    row = restored[0]
    assert row.get("preset_after") == "manual", "preset_after not populated"
    assert row.get("mode_after") == "cool", "mode_after not populated"
    assert row.get("restore_ok") is False, (
        "restore_ok must be False when intent=sleep but preset stayed manual "
        "(ordering-race / cloud-clobber signature)"
    )

    # Self-disarm case: no intent stashed -> restore_ok must be None.
    coord._db = _CapturingDB()
    coord._nudge_pre_preset = {}  # self-disarm (preset was already "manual")
    coord._nudge_in_flight = {"z1"}
    await coord._restore_after_nudge(zone, original_target=76.0)
    row2 = [
        c for c in coord._db.calls if c.get("event_type") == "nudge_restored"
    ][0]
    assert row2.get("restore_ok") is None, (
        "self-disarm must log restore_ok=NULL, never guess"
    )
