"""v4.5.11 — AC Energy-Aware Ramp-Down + Observability (slice 1).

Tests the structural shape + wiring of the ramp-down feature. Source-grep
style (matches v4.5.10 pattern) — fast, no running HA required. Runtime
behavior is covered by post-deploy live validation.

What this file covers (slice 1 only):
  D1 — Detection redesign (overshoot + sustained kWh-rate)
  D2 — Soft nudge action (restart-safe DB ordering, R1)
  D3 — Hard reset escalation (daily cap + global min-interval, R2)
  D4 — SQLite tables (ac_reset_state + ac_ramp_events)
  D5 — 6 house-wide Number sliders + per-zone kWh threshold + form fields
  D6 — Lockout notification + day-rollover-safe counters
  D9 — Master switch + per-zone buttons (force/cancel/clear)
  D10 — Event log retention (30-day prune)

Deferred to slice 2 (v4.5.11.x): per-zone state sensors (D7), house-wide
impact sensors (D8), diagnostic-dump button, HC + EC user manuals (D11).

Special regression guards:
  - AST-walk import resolution (replays v4.5.10.1 ImportError class)
  - Global last_hard_reset_ts query is NOT date-filtered (R2)
  - DB write happens BEFORE setpoint change in _perform_soft_nudge (R1)
"""

import ast
import json
import pytest


# ===========================================================================
# Source fixtures — read each file once, share across all tests in this file
# ===========================================================================


@pytest.fixture(scope="module")
def hvac_const_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/hvac_const.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def hvac_override_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/hvac_override.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def hvac_zones_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/hvac_zones.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def hvac_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/hvac.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def database_src() -> str:
    with open(
        "custom_components/universal_room_automation/database.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def number_src() -> str:
    with open(
        "custom_components/universal_room_automation/number.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def switch_src() -> str:
    with open(
        "custom_components/universal_room_automation/switch.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def button_src() -> str:
    with open(
        "custom_components/universal_room_automation/button.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def config_flow_src() -> str:
    with open(
        "custom_components/universal_room_automation/config_flow.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def strings_json() -> dict:
    with open(
        "custom_components/universal_room_automation/strings.json"
    ) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def translations_en_json() -> dict:
    with open(
        "custom_components/universal_room_automation/translations/en.json"
    ) as f:
        return json.load(f)


# ===========================================================================
# D4 — SQLite schema (ac_reset_state + ac_ramp_events)
# ===========================================================================


class TestSchema:
    """Schema additions live in database.py alongside the existing 35+
    tables. No migration framework — `CREATE TABLE IF NOT EXISTS` pattern
    matches existing convention."""

    def test_ac_reset_state_table_created(self, database_src):
        assert "CREATE TABLE IF NOT EXISTS ac_reset_state" in database_src

    def test_ac_reset_state_has_compound_pk(self, database_src):
        # Day-keyed rows so counter reset is automatic at midnight
        assert "PRIMARY KEY (zone_id, date)" in database_src

    def test_ac_reset_state_in_flight_columns(self, database_src):
        for col in (
            "in_flight_nudge_original_target",
            "in_flight_nudge_started_ts",
            "in_flight_nudge_duration_s",
        ):
            assert col in database_src, (
                f"ac_reset_state must persist {col} so an HA restart "
                f"during a nudge can either resume or restore (R1)"
            )

    def test_ac_ramp_events_table_created(self, database_src):
        assert "CREATE TABLE IF NOT EXISTS ac_ramp_events" in database_src

    def test_ac_ramp_events_has_indexes(self, database_src):
        assert "idx_ac_ramp_events_zone_ts" in database_src
        assert "idx_ac_ramp_events_ts" in database_src

    def test_ac_ramp_events_triggered_by_column(self, database_src):
        # Used to exclude manual force_nudge events from false-positive math (R6)
        assert "triggered_by TEXT NOT NULL DEFAULT 'auto'" in database_src


# ===========================================================================
# D4 helpers — DB methods on UniversalRoomDatabase
# ===========================================================================


@pytest.mark.parametrize(
    "method_name",
    [
        "get_ac_reset_state",
        "save_ac_reset_state",
        "get_global_last_hard_reset_ts",  # R2 — no date filter
        "set_ac_in_flight_nudge",
        "clear_ac_in_flight_nudge",
        "get_zones_with_in_flight_nudge",  # R1 startup audit
        "set_ac_lockout",
        "clear_ac_zone_today",
        "log_ac_ramp_event",
        "get_ac_ramp_events_recent",
        "get_ac_ramp_kwh_avoided",
        "cleanup_ac_ramp_events",
    ],
)
def test_database_helper_method_exists(database_src, method_name):
    """All v4.5.11 DB helper methods are public on UniversalRoomDatabase."""
    assert f"async def {method_name}(" in database_src, (
        f"UniversalRoomDatabase must expose {method_name} so the "
        f"OverrideArrester can persist v4.5.11 state"
    )


class TestSchemaCriticalProperties:

    def test_global_last_hard_reset_ts_query_is_NOT_date_filtered(
        self, database_src,
    ):
        """Risk R2 — day-rollover edge.

        If the query for "when was the last hard reset?" filtered by today's
        date, a hard reset at 23:55 followed by midnight rollover would let
        another hard reset fire at 00:02 (new date row returns NULL). That's
        a 7-minute compressor short-cycle — warranty-voiding.

        The implementation must use `MAX(last_hard_reset_ts) WHERE zone_id=?`
        (no date filter).
        """
        idx = database_src.find("get_global_last_hard_reset_ts")
        assert idx > 0
        # Look at the method body
        body = database_src[idx:idx + 1500]
        assert "MAX(last_hard_reset_ts)" in body
        assert "WHERE zone_id = ?" in body
        # Critical: there must be NO `AND date =` in this query body
        assert "AND date =" not in body, (
            "get_global_last_hard_reset_ts must NOT date-filter — that "
            "would bypass the min-interval gate at day rollover (R2)"
        )

    def test_kwh_avoided_excludes_manual_triggered(self, database_src):
        """Risk R6 — force_nudge button presses for testing must not count
        toward false-positive rate or kwh-avoided math."""
        idx = database_src.find("get_ac_ramp_kwh_avoided")
        body = database_src[idx:idx + 2500]
        assert "triggered_by != 'manual'" in body

    def test_retention_uses_batched_delete(self, database_src):
        """30-day retention prune must be batched (not a single huge DELETE)
        to avoid blocking the write worker."""
        idx = database_src.find("cleanup_ac_ramp_events")
        body = database_src[idx:idx + 2000]
        assert "LIMIT ?" in body
        assert "batch_size" in body


# ===========================================================================
# D1 + D2 + D3 — Constants in hvac_const.py
# ===========================================================================


@pytest.mark.parametrize(
    "const_name,expected_default",
    [
        ("DEFAULT_HVAC_AC_RAMP_MASTER_ENABLED", "False"),  # R: off by default
        ("DEFAULT_HVAC_AC_NUDGE_SIZE", "1.5"),
        ("DEFAULT_HVAC_AC_NUDGE_DURATION", "5"),
        ("DEFAULT_HVAC_AC_SUSTAINED_SAMPLES", "3"),
        ("DEFAULT_HVAC_AC_DETECTION_TIME_GATE", "10"),
        ("DEFAULT_HVAC_AC_HARD_RESET_DAILY_LIMIT", "2"),
        ("DEFAULT_HVAC_AC_HARD_RESET_MIN_INTERVAL", "120"),
        ("DEFAULT_HVAC_AC_KWH_RATE_THRESHOLD", "0.8"),
        ("DEFAULT_HVAC_AC_RAMP_ZONE_ENABLED", "True"),
    ],
)
def test_v4511_default_const_exists_with_expected_value(
    hvac_const_src, const_name, expected_default,
):
    """Defaults are load-bearing — master OFF, daily cap of 2,
    min interval 120 min are compressor-protection invariants. Test
    the literal value to catch accidental changes."""
    assert f"{const_name}: Final = {expected_default}" in hvac_const_src, (
        f"{const_name} must default to {expected_default}"
    )


@pytest.mark.parametrize(
    "conf_name",
    [
        "CONF_HVAC_AC_RAMP_MASTER_ENABLED",
        "CONF_HVAC_AC_NUDGE_SIZE",
        "CONF_HVAC_AC_NUDGE_DURATION",
        "CONF_HVAC_AC_SUSTAINED_SAMPLES",
        "CONF_HVAC_AC_DETECTION_TIME_GATE",
        "CONF_HVAC_AC_HARD_RESET_DAILY_LIMIT",
        "CONF_HVAC_AC_HARD_RESET_MIN_INTERVAL",
        "CONF_HVAC_AC_KWH_RATE_THRESHOLD",
        "CONF_HVAC_AC_LOAD_SENSOR",
        "CONF_HVAC_AC_RAMP_ZONE_ENABLED",
    ],
)
def test_v4511_conf_key_defined(hvac_const_src, conf_name):
    assert f"{conf_name}: Final" in hvac_const_src


class TestConstants:

    def test_overshoot_gap_is_half_degree(self, hvac_const_src):
        """0.5°F gap below target prevents flap (Bryant rounds to 0.5°F so
        current==target is constant during legit cycling)."""
        assert "AC_NUDGE_OVERSHOOT_GAP: Final = 0.5" in hvac_const_src

    def test_kwh_staleness_threshold(self, hvac_const_src):
        # 10 min before treating a sensor reading as missing (R3)
        assert "AC_KWH_SENSOR_STALENESS_S: Final = 600" in hvac_const_src

    def test_kwh_avoided_projection_cap(self, hvac_const_src):
        # Cap at 30 min to keep the rough-estimate honest (tech debt note)
        assert "AC_KWH_AVOIDED_PROJECTION_CAP_MIN: Final = 30" in hvac_const_src

    def test_eval_delay_is_10_minutes(self, hvac_const_src):
        assert "AC_NUDGE_EVALUATION_DELAY_S: Final = 600" in hvac_const_src

    def test_all_state_machine_states_defined(self, hvac_const_src):
        for state in (
            "AC_RAMP_STATE_IDLE",
            "AC_RAMP_STATE_DETECTING",
            "AC_RAMP_STATE_NUDGING",
            "AC_RAMP_STATE_AWAITING_EVAL",
            "AC_RAMP_STATE_ESCALATING",
            "AC_RAMP_STATE_LOCKED_OUT",
            "AC_RAMP_STATE_DISABLED",
        ):
            assert f"{state}: Final" in hvac_const_src

    def test_event_types_defined(self, hvac_const_src):
        for evt in (
            "AC_RAMP_EVENT_DETECTION_FIRED",
            "AC_RAMP_EVENT_NUDGE_STARTED",
            "AC_RAMP_EVENT_NUDGE_RESTORED",
            "AC_RAMP_EVENT_NUDGE_EVALUATED",
            "AC_RAMP_EVENT_HARD_RESET_STARTED",
            "AC_RAMP_EVENT_HARD_RESET_COMPLETED",
            "AC_RAMP_EVENT_LOCKOUT_ENGAGED",
            "AC_RAMP_EVENT_CANCEL_INVOKED",
            "AC_RAMP_EVENT_STARTUP_RESTORE",
        ):
            assert f"{evt}: Final" in hvac_const_src


# ===========================================================================
# ZoneState additions
# ===========================================================================


@pytest.mark.parametrize(
    "field_name",
    [
        "ac_load_sensor",
        "kwh_rate_threshold",
        "ramp_zone_enabled",
        "kwh_samples_above_threshold",
        "last_overshoot_started",
        "ramp_state",
        "last_kwh_rate",
        "last_kwh_rate_ts",
        "nudge_kwh_rate_before",
        "last_kwh_stale_warned_ts",
    ],
)
def test_zone_state_has_v4511_field(hvac_zones_src, field_name):
    """All per-zone runtime state lives on ZoneState (in-memory; the
    persistent counters live in SQLite). The HVAC zone discovery wires
    these from form config + database state."""
    assert f"    {field_name}:" in hvac_zones_src, (
        f"ZoneState must declare {field_name}"
    )


class TestZoneDiscoveryWiring:

    def test_discover_zones_reads_ac_load_sensor(self, hvac_zones_src):
        assert "CONF_HVAC_AC_LOAD_SENSOR" in hvac_zones_src
        assert (
            "zone_cfg.get(CONF_HVAC_AC_LOAD_SENSOR, \"\")"
            in hvac_zones_src
        )

    def test_discover_zones_reads_ramp_zone_enabled(self, hvac_zones_src):
        assert "CONF_HVAC_AC_RAMP_ZONE_ENABLED" in hvac_zones_src

    def test_zone_state_constructor_passes_v4511_fields(self, hvac_zones_src):
        idx = hvac_zones_src.find("zone_state = ZoneState(")
        body = hvac_zones_src[idx:idx + 1500]
        assert "ac_load_sensor=ac_load_sensor" in body
        assert "ramp_zone_enabled=" in body

    def test_merge_path_handles_v4511_fields(self, hvac_zones_src):
        """When two ZM zones share a thermostat (rare merge case), prefer
        first non-empty ac_load_sensor and OR the ramp_zone_enabled flags."""
        # Look for the v4.5.11 merge comment block
        assert "prefer first non-empty ac_load_sensor" in hvac_zones_src
        # And the actual merge logic
        assert "existing.ramp_zone_enabled = (" in hvac_zones_src


# ===========================================================================
# D1 — Detection logic (check_ac_reset rewrite)
# ===========================================================================


class TestDetectionLogic:
    """check_ac_reset is the polling-driven entry point for the ramp-down
    feature. Gates are AND'd in a strict order — any failure skips the
    zone without firing an action."""

    def test_check_ac_reset_master_gate(self, hvac_override_src):
        idx = hvac_override_src.find("async def check_ac_reset(")
        body = hvac_override_src[idx:idx + 6000]
        # Gate 1: master switch
        assert "self._ramp_master_enabled" in body
        # Must return BEFORE iterating zones
        master_pos = body.find("if not self._ramp_master_enabled:")
        zone_pos = body.find("for zone_id, zone in")
        assert master_pos > 0 and zone_pos > 0
        assert master_pos < zone_pos, (
            "Master switch gate must short-circuit BEFORE iterating zones"
        )

    def test_check_ac_reset_per_zone_enable_gate(self, hvac_override_src):
        idx = hvac_override_src.find("async def check_ac_reset(")
        body = hvac_override_src[idx:idx + 6000]
        assert "zone.ramp_zone_enabled" in body

    def test_check_ac_reset_ac_load_sensor_gate(self, hvac_override_src):
        idx = hvac_override_src.find("async def check_ac_reset(")
        body = hvac_override_src[idx:idx + 6000]
        assert "zone.ac_load_sensor" in body
        # Must set ramp_state to DISABLED when sensor not configured (graceful)
        assert "AC_RAMP_STATE_DISABLED" in body

    def test_check_ac_reset_uses_overshoot_gap(self, hvac_override_src):
        """Overshoot threshold is current <= target - 0.5°F (the gap
        prevents flap when AC is at setpoint and modulating naturally)."""
        idx = hvac_override_src.find("async def check_ac_reset(")
        body = hvac_override_src[idx:idx + 6000]
        assert "AC_NUDGE_OVERSHOOT_GAP" in body
        assert "<= zone.target_temp_high - AC_NUDGE_OVERSHOOT_GAP" in body

    def test_check_ac_reset_per_zone_threshold(self, hvac_override_src):
        """kWh threshold is read from ZoneState (per-zone), not from a
        house-wide attr — your 4-ton unit can use 1.0 while 3-tons use 0.8."""
        idx = hvac_override_src.find("async def check_ac_reset(")
        body = hvac_override_src[idx:idx + 6000]
        assert "zone.kwh_rate_threshold" in body
        assert "if kwh_rate > zone.kwh_rate_threshold" in body

    def test_check_ac_reset_three_sample_debounce(self, hvac_override_src):
        idx = hvac_override_src.find("async def check_ac_reset(")
        body = hvac_override_src[idx:idx + 6000]
        assert "kwh_samples_above_threshold" in body
        assert "self._sustained_samples" in body

    def test_check_ac_reset_lockout_gate(self, hvac_override_src):
        idx = hvac_override_src.find("async def check_ac_reset(")
        body = hvac_override_src[idx:idx + 6000]
        assert "lockout_flag" in body
        assert "AC_RAMP_STATE_LOCKED_OUT" in body

    def test_check_ac_reset_dispatches_handler_when_all_gates_pass(
        self, hvac_override_src,
    ):
        idx = hvac_override_src.find("async def check_ac_reset(")
        body = hvac_override_src[idx:idx + 6000]
        assert "await self._handle_overshoot_detected(" in body


class TestKwhRateReader:

    def test_read_kwh_rate_method_exists(self, hvac_override_src):
        assert "def _read_kwh_rate(" in hvac_override_src

    def test_read_kwh_rate_staleness_check(self, hvac_override_src):
        """Risk R3 — if Span goes offline, we must not trust the stuck
        last-known value. 10-min staleness threshold => treat as missing."""
        idx = hvac_override_src.find("def _read_kwh_rate(")
        body = hvac_override_src[idx:idx + 2500]
        assert "AC_KWH_SENSOR_STALENESS_S" in body
        assert "last_updated" in body

    def test_read_kwh_rate_handles_watts_unit(self, hvac_override_src):
        """If user's sensor reports in W, auto-convert to kW so threshold
        units match."""
        idx = hvac_override_src.find("def _read_kwh_rate(")
        body = hvac_override_src[idx:idx + 2500]
        assert '"w"' in body and "watt" in body
        assert "value / 1000" in body

    def test_read_kwh_rate_returns_none_on_unavailable(self, hvac_override_src):
        idx = hvac_override_src.find("def _read_kwh_rate(")
        body = hvac_override_src[idx:idx + 2500]
        assert '"unavailable"' in body

    def test_stale_warning_is_rate_limited(self, hvac_override_src):
        """Don't spam logs every 5 min when sensor is offline — once per
        6h per zone is enough."""
        assert "AC_KWH_STALE_WARN_INTERVAL_S" in hvac_override_src
        assert "def _maybe_warn_stale(" in hvac_override_src


# ===========================================================================
# D2 — Soft nudge (R1 restart safety)
# ===========================================================================


class TestSoftNudge:

    def test_perform_soft_nudge_method_exists(self, hvac_override_src):
        assert "async def _perform_soft_nudge(" in hvac_override_src

    def test_db_write_BEFORE_setpoint_change(self, hvac_override_src):
        """Risk R1 — if HA crashes between DB write and service call, we
        have a DB record claiming nudge in-flight but no actual drift.
        Next startup audit restores the original target (no-op since it
        equals current). Safe failure.

        If we did setpoint FIRST then DB, a crash leaves Bryant at +1.5°F
        forever with no record. R1 mitigation requires DB-first ordering.
        """
        idx = hvac_override_src.find("async def _perform_soft_nudge(")
        body = hvac_override_src[idx:idx + 4000]
        db_write_pos = body.find("set_ac_in_flight_nudge")
        service_pos = body.find('services.async_call(')
        assert db_write_pos > 0 and service_pos > 0
        assert db_write_pos < service_pos, (
            "R1 mitigation: DB write MUST precede setpoint change. "
            "If a crash happens between them, a no-op restore (target "
            "unchanged) is much safer than +1.5°F orphaned drift."
        )

    def test_perform_soft_nudge_suppresses_override(self, hvac_override_src):
        """Risk R11 — URA's own setpoint change must be suppressed so
        the OverrideArrester doesn't misclassify it as a user override."""
        idx = hvac_override_src.find("async def _perform_soft_nudge(")
        body = hvac_override_src[idx:idx + 4000]
        suppress_pos = body.find("self._suppressed_entities.add")
        service_pos = body.find('services.async_call(')
        assert suppress_pos > 0
        assert suppress_pos < service_pos, (
            "Suppress override BEFORE issuing setpoint change (R11)"
        )

    def test_perform_soft_nudge_schedules_restore(self, hvac_override_src):
        idx = hvac_override_src.find("async def _perform_soft_nudge(")
        body = hvac_override_src[idx:idx + 4000]
        assert "_nudge_restore_timers" in body
        assert "async_call_later" in body

    def test_perform_soft_nudge_logs_event(self, hvac_override_src):
        idx = hvac_override_src.find("async def _perform_soft_nudge(")
        body = hvac_override_src[idx:idx + 4000]
        assert "AC_RAMP_EVENT_NUDGE_STARTED" in body

    def test_perform_soft_nudge_increments_counter(self, hvac_override_src):
        idx = hvac_override_src.find("async def _perform_soft_nudge(")
        body = hvac_override_src[idx:idx + 4000]
        assert "soft_nudge_count" in body
        assert "+ 1" in body  # increment

    def test_restore_after_nudge_clears_in_flight(self, hvac_override_src):
        idx = hvac_override_src.find("async def _restore_after_nudge(")
        body = hvac_override_src[idx:idx + 3000]
        assert "clear_ac_in_flight_nudge" in body
        assert "AC_RAMP_EVENT_NUDGE_RESTORED" in body

    def test_restore_after_nudge_schedules_evaluation(self, hvac_override_src):
        idx = hvac_override_src.find("async def _restore_after_nudge(")
        body = hvac_override_src[idx:idx + 3000]
        assert "AC_NUDGE_EVALUATION_DELAY_S" in body
        assert "_nudge_eval_timers" in body


# ===========================================================================
# D3 — Hard reset escalation
# ===========================================================================


class TestHardResetEscalation:

    def test_evaluate_nudge_outcome_method_exists(self, hvac_override_src):
        assert "async def _evaluate_nudge_outcome(" in hvac_override_src

    def test_evaluation_uses_85_percent_threshold(self, hvac_override_src):
        """Tolerance for natural fluctuation: a 15% drop = nudge worked."""
        idx = hvac_override_src.find("async def _evaluate_nudge_outcome(")
        body = hvac_override_src[idx:idx + 3000]
        assert "0.85" in body

    def test_evaluation_escalates_on_ineffective_nudge(
        self, hvac_override_src,
    ):
        idx = hvac_override_src.find("async def _evaluate_nudge_outcome(")
        body = hvac_override_src[idx:idx + 3000]
        assert "_perform_hard_reset_escalation" in body

    def test_perform_hard_reset_escalation_exists(self, hvac_override_src):
        assert (
            "async def _perform_hard_reset_escalation("
            in hvac_override_src
        )

    def test_hard_reset_checks_daily_cap(self, hvac_override_src):
        idx = hvac_override_src.find(
            "async def _perform_hard_reset_escalation("
        )
        body = hvac_override_src[idx:idx + 3000]
        assert "self._hard_reset_daily_limit" in body

    def test_hard_reset_checks_global_min_interval(self, hvac_override_src):
        """Risk R2 — min-interval gate must use the global query so
        day-rollover doesn't bypass it."""
        idx = hvac_override_src.find(
            "async def _perform_hard_reset_escalation("
        )
        body = hvac_override_src[idx:idx + 3000]
        assert "get_global_last_hard_reset_ts" in body
        assert "self._hard_reset_min_interval_min" in body

    def test_hard_reset_engages_lockout_at_cap(self, hvac_override_src):
        idx = hvac_override_src.find(
            "async def _perform_hard_reset_escalation("
        )
        body = hvac_override_src[idx:idx + 3000]
        assert "_engage_lockout" in body

    def test_hard_reset_reuses_existing_perform_ac_reset(
        self, hvac_override_src,
    ):
        """Don't reinvent the off→wait→restore lifecycle — reuse
        _perform_ac_reset (v3.18.x verify+retry pathway). Tests this by
        confirming the call exists in escalation."""
        idx = hvac_override_src.find(
            "async def _perform_hard_reset_escalation("
        )
        body = hvac_override_src[idx:idx + 3000]
        assert "await self._perform_ac_reset(zone)" in body


# ===========================================================================
# D6 — Lockout + notification
# ===========================================================================


class TestLockout:

    def test_engage_lockout_exists(self, hvac_override_src):
        assert "async def _engage_lockout(" in hvac_override_src

    def test_lockout_uses_unique_notification_id(self, hvac_override_src):
        """One persistent notification per zone (HA dedupes by id) — no
        spam if multiple lockouts fire in sequence."""
        idx = hvac_override_src.find("async def _engage_lockout(")
        body = hvac_override_src[idx:idx + 3000]
        assert "ura_ac_ramp_lockout_" in body
        assert "notification_id" in body

    def test_lockout_logs_event_with_flag(self, hvac_override_src):
        idx = hvac_override_src.find("async def _engage_lockout(")
        body = hvac_override_src[idx:idx + 3000]
        assert "AC_RAMP_EVENT_LOCKOUT_ENGAGED" in body
        assert "lockout_triggered=True" in body

    def test_clear_zone_lockout_dismisses_notification(self, hvac_override_src):
        idx = hvac_override_src.find("async def clear_zone_lockout(")
        body = hvac_override_src[idx:idx + 2000]
        assert "persistent_notification" in body
        assert '"dismiss"' in body


# ===========================================================================
# R1 restart resilience — startup audit
# ===========================================================================


class TestStartupRampAudit:

    def test_audit_method_exists(self, hvac_override_src):
        assert "async def async_startup_ramp_audit(" in hvac_override_src

    def test_audit_called_from_hvac_first_decision_cycle(self, hvac_src):
        # Audit must run on coordinator init so a mid-nudge restart doesn't
        # leave the thermostat at +1.5°F forever
        assert "async_startup_ramp_audit()" in hvac_src

    def test_audit_handles_expired_nudges(self, hvac_override_src):
        idx = hvac_override_src.find(
            "async def async_startup_ramp_audit("
        )
        body = hvac_override_src[idx:idx + 4000]
        assert "elapsed_s >= duration_s" in body

    def test_audit_resumes_in_flight_nudges(self, hvac_override_src):
        """If restart happens mid-nudge with time remaining, schedule
        restore for the remaining time — not the full duration."""
        idx = hvac_override_src.find(
            "async def async_startup_ramp_audit("
        )
        body = hvac_override_src[idx:idx + 4000]
        assert "remaining_s = duration_s - elapsed_s" in body

    def test_audit_clears_stale_rows_for_missing_zones(
        self, hvac_override_src,
    ):
        """If a zone was removed from config but an in_flight row remains,
        clear it instead of crashing."""
        idx = hvac_override_src.find(
            "async def async_startup_ramp_audit("
        )
        body = hvac_override_src[idx:idx + 4000]
        assert "if zone is None:" in body
        assert "clear_ac_in_flight_nudge" in body


# ===========================================================================
# D5 — Number entities (6 house-wide + per-zone factory)
# ===========================================================================


class TestNumberEntities:

    def test_build_hvac_v4511_numbers_exists(self, number_src):
        assert "def _build_hvac_v4511_numbers(" in number_src

    @pytest.mark.parametrize(
        "suffix",
        [
            "ac_nudge_size",
            "ac_nudge_duration",
            "ac_sustained_samples",
            "ac_detection_time_gate",
            "ac_hard_reset_daily_limit",
            "ac_hard_reset_min_interval",
        ],
    )
    def test_v4511_house_wide_number_built(self, number_src, suffix):
        # Each suffix maps to one factory call inside _build_hvac_v4511_numbers
        idx = number_src.find("def _build_hvac_v4511_numbers(")
        body = number_src[idx:idx + 5000]
        assert f'suffix="{suffix}"' in body

    def test_per_zone_kwh_threshold_factory_exists(self, number_src):
        assert "def _hvac_zone_kwh_threshold_factory(" in number_src

    def test_per_zone_factory_uses_zone_id_in_unique_id(self, number_src):
        idx = number_src.find("def _hvac_zone_kwh_threshold_factory(")
        body = number_src[idx:idx + 4000]
        assert 'f"{DOMAIN}_hvac_ac_kwh_threshold_{zone_id}"' in body

    def test_per_zone_factory_pushes_to_zone_state(self, number_src):
        idx = number_src.find("def _hvac_zone_kwh_threshold_factory(")
        body = number_src[idx:idx + 4000]
        # Push target is ZoneState.kwh_rate_threshold, not sub-controller
        assert "zone.kwh_rate_threshold = float(self._value)" in body

    def test_discover_ac_zones_reads_zone_manager(self, number_src):
        assert "def _discover_ac_zones(" in number_src
        idx = number_src.find("def _discover_ac_zones(")
        body = number_src[idx:idx + 2000]
        assert "ENTRY_TYPE_ZONE_MANAGER" in body
        assert "CONF_ZONE_THERMOSTAT" in body

    def test_setup_entry_wires_v4511_numbers(self, number_src):
        # In async_setup_entry, the v4.5.11 factories must be iterated
        # for the CM entry (same place v4.5.10 numbers are added)
        assert "_build_hvac_v4511_numbers()" in number_src
        assert "_discover_ac_zones(hass)" in number_src
        assert "_hvac_zone_kwh_threshold_factory(**zone_spec)" in number_src

    def test_per_zone_default_is_0_8_kw(self, number_src):
        """3-ton heuristic: ~25-30% of rated. User raises to 1.0 for 4-ton
        post-deploy via slider — no redeploy needed."""
        idx = number_src.find("def _hvac_zone_kwh_threshold_factory(")
        body = number_src[idx:idx + 4000]
        assert "DEFAULT_HVAC_AC_KWH_RATE_THRESHOLD" in body


# ===========================================================================
# AST regression — v4.5.10.1 lesson (import resolution)
# ===========================================================================


class TestImportResolution:
    """v4.5.10 shipped a broken `from .domain_coordinators.signals import
    SIGNAL_HVAC_ENTITIES_UPDATE` — the signal lives in hvac_const, not
    signals.py. Source-grep tests verified the import statement existed
    but didn't verify the symbol resolved at the import target.

    These tests AST-walk every `from .` import in number.py + switch.py
    + button.py, then text-search the target module to confirm each
    symbol is actually defined there.
    """

    def _check_imports_resolve(self, source: str, source_path_hint: str):
        """Walk every from-import in `source`, follow to the target module,
        verify each imported name appears as a definition there."""
        import os
        tree = ast.parse(source)
        cc_root = "custom_components/universal_room_automation"

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module is None:
                continue
            # Only check intra-package imports
            if node.level == 0:
                continue
            # Resolve relative module path
            base = cc_root
            if node.level > 1:
                # ".." goes up another level (uncommon here)
                base = cc_root  # we keep it flat — patterns in this repo
            module_rel = node.module.replace(".", os.sep)
            candidates = [
                f"{base}/{module_rel}.py",
                f"{base}/{module_rel}/__init__.py",
            ]
            target = None
            for c in candidates:
                if os.path.exists(c):
                    target = c
                    break
            if target is None:
                continue  # external or HA core import
            with open(target) as f:
                target_src = f.read()
            for alias in node.names:
                symbol = alias.name
                if symbol == "*":
                    continue
                # Look for a likely definition: `symbol =`, `def symbol`,
                # `class symbol`, or `symbol: Final` style.
                patterns = [
                    f"{symbol} =",
                    f"{symbol}: Final",
                    f"{symbol}: Final =",
                    f"def {symbol}(",
                    f"async def {symbol}(",
                    f"class {symbol}",
                    f"class {symbol}(",
                ]
                found = any(p in target_src for p in patterns)
                assert found, (
                    f"{source_path_hint}: imports {symbol} from "
                    f"{node.module} but {target} does not define it"
                )

    def test_number_imports_resolve(self, number_src):
        self._check_imports_resolve(number_src, "number.py")

    def test_switch_imports_resolve(self, switch_src):
        self._check_imports_resolve(switch_src, "switch.py")

    def test_button_imports_resolve(self, button_src):
        self._check_imports_resolve(button_src, "button.py")

    def test_hvac_override_imports_resolve(self, hvac_override_src):
        self._check_imports_resolve(
            hvac_override_src,
            "domain_coordinators/hvac_override.py",
        )


# ===========================================================================
# D9 partial — Master switch + per-zone buttons
# ===========================================================================


class TestMasterSwitch:

    def test_master_switch_class_exists(self, switch_src):
        assert "class HVACACRampMasterSwitch" in switch_src

    def test_master_switch_friendly_name(self, switch_src):
        idx = switch_src.find("class HVACACRampMasterSwitch")
        body = switch_src[idx:idx + 3000]
        assert '_attr_name = "AC Ramp-Down (Energy-Aware)"' in body

    def test_master_switch_registered(self, switch_src):
        assert "HVACACRampMasterSwitch(hass, entry)" in switch_src

    def test_master_switch_default_off_means_unavailable_default(
        self, switch_src,
    ):
        """When arrester missing or first install: is_on returns False."""
        idx = switch_src.find("class HVACACRampMasterSwitch")
        body = switch_src[idx:idx + 3000]
        assert "return False" in body

    def test_master_off_cancels_in_flight_nudges(self, hvac_override_src):
        """Toggling master OFF must not strand zones at +nudge_size°F —
        the setter cancels in-flight nudges and restores original
        setpoints."""
        idx = hvac_override_src.find("def ramp_master_enabled(self, value:")
        body = hvac_override_src[idx:idx + 2000]
        assert "cancel_nudge" in body
        assert '"master_off"' in body


class TestPerZoneButtons:

    def test_button_factory_exists(self, button_src):
        assert "def _make_ac_ramp_button(" in button_src

    @pytest.mark.parametrize(
        "action,method",
        [
            ("force_nudge", "force_nudge"),
            ("cancel_nudge", "cancel_nudge"),
            ("clear_lockout", "clear_zone_lockout"),
        ],
    )
    def test_button_spec_for_action(self, button_src, action, method):
        assert f'"{action}"' in button_src
        assert f'"method": "{method}"' in button_src

    def test_buttons_registered_per_zone(self, button_src):
        # Setup iterates _discover_ac_zones and adds 3 buttons per zone
        idx = button_src.find("ENTRY_TYPE_COORDINATOR_MANAGER")
        body = button_src[idx:idx + 3000]
        for action in ("force_nudge", "cancel_nudge", "clear_lockout"):
            assert f'"{action}"' in body

    def test_button_routes_to_arrester_method(self, button_src):
        idx = button_src.find("class _ACRampButton(")
        body = button_src[idx:idx + 4000]
        assert "self._method_name" in body
        assert "getattr(arr, self._method_name" in body

    def test_force_nudge_respects_master_switch(self, hvac_override_src):
        """User direction: force_nudge respects master kill-switch, but
        ignores daily caps (so testing counts toward day's budget)."""
        idx = hvac_override_src.find("async def force_nudge(")
        body = hvac_override_src[idx:idx + 2000]
        assert "if not self._ramp_master_enabled:" in body


# ===========================================================================
# D5 — Form fields (zone_hvac step in config_flow)
# ===========================================================================


class TestZoneHVACFormFields:

    def test_zone_hvac_schema_includes_ac_load_sensor(self, config_flow_src):
        idx = config_flow_src.find('step_id="zone_hvac"')
        # Look backward to find the schema block
        body = config_flow_src[max(0, idx - 5000):idx + 500]
        assert "CONF_HVAC_AC_LOAD_SENSOR" in body

    def test_zone_hvac_schema_includes_ramp_zone_enabled(self, config_flow_src):
        idx = config_flow_src.find('step_id="zone_hvac"')
        body = config_flow_src[max(0, idx - 5000):idx + 500]
        assert "CONF_HVAC_AC_RAMP_ZONE_ENABLED" in body

    def test_zone_hvac_form_uses_power_or_energy_selector(
        self, config_flow_src,
    ):
        """ac_load_sensor accepts kW (preferred) or kWh. Filter by device_class."""
        idx = config_flow_src.find('step_id="zone_hvac"')
        body = config_flow_src[max(0, idx - 5000):idx + 500]
        assert 'device_class=["power", "energy"]' in body

    def test_strings_json_has_ac_load_sensor_label(self, strings_json):
        zone_hvac = strings_json["options"]["step"]["zone_hvac"]
        assert "hvac_ac_load_sensor" in zone_hvac["data"]
        assert "hvac_ac_load_sensor" in zone_hvac["data_description"]

    def test_strings_json_has_ramp_zone_enabled_label(self, strings_json):
        zone_hvac = strings_json["options"]["step"]["zone_hvac"]
        assert "hvac_ac_ramp_zone_enabled" in zone_hvac["data"]
        assert "hvac_ac_ramp_zone_enabled" in zone_hvac["data_description"]

    def test_translations_match_strings(self, translations_en_json):
        zone_hvac = translations_en_json["options"]["step"]["zone_hvac"]
        assert "hvac_ac_load_sensor" in zone_hvac["data"]
        assert "hvac_ac_ramp_zone_enabled" in zone_hvac["data"]


# ===========================================================================
# HVAC coordinator integration
# ===========================================================================


# ===========================================================================
# v4.5.11.1 — Zone-ID vs climate_entity resolution (regression guard)
# ===========================================================================


class TestZoneResolutionAcrossSchemes:
    """v4.5.11 slice-1 review-2 caught a critical bug: button + Number
    factories derived zone_id locally as
        thermostat.replace("climate.", "").replace(".", "_")
    while ZoneManager._zone_id_from_thermostat extracts "zone_N" from
    the same entity. The two schemes don't match, so every per-zone
    Number slider, every per-zone button, and the OverrideArrester's
    public force_nudge/cancel_nudge/clear_zone_lockout methods would
    fail to find their ZoneState at runtime.

    Fix: OverrideArrester._resolve_zone(zone_id_or_entity) accepts both
    the local zone_id and the climate_entity. Buttons + Number factories
    store climate_entity (stable identifier) and pass it to the
    arrester methods.
    """

    def test_arrester_has_resolve_zone_helper(self, hvac_override_src):
        assert "def _resolve_zone(self, zone_id_or_entity:" in hvac_override_src

    def test_resolve_zone_falls_through_to_climate_entity_match(
        self, hvac_override_src,
    ):
        idx = hvac_override_src.find(
            "def _resolve_zone(self, zone_id_or_entity:"
        )
        body = hvac_override_src[idx:idx + 1500]
        assert "self._zone_manager.zones.get(zone_id_or_entity)" in body
        assert "z.climate_entity == zone_id_or_entity" in body

    def test_force_nudge_uses_resolve_zone(self, hvac_override_src):
        idx = hvac_override_src.find("async def force_nudge(")
        body = hvac_override_src[idx:idx + 2000]
        assert "self._resolve_zone(zone_id)" in body
        # Canonicalize zone_id after resolution so downstream DB ops
        # use the ZoneManager-owned zone_id
        assert "zone_id = zone.zone_id" in body

    def test_cancel_nudge_uses_resolve_zone(self, hvac_override_src):
        idx = hvac_override_src.find("async def cancel_nudge(")
        body = hvac_override_src[idx:idx + 2500]
        assert "self._resolve_zone(zone_id)" in body
        assert "zone_id = zone.zone_id" in body

    def test_clear_zone_lockout_uses_resolve_zone(self, hvac_override_src):
        idx = hvac_override_src.find("async def clear_zone_lockout(")
        body = hvac_override_src[idx:idx + 2000]
        assert "self._resolve_zone(zone_id)" in body

    def test_number_factory_stores_climate_entity(self, number_src):
        # Scope to the function body via the next top-level def
        idx = number_src.find("def _hvac_zone_kwh_threshold_factory(")
        assert idx > 0
        rest = number_src[idx + len("def _hvac_zone_kwh_threshold_factory("):]
        next_def = rest.find("\ndef ")
        end = (idx + len("def _hvac_zone_kwh_threshold_factory(") + next_def
               if next_def > 0 else len(number_src))
        body = number_src[idx:end]
        assert "self._climate_entity = climate_entity" in body
        assert "zone.climate_entity == self._climate_entity" in body

    def test_button_factory_passes_climate_entity(self, button_src):
        idx = button_src.find("def _make_ac_ramp_button(")
        body = button_src[idx:idx + 1500]
        assert 'climate_entity=zone_spec["climate_entity"]' in body

    def test_button_init_stores_climate_entity(self, button_src):
        idx = button_src.find("class _ACRampButton(")
        body = button_src[idx:idx + 4000]
        assert "self._climate_entity = climate_entity" in body

    def test_button_press_passes_climate_entity_not_zone_id(self, button_src):
        idx = button_src.find("class _ACRampButton(")
        body = button_src[idx:idx + 4000]
        # The runtime call to OverrideArrester methods should use
        # climate_entity (which _resolve_zone handles) — NOT the
        # locally-derived zone_id.
        assert "method(self._climate_entity)" in body


class TestHVACCoordIntegration:

    def test_hvac_wires_database_to_arrester(self, hvac_src):
        """OverrideArrester needs DB for persistent caps — HVAC coord
        must call set_database during setup."""
        assert "set_database(db)" in hvac_src
        # And the database is fetched from hass.data
        assert 'hass.data.get(DOMAIN, {}).get("database")' in hvac_src

    def test_hvac_runs_startup_ramp_audit(self, hvac_src):
        """First decision cycle (post-init) must call async_startup_ramp_audit
        so a mid-nudge restart doesn't strand zones (R1)."""
        idx = hvac_src.find("async_startup_audit(")
        body = hvac_src[idx:idx + 1500]
        assert "async_startup_ramp_audit()" in body

    def test_arrester_has_set_database_method(self, hvac_override_src):
        assert "def set_database(self, db) -> None:" in hvac_override_src


# ===========================================================================
# OverrideArrester teardown cleanup
# ===========================================================================


class TestTeardownCleanup:

    def test_teardown_cancels_nudge_timers(self, hvac_override_src):
        """teardown() must cancel both restore and evaluation timers so
        unloading doesn't leak callbacks."""
        idx = hvac_override_src.find("def teardown(self) -> None:")
        body = hvac_override_src[idx:idx + 2500]
        assert "_nudge_restore_timers" in body
        assert "_nudge_eval_timers" in body
        assert "_nudge_in_flight.clear()" in body


# ===========================================================================
# Plan-completion tracking (CLAUDE.md mandate)
# ===========================================================================


class TestPlanCompletion:
    """v4.5.11 ships as 'slice 1' — explicitly document what was
    deferred so future cycles don't lose track."""

    def test_planning_doc_exists(self):
        import os
        assert os.path.exists(
            "docs/planning/"
            "PLANNING_v4.5.11_ac_energy_aware_ramp_down.md"
        )

    def test_planning_doc_lists_all_deliverables(self):
        with open(
            "docs/planning/"
            "PLANNING_v4.5.11_ac_energy_aware_ramp_down.md"
        ) as f:
            content = f.read()
        for d in ("D1:", "D2:", "D3:", "D4:", "D5:", "D6:",
                  "D7:", "D8:", "D9:", "D10", "D11"):
            assert d in content, f"Plan must call out {d}"
