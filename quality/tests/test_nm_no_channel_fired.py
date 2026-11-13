"""NM-NO-CHANNEL-FIRED-1 (2026-11-13) — alerts that reach nobody.

Audit: docs/planning/AUDIT_nm_no_channel_fired_2026_11_13.md

Live shape reproduced here: one digest-pref recipient, every channel gate
HIGH/CRITICAL, a MEDIUM alert -> the router returns an empty set, so before
this card no digest-queue row was written and the alert reached nobody.

Deliverables + load-bearing sites (each has a RED-on-neuter drill):
  (1) legacy no-route digest fallback row (async_notify per-person loop)
  (2) digest heartbeat says "N alerts had no route" (_fire_digest)
  (3) delivery_rate counts no_channel_fired as not delivered
  (4) zero-route trip-wire -> anomaly + HIGH NM alert

DB: production SQL (UniversalRoomDatabase methods, unbound) runs against the
real schema extracted from database.py by conftest_db.real_schema_db.
"""
from __future__ import annotations

import sys as _sys
from contextlib import asynccontextmanager
from datetime import datetime as _datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from test_notification_manager import _make_hass, _make_config  # noqa: F401
from conftest_db import real_schema_db  # noqa: F401


@pytest.fixture(autouse=True)
def _naive_nm_clock(monkeypatch):
    """Per-test, auto-restored pin of the dt_util NM + database read."""
    import test_notification_manager as _tnm
    from custom_components.universal_room_automation import database as _dbm
    targets = []
    for _m in (_sys.modules.get("homeassistant.util.dt"),
               _tnm.NotificationManager.__init__.__globals__.get("dt_util"),
               getattr(_dbm, "dt_util", None)):
        if _m is not None and all(_m is not _t for _t in targets):
            targets.append(_m)
    for _m in targets:
        monkeypatch.setattr(_m, "utcnow", _datetime.utcnow, raising=False)
        monkeypatch.setattr(_m, "now", _datetime.now, raising=False)
        monkeypatch.setattr(_m, "as_local", lambda dt: dt, raising=False)
    yield


from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_NM_PERSONS,
    CONF_NM_PERSON_ENTITY,
    CONF_NM_PERSON_PUSHOVER_KEY,
    CONF_NM_PERSON_COMPANION_SERVICE,
    CONF_NM_PERSON_WHATSAPP_PHONE,
    CONF_NM_PERSON_IMESSAGE_HANDLE,
    CONF_NM_PERSON_DELIVERY_PREF,
    CONF_NM_PERSON_DIGEST_CHANNELS,
    CONF_NM_PERSON_ROUTING_MATRIX,
    CONF_NM_PUSHOVER_ENABLED,
    CONF_NM_PUSHOVER_SEVERITY,
    CONF_NM_COMPANION_ENABLED,
    CONF_NM_COMPANION_SEVERITY,
    CONF_NM_WHATSAPP_ENABLED,
    CONF_NM_WHATSAPP_SEVERITY,
    CONF_NM_IMESSAGE_ENABLED,
    CONF_NM_IMESSAGE_SEVERITY,
    CONF_NM_TTS_ENABLED,
    CONF_NM_LIGHTS_ENABLED,
    CONF_NM_QUIET_USE_HOUSE_STATE,
    DOMAIN,
    NM_DELIVERY_DIGEST,
    NM_DELIVERY_IMMEDIATE,
)
import custom_components.universal_room_automation.domain_coordinators.notification_manager as _nm_mod  # noqa: E402
from custom_components.universal_room_automation.domain_coordinators.notification_manager import (  # noqa: E402
    NotificationManager,
)
from custom_components.universal_room_automation.domain_coordinators.base import Severity  # noqa: E402
from custom_components.universal_room_automation.database import (  # noqa: E402
    UniversalRoomDatabase,
)

PID = "person.oji"


# ---------------------------------------------------------------------------
# Real-schema DB: production DAO methods over the extracted schema
# ---------------------------------------------------------------------------


class _ACursor:
    def __init__(self, cur):
        self._cur = cur
        self.lastrowid = cur.lastrowid

    async def fetchall(self):
        return self._cur.fetchall()

    async def fetchone(self):
        return self._cur.fetchone()


class _AConn:
    def __init__(self, conn):
        self._conn = conn

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._conn.row_factory = value

    async def execute(self, sql, params=()):
        return _ACursor(self._conn.execute(sql, params))

    async def commit(self):
        self._conn.commit()


def _real_db(conn):
    db = object.__new__(UniversalRoomDatabase)

    @asynccontextmanager
    async def _ctx():
        yield _AConn(conn)

    db._db = _ctx
    db._db_read = _ctx
    db._db_stats = {"reads": 0}
    db.save_anomaly_event = AsyncMock(return_value=1)
    return db


# ---------------------------------------------------------------------------
# Live-shaped config
# ---------------------------------------------------------------------------


def _person(pref=NM_DELIVERY_DIGEST, matrix=None):
    p = {
        CONF_NM_PERSON_ENTITY: PID,
        CONF_NM_PERSON_PUSHOVER_KEY: "pk",
        CONF_NM_PERSON_COMPANION_SERVICE: "notify.mobile_app_oji",
        CONF_NM_PERSON_WHATSAPP_PHONE: "+15551234",
        CONF_NM_PERSON_IMESSAGE_HANDLE: "oji@icloud",
        CONF_NM_PERSON_DELIVERY_PREF: pref,
        CONF_NM_PERSON_DIGEST_CHANNELS: ["whatsapp", "imessage"],
    }
    if matrix is not None:
        p[CONF_NM_PERSON_ROUTING_MATRIX] = matrix
    return p


def _live_cfg(person, whatsapp_sev="CRITICAL"):
    """Live gates (audit §3): companion HIGH, the rest CRITICAL."""
    return _make_config(**{
        CONF_NM_PUSHOVER_ENABLED: True,
        CONF_NM_PUSHOVER_SEVERITY: "CRITICAL",
        CONF_NM_COMPANION_ENABLED: True,
        CONF_NM_COMPANION_SEVERITY: "HIGH",
        CONF_NM_WHATSAPP_ENABLED: True,
        CONF_NM_WHATSAPP_SEVERITY: whatsapp_sev,
        CONF_NM_IMESSAGE_ENABLED: True,
        CONF_NM_IMESSAGE_SEVERITY: "CRITICAL",
        CONF_NM_TTS_ENABLED: False,
        CONF_NM_LIGHTS_ENABLED: False,
        CONF_NM_QUIET_USE_HOUSE_STATE: True,
        CONF_NM_PERSONS: [person],
    })


def _build(conn, person, **kw):
    hass = _make_hass()
    cm = MagicMock()
    cm.house_state = "home_day"  # not quiet hours
    hass.data[DOMAIN]["coordinator_manager"] = cm
    db = _real_db(conn)
    hass.data[DOMAIN]["database"] = db
    nm = NotificationManager(hass, _live_cfg(person, **kw))
    nm._send_pushover = AsyncMock()
    nm._send_companion = AsyncMock()
    nm._send_whatsapp = AsyncMock(return_value=True)
    nm._send_imessage = AsyncMock()
    return nm, db


async def _medium(nm, n=0):
    await nm.async_notify(
        "energy", Severity.MEDIUM, f"Circuit anomaly {n}",
        f"Circuit {n} drew unusual power", hazard_type="circuit_anomaly",
        location=f"panel_{n}",
    )


def _audit_rows(conn):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM notification_log WHERE message='[audit]' ORDER BY id"
    ).fetchall()]


_ALL_FALSE_MEDIUM = {"MEDIUM": {
    "pushover": False, "companion": False, "whatsapp": False, "imessage": False,
}}


# ---------------------------------------------------------------------------
# (1) digest fallback row
# ---------------------------------------------------------------------------


class TestDigestFallbackRow:

    @pytest.mark.asyncio
    async def test_live_shape_medium_reaches_digest_queue(self, real_schema_db):
        """Digest pref + all gates >= HIGH + MEDIUM alert -> exactly one
        pending digest row (channel 'digest'), audit row = digest_queued.
        Drill: neuter the fallback log_notification call -> RED."""
        nm, db = _build(real_schema_db, _person())
        await _medium(nm)
        pending = await db.get_pending_digest(PID)
        assert len(pending) == 1
        assert pending[0]["channel"] == "digest"
        assert pending[0]["severity"] == "MEDIUM"
        assert pending[0]["title"] == "Circuit anomaly 0"
        audit = _audit_rows(real_schema_db)
        assert [a["bucket_outcome"] for a in audit] == ["digest_queued"]
        assert nm._send_whatsapp.await_count == 0
        assert nm._send_companion.await_count == 0

    @pytest.mark.asyncio
    async def test_fallback_row_flushes_into_digest_body(self, real_schema_db):
        """End to end: the queued row is rendered by the real digest flush
        and then swept to delivered=2."""
        nm, db = _build(real_schema_db, _person())
        await _medium(nm)
        nm._build_optimizer_digest_section = MagicMock(return_value="")
        nm._deliver_digest = AsyncMock(return_value=True)
        await nm._fire_digest(PID, _person())
        body = nm._deliver_digest.await_args.args[2]
        assert "Circuit anomaly 0" in body
        assert "All quiet" not in body
        assert await db.get_pending_digest(PID) == []

    @pytest.mark.asyncio
    async def test_router_allowed_digest_row_not_duplicated(self, real_schema_db):
        """Router allows whatsapp at MEDIUM -> the normal per-channel row is
        written and the fallback is NOT added (conjunct `not _digest_queued`)."""
        nm, db = _build(real_schema_db, _person(), whatsapp_sev="MEDIUM")
        await _medium(nm)
        pending = await db.get_pending_digest(PID)
        assert [p["channel"] for p in pending] == ["whatsapp"]
        assert [a["bucket_outcome"] for a in _audit_rows(real_schema_db)] == [
            "digest_queued"
        ]

    @pytest.mark.asyncio
    async def test_immediate_pref_gets_no_fallback_row(self, real_schema_db):
        """Immediate pref + empty router -> no digest row (conjunct
        `effective_pref == DIGEST`); still an honest no_channel_fired."""
        nm, db = _build(real_schema_db, _person(pref=NM_DELIVERY_IMMEDIATE))
        await _medium(nm)
        assert await db.get_pending_digest(PID) == []
        assert [a["bucket_outcome"] for a in _audit_rows(real_schema_db)] == [
            "no_channel_fired"
        ]

    @pytest.mark.asyncio
    async def test_explicit_matrix_silence_is_respected(self, real_schema_db):
        """Explicit matrix row with every channel off at MEDIUM is operator
        intent -> no fallback (conjunct `_matrix_branch == legacy_fallback`)."""
        nm, db = _build(real_schema_db, _person(matrix=_ALL_FALSE_MEDIUM))
        await _medium(nm)
        assert await db.get_pending_digest(PID) == []
        assert [a["bucket_outcome"] for a in _audit_rows(real_schema_db)] == [
            "no_channel_fired"
        ]

    @pytest.mark.asyncio
    async def test_active_mute_is_respected(self, real_schema_db):
        """Every digest channel muted -> no fallback row (mute conjunct)."""
        nm, db = _build(real_schema_db, _person())
        for ch in ("whatsapp", "imessage"):
            nm._person_channel_mutes[(PID, ch)] = (
                _datetime.utcnow() + timedelta(minutes=30)
            )
        await _medium(nm)
        assert await db.get_pending_digest(PID) == []

    @pytest.mark.asyncio
    async def test_non_digest_channel_mute_does_not_block_fallback(
        self, real_schema_db,
    ):
        """Fix-up A2: pushover (not a digest channel) muted -> the fallback
        row is still queued. Drill: mute set = NM_CHANNELS_KNOWN -> RED."""
        nm, db = _build(real_schema_db, _person())
        nm._person_channel_mutes[(PID, "pushover")] = (
            _datetime.utcnow() + timedelta(minutes=30)
        )
        await _medium(nm)
        pending = await db.get_pending_digest(PID)
        assert [p["channel"] for p in pending] == ["digest"]

    @pytest.mark.asyncio
    async def test_one_of_two_digest_channels_muted_still_queues(
        self, real_schema_db,
    ):
        """Fix-up A2: only whatsapp muted, imessage still carries the digest
        -> fallback queued. Drill: all() -> any() -> RED."""
        nm, db = _build(real_schema_db, _person())
        nm._person_channel_mutes[(PID, "whatsapp")] = (
            _datetime.utcnow() + timedelta(minutes=30)
        )
        await _medium(nm)
        pending = await db.get_pending_digest(PID)
        assert [p["channel"] for p in pending] == ["digest"]


# ---------------------------------------------------------------------------
# (2) heartbeat honesty
# ---------------------------------------------------------------------------


class TestHeartbeatNoRoute:

    def _arm(self, nm):
        nm._build_optimizer_digest_section = MagicMock(return_value="")
        nm._deliver_digest = AsyncMock(return_value=True)

    @pytest.mark.asyncio
    async def test_heartbeat_reports_no_route_instead_of_all_quiet(
        self, real_schema_db,
    ):
        person = _person(matrix=_ALL_FALSE_MEDIUM)
        nm, db = _build(real_schema_db, person)
        await _medium(nm, 1)
        await _medium(nm, 2)
        self._arm(nm)
        await nm._fire_digest(PID, person)
        body = nm._deliver_digest.await_args.args[2]
        assert "2 alerts had no route" in body
        assert "All quiet" not in body

    @pytest.mark.asyncio
    async def test_heartbeat_all_quiet_without_no_route_rows(
        self, real_schema_db,
    ):
        person = _person()
        nm, db = _build(real_schema_db, person)
        self._arm(nm)
        await nm._fire_digest(PID, person)
        body = nm._deliver_digest.await_args.args[2]
        assert "All quiet" in body
        assert "no route" not in body

    @pytest.mark.asyncio
    async def test_second_flush_counts_only_since_last_flush(
        self, real_schema_db,
    ):
        """The count window starts at the last successful flush (drill:
        neuter the `_last_digest_flush` stamp -> second body repeats 1)."""
        person = _person(matrix=_ALL_FALSE_MEDIUM)
        nm, db = _build(real_schema_db, person)
        await _medium(nm, 1)
        self._arm(nm)
        await nm._fire_digest(PID, person)
        assert "1 alert had no route" in nm._deliver_digest.await_args.args[2]
        await nm._fire_digest(PID, person)
        assert "All quiet" in nm._deliver_digest.await_args.args[2]

    @pytest.mark.asyncio
    async def test_no_route_during_delivery_lands_in_next_flush(
        self, real_schema_db,
    ):
        """Fix-up A4/B1: a no-route row written while _deliver_digest awaits
        is reported by the NEXT flush (window end captured before the count
        query). Drill: stamp utcnow() after delivery -> RED."""
        person = _person(matrix=_ALL_FALSE_MEDIUM)
        nm, db = _build(real_schema_db, person)
        nm._build_optimizer_digest_section = MagicMock(return_value="")
        bodies = []

        async def _deliver(pid, cfg, body):
            bodies.append(body)
            if len(bodies) == 1:
                await _medium(nm, 9)
            return True

        nm._deliver_digest = _deliver
        await nm._fire_digest(PID, person)
        assert "All quiet" in bodies[0]
        await nm._fire_digest(PID, person)
        assert "1 alert had no route" in bodies[1]

    @pytest.mark.asyncio
    async def test_no_route_line_appended_to_real_digest(self, real_schema_db):
        """Pending items present AND a no-route row -> body carries both."""
        person = _person(matrix={"MEDIUM": {"whatsapp": True}, "LOW": {
            "pushover": False, "companion": False,
            "whatsapp": False, "imessage": False,
        }})
        nm, db = _build(real_schema_db, person)
        await _medium(nm, 1)  # queued via matrix
        await nm.async_notify("presence", Severity.LOW, "Presence blip", "x")
        self._arm(nm)
        await nm._fire_digest(PID, person)
        body = nm._deliver_digest.await_args.args[2]
        assert "Circuit anomaly 1" in body
        assert "1 alert had no route" in body


# ---------------------------------------------------------------------------
# (3) delivery_rate
# ---------------------------------------------------------------------------


class TestDeliveryRateCountsNoRoute:

    @pytest.mark.asyncio
    async def test_no_route_drives_delivery_rate_to_zero(self, real_schema_db):
        nm, db = _build(real_schema_db, _person(matrix=_ALL_FALSE_MEDIUM))
        assert nm.delivery_rate == 100.0
        await _medium(nm)
        assert nm.diagnostics_summary["no_route_count"] == 1
        assert nm.delivery_rate == 0.0

    @pytest.mark.asyncio
    async def test_digest_queued_is_not_counted_as_no_route(self, real_schema_db):
        nm, db = _build(real_schema_db, _person())
        await _medium(nm)
        assert nm.diagnostics_summary["no_route_count"] == 0
        assert nm.delivery_rate == 100.0

    @pytest.mark.asyncio
    async def test_immediate_pref_policy_drop_not_counted(
        self, real_schema_db, monkeypatch,
    ):
        """Fix-up A1: immediate pref, gates above MEDIUM -> the router allows
        nothing: the recipient's own policy. Audit row is still
        no_channel_fired, but delivery_rate / trip-wire are not fed.
        Drill: routing_hole=True at the call site -> RED."""
        monkeypatch.setattr(_nm_mod, "NM_NO_ROUTE_TRIPWIRE_COUNT", 1)
        nm, db = _build(real_schema_db, _person(pref=NM_DELIVERY_IMMEDIATE))
        await _medium(nm)
        assert [a["bucket_outcome"] for a in _audit_rows(real_schema_db)] == [
            "no_channel_fired"
        ]
        assert nm.diagnostics_summary["no_route_count"] == 0
        assert nm.delivery_rate == 100.0
        assert len(nm._no_route_times) == 0
        assert _tripwire_calls(nm) == []

    @pytest.mark.asyncio
    async def test_immediate_pref_router_allowed_but_unsent_is_a_hole(
        self, real_schema_db,
    ):
        """Router allows whatsapp at MEDIUM but the person has no phone ->
        nothing fires: a real routing hole, counted (discriminates the
        `not _router_allowed` conjunct)."""
        person = _person(pref=NM_DELIVERY_IMMEDIATE)
        person[CONF_NM_PERSON_WHATSAPP_PHONE] = ""
        nm, db = _build(real_schema_db, person, whatsapp_sev="MEDIUM")
        await _medium(nm)
        assert [a["bucket_outcome"] for a in _audit_rows(real_schema_db)] == [
            "no_channel_fired"
        ]
        assert nm.diagnostics_summary["no_route_count"] == 1
        assert len(nm._no_route_times) == 1

    @pytest.mark.asyncio
    async def test_low_no_route_counts_rate_but_not_tripwire(
        self, real_schema_db,
    ):
        """Fix-up A1: trip-wire scope is MEDIUM+. A LOW hole still lowers
        delivery_rate but does not enter the trip-wire window."""
        person = _person(matrix={"LOW": {
            "pushover": False, "companion": False,
            "whatsapp": False, "imessage": False,
        }})
        nm, db = _build(real_schema_db, person)
        await nm.async_notify("presence", Severity.LOW, "Presence blip", "x")
        assert nm.diagnostics_summary["no_route_count"] == 1
        assert len(nm._no_route_times) == 0

    def test_delivery_rate_mixed_denominator(self):
        """3 successes of 4 attempts + 4 no-route -> 3/8 = 37.5."""
        hass = _make_hass()
        nm = NotificationManager(hass, _live_cfg(_person()))
        nm._send_attempts = 4
        nm._send_successes = 3
        nm._no_route_count = 4
        assert nm.delivery_rate == 37.5


# ---------------------------------------------------------------------------
# (4) zero-route trip-wire
# ---------------------------------------------------------------------------


def _tripwire_calls(nm):
    return [c for c in nm._send_companion.await_args_list
            if c.args and c.args[0] == "URA alerts reaching nobody"]


class TestNoRouteTripwire:

    def test_default_knobs_pinned(self):
        assert _nm_mod.NM_NO_ROUTE_TRIPWIRE_COUNT == 20
        assert _nm_mod.NM_NO_ROUTE_TRIPWIRE_WINDOW_S == 86400

    @pytest.mark.asyncio
    async def test_fires_at_threshold_not_before_and_once(
        self, real_schema_db, monkeypatch,
    ):
        monkeypatch.setattr(_nm_mod, "NM_NO_ROUTE_TRIPWIRE_COUNT", 3)
        nm, db = _build(real_schema_db, _person(matrix=_ALL_FALSE_MEDIUM))
        await _medium(nm, 1)
        await _medium(nm, 2)
        assert _tripwire_calls(nm) == []
        assert db.save_anomaly_event.await_count == 0
        await _medium(nm, 3)
        # HIGH alert went out on companion (gate HIGH) - a channel that fires.
        assert len(_tripwire_calls(nm)) == 1
        events = [c.args[0] for c in db.save_anomaly_event.await_args_list
                  if c.args[0].type == "nm.no_route_tripwire"]
        assert len(events) == 1
        assert events[0].observed_value == 3.0
        # Cooldown: more no-routes inside the window do not re-fire.
        await _medium(nm, 4)
        await _medium(nm, 5)
        assert len(_tripwire_calls(nm)) == 1

    @pytest.mark.asyncio
    async def test_old_no_routes_age_out_of_window(
        self, real_schema_db, monkeypatch,
    ):
        monkeypatch.setattr(_nm_mod, "NM_NO_ROUTE_TRIPWIRE_COUNT", 3)
        nm, db = _build(real_schema_db, _person(matrix=_ALL_FALSE_MEDIUM))
        await _medium(nm, 1)
        await _medium(nm, 2)
        # Age both entries past the 24 h window (86400 s + 1 s).
        old = _datetime.utcnow() - timedelta(seconds=86401)
        nm._no_route_times = type(nm._no_route_times)([old, old])
        await _medium(nm, 3)
        assert _tripwire_calls(nm) == []

    @pytest.mark.asyncio
    async def test_kill_switch_zero_disables(self, real_schema_db, monkeypatch):
        monkeypatch.setattr(_nm_mod, "NM_NO_ROUTE_TRIPWIRE_COUNT", 0)
        nm, db = _build(real_schema_db, _person(matrix=_ALL_FALSE_MEDIUM))
        for i in range(3):
            await _medium(nm, i)
        assert _tripwire_calls(nm) == []

    @pytest.mark.asyncio
    async def test_live_shape_no_longer_trips(self, real_schema_db, monkeypatch):
        """After fix (1) the live config produces digest_queued, not
        no_channel_fired, so the trip-wire stays quiet."""
        monkeypatch.setattr(_nm_mod, "NM_NO_ROUTE_TRIPWIRE_COUNT", 3)
        nm, db = _build(real_schema_db, _person())
        for i in range(5):
            await _medium(nm, i)
        assert _tripwire_calls(nm) == []


# ---------------------------------------------------------------------------
# Fix-up A5: schema extractor must not bleed a neighbour table's tuple list
# ---------------------------------------------------------------------------


class TestSchemaExtractorNoBleed:

    def _cols(self, table):
        import pathlib
        from conftest_db import _extract_alter_table_statements
        src = (pathlib.Path(__file__).resolve().parents[2]
               / "custom_components/universal_room_automation/database.py"
               ).read_text()
        return {s.split(" ADD COLUMN ")[1].split()[0]
                for s in _extract_alter_table_statements(src, table)}

    def test_midnight_snapshot_gets_only_its_own_columns(self):
        assert self._cols("energy_midnight_snapshot") == {
            "counter_import_last", "counter_export_last", "billing_source_today",
        }

    def test_ac_reset_state_does_not_absorb_ac_ramp_events_columns(self):
        assert "settled_reason" not in self._cols("ac_reset_state")

    def test_notification_log_split_alters_extracted(self):
        assert {"dry_run", "recipient_id", "route_reason", "dnd_bypass_applied",
                "bucket_outcome", "matrix_branch"} <= self._cols("notification_log")
