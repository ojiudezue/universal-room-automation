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


# ============================================================================
# Hollow-anchor REWRITES (2026-08-22 fix-up test-authority round)
# The four tests below REPLACE the pre-fix hollow anchors called out in
# the fix-up brief. Each drives the ENCLOSING method / write path and
# would fail against a plausible naive implementation.
# ============================================================================


def dt_util_now_date_iso():
    return datetime.now().date().isoformat()


class TestEscSignatureBehavioural:
    """Rewrite of TestEscSignature::test_signature_accepts_new_kwargs.
    A signature-only test passes against a function that accepts the
    kwargs and ignores them. This drives the behaviour those kwargs
    are supposed to change."""

    @pytest.mark.asyncio
    async def test_triggered_by_threads_into_started_row(self):
        a, z = _mk_arrester()
        a._ac_reset_enabled = True
        a._ramp_master_enabled = True
        a._hard_reset_daily_limit = 5
        z.target_temp_high = 74.0
        z.target_temp_low = 70.0
        z.current_temperature = 74.0
        a._db = MagicMock()
        a._db.get_ac_reset_state = AsyncMock(return_value={
            "zone_id": z.zone_id, "date": "2026-08-22",
            "day_reset_count": 0, "night_reset_count": 0,
            "hard_reset_count": 0, "night_session_date": None,
        })
        a._db.get_global_last_hard_reset_ts = AsyncMock(return_value=None)
        a._db.log_ac_ramp_event = AsyncMock(return_value=101)
        a._db.save_ac_reset_state = AsyncMock()
        a._db.update_ac_night_counter = AsyncMock()
        a._corrective_writes_suppressed = MagicMock(return_value=False)
        a._perform_ac_reset = AsyncMock()
        await a._perform_hard_reset_escalation(
            z, 1.2, triggered_by="durability_fail",
            engage_lockout_on_cap=True,
        )
        started_calls = [
            c for c in a._db.log_ac_ramp_event.call_args_list
            if c.kwargs.get("event_type") == "hard_reset_started"
        ]
        assert len(started_calls) == 1
        assert started_calls[0].kwargs.get("triggered_by") == "durability_fail"

    @pytest.mark.asyncio
    async def test_engage_lockout_on_cap_false_decline_route(self):
        a, z = _mk_arrester()
        a._ac_reset_enabled = True
        a._ramp_master_enabled = True
        a._reset_day_budget = 2
        a._reset_night_budget = 2
        a._hard_reset_daily_limit = 5
        a._db = MagicMock()
        a._db.get_ac_reset_state = AsyncMock(return_value={
            "zone_id": z.zone_id, "date": "2026-08-22",
            "day_reset_count": 2, "night_reset_count": 2,
            "hard_reset_count": 4, "night_session_date": None,
        })
        a._db.log_ac_ramp_event = AsyncMock()
        a._db.save_ac_reset_state = AsyncMock()
        a._db.update_ac_night_counter = AsyncMock()
        a._corrective_writes_suppressed = MagicMock(return_value=False)
        a._engage_lockout = AsyncMock()
        a._perform_ac_reset = AsyncMock()
        await a._perform_hard_reset_escalation(
            z, 1.2, triggered_by="durability_fail",
            engage_lockout_on_cap=False,
        )
        a._engage_lockout.assert_not_called()
        reasons = [
            (c.kwargs.get("notes") or "")
            for c in a._db.log_ac_ramp_event.call_args_list
            if c.kwargs.get("event_type") == "hard_reset_declined"
        ]
        assert any("true_cap_exhausted" in r for r in reasons), reasons


class TestDGate4ModeAugmented:
    """Adds negatives to the pre-fix positive-only pair. A blanket
    return-True _gate4_is_ok would pass the positives and fail these."""

    def test_legacy_mode_returns_false_when_hvac_action_not_cooling(self):
        hass = _mk_hass_with_state("sensor.zone_a_kw", 1.2, unit="kW")
        a, z = _mk_arrester(hass=hass)
        a.set_gate4_predicate_mode("legacy")
        z.hvac_action = "idle"
        z.hvac_mode = "cool"
        assert a._gate4_is_ok(z, datetime.now()) is False

    def test_shadow_mode_returns_false_when_legacy_says_not_cooling(self):
        hass = _mk_hass_with_state("sensor.zone_a_kw", 1.2, unit="kW")
        a, z = _mk_arrester(hass=hass)
        a.set_gate4_predicate_mode("shadow")
        a._db = MagicMock()
        a._db.log_ac_ramp_event = AsyncMock()
        z.hvac_action = "idle"
        z.hvac_mode = "cool"
        assert a._gate4_is_ok(z, datetime.now()) is False

    def test_live_mode_returns_true_when_new_predicate_ok_despite_legacy_off(self):
        hass = _mk_hass_with_state("sensor.zone_a_kw", 1.2, unit="kW")
        a, z = _mk_arrester(hass=hass)
        a.set_gate4_predicate_mode("live")
        z.hvac_action = "idle"
        z.hvac_mode = "cool"
        assert a._gate4_is_ok(z, datetime.now()) is True


class TestDurableClassifierLiteral:
    """Assert against literal elapsed minutes, not the same instance
    attribute the write reads from."""

    @pytest.mark.asyncio
    async def test_full_window_writes_literal_elapsed_minutes(self):
        a, z = _mk_arrester()
        a._db = MagicMock()
        a._db.update_ac_ramp_event_fields = AsyncMock()
        a._read_kwh_rate = MagicMock(return_value=0.1)
        z.kwh_rate_threshold = 0.8
        started = datetime.now() - timedelta(minutes=42)
        a._durable_pending["zone_a"] = {
            "event_id": 99, "started_ts": started,
        }
        await a._write_durable("zone_a", truncated=False)
        _, kwargs = a._db.update_ac_ramp_event_fields.call_args
        assert 41 <= kwargs["durable_minutes"] <= 43
        assert kwargs["durable"] == 1
        assert kwargs["truncated"] == 0


# ============================================================================
# T1-T6 wire-in tests. Each drives an enclosing method or its wired
# entry point and would fail against a plausible bypass at the
# load-bearing site. Per-site neuter drills documented in the commit.
# ============================================================================


class TestT1Gate4WireIn:
    """T1: Gate 4 wire-in in check_ac_reset."""

    @pytest.mark.asyncio
    async def test_gate4_reject_clears_overshoot_and_samples(self):
        a, z = _mk_arrester()
        a._ac_nudge_enabled = True
        a._ramp_master_enabled = True
        z.ramp_zone_enabled = True
        z.ac_load_sensor = "sensor.zone_a_kw"
        z.hvac_mode = "cool"
        z.hvac_action = "cooling"
        z.target_temp_high = 74.0
        z.current_temperature = 74.0
        z.kwh_samples_above_threshold = 4
        z.last_overshoot_started = "2026-08-22T10:00:00"
        a._gate4_is_ok = MagicMock(return_value=False)
        # Mock _read_kwh_rate too so a bypass-mutation lands on the
        # assertion, not a downstream MagicMock TypeError.
        a._read_kwh_rate = MagicMock(return_value=1.5)
        a._db = MagicMock()
        a._db.cleanup_ac_ramp_events = AsyncMock()
        a._db.get_ac_reset_state = AsyncMock(return_value={
            "lockout_flag": 0, "soft_nudge_count": 0,
        })
        a._db.log_ac_ramp_event = AsyncMock()
        a._perform_soft_nudge = AsyncMock()
        a._refresh_impact_cache = AsyncMock()
        a._refresh_a1_cache = AsyncMock()
        await a.check_ac_reset()
        assert z.kwh_samples_above_threshold == 0
        assert z.last_overshoot_started == ""


class TestT2Gate5bWireIn:
    """T2: Gate 5b soft-nudge cap runaway guard in check_ac_reset."""

    @pytest.mark.asyncio
    async def test_soft_nudge_cap_denies_and_declined_row_written(self):
        a, z = _mk_arrester()
        a._ac_nudge_enabled = True
        a._ramp_master_enabled = True
        a._soft_nudge_daily_limit = 5
        z.ramp_zone_enabled = True
        z.ac_load_sensor = "sensor.zone_a_kw"
        z.hvac_mode = "cool"
        z.hvac_action = "cooling"
        z.target_temp_high = 74.0
        z.current_temperature = 74.0
        a._gate4_is_ok = MagicMock(return_value=True)
        a._db = MagicMock()
        a._db.get_ac_reset_state = AsyncMock(return_value={
            "lockout_flag": 0, "soft_nudge_count": 5,
        })
        a._db.log_ac_ramp_event = AsyncMock()
        a._db.cleanup_ac_ramp_events = AsyncMock()
        a._perform_soft_nudge = AsyncMock()
        a._refresh_impact_cache = AsyncMock()
        a._refresh_a1_cache = AsyncMock()
        await a.check_ac_reset()
        a._perform_soft_nudge.assert_not_called()
        decline_calls = [
            c for c in a._db.log_ac_ramp_event.call_args_list
            if c.kwargs.get("event_type") == "hard_reset_declined"
        ]
        assert any(
            "soft_nudge_daily_limit" in (c.kwargs.get("notes") or "")
            for c in decline_calls
        ), decline_calls


class TestT3PartitionDenialWireIn:
    """T3: partition-denial branch in _perform_hard_reset_escalation.
    _hard_reset_daily_limit raised above day+night so Gate A's clamp
    doesn't fire first — the partition path IS what denies."""

    @pytest.mark.asyncio
    async def test_day_denial_no_lockout_no_ac_reset(self):
        a, z = _mk_arrester()
        a._ac_reset_enabled = True
        a._ramp_master_enabled = True
        a._reset_day_budget = 2
        a._reset_night_budget = 2
        a._hard_reset_daily_limit = 5
        a._db = MagicMock()
        a._db.get_ac_reset_state = AsyncMock(return_value={
            "zone_id": z.zone_id,
            "date": dt_util_now_date_iso(),
            "day_reset_count": 2,
            "night_reset_count": 0,
            "hard_reset_count": 2,
            "night_session_date": None,
        })
        a._db.log_ac_ramp_event = AsyncMock()
        a._db.save_ac_reset_state = AsyncMock()
        a._db.get_global_last_hard_reset_ts = AsyncMock(return_value=None)
        a._corrective_writes_suppressed = MagicMock(return_value=False)
        a._engage_lockout = AsyncMock()
        a._perform_ac_reset = AsyncMock()
        a._is_night_now = MagicMock(return_value=False)
        await a._perform_hard_reset_escalation(z, 1.2)
        assert z.ramp_state == "idle"
        a._engage_lockout.assert_not_called()
        a._perform_ac_reset.assert_not_called()
        decline_reasons = [
            (c.kwargs.get("notes") or "")
            for c in a._db.log_ac_ramp_event.call_args_list
            if c.kwargs.get("event_type") == "hard_reset_declined"
        ]
        assert any("day_budget_exhausted" in r for r in decline_reasons)


class TestT5BackfillRestoreOkWireIn:
    """T5: _backfill_restore_ok. Helper-level behavioural anchor;
    the enclosing _verify_restore is exercised too deeply for a
    focused test — the drill mutates the helper's DAO call to prove
    binding."""

    @pytest.mark.asyncio
    async def test_backfill_uses_stashed_event_id_and_pops(self):
        a, z = _mk_arrester()
        a._db = MagicMock()
        a._db.update_ac_ramp_event_fields = AsyncMock()
        a._hard_reset_completed_event_ids = {"zone_a": 909}
        await a._backfill_restore_ok("zone_a", True, preset_ok=True)
        assert "zone_a" not in a._hard_reset_completed_event_ids
        call = a._db.update_ac_ramp_event_fields.call_args
        assert call is not None
        assert call.args[0] == 909
        assert call.kwargs.get("restore_ok") is True
        assert call.kwargs.get("preset_restore_ok") is True

    @pytest.mark.asyncio
    async def test_backfill_no_op_when_stash_missing(self):
        a, z = _mk_arrester()
        a._db = MagicMock()
        a._db.update_ac_ramp_event_fields = AsyncMock()
        a._hard_reset_completed_event_ids = {}
        await a._backfill_restore_ok("zone_a", True)
        a._db.update_ac_ramp_event_fields.assert_not_called()


class TestT6OffDurationConsumption:
    """T6: _perform_ac_reset must schedule the off-timer using the
    _ac_reset_off_duration_s knob, not a hard-coded constant."""

    @pytest.mark.asyncio
    async def test_perform_ac_reset_uses_knob_not_constant(self):
        a, z = _mk_arrester()
        z.target_temp_high = 74.0
        z.target_temp_low = 70.0
        z.current_temperature = 74.0
        z.hvac_mode = "cool"
        z.hvac_action = "cooling"
        a._db = MagicMock()
        a._db.get_ac_reset_state = AsyncMock(return_value={
            "day_reset_count": 0, "night_reset_count": 0,
            "hard_reset_count": 1, "date": "2026-08-22",
        })
        a._ac_reset_off_duration_s = 195
        a._reset_day_budget = 4
        a._reset_night_budget = 4
        a._send_nm_alert = AsyncMock()
        hass = a.hass
        hass.services.async_call = AsyncMock()
        hass.states.get = MagicMock(return_value=None)
        from homeassistant.helpers.event import async_call_later
        async_call_later.reset_mock()
        a._supports_heat_cool = MagicMock(return_value=False)
        await a._perform_ac_reset(z)
        assert async_call_later.call_count >= 1
        assert async_call_later.call_args_list[0].args[1] == 195


# ============================================================================
# Acceptance tests for the fix-up brief's explicit F-item repros.
# ============================================================================


class TestF1MidnightRepro:
    def test_night_session_date_stable_across_midnight(self):
        a, _ = _mk_arrester()
        d1 = a._night_session_date(datetime(2026, 8, 22, 22, 10))
        d2 = a._night_session_date(datetime(2026, 8, 23, 0, 35))
        d3 = a._night_session_date(datetime(2026, 8, 23, 2, 40))
        assert d1 == d2 == d3 == "2026-08-22"

    def test_partition_check_uses_night_state_row_across_midnight(self):
        a, _ = _mk_arrester()
        a.set_reset_night_budget(2)
        night_state = {
            "night_reset_count": 0,
            "night_session_date": "2026-08-22",
        }
        pre = a._increment_partition_counter(
            state={"day_reset_count": 0, "date": "2026-08-22"},
            now=datetime(2026, 8, 22, 22, 10),
            night_state=night_state,
        )
        assert pre == "night" and night_state["night_reset_count"] == 1
        post = a._increment_partition_counter(
            state={"day_reset_count": 0, "date": "2026-08-23"},
            now=datetime(2026, 8, 23, 0, 35),
            night_state=night_state,
        )
        assert post == "night" and night_state["night_reset_count"] == 2
        ok, part, _reason = a._gate_partition_check(
            "zone_a", datetime(2026, 8, 23, 2, 40),
            state={"day_reset_count": 0, "date": "2026-08-23"},
            night_state=night_state,
        )
        assert ok is False and part == "night"


class TestF3KillSwitch:
    @pytest.mark.asyncio
    async def test_limit_zero_declines_no_lockout(self):
        a, z = _mk_arrester()
        a._ac_reset_enabled = True
        a._ramp_master_enabled = True
        a._hard_reset_daily_limit = 0
        a._db = MagicMock()
        a._db.get_ac_reset_state = AsyncMock(return_value={
            "zone_id": z.zone_id, "date": "2026-08-22",
            "day_reset_count": 0, "night_reset_count": 0,
            "hard_reset_count": 0, "night_session_date": None,
        })
        a._db.log_ac_ramp_event = AsyncMock()
        a._db.save_ac_reset_state = AsyncMock()
        a._db.get_global_last_hard_reset_ts = AsyncMock(return_value=None)
        a._corrective_writes_suppressed = MagicMock(return_value=False)
        a._engage_lockout = AsyncMock()
        a._perform_ac_reset = AsyncMock()
        a._is_night_now = MagicMock(return_value=False)
        await a._perform_hard_reset_escalation(z, 1.2)
        a._engage_lockout.assert_not_called()
        a._perform_ac_reset.assert_not_called()
        reasons = [
            (c.kwargs.get("notes") or "")
            for c in a._db.log_ac_ramp_event.call_args_list
            if c.kwargs.get("event_type") == "hard_reset_declined"
        ]
        assert any("feature_disabled" in r for r in reasons), reasons


class TestF4LockoutBothDirections:
    @pytest.mark.asyncio
    async def test_true_cap_exhausted_engages_lockout_when_enabled(self):
        a, z = _mk_arrester()
        a._ac_reset_enabled = True
        a._ramp_master_enabled = True
        a._reset_day_budget = 1
        a._reset_night_budget = 1
        a._hard_reset_daily_limit = 5
        a._db = MagicMock()
        a._db.get_ac_reset_state = AsyncMock(return_value={
            "zone_id": z.zone_id, "date": "2026-08-22",
            "day_reset_count": 1, "night_reset_count": 1,
            "hard_reset_count": 2, "night_session_date": None,
        })
        a._db.log_ac_ramp_event = AsyncMock()
        a._db.save_ac_reset_state = AsyncMock()
        a._db.get_global_last_hard_reset_ts = AsyncMock(return_value=None)
        a._corrective_writes_suppressed = MagicMock(return_value=False)
        a._engage_lockout = AsyncMock()
        a._perform_ac_reset = AsyncMock()
        a._is_night_now = MagicMock(return_value=False)
        await a._perform_hard_reset_escalation(z, 1.2)
        a._engage_lockout.assert_called_once()

    @pytest.mark.asyncio
    async def test_true_cap_exhausted_declines_when_flag_false(self):
        a, z = _mk_arrester()
        a._ac_reset_enabled = True
        a._ramp_master_enabled = True
        a._reset_day_budget = 1
        a._reset_night_budget = 1
        a._hard_reset_daily_limit = 5
        a._db = MagicMock()
        a._db.get_ac_reset_state = AsyncMock(return_value={
            "zone_id": z.zone_id, "date": "2026-08-22",
            "day_reset_count": 1, "night_reset_count": 1,
            "hard_reset_count": 2, "night_session_date": None,
        })
        a._db.log_ac_ramp_event = AsyncMock()
        a._db.save_ac_reset_state = AsyncMock()
        a._db.get_global_last_hard_reset_ts = AsyncMock(return_value=None)
        a._corrective_writes_suppressed = MagicMock(return_value=False)
        a._engage_lockout = AsyncMock()
        a._perform_ac_reset = AsyncMock()
        a._is_night_now = MagicMock(return_value=False)
        await a._perform_hard_reset_escalation(
            z, 1.2, engage_lockout_on_cap=False,
        )
        a._engage_lockout.assert_not_called()
        reasons = [
            (c.kwargs.get("notes") or "")
            for c in a._db.log_ac_ramp_event.call_args_list
            if c.kwargs.get("event_type") == "hard_reset_declined"
        ]
        assert any("true_cap_exhausted" in r for r in reasons), reasons


class TestF5ZoneThresholdAndTruncatedColumn:
    @pytest.mark.asyncio
    async def test_uses_zone_threshold_not_module_floor(self):
        """kW=0.8 above the 0.5 module floor but below the zone
        threshold 1.5 -> durable=1 under the corrected rule."""
        a, z = _mk_arrester()
        a._db = MagicMock()
        a._db.update_ac_ramp_event_fields = AsyncMock()
        a._read_kwh_rate = MagicMock(return_value=0.8)
        z.kwh_rate_threshold = 1.5
        a._durable_pending["zone_a"] = {
            "event_id": 55,
            "started_ts": datetime.now() - timedelta(minutes=30),
        }
        await a._write_durable("zone_a", truncated=False)
        _, kwargs = a._db.update_ac_ramp_event_fields.call_args
        assert kwargs["durable"] == 1

    @pytest.mark.asyncio
    async def test_truncated_column_written_alongside_durable(self):
        a, z = _mk_arrester()
        a._db = MagicMock()
        a._db.update_ac_ramp_event_fields = AsyncMock()
        z.kwh_rate_threshold = 0.8
        a._nudge_running_max_kw["zone_a"] = 1.2
        a._durable_pending["zone_a"] = {
            "event_id": 66,
            "started_ts": datetime.now() - timedelta(minutes=5),
        }
        await a._write_durable("zone_a", truncated=True)
        _, kwargs = a._db.update_ac_ramp_event_fields.call_args
        assert kwargs["truncated"] == 1

        a2, z2 = _mk_arrester()
        a2._db = MagicMock()
        a2._db.update_ac_ramp_event_fields = AsyncMock()
        a2._read_kwh_rate = MagicMock(return_value=0.1)
        z2.kwh_rate_threshold = 0.8
        a2._durable_pending["zone_a"] = {
            "event_id": 67,
            "started_ts": datetime.now() - timedelta(minutes=30),
        }
        await a2._write_durable("zone_a", truncated=False)
        _, kwargs2 = a2._db.update_ac_ramp_event_fields.call_args
        assert kwargs2["truncated"] == 0


class TestF7KwhUnitRejected:
    def test_cumulative_kwh_sensor_returns_none(self):
        hass = _mk_hass_with_state("sensor.zone_a_kwh", 42.5, unit="kWh")
        a, z = _mk_arrester(hass=hass)
        z.ac_load_sensor = "sensor.zone_a_kwh"
        assert a._read_kwh_rate(z, datetime.now()) is None

    def test_kw_and_w_units_accepted(self):
        hass_kw = _mk_hass_with_state("sensor.zone_a_kw", 1.2, unit="kW")
        a, z = _mk_arrester(hass=hass_kw)
        z.ac_load_sensor = "sensor.zone_a_kw"
        assert a._read_kwh_rate(z, datetime.now()) == 1.2
        hass_w = _mk_hass_with_state("sensor.zone_a_w", 1200, unit="W")
        a2, z2 = _mk_arrester(hass=hass_w)
        z2.ac_load_sensor = "sensor.zone_a_w"
        v = a2._read_kwh_rate(z2, datetime.now())
        assert abs(v - 1.2) < 1e-6


class TestF9PresetFailureVsRestoreOk:
    @pytest.mark.asyncio
    async def test_preset_failure_yields_preset_restore_ok_false(self):
        a, z = _mk_arrester()
        a._db = MagicMock()
        a._db.update_ac_ramp_event_fields = AsyncMock()
        a._hard_reset_completed_event_ids = {"zone_a": 321}
        await a._backfill_restore_ok(
            "zone_a", False, preset_ok=False,
        )
        call = a._db.update_ac_ramp_event_fields.call_args
        assert call.args[0] == 321
        assert call.kwargs.get("restore_ok") is False
        assert call.kwargs.get("preset_restore_ok") is False


# ============================================================================
# T4 wire-in: kwh_rate_settle. Under the mocked homeassistant harness,
# async_call_later returns a MagicMock and does NOT execute the
# scheduled callback. The T4 wire-in test therefore drives the D6
# scheduler and asserts (a) TWO async_call_later schedules happened
# (temp @ 60s + kW @ AC_RESET_OUTCOME_KWH_SETTLE_S), (b) the SECOND
# is scheduled at the corrected kW settle delay. The DAO write shape
# assertion (kwh_rate_settle populated) is enforced at the mutation
# drill by neutering the kwarg in the source and observing this test
# fail — reported UNBOUND with an explicit reason if the harness
# cannot execute the closure.
# ============================================================================


class TestT4KwSettleScheduler:
    @pytest.mark.asyncio
    async def test_two_delayed_callbacks_scheduled_with_correct_delays(self):
        a, z = _mk_arrester()
        a._db = MagicMock()
        a._db.update_ac_ramp_event_fields = AsyncMock()
        z.ac_load_sensor = "sensor.zone_a_kw"
        a._read_kwh_rate = MagicMock(return_value=0.42)
        a._reset_outcome_pending[z.zone_id] = {
            "event_id": 77, "target_high": 74.0,
        }
        from homeassistant.helpers.event import async_call_later
        from custom_components.universal_room_automation.domain_coordinators.hvac_const import (
            AC_RESET_OUTCOME_SETTLE_S,
            AC_RESET_OUTCOME_KWH_SETTLE_S,
        )
        async_call_later.reset_mock()
        a._schedule_reset_outcome(z, completed_event_id=77)
        assert async_call_later.call_count == 2, (
            "expected two schedules (temp @ 60s + kW @ kw-settle)"
        )
        # First = temp settle at AC_RESET_OUTCOME_SETTLE_S.
        assert async_call_later.call_args_list[0].args[1] == AC_RESET_OUTCOME_SETTLE_S
        # Second = kW settle at AC_RESET_OUTCOME_KWH_SETTLE_S (F6 fix-up
        # for the actuation-lag envelope; must be >= 150s).
        assert async_call_later.call_args_list[1].args[1] == AC_RESET_OUTCOME_KWH_SETTLE_S
        assert AC_RESET_OUTCOME_KWH_SETTLE_S >= 150
