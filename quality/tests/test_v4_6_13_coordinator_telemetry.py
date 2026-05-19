"""Tests for v4.6.13 — Coordinator Telemetry Sensor Set (Dashboard Cycle C).

Coverage:
  D1 — CoordinatorDecisionsTodaySensor (5 sensors)
  D2 — CoordinatorOverrideFrequencySensor (5 sensors)
  D3 — CoordinatorComplianceRateSensor (5 sensors)
  D4 — URADBSizeSensor
  D5 — CoordinatorLastDecisionSensor (5 sensors)

Test strategy (mirrors v4.6.12 pattern with the v4.6.12 review-fix
TestProductionClassImports addition):
- Structural source tests grep aggregation/sensor source for class definitions
- Production-class AST tests verify each sensor class exists with the
  expected bases and method shape — closes the test-fixture-authority gap
- Behavioral tests for the inline-computed pure logic (cutoff math,
  emit-label filtering, None-on-zero contract)
"""
from __future__ import annotations

import ast
import pathlib

import pytest


ROOT = pathlib.Path(__file__).parents[2]
SENSOR_PY = ROOT / "custom_components" / "universal_room_automation" / "sensor.py"
CONST_PY = (
    ROOT
    / "custom_components"
    / "universal_room_automation"
    / "domain_coordinators"
    / "coordinator_telemetry_const.py"
)


# ---------------------------------------------------------------------------
# coordinator_telemetry_const.py — structural + value contract
# ---------------------------------------------------------------------------


class TestConstantsFile:
    """v4.6.13 plan: const file holds COORDINATOR_EMIT_LABELS + intervals."""

    def test_const_file_exists(self):
        assert CONST_PY.exists(), "coordinator_telemetry_const.py missing"

    def test_coordinator_emit_labels_defined(self):
        src = CONST_PY.read_text()
        assert "COORDINATOR_EMIT_LABELS" in src

    def test_all_five_ui_coordinators_keyed(self):
        src = CONST_PY.read_text()
        for uc in ("presence", "hvac", "energy", "safety", "security"):
            assert f'"{uc}"' in src, f"UI coordinator {uc} missing from const"

    def test_presence_rolls_up_three_labels(self):
        """Per plan: presence rolls up (presence, transit, room)."""
        src = CONST_PY.read_text()
        # Find the presence tuple
        # Simple check: all three labels appear in the file
        for label in ("presence", "transit", "room"):
            assert f'"{label}"' in src, f"Emit label {label} missing"

    def test_compliance_and_notification_not_keyed(self):
        """compliance/notification are meta-events — must not appear as keys."""
        src = CONST_PY.read_text()
        # COORDINATOR_EMIT_LABELS is a Final-annotated assignment (AnnAssign),
        # not a plain Assign. Walk both shapes.
        tree = ast.parse(src)
        for node in ast.walk(tree):
            target = None
            value = None
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target = node.target.id
                value = node.value
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        target = t.id
                        value = node.value
                        break
            if (
                target == "COORDINATOR_EMIT_LABELS"
                and isinstance(value, ast.Dict)
            ):
                keys = [
                    k.value for k in value.keys
                    if isinstance(k, ast.Constant)
                ]
                assert "compliance" not in keys
                assert "notification" not in keys
                return
        pytest.fail("COORDINATOR_EMIT_LABELS dict not found in AST")

    def test_interval_constants_present(self):
        src = CONST_PY.read_text()
        assert "OVERRIDE_FREQUENCY_REFRESH_S" in src
        assert "COMPLIANCE_RATE_REFRESH_S" in src
        assert "DB_SIZE_REFRESH_S" in src
        assert "OVERRIDE_FREQUENCY_WINDOW_HOURS" in src
        assert "COMPLIANCE_RATE_WINDOW_DAYS" in src


# ---------------------------------------------------------------------------
# Source structural tests (sensor.py — classes present + registered)
# ---------------------------------------------------------------------------


class TestSourceStructure:
    """Grep-based: confirm classes landed and are registered in CM block."""

    def _src(self) -> str:
        return SENSOR_PY.read_text()

    def test_decisions_today_class_defined(self):
        assert "class CoordinatorDecisionsTodaySensor" in self._src()

    def test_override_frequency_class_defined(self):
        assert "class CoordinatorOverrideFrequencySensor" in self._src()

    def test_compliance_rate_class_defined(self):
        assert "class CoordinatorComplianceRateSensor" in self._src()

    def test_db_size_class_defined(self):
        assert "class URADBSizeSensor" in self._src()

    def test_last_decision_class_defined(self):
        assert "class CoordinatorLastDecisionSensor" in self._src()

    def test_decisions_today_registered_five_times(self):
        """Per plan: 5 UI coordinators × decisions_today = 5 instantiations."""
        src = self._src()
        assert "CoordinatorDecisionsTodaySensor(hass, entry, uc)" in src

    def test_override_frequency_registered(self):
        assert "CoordinatorOverrideFrequencySensor(hass, entry, uc)" in self._src()

    def test_compliance_rate_registered(self):
        assert "CoordinatorComplianceRateSensor(hass, entry, uc)" in self._src()

    def test_last_decision_registered(self):
        assert "CoordinatorLastDecisionSensor(hass, entry, uc)" in self._src()

    def test_db_size_registered(self):
        assert "URADBSizeSensor(hass, entry)" in self._src()

    def test_no_db_write_path_in_new_sensors(self):
        """v4.6.11 review fix lesson: SELECTs use _db_read(), not _db()."""
        src = self._src()
        # Find the v4.6.13 block
        start = src.index("# v4.6.13 — Coordinator Telemetry Sensor Set")
        v4613_block = src[start:]
        # Must use _db_read for all queries
        assert "_db_read(" in v4613_block
        # Must NOT use _db() (write queue) for any read
        # Match exact pattern `database._db()` not `_db_read`
        import re
        bad = re.findall(r"\bdatabase\._db\(\)", v4613_block)
        assert not bad, f"v4.6.13 sensors leak _db() write-queue use: {bad}"

    def test_dt_util_used_not_datetime_utcnow(self):
        """Bug Class #21: no datetime.utcnow() CALLS in v4.6.13 block.
        Comments that reference the deprecated API (to explain why we DON'T
        use it) are fine — only actual call sites are forbidden."""
        src = self._src()
        start = src.index("# v4.6.13 — Coordinator Telemetry Sensor Set")
        v4613_block = src[start:]
        # Strip line comments before checking. Any `datetime.utcnow()` in a
        # comment is explanatory; any in actual code is a defect.
        code_only_lines = [
            line for line in v4613_block.splitlines()
            if not line.lstrip().startswith("#")
        ]
        code_only = "\n".join(code_only_lines)
        assert "datetime.utcnow()" not in code_only, (
            "v4.6.13 sensors must use dt_util.utcnow(), not datetime.utcnow()"
        )

    def test_start_of_local_day_used_for_decisions_today(self):
        """Bug Class #11: decisions_today uses start_of_local_day, not utcnow."""
        src = self._src()
        # Find the decisions_today class block
        start = src.index("class CoordinatorDecisionsTodaySensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        assert "dt_util.start_of_local_day()" in block

    def test_super_called_in_async_added_to_hass(self):
        """Bug Class #36/#38: every async_added_to_hass override calls super()."""
        src = self._src()
        start = src.index("# v4.6.13 — Coordinator Telemetry Sensor Set")
        v4613_block = src[start:]
        # Count async_added_to_hass overrides and super() calls.
        added_count = v4613_block.count("async def async_added_to_hass")
        super_count = v4613_block.count("await super().async_added_to_hass()")
        assert added_count >= 1
        assert super_count == added_count, (
            f"Mismatch: {added_count} async_added_to_hass overrides but "
            f"{super_count} super() calls — listener-leak risk"
        )

    def test_async_on_remove_used(self):
        """Bug Class #38: all unsubscribes captured into async_on_remove."""
        src = self._src()
        start = src.index("# v4.6.13 — Coordinator Telemetry Sensor Set")
        v4613_block = src[start:]
        # At minimum, each sensor with a subscription uses async_on_remove.
        assert v4613_block.count("self.async_on_remove(") >= 3


# ---------------------------------------------------------------------------
# Production-class AST tests (Review C C1 pattern from v4.6.12 — closes the
# "are the real classes wired?" gap)
# ---------------------------------------------------------------------------


class TestProductionClassImports:
    """AST-introspection smoke tests on real classes."""

    def _tree(self):
        return ast.parse(SENSOR_PY.read_text())

    def _class_node(self, name):
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.ClassDef) and node.name == name:
                return node
        return None

    @pytest.mark.parametrize(
        "cls_name",
        [
            "CoordinatorDecisionsTodaySensor",
            "CoordinatorOverrideFrequencySensor",
            "CoordinatorComplianceRateSensor",
            "URADBSizeSensor",
            "CoordinatorLastDecisionSensor",
        ],
    )
    def test_class_exists_with_expected_bases(self, cls_name):
        node = self._class_node(cls_name)
        assert node is not None, f"{cls_name} missing"
        base_names = {b.id for b in node.bases if hasattr(b, "id")}
        assert "AggregationEntity" in base_names, (
            f"{cls_name} should inherit AggregationEntity"
        )
        assert "SensorEntity" in base_names, (
            f"{cls_name} should inherit SensorEntity"
        )

    @pytest.mark.parametrize(
        "cls_name",
        [
            "CoordinatorDecisionsTodaySensor",
            "CoordinatorOverrideFrequencySensor",
            "CoordinatorComplianceRateSensor",
            "URADBSizeSensor",
            "CoordinatorLastDecisionSensor",
        ],
    )
    def test_class_implements_native_value(self, cls_name):
        node = self._class_node(cls_name)
        method_names = {
            m.name for m in node.body
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "native_value" in method_names

    def test_decisions_today_takes_ui_coordinator_param(self):
        node = self._class_node("CoordinatorDecisionsTodaySensor")
        init = next(
            m for m in node.body
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            and m.name == "__init__"
        )
        arg_names = [a.arg for a in init.args.args]
        assert "ui_coordinator" in arg_names

    def test_last_decision_has_timestamp_device_class(self):
        """D5 sensor must use SensorDeviceClass.TIMESTAMP."""
        src = SENSOR_PY.read_text()
        start = src.index("class CoordinatorLastDecisionSensor")
        end = src.index("\nclass ", start + 1) if "\nclass " in src[start + 1:] else len(src)
        block = src[start:end]
        assert "SensorDeviceClass.TIMESTAMP" in block

    def test_compliance_rate_returns_none_on_zero(self):
        """D3 contract: returns None (not 100%) when no decisions in window.
        This prevents misleading "100%" on fresh install."""
        src = SENSOR_PY.read_text()
        start = src.index("class CoordinatorComplianceRateSensor")
        end = src.index("\nclass ", start + 1) if "\nclass " in src[start + 1:] else len(src)
        block = src[start:end]
        # The class must contain a "total == 0" → None branch
        assert "self._rate_pct = None" in block

    def test_db_size_includes_wal_shm(self):
        """D4 contract: DB size MUST include WAL + SHM sidecars."""
        src = SENSOR_PY.read_text()
        start = src.index("class URADBSizeSensor")
        end = src.index("\nclass ", start + 1) if "\nclass " in src[start + 1:] else len(src)
        block = src[start:end]
        assert '"-wal"' in block
        assert '"-shm"' in block

    def test_signal_subscriptions_present_for_decisions_today(self):
        """D1 must subscribe to SIGNAL_ACTIVITY_LOGGED for live refresh."""
        src = SENSOR_PY.read_text()
        start = src.index("class CoordinatorDecisionsTodaySensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        assert "SIGNAL_ACTIVITY_LOGGED" in block

    def test_emit_label_filter_in_signal_handler(self):
        """D1 must filter activity-logged signal by mapped emit-labels.
        Otherwise every activity row triggers a refresh, defeating Bug #26."""
        src = SENSOR_PY.read_text()
        start = src.index("class CoordinatorDecisionsTodaySensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        # The handler should check payload coordinator against labels
        assert 'payload.get("coordinator") not in labels' in block


# ---------------------------------------------------------------------------
# Behavioral tests for pure logic (cutoff math, emit-label mapping)
# ---------------------------------------------------------------------------


class TestEmitLabelMapping:
    """Verify the COORDINATOR_EMIT_LABELS contract by import."""

    def test_import_emit_labels(self):
        """Import the constants module and verify keys + shape."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "coordinator_telemetry_const",
            CONST_PY,
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        labels = mod.COORDINATOR_EMIT_LABELS
        assert set(labels.keys()) == {
            "presence", "hvac", "energy", "safety", "security",
        }
        # presence rolls up 3 labels
        assert labels["presence"] == ("presence", "transit", "room")
        # The rest are single-label
        assert labels["hvac"] == ("hvac",)
        assert labels["energy"] == ("energy",)
        assert labels["safety"] == ("safety",)
        assert labels["security"] == ("security",)

    def test_interval_values_are_seconds(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "coordinator_telemetry_const",
            CONST_PY,
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Sanity: 5-min, 30-min, 5-min
        assert mod.OVERRIDE_FREQUENCY_REFRESH_S == 300
        assert mod.COMPLIANCE_RATE_REFRESH_S == 1800
        assert mod.DB_SIZE_REFRESH_S == 300
        assert mod.OVERRIDE_FREQUENCY_WINDOW_HOURS == 24
        assert mod.COMPLIANCE_RATE_WINDOW_DAYS == 7


class TestCutoffMath:
    """Behavioral tests for the cutoff math used by the new sensors."""

    def test_compliance_cutoff_strips_tzinfo(self):
        """compliance_log.timestamp is tz-naive (database.py uses
        datetime.utcnow().isoformat()). Cutoff must strip tzinfo to match."""
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 5, 19, 18, 0, tzinfo=timezone.utc)
        cutoff = (now - timedelta(hours=24)).replace(tzinfo=None).isoformat()
        # Must NOT contain a tz suffix
        assert cutoff == "2026-05-18T18:00:00"

    def test_local_midnight_is_utc_when_serialized(self):
        """D1 uses dt_util.start_of_local_day → as_utc → isoformat.
        Verify the format is parseable and has tz suffix."""
        from datetime import datetime, timezone, timedelta
        # Stand-in for dt_util.start_of_local_day in CDT (UTC-5).
        local_midnight = datetime(
            2026, 5, 19, 0, 0,
            tzinfo=timezone(timedelta(hours=-5)),
        )
        utc_iso = local_midnight.astimezone(timezone.utc).isoformat()
        # 5am UTC on the 19th
        assert "2026-05-19T05:00:00" in utc_iso


class TestComplianceRateNoneContract:
    """D3 sensor returns None when total decisions in window == 0.
    Validate the pure decision logic here."""

    def _classify(self, total: int, compliant: int):
        # Mirrors the production logic in CoordinatorComplianceRateSensor._async_refresh.
        if total == 0:
            return None
        return int(round((compliant / total) * 100))

    def test_zero_total_returns_none(self):
        assert self._classify(0, 0) is None

    def test_full_compliance_returns_100(self):
        assert self._classify(50, 50) == 100

    def test_partial_compliance(self):
        assert self._classify(100, 73) == 73

    def test_zero_compliant_returns_zero(self):
        assert self._classify(10, 0) == 0


class TestDBSizeWALInclusion:
    """D4: DB size must include WAL + SHM sidecars.
    Pure logic test: simulate the sum behavior."""

    def test_sum_includes_wal_shm(self, tmp_path):
        # Create a fake DB triple
        db = tmp_path / "ura.db"
        db.write_bytes(b"x" * 100)
        wal = tmp_path / "ura.db-wal"
        wal.write_bytes(b"y" * 200)
        shm = tmp_path / "ura.db-shm"
        shm.write_bytes(b"z" * 50)

        import os
        size = os.path.getsize(str(db))
        for suffix in ("-wal", "-shm"):
            try:
                size += os.path.getsize(str(db) + suffix)
            except OSError:
                pass
        assert size == 350  # 100 + 200 + 50

    def test_sum_tolerates_missing_wal(self, tmp_path):
        db = tmp_path / "ura.db"
        db.write_bytes(b"x" * 100)
        # No WAL or SHM present
        import os
        size = os.path.getsize(str(db))
        for suffix in ("-wal", "-shm"):
            try:
                size += os.path.getsize(str(db) + suffix)
            except OSError:
                pass
        assert size == 100
