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
            "restore_ok_immediate INTEGER",
        ):
            assert col in ddl, f"schema missing: {col}"

    def test_migration_alter_table_present_and_guarded(self, database_src):
        # Each new column must appear in an idempotent ALTER TABLE
        # migration (guarded by the "not in are_columns" check).
        for col in (
            "preset_before", "preset_after",
            "mode_before", "mode_after",
            "restore_ok", "restore_ok_immediate",
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
            "mode_before", "mode_after",
            "restore_ok", "restore_ok_immediate",
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
        for kw in (
            "preset_after=", "mode_after=",
            "restore_ok=", "restore_ok_immediate=",
        ):
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
            "HVAC-GOVERNED-EXCURSION-1 D1: paired IMMEDIATE / SETTLED",
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
            "mode_before", "mode_after",
            "restore_ok", "restore_ok_immediate",
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


# ===========================================================================
# HVAC-GOVERNED-EXCURSION-1 D1 — SETTLED-verdict paired-sample tests.
#
# Rationale (coordinator directive): an immediate post-restore read
# systematically records restore_ok=1 in the FAILURE case (late cloud-poll
# clobber lands ~500 ms later), so the metric would lie about the very
# defect this deliverable exists to measure. The paired
# (immediate=1, settled=0) signature is what identifies the clobber.
# ===========================================================================


class TestSettledSampleConstant:

    def test_settle_delay_constant_declared_as_module_const(self):
        # Rung: module constant (numbers-get-knobs ladder rung 1).
        # Changing this window should require a code review, not an
        # operator turn — it is a measurement window, not policy.
        path = (
            "custom_components/universal_room_automation/"
            "domain_coordinators/hvac_const.py"
        )
        with open(path) as f:
            src = f.read()
        assert "AC_NUDGE_RESTORE_SETTLE_DELAY_S: Final = 12" in src, (
            "settled-sample delay must be a Final module constant"
        )


class TestSettledSampleWireIn:

    def test_restore_after_nudge_imports_and_schedules_settled_timer(
        self, hvac_override_src,
    ):
        # Import present.
        assert "AC_NUDGE_RESTORE_SETTLE_DELAY_S" in hvac_override_src

        idx = hvac_override_src.find("async def _restore_after_nudge")
        # 12000 covers the post-restore telemetry + settled-callback block.
        body = hvac_override_src[idx: idx + 12000]

        # Scheduler: async_call_later using the NAMED constant, not a literal.
        assert "AC_NUDGE_RESTORE_SETTLE_DELAY_S" in body, (
            "delayed settled callback must use the named constant"
        )
        # Handle stored on the per-zone timer dict for cancel-safety.
        assert "_nudge_settled_timers[zone_id]" in body, (
            "settled timer handle must be registered for teardown cancel"
        )
        # DAO call must be the settled-update helper (not another INSERT).
        assert "update_ac_ramp_restore_settled" in body, (
            "settled verdict must be UPDATE-ed onto the existing row, "
            "not inserted as a new one"
        )
        # Immediate row must be inserted with restore_ok=None so the
        # settled UPDATE has a NULL to fill.
        assert "restore_ok=None," in body, (
            "immediate INSERT must leave restore_ok NULL for the settled "
            "callback to fill"
        )

    def test_settled_timer_dict_initialised_and_torn_down(
        self, hvac_override_src,
    ):
        assert (
            "self._nudge_settled_timers: dict[str, CALLBACK_TYPE] = {}"
            in hvac_override_src
        ), "settled-timer dict must be initialised on the coordinator"
        # Teardown block must cancel + clear the dict.
        assert "self._nudge_settled_timers.values()" in hvac_override_src, (
            "teardown must iterate the settled-timer dict"
        )
        assert "self._nudge_settled_timers.clear()" in hvac_override_src, (
            "teardown must clear the settled-timer dict"
        )

    def test_settled_callback_reads_state_and_writes_verdict_no_service_calls(
        self, hvac_override_src,
    ):
        """2026-08-23 fix-up (F8 REVERSED after operator re-measurement):
        the 2026-08-22 option-c ruling that disabled this sample was
        built on an unmeasured number (`DEFAULT_UPDATE_INTERVAL_MINUTES
        = 30` read as the real refresh cadence). The recorder shows
        the climate entities actually refresh every 42-79 s median.
        The settled sample now fires at 3 min (past the refresh
        envelope, inside the 25-min nudge cadence), reads state,
        writes a real True/False/None verdict, and populates
        settled_reason ONLY for genuinely-unreadable / cancelled
        cases.

        This test asserts the RESTORED contract:
          - passive `hass.states.get(` read;
          - writes restore_ok via `update_ac_ramp_restore_settled`;
          - populates settled_reason only when the entity is missing
            (via AC_NUDGE_SETTLED_REASON_ENTITY_MISSING); a
            cancelled-by-renudge case is handled OUTSIDE this
            closure (see _perform_soft_nudge).

        The NO-SERVICE-CALLS half of the original invariant is
        PRESERVED VERBATIM — that guarantee is what enforces
        perturbation-free measurement.
        """
        idx = hvac_override_src.find("async def _write_settled(")
        assert idx > 0, "settled-write inner coroutine must exist"
        body = hvac_override_src[idx: idx + 3500]
        # Restored contract: real read + verdict.
        assert "self.hass.states.get(" in body, (
            "F8 reversed: settled callback must re-read state to compute "
            "a real True/False verdict"
        )
        assert "update_ac_ramp_restore_settled(" in body, (
            "verdict must be UPDATE-ed onto the immediate row's "
            "existing slot, not INSERT-ed as a new row"
        )
        assert "AC_NUDGE_SETTLED_REASON_ENTITY_MISSING" in body, (
            "genuinely-unreadable case (entity missing at settle) must "
            "populate settled_reason via the named constant"
        )
        # The old unmeasurable-reason claim is retired — it was built
        # on the unmeasured 30-min figure.
        assert "AC_NUDGE_RESTORE_SETTLED_UNMEASURABLE_REASON" not in body, (
            "the 'poll_interval_30min_exceeds_nudge_cadence_25min' claim "
            "was built on an unmeasured cadence and has been retired"
        )
        # PRESERVED invariant (unchanged from pre-fix contract):
        # no thermostat writes / service calls / suppression flips
        # inside the settled callback. Whatever the verdict rule
        # becomes, perturbation-free measurement is what makes the
        # observation admissible.
        for banned in (
            "async_call_service",
            "hass.services.async_call",
            "emit_set_temperature",
            "emit_set_preset_mode",
            "self.suppress(",
        ):
            assert banned not in body, (
                f"settled callback must not perform {banned} — that would "
                f"perturb the race being measured"
            )


class TestDAOSettledUpdate:

    def test_update_dao_signature_and_only_touches_null_rows(
        self, database_src,
    ):
        # Signature.
        assert "async def update_ac_ramp_restore_settled(" in database_src
        # Guarded UPDATE: must only touch the row where restore_ok IS NULL
        # so a delayed callback can never overwrite a subsequent nudge's
        # settled row.
        idx = database_src.find("async def update_ac_ramp_restore_settled(")
        body = database_src[idx: idx + 2500]
        # Anchor on the SQL fragment (AND ...) not the bare phrase, so
        # deleting the WHERE clause is not masked by the docstring
        # mentioning the same words.
        assert "AND restore_ok IS NULL" in body, (
            "settled UPDATE must be guarded by 'AND restore_ok IS NULL' "
            "in its SQL so a delayed callback cannot overwrite a fresh row"
        )
        # Silent no-op via WHERE clause when row is absent (retention or
        # DB reset): a filtered UPDATE that matches zero rows is a no-op
        # by construction, and the outer try/except is the belt-and-braces.
        assert "try:" in body and "except Exception" in body, (
            "settled UPDATE must be exception-guarded so a delayed "
            "callback firing after DB teardown degrades silently"
        )


# ---- Behavioural: paired-sample distinguishes clobber from clean ----------


@_ha_only
@pytest.mark.asyncio
async def test_d1_paired_sample_distinguishes_clobber_from_clean(tmp_path):
    """Round-trip that proves the (immediate, settled) pair identifies the
    late-clobber defect signature vs a clean restore.

    Scenario A (CLOBBER): _restore_after_nudge sees preset restored
    immediately (immediate=1), then a delayed cloud poll re-flips it to
    "manual" — settled UPDATE writes restore_ok=0. Pair = (1, 0).

    Scenario B (CLEAN): both immediate and settled see the intended
    preset — pair = (1, 1).

    Scenario C (SELF-DISARM): no intent captured — both verdicts NULL.
    """
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    from runtime_harness import StubHass

    hass = StubHass(config_dir=str(tmp_path))
    db = UniversalRoomDatabase(hass)
    await db.start_write_worker()
    try:
        assert await db.init_db()

        # A — insert immediate=1 with restore_ok=NULL, then settled UPDATE
        # writes restore_ok=0 (the clobber).
        await db.log_ac_ramp_event(
            zone_id="clobber_zone",
            event_type="nudge_restored",
            preset_after="sleep",
            mode_after="cool",
            restore_ok=None,
            restore_ok_immediate=True,
        )
        # B — insert immediate=1, settled will also be 1.
        await db.log_ac_ramp_event(
            zone_id="clean_zone",
            event_type="nudge_restored",
            preset_after="sleep",
            mode_after="cool",
            restore_ok=None,
            restore_ok_immediate=True,
        )
        # C — self-disarm.
        await db.log_ac_ramp_event(
            zone_id="disarm_zone",
            event_type="nudge_restored",
            preset_after="manual",
            mode_after="cool",
            restore_ok=None,
            restore_ok_immediate=None,
        )
        for _ in range(30):
            if db._write_queue.empty():
                break
            await asyncio.sleep(0.05)

        # Simulated settled samples (as the callback would run).
        await db.update_ac_ramp_restore_settled(
            zone_id="clobber_zone",
            preset_settled="manual",  # cloud-poll clobber landed
            mode_settled="cool",
            restore_ok=False,
        )
        await db.update_ac_ramp_restore_settled(
            zone_id="clean_zone",
            preset_settled="sleep",
            mode_settled="cool",
            restore_ok=True,
        )
        await db.update_ac_ramp_restore_settled(
            zone_id="disarm_zone",
            preset_settled="manual",
            mode_settled="cool",
            restore_ok=None,
        )
        for _ in range(30):
            if db._write_queue.empty():
                break
            await asyncio.sleep(0.05)

        import aiosqlite
        async with aiosqlite.connect(db.db_file) as conn:
            cur = await conn.execute(
                "SELECT zone_id, preset_after, restore_ok, "
                "restore_ok_immediate "
                "FROM ac_ramp_events "
                "WHERE event_type = 'nudge_restored' "
                "ORDER BY zone_id"
            )
            rows = {r[0]: r for r in await cur.fetchall()}

        # Load-bearing invariant: pair distinguishes clobber from clean.
        assert rows["clobber_zone"][3] == 1 and rows["clobber_zone"][2] == 0, (
            "clobber signature = (immediate=1, settled=0); got "
            f"{rows['clobber_zone']}"
        )
        assert rows["clean_zone"][3] == 1 and rows["clean_zone"][2] == 1, (
            "clean = (1, 1)"
        )
        assert (
            rows["disarm_zone"][3] is None and rows["disarm_zone"][2] is None
        ), "self-disarm = (NULL, NULL) — never guessed"

        # Explicit discrimination check: the immediate column alone would
        # fail to distinguish clobber from clean (both =1).
        assert (
            rows["clobber_zone"][3] == rows["clean_zone"][3]
        ), "sanity: immediate values match — paired settled is what discriminates"
        # But settled column DOES distinguish them.
        assert (
            rows["clobber_zone"][2] != rows["clean_zone"][2]
        ), "settled column must discriminate clobber (0) from clean (1)"

        # And the settled UPDATE must have only touched restore_ok=NULL
        # rows — insert a second row for clobber_zone and confirm a
        # subsequent settled UPDATE cannot corrupt the first.
        await db.log_ac_ramp_event(
            zone_id="clobber_zone",
            event_type="nudge_restored",
            preset_after="sleep",
            mode_after="cool",
            restore_ok=None,
            restore_ok_immediate=True,
        )
        for _ in range(30):
            if db._write_queue.empty():
                break
            await asyncio.sleep(0.05)
        await db.update_ac_ramp_restore_settled(
            zone_id="clobber_zone",
            preset_settled="sleep",
            mode_settled="cool",
            restore_ok=True,
        )
        for _ in range(30):
            if db._write_queue.empty():
                break
            await asyncio.sleep(0.05)
        async with aiosqlite.connect(db.db_file) as conn:
            cur = await conn.execute(
                "SELECT restore_ok, restore_ok_immediate FROM ac_ramp_events "
                "WHERE zone_id='clobber_zone' AND event_type='nudge_restored' "
                "ORDER BY event_id"
            )
            two = await cur.fetchall()
        assert len(two) == 2
        assert two[0] == (0, 1), (
            "original clobber row must remain (settled=0, immediate=1) — "
            "a subsequent settled UPDATE must not overwrite an already-"
            "settled row"
        )
        assert two[1] == (1, 1), "second row settled cleanly"
    finally:
        if db._write_task and not db._write_task.done():
            db._write_task.cancel()


@_ha_only
@pytest.mark.asyncio
async def test_d1_settled_update_no_row_is_silent_noop(tmp_path):
    """If the row is gone (retention, kill, wrong zone), the settled
    UPDATE must silently no-op rather than raise or insert a phantom row.
    """
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    from runtime_harness import StubHass

    hass = StubHass(config_dir=str(tmp_path))
    db = UniversalRoomDatabase(hass)
    await db.start_write_worker()
    try:
        assert await db.init_db()
        # No row exists for this zone.
        await db.update_ac_ramp_restore_settled(
            zone_id="ghost",
            preset_settled="sleep",
            mode_settled="cool",
            restore_ok=True,
        )
        for _ in range(30):
            if db._write_queue.empty():
                break
            await asyncio.sleep(0.05)
        import aiosqlite
        async with aiosqlite.connect(db.db_file) as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM ac_ramp_events WHERE zone_id='ghost'"
            )
            (n,) = await cur.fetchone()
        assert n == 0, "settled UPDATE must not insert a phantom row"
    finally:
        if db._write_task and not db._write_task.done():
            db._write_task.cancel()
