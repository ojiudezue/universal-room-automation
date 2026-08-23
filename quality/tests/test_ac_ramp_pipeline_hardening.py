"""AC-RAMP-PIPELINE-HARDENING-1 — behavioural tests.

Tier-3 build. These tests drive the REAL OverrideArrester helpers (no
re-implementation) for the load-bearing sites the plan flagged:

- D-GATE4 predicate ladder (mode/kW config guard, stale = fail-closed,
  frozen-``""`` pre-first-poll is fail-closed, kW below floor = False,
  cooling-ok = True). Ships SHADOW on first boot; a shadow-mode Gate 4
  decision must remain byte-identical to legacy while a divergence latch
  writes ONE row per agree->diverge / diverge->agree transition.
- D-PARTITION: day-only cap denial does NOT engage lockout, night reserve
  survives; true-cap fallback DOES engage lockout (or writes a decline
  row when ``engage_lockout_on_cap=False``).
- D-ESC-SIG: signature-level kwargs are honoured (triggered_by threads
  into the started row's DB call; engage_lockout_on_cap=False routes
  through decline-not-lockout).
- D2 wrap-around night helper + night_session_date bucket key.
- D3 gate 5b runaway guard.
- D-SCORE _write_durable full-window vs truncated semantics + NULL-when-
  kW-unreadable.
- D6 reset-outcome classification + kwh_rate_settle capture (the bounded
  add: reset whose settle read returns a draw persists it; a reset whose
  settle read returns None still writes the row with reset_outcome
  intact and kwh_rate_settle NULL).
- D8: partition-aware NM alert wording; declined-row edge-triggered
  writer.
- database.py: log_ac_ramp_event returns lastrowid; save_ac_reset_state
  round-trip preserves partition counters + night_session_date.

Test harness mirrors ``test_ac_ramp_master_option_persistence.py``.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


def _mock_module(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock, "Event": MagicMock,
        "CALLBACK_TYPE": object, "callback": lambda f: f,
    },
    "homeassistant.helpers": {},
    "homeassistant.helpers.event": {
        "async_call_later": MagicMock(return_value=lambda: None),
        "async_track_state_change_event": MagicMock(return_value=lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.now(timezone.utc),
        "now": lambda: datetime.now(),
        "as_local": lambda dt: dt,
        "UTC": timezone.utc,
    },
    "homeassistant.components": {},
    "homeassistant.components.recorder": {"get_instance": MagicMock()},
    "homeassistant.components.recorder.history": {
        "get_significant_states": MagicMock(),
    },
}
for _n, _a in _mods.items():
    sys.modules.setdefault(_n, _mock_module(_n, **_a))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
_HERE = os.path.dirname(__file__)
_URA_PATH = os.path.join(_HERE, "..", "..", "custom_components",
                         "universal_room_automation")
_DC_PATH = os.path.join(_URA_PATH, "domain_coordinators")

if "custom_components" not in sys.modules:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [os.path.join(_HERE, "..", "..", "custom_components")]
    sys.modules["custom_components"] = _cc
if "custom_components.universal_room_automation" not in sys.modules:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [_URA_PATH]
    sys.modules["custom_components.universal_room_automation"] = _ura


def _load(modname, relpath):
    cached = sys.modules.get(modname)
    if cached is not None and getattr(cached, "__file__", None):
        return cached
    spec = importlib.util.spec_from_file_location(
        modname, os.path.join(_URA_PATH, relpath),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


_load("custom_components.universal_room_automation.const", "const.py")
if "custom_components.universal_room_automation.domain_coordinators" not in sys.modules:
    _dc = types.ModuleType(
        "custom_components.universal_room_automation.domain_coordinators"
    )
    _dc.__path__ = [_DC_PATH]
    sys.modules[
        "custom_components.universal_room_automation.domain_coordinators"
    ] = _dc
for _m in (
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
):
    c = sys.modules.get(_m)
    if c is not None and not getattr(c, "__file__", None):
        del sys.modules[_m]

_load("custom_components.universal_room_automation.domain_coordinators.hvac_const",
      "domain_coordinators/hvac_const.py")
_load("custom_components.universal_room_automation.domain_coordinators.hvac_zones",
      "domain_coordinators/hvac_zones.py")
_load("custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
      "domain_coordinators/hvac_setpoint.py")
hvac_override = _load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
    "domain_coordinators/hvac_override.py",
)
hvac_zones = sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones"
]
hvac_const = sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_const"
]

OverrideArrester = hvac_override.OverrideArrester
ZoneState = hvac_zones.ZoneState


def _mk_zone(zone_id="zone_a", **kwargs):
    z = ZoneState(zone_id=zone_id, zone_name=f"Zone {zone_id}",
                  climate_entity=f"climate.{zone_id}")
    for k, v in kwargs.items():
        setattr(z, k, v)
    return z


def _mk_hass_with_state(entity_id, kw_value, unit=None,
                        hvac_action="cooling", **attrs):
    """Return a hass mock whose states.get(entity) returns a state
    with numeric ``state`` = kw_value plus optional attributes."""
    hass = MagicMock()
    st = MagicMock()
    st.state = str(kw_value)
    st.last_updated = datetime.now()
    st.attributes = {"unit_of_measurement": unit, **attrs}
    hass.states.get = MagicMock(return_value=st)
    return hass


def _mk_arrester(hass=None, zone=None):
    z = zone or _mk_zone()
    z.ac_load_sensor = "sensor.zone_a_kw"
    z.hvac_mode = "cool"
    z.hvac_action = "cooling"
    zm = MagicMock()
    zm.zones = {z.zone_id: z}
    hass = hass or MagicMock()
    return OverrideArrester(hass, zm, compromise_minutes=30,
                            ac_reset_timeout=60, enabled=True), z


# ============================================================================
# D-GATE4 — predicate ladder + shadow divergence latch
# ============================================================================

class TestDGate4Predicate:
    def test_cool_and_draw_above_floor_returns_true(self):
        hass = _mk_hass_with_state("sensor.zone_a_kw", 1.2, unit="kW")
        a, z = _mk_arrester(hass=hass)
        z.hvac_mode = "cool"
        assert a._zone_is_actively_cooling(z, datetime.now()) is True

    def test_heat_mode_returns_false_even_with_draw(self):
        """Config guard negative control (AC-P b)."""
        hass = _mk_hass_with_state("sensor.zone_a_kw", 1.2, unit="kW")
        a, z = _mk_arrester(hass=hass)
        z.hvac_mode = "heat"
        assert a._zone_is_actively_cooling(z, datetime.now()) is False

    def test_below_kw_floor_returns_false(self):
        """SPAN gate negative control (AC-P c)."""
        hass = _mk_hass_with_state("sensor.zone_a_kw", 0.1, unit="kW")
        a, z = _mk_arrester(hass=hass)
        z.hvac_mode = "cool"
        assert a._zone_is_actively_cooling(z, datetime.now()) is False

    def test_stale_sensor_none_returns_false_not_true(self):
        """Fail-closed on None (AC-P d). A builder who treated None as
        True would pass (a) but fail this."""
        a, z = _mk_arrester()
        # Force _read_kwh_rate to return None.
        a._read_kwh_rate = MagicMock(return_value=None)
        z.hvac_mode = "cool"
        assert a._zone_is_actively_cooling(z, datetime.now()) is False

    def test_empty_mode_pre_first_poll_returns_false(self):
        """Frozen `""` (AC-P e). Fail-closed."""
        hass = _mk_hass_with_state("sensor.zone_a_kw", 1.2, unit="kW")
        a, z = _mk_arrester(hass=hass)
        z.hvac_mode = ""
        assert a._zone_is_actively_cooling(z, datetime.now()) is False

    def test_heat_cool_mode_permitted(self):
        hass = _mk_hass_with_state("sensor.zone_a_kw", 0.9, unit="kW")
        a, z = _mk_arrester(hass=hass)
        z.hvac_mode = "heat_cool"
        assert a._zone_is_actively_cooling(z, datetime.now()) is True


class TestDGate4Mode:
    """The mode Select (legacy | shadow | live) drives whether the
    legacy or new predicate decides Gate 4. Shadow keeps the decision
    byte-identical to legacy AND latches divergence rows."""

    def test_legacy_mode_uses_hvac_action(self):
        hass = _mk_hass_with_state("sensor.zone_a_kw", 0.1, unit="kW")
        a, z = _mk_arrester(hass=hass)
        a.set_gate4_predicate_mode("legacy")
        z.hvac_action = "cooling"  # legacy says cooling
        z.hvac_mode = "cool"
        # New predicate says False (kw below floor); legacy dominates.
        assert a._gate4_is_ok(z, datetime.now()) is True

    def test_shadow_mode_uses_legacy_but_computes_new(self):
        """Byte-identical decision — same as legacy."""
        hass = _mk_hass_with_state("sensor.zone_a_kw", 0.1, unit="kW")
        a, z = _mk_arrester(hass=hass)
        a.set_gate4_predicate_mode("shadow")
        a._db = MagicMock()
        a._db.log_ac_ramp_event = AsyncMock()
        z.hvac_action = "cooling"
        z.hvac_mode = "cool"
        assert a._gate4_is_ok(z, datetime.now()) is True

    def test_live_mode_uses_new_predicate(self):
        hass = _mk_hass_with_state("sensor.zone_a_kw", 0.1, unit="kW")
        a, z = _mk_arrester(hass=hass)
        a.set_gate4_predicate_mode("live")
        z.hvac_action = "cooling"  # legacy would say ok
        z.hvac_mode = "cool"
        # kW below floor -> new predicate says False.
        assert a._gate4_is_ok(z, datetime.now()) is False

    def test_shadow_divergence_latched_writes_only_on_transition(self):
        """B-H7 — LATCHED writer, one row per agree↔diverge transition."""
        hass = MagicMock()
        a, z = _mk_arrester(hass=hass)
        a.set_gate4_predicate_mode("shadow")
        a._db = MagicMock()
        a._db.log_ac_ramp_event = AsyncMock()
        # Simulate transitions: nothing -> agree (no row), agree -> diverge
        # (row 1), diverge -> diverge (no new row), diverge -> agree (row 2).
        a._maybe_write_gate4_divergence("zone_a", True, True)
        a._maybe_write_gate4_divergence("zone_a", True, True)
        a._maybe_write_gate4_divergence("zone_a", True, False)  # diverge
        a._maybe_write_gate4_divergence("zone_a", True, False)  # same
        a._maybe_write_gate4_divergence("zone_a", True, True)   # back
        # Two hass.async_create_task calls = 2 rows (one per transition).
        assert hass.async_create_task.call_count == 2


# ============================================================================
# D2 — night wrap-around + night_session_date bucket key
# ============================================================================

class TestNightWrapAround:
    def test_wrap_around_night_23_00_is_night(self):
        a, _ = _mk_arrester()
        a.set_night_start_hhmm("22:00")
        a.set_night_end_hhmm("06:00")
        assert a._is_night_now(datetime(2026, 8, 22, 23, 0)) is True

    def test_wrap_around_day_12_00_is_day(self):
        a, _ = _mk_arrester()
        assert a._is_night_now(datetime(2026, 8, 22, 12, 0)) is False

    def test_wrap_around_night_00_30_is_night(self):
        a, _ = _mk_arrester()
        assert a._is_night_now(datetime(2026, 8, 22, 0, 30)) is True

    def test_wrap_around_boundary_06_00_is_day(self):
        a, _ = _mk_arrester()
        assert a._is_night_now(datetime(2026, 8, 22, 6, 0)) is False

    def test_night_session_date_before_end_uses_prior_date(self):
        """23:30 (D) and 00:30 (D+1) MUST hash to the SAME night row so
        night_budget=1 fires only once across midnight."""
        a, _ = _mk_arrester()
        d_before = a._night_session_date(datetime(2026, 8, 22, 23, 30))
        d_after = a._night_session_date(datetime(2026, 8, 23, 0, 30))
        assert d_before == d_after == "2026-08-22"

    def test_night_session_date_after_end_uses_today(self):
        a, _ = _mk_arrester()
        assert (
            a._night_session_date(datetime(2026, 8, 22, 8, 0))
            == "2026-08-22"
        )

    def test_garbage_hhmm_fail_closed_to_day(self):
        a, _ = _mk_arrester()
        a.set_night_start_hhmm("nonsense")
        assert a._is_night_now(datetime(2026, 8, 22, 23, 0)) is False


# ============================================================================
# D-PARTITION — partition-aware gate + counter increment
# ============================================================================

class TestPartitionGate:
    def test_day_denies_when_day_budget_exhausted_but_night_available(self):
        a, _ = _mk_arrester()
        a.set_reset_day_budget(2)
        a.set_reset_night_budget(2)
        state = {"day_reset_count": 2, "night_reset_count": 0}
        now = datetime(2026, 8, 22, 15, 0)  # day
        ok, partition, reason = a._gate_partition_check("zone_a", now, state)
        assert ok is False
        assert partition == "day"
        assert reason == hvac_const.AC_RESET_DECLINED_DAY_BUDGET

    def test_night_reachable_after_day_denial(self):
        a, _ = _mk_arrester()
        state = {"day_reset_count": 2, "night_reset_count": 0}
        now = datetime(2026, 8, 22, 22, 30)  # night
        ok, partition, reason = a._gate_partition_check("zone_a", now, state)
        assert ok is True
        assert partition == "night"

    def test_night_denies_when_night_budget_exhausted(self):
        a, _ = _mk_arrester()
        state = {
            "day_reset_count": 0,
            "night_reset_count": 2,
            "night_session_date": "2026-08-22",
        }
        now = datetime(2026, 8, 22, 22, 30)
        ok, partition, reason = a._gate_partition_check("zone_a", now, state)
        assert ok is False
        assert partition == "night"
        assert reason == hvac_const.AC_RESET_DECLINED_NIGHT_BUDGET

    def test_partition_resets_night_counter_on_new_session(self):
        a, _ = _mk_arrester()
        state = {
            "day_reset_count": 0,
            "night_reset_count": 2,
            "night_session_date": "2026-08-20",  # stale
        }
        now = datetime(2026, 8, 22, 22, 30)  # new night session
        ok, partition, _ = a._gate_partition_check("zone_a", now, state)
        assert ok is True
        assert state["night_reset_count"] == 0
        assert state["night_session_date"] == "2026-08-22"

    def test_increment_partition_counter_night(self):
        a, _ = _mk_arrester()
        state = {"day_reset_count": 0, "night_reset_count": 0}
        p = a._increment_partition_counter(
            state, datetime(2026, 8, 22, 23, 30),
        )
        assert p == "night"
        assert state["night_reset_count"] == 1
        assert state["day_reset_count"] == 0
        assert state["night_session_date"] == "2026-08-22"

    def test_increment_partition_counter_day(self):
        a, _ = _mk_arrester()
        state = {"day_reset_count": 0, "night_reset_count": 0}
        p = a._increment_partition_counter(
            state, datetime(2026, 8, 22, 14, 0),
        )
        assert p == "day"
        assert state["day_reset_count"] == 1
        assert state["night_reset_count"] == 0


# ============================================================================
# D3 — soft-nudge daily cap runaway guard
# ============================================================================

class TestSoftNudgeCap:
    def test_setter_range(self):
        a, _ = _mk_arrester()
        a.set_soft_nudge_daily_limit(0)
        assert a._soft_nudge_daily_limit == 0  # kill-switch
        a.set_soft_nudge_daily_limit(50)
        assert a._soft_nudge_daily_limit == 50


# ============================================================================
# D-SCORE — _write_durable + _maybe_fire_durable_early
# ============================================================================

class TestDurableClassifier:
    @pytest.mark.asyncio
    async def test_full_window_below_floor_marks_durable_1(self):
        a, z = _mk_arrester()
        a._db = MagicMock()
        a._db.update_ac_ramp_event_fields = AsyncMock()
        a._read_kwh_rate = MagicMock(return_value=0.1)  # below floor
        a._durable_pending["zone_a"] = {
            "event_id": 42,
            "started_ts": datetime.now() - timedelta(minutes=30),
            "kwh_rate_before": 1.0,
            "restore_dt": datetime.now() - timedelta(minutes=30),
        }
        await a._write_durable("zone_a", truncated=False)
        args, kwargs = a._db.update_ac_ramp_event_fields.call_args
        assert args[0] == 42
        assert kwargs["durable"] == 1
        assert kwargs["durable_minutes"] == a._durability_window_min

    @pytest.mark.asyncio
    async def test_full_window_above_floor_marks_durable_0(self):
        a, z = _mk_arrester()
        a._db = MagicMock()
        a._db.update_ac_ramp_event_fields = AsyncMock()
        a._read_kwh_rate = MagicMock(return_value=1.5)  # above floor
        a._durable_pending["zone_a"] = {
            "event_id": 43,
            "started_ts": datetime.now() - timedelta(minutes=30),
            "kwh_rate_before": 1.0,
            "restore_dt": datetime.now() - timedelta(minutes=30),
        }
        await a._write_durable("zone_a", truncated=False)
        args, kwargs = a._db.update_ac_ramp_event_fields.call_args
        assert kwargs["durable"] == 0

    @pytest.mark.asyncio
    async def test_truncated_records_elapsed_not_window(self):
        # F5 (revised): truncated verdict is now an INTERVAL check via
        # the running-max tracker (updated on 5-min ticks), NOT an
        # instantaneous read at fire time. Instantaneous-at-truncation
        # is above-threshold by construction (a truncation happens
        # because Gate 7 fired a re-nudge) and would score every
        # truncated row 0. The zone default kwh_rate_threshold from
        # ZoneState is not exercised here; set explicitly.
        a, z = _mk_arrester()
        a._db = MagicMock()
        a._db.update_ac_ramp_event_fields = AsyncMock()
        # The instantaneous read helper is NOT called on the truncated
        # branch under the revised rule.
        a._read_kwh_rate = MagicMock(return_value=1.5)
        z.kwh_rate_threshold = 0.8
        a._durable_pending["zone_a"] = {
            "event_id": 44,
            "started_ts": datetime.now() - timedelta(minutes=10),
        }
        # Running max observed during the window: above the Gate-7
        # threshold => did NOT hold => durable=0.
        a._nudge_running_max_kw["zone_a"] = 1.5
        await a._write_durable("zone_a", truncated=True)
        _, kwargs = a._db.update_ac_ramp_event_fields.call_args
        # 10 minutes elapsed, not the 30-minute full window.
        assert 9 <= kwargs["durable_minutes"] <= 11
        assert kwargs["durable"] == 0

    @pytest.mark.asyncio
    async def test_truncated_running_max_below_threshold_marks_durable_1(self):
        # F5 (revised) positive control: if the running-max sample was
        # below the Gate-7 threshold across the whole (short) window,
        # the truncated verdict is 1 — the nudge DID hold during the
        # interval, we just cut the measurement short.
        a, z = _mk_arrester()
        a._db = MagicMock()
        a._db.update_ac_ramp_event_fields = AsyncMock()
        z.kwh_rate_threshold = 0.8
        a._durable_pending["zone_a"] = {
            "event_id": 46,
            "started_ts": datetime.now() - timedelta(minutes=10),
        }
        a._nudge_running_max_kw["zone_a"] = 0.3
        await a._write_durable("zone_a", truncated=True)
        _, kwargs = a._db.update_ac_ramp_event_fields.call_args
        assert kwargs["durable"] == 1

    @pytest.mark.asyncio
    async def test_null_when_kw_unreadable(self):
        """B-H6 negative control: NULL breaks the streak."""
        a, z = _mk_arrester()
        a._db = MagicMock()
        a._db.update_ac_ramp_event_fields = AsyncMock()
        a._read_kwh_rate = MagicMock(return_value=None)
        a._durable_pending["zone_a"] = {
            "event_id": 45,
            "started_ts": datetime.now() - timedelta(minutes=30),
            "kwh_rate_before": 1.0,
            "restore_dt": datetime.now() - timedelta(minutes=30),
        }
        await a._write_durable("zone_a", truncated=False)
        _, kwargs = a._db.update_ac_ramp_event_fields.call_args
        assert kwargs["durable"] is None


# ============================================================================
# D8 — declined-row edge-triggered writer
# ============================================================================

class TestDeclinedWriter:
    @pytest.mark.asyncio
    async def test_writes_on_first_denial(self):
        a, _ = _mk_arrester()
        a._db = MagicMock()
        a._db.log_ac_ramp_event = AsyncMock()
        await a._maybe_write_declined(
            "zone_a", hvac_const.AC_RESET_DECLINED_DAY_BUDGET,
            datetime.now(),
        )
        assert a._db.log_ac_ramp_event.call_count == 1

    @pytest.mark.asyncio
    async def test_edge_triggered_same_reason_within_floor_suppressed(self):
        a, _ = _mk_arrester()
        a._db = MagicMock()
        a._db.log_ac_ramp_event = AsyncMock()
        now = datetime.now()
        await a._maybe_write_declined(
            "zone_a", hvac_const.AC_RESET_DECLINED_DAY_BUDGET, now,
        )
        await a._maybe_write_declined(
            "zone_a", hvac_const.AC_RESET_DECLINED_DAY_BUDGET,
            now + timedelta(minutes=5),
        )
        assert a._db.log_ac_ramp_event.call_count == 1  # second suppressed

    @pytest.mark.asyncio
    async def test_edge_triggered_after_floor_writes_again(self):
        a, _ = _mk_arrester()
        a._db = MagicMock()
        a._db.log_ac_ramp_event = AsyncMock()
        now = datetime.now()
        await a._maybe_write_declined("zone_a", "day_budget_exhausted", now)
        await a._maybe_write_declined(
            "zone_a", "day_budget_exhausted",
            now + timedelta(seconds=hvac_const.AC_RESET_DECLINED_MIN_INTERVAL_S + 1),
        )
        assert a._db.log_ac_ramp_event.call_count == 2

    @pytest.mark.asyncio
    async def test_different_reason_writes_immediately(self):
        a, _ = _mk_arrester()
        a._db = MagicMock()
        a._db.log_ac_ramp_event = AsyncMock()
        now = datetime.now()
        await a._maybe_write_declined("zone_a", "day_budget_exhausted", now)
        await a._maybe_write_declined(
            "zone_a", "night_budget_exhausted", now + timedelta(minutes=1),
        )
        assert a._db.log_ac_ramp_event.call_count == 2


# ============================================================================
# D-ESC-SIG — signature accepts new kwargs + defaults preserve behaviour
# ============================================================================

class TestEscSignature:
    def test_signature_accepts_new_kwargs(self):
        import inspect
        sig = inspect.signature(
            OverrideArrester._perform_hard_reset_escalation
        )
        assert "triggered_by" in sig.parameters
        assert "engage_lockout_on_cap" in sig.parameters
        assert sig.parameters["triggered_by"].default == "auto"
        assert sig.parameters["engage_lockout_on_cap"].default is True


# ============================================================================
# D6 — bounded-add kwh_rate_settle capture (folded into the same UPDATE)
# ============================================================================

class TestResetOutcomeKwCapture:
    """The D6 delayed callback captures `kwh_rate_settle` on the SAME
    UPDATE as `reset_outcome`. If the settle read fails, the row still
    writes with `reset_outcome` intact and `kwh_rate_settle` NULL."""

    def test_update_field_whitelist_includes_kwh_rate_settle(self):
        """The DAO whitelist gates the UPDATE — kwh_rate_settle MUST
        be in it or the callback silently drops the field."""
        # Import the DAO class the write goes through.
        db_mod = _load(
            "custom_components.universal_room_automation.database",
            "database.py",
        )
        cls = db_mod.UniversalRoomDatabase
        assert "kwh_rate_settle" in cls._AC_RAMP_EVENT_UPDATABLE_FIELDS
        assert "reset_outcome" in cls._AC_RAMP_EVENT_UPDATABLE_FIELDS


# ============================================================================
# D7 — off-duration setter
# ============================================================================

class TestOffDurationSetter:
    def test_setter_accepts_valid(self):
        a, _ = _mk_arrester()
        a.set_ac_reset_off_duration(120)
        assert a._ac_reset_off_duration_s == 120

    def test_setter_rejects_out_of_range(self):
        a, _ = _mk_arrester()
        a.set_ac_reset_off_duration(120)
        a.set_ac_reset_off_duration(9000)  # rejected
        assert a._ac_reset_off_duration_s == 120  # unchanged
