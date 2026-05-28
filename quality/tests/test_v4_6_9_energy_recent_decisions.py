"""Tests for v4.6.9 D3 — EnergyRecentDecisionsSensor (decision stream timeline).

Mandatory test names from plan acceptance criteria:
  - test_recent_decisions_empty_buffer_reports_zero
  - test_recent_decisions_caps_at_20
  - test_recent_decisions_attrs_shape_flat
  - test_recent_decisions_timestamp_iso_utc

Additional behavioral tests:
  - test_record_decision_appends_to_buffer
  - test_24h_count_filters_old_entries
  - test_decisions_ordered_newest_first

Bug-class guards exercised:
  #11  (timezone — all timestamps UTC ISO 8601)
  #22  (tou_period from _VALID_PERIODS — not redefined here)
  #25  (bounded list — deque(maxlen=20) hard cap)
  #29  (empty-buffer branch: state=0, decisions=[], last_action_at_iso=None)
  #37  (stable attribute shape — both keys always present)
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup — run from quality/ with PYTHONPATH=quality
# ---------------------------------------------------------------------------
ROOT = pathlib.Path(__file__).parents[2]
ENERGY_PY = (
    ROOT
    / "custom_components"
    / "universal_room_automation"
    / "domain_coordinators"
    / "energy.py"
)
SENSOR_PY = ROOT / "custom_components" / "universal_room_automation" / "sensor.py"

# Stub heavy HA deps before any integration import
_HA_STUBS: dict = {
    "homeassistant": MagicMock(),
    "homeassistant.core": MagicMock(),
    "homeassistant.config_entries": MagicMock(),
    "homeassistant.helpers": MagicMock(),
    "homeassistant.helpers.update_coordinator": MagicMock(),
    "homeassistant.helpers.restore_state": MagicMock(),
    "homeassistant.helpers.dispatcher": MagicMock(),
    "homeassistant.helpers.entity": MagicMock(),
    "homeassistant.helpers.entity_platform": MagicMock(),
    "homeassistant.helpers.event": MagicMock(),
    "homeassistant.helpers.device_registry": MagicMock(),
    "homeassistant.components.sensor": MagicMock(),
    "homeassistant.components.button": MagicMock(),
    "homeassistant.components.binary_sensor": MagicMock(),
    "homeassistant.util": MagicMock(),
    "homeassistant.util.dt": MagicMock(),
    "homeassistant.const": MagicMock(),
}
for _k, _v in _HA_STUBS.items():
    sys.modules.setdefault(_k, _v)

sys.modules["homeassistant.const"].STATE_UNAVAILABLE = "unavailable"

# Configure dt_util stub so _record_decision gets a real UTC timestamp
_dt_stub = sys.modules["homeassistant.util.dt"]
_dt_stub.utcnow = lambda: datetime.now(timezone.utc)
_dt_stub.now = lambda: datetime.now(timezone.utc)

# ---------------------------------------------------------------------------
# Helpers: build a minimal EnergyCoordinator-like object with the real methods
# ---------------------------------------------------------------------------

def _build_coordinator(now_override: datetime | None = None) -> MagicMock:
    """Build a mock object that runs the real _record_decision / get_recent_decisions
    method bodies from energy.py source.

    We exec the two method bodies against a self-contained exec environment so:
    - dt_util is injected directly into exec_globals (never pulled from sys.modules)
    - each coordinator instance has its own fixed "now" for reproducible tests
    """
    import logging
    import types

    src = ENERGY_PY.read_text()

    # Extract _record_decision
    rec_start = src.index("    def _record_decision(")
    rec_end = src.index("\n    def get_recent_decisions(", rec_start)
    rec_src = src[rec_start:rec_end]

    # Extract get_recent_decisions
    get_start = src.index("    def get_recent_decisions(")
    get_end = src.index("\n    def _build_entity_map(", get_start)
    get_src = src[get_start:get_end]

    # Strip 4-space class-body indent to make them module-level functions
    def _strip_indent(method_src: str) -> str:
        lines = method_src.splitlines()
        return "\n".join(l[4:] if len(l) >= 4 else l for l in lines) + "\n"

    rec_func_src = _strip_indent(rec_src)
    get_func_src = _strip_indent(get_src)

    # Fixed "now" for this coordinator instance
    effective_now = now_override or datetime.now(timezone.utc)

    # Self-contained dt_util shim — NOT stored in sys.modules so parallel
    # coordinator builds don't clobber each other.
    class _DtUtil:
        @staticmethod
        def utcnow() -> datetime:
            return effective_now

        @staticmethod
        def now() -> datetime:
            return effective_now

    dt_util_shim = _DtUtil()

    # The method bodies do `from homeassistant.util import dt as dt_util` —
    # we rewrite those lines to a no-op and inject dt_util directly instead.
    # Simpler: provide dt_util in exec_globals so the name is already bound
    # when the import statement runs (Python resolves the name from globals
    # before hitting the import machinery for `from X import Y as Z` when Z
    # is already in globals? No — that's not how it works). Instead we patch
    # sys.modules locally for the duration of the exec, then restore it.
    dt_mod = types.ModuleType("homeassistant.util.dt")
    dt_mod.utcnow = _DtUtil.utcnow
    dt_mod.now = _DtUtil.now

    # Also patch homeassistant.util so `from homeassistant.util import dt` works
    ha_util_mod = types.ModuleType("homeassistant.util")
    ha_util_mod.dt = dt_mod

    old_dt = sys.modules.get("homeassistant.util.dt")
    old_util = sys.modules.get("homeassistant.util")
    sys.modules["homeassistant.util.dt"] = dt_mod
    sys.modules["homeassistant.util"] = ha_util_mod

    exec_globals: dict = {
        "datetime": datetime,
        "timezone": timezone,
        "timedelta": timedelta,
        "Any": object,
        "_LOGGER": logging.getLogger("test.energy"),
    }

    try:
        exec(compile(rec_func_src, "<_record_decision>", "exec"), exec_globals)
        exec(compile(get_func_src, "<get_recent_decisions>", "exec"), exec_globals)
    finally:
        # Restore sys.modules to not pollute other tests
        if old_dt is not None:
            sys.modules["homeassistant.util.dt"] = old_dt
        elif "homeassistant.util.dt" in sys.modules:
            del sys.modules["homeassistant.util.dt"]
        if old_util is not None:
            sys.modules["homeassistant.util"] = old_util
        elif "homeassistant.util" in sys.modules:
            del sys.modules["homeassistant.util"]

    coord = MagicMock()
    coord._decision_buffer = collections.deque(maxlen=20)
    coord._LOGGER = logging.getLogger("test.energy")

    # Mock TOU engine: default "off_peak"; tests override as needed
    coord._tou = MagicMock()
    coord._tou.get_current_period.return_value = "off_peak"

    # Each call to _record_decision / get_recent_decisions re-installs the
    # dt shim for the duration of the call so the correct "now" is used.
    def _call_with_shim(fn, *args, **kwargs):
        old_dt2 = sys.modules.get("homeassistant.util.dt")
        old_util2 = sys.modules.get("homeassistant.util")
        sys.modules["homeassistant.util.dt"] = dt_mod
        sys.modules["homeassistant.util"] = ha_util_mod
        try:
            return fn(*args, **kwargs)
        finally:
            if old_dt2 is not None:
                sys.modules["homeassistant.util.dt"] = old_dt2
            elif "homeassistant.util.dt" in sys.modules:
                del sys.modules["homeassistant.util.dt"]
            if old_util2 is not None:
                sys.modules["homeassistant.util"] = old_util2
            elif "homeassistant.util" in sys.modules:
                del sys.modules["homeassistant.util"]

    _rec_fn = exec_globals["_record_decision"]
    _get_fn = exec_globals["get_recent_decisions"]

    coord._record_decision = lambda action, reason, target_entity=None: (
        _call_with_shim(_rec_fn, coord, action, reason, target_entity)
    )
    coord.get_recent_decisions = lambda: _call_with_shim(_get_fn, coord)

    return coord


# ---------------------------------------------------------------------------
# Structural tests: source file shape
# ---------------------------------------------------------------------------

class TestSourceStructure:
    """Confirm class, registration, and coordinator method exist in source."""

    def _sensor_src(self) -> str:
        return SENSOR_PY.read_text()

    def _energy_src(self) -> str:
        return ENERGY_PY.read_text()

    def test_energy_recent_decisions_sensor_class_defined(self):
        assert "class EnergyRecentDecisionsSensor" in self._sensor_src()

    def test_sensor_registered_in_cm_block(self):
        src = self._sensor_src()
        assert "EnergyRecentDecisionsSensor(hass, entry)" in src

    def test_get_recent_decisions_method_defined(self):
        assert "def get_recent_decisions" in self._energy_src()

    def test_record_decision_method_defined(self):
        assert "def _record_decision" in self._energy_src()

    def test_decision_buffer_is_deque_maxlen_20(self):
        """Bug Class #25: ring buffer must use deque(maxlen=20)."""
        src = self._energy_src()
        assert "deque(maxlen=20)" in src

    def test_timestamp_uses_utcnow(self):
        """Bug Class #11: timestamps must come from dt_util.utcnow()."""
        src = self._energy_src()
        start = src.index("def _record_decision(")
        end = src.index("\n    def get_recent_decisions(", start)
        block = src[start:end]
        assert "dt_util.utcnow()" in block, (
            "_record_decision must use dt_util.utcnow() for timestamps (Bug Class #11)"
        )

    def test_timestamp_uses_isoformat(self):
        """Bug Class #11: timestamp stored as ISO string, not datetime object."""
        src = self._energy_src()
        start = src.index("def _record_decision(")
        end = src.index("\n    def get_recent_decisions(", start)
        block = src[start:end]
        assert ".isoformat()" in block

    def test_attr_keys_in_sensor_extra_state_attributes(self):
        """Bug Class #37: stable shape — both contract keys always present."""
        src = self._sensor_src()
        start = src.index("class EnergyRecentDecisionsSensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        for key in ("decisions", "last_action_at_iso"):
            assert f'"{key}"' in block, f"Contract key {key!r} missing"

    def test_native_value_returns_int_zero_on_empty(self):
        """Bug Class #29: state returns int 0 (not None/unknown/str) when empty."""
        src = self._sensor_src()
        start = src.index("class EnergyRecentDecisionsSensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        assert "return 0" in block, (
            "native_value must return literal 0 when data is None (empty buffer)"
        )

    def test_async_added_to_hass_calls_super(self):
        """Bug Class #1: lifecycle super() call must be present."""
        src = self._sensor_src()
        start = src.index("class EnergyRecentDecisionsSensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        assert "await super().async_added_to_hass()" in block

    def test_signal_energy_entities_update_subscribed(self):
        """Sensor must subscribe to SIGNAL_ENERGY_ENTITIES_UPDATE for live updates."""
        src = self._sensor_src()
        start = src.index("class EnergyRecentDecisionsSensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        assert "SIGNAL_ENERGY_ENTITIES_UPDATE" in block

    def test_no_async_create_task_in_sensor(self):
        """Bug Class #19: no untracked background tasks in sensor."""
        src = self._sensor_src()
        start = src.index("class EnergyRecentDecisionsSensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        assert "async_create_task" not in block

    def test_record_decision_calls_present_in_async_decision_cycle(self):
        """At least 2 _record_decision calls wired in _async_decision_cycle."""
        src = self._energy_src()
        start = src.index("async def _async_decision_cycle(")
        end = src.index("\n    async def _evaluate_battery(", start)
        block = src[start:end]
        count = block.count("self._record_decision(")
        assert count >= 2, (
            f"Expected ≥2 _record_decision calls in _async_decision_cycle, found {count}"
        )

    def test_record_decision_call_in_update_load_shedding(self):
        """_update_load_shedding must instrument load_shed_escalate."""
        src = self._energy_src()
        start = src.index("def _update_load_shedding(")
        end = src.index("\n    def _execute_shed_action(", start)
        block = src[start:end]
        assert "self._record_decision(" in block

    def test_record_decision_call_in_update_hvac_constraint(self):
        """_update_hvac_constraint must instrument hvac_constraint changes."""
        src = self._energy_src()
        start = src.index("def _update_hvac_constraint(")
        end = src.index("\n    def _update_energy_situation(", start)
        block = src[start:end]
        assert "self._record_decision(" in block

    def test_tou_period_from_existing_engine_not_redefined(self):
        """Bug Class #22: _record_decision reads from self._tou — never redefines vocab."""
        src = self._energy_src()
        start = src.index("def _record_decision(")
        end = src.index("\n    def get_recent_decisions(", start)
        block = src[start:end]
        # Must reference the engine, not a local literal set
        assert "self._tou.get_current_period()" in block, (
            "_record_decision must read tou_period from self._tou.get_current_period() "
            "(Bug Class #22 — reuse existing vocabulary, do not redefine)"
        )

    def test_collections_import_added(self):
        """deque requires 'import collections' in energy.py."""
        src = self._energy_src()
        assert "import collections" in src


# ---------------------------------------------------------------------------
# Mandatory behavioral tests (plan acceptance criteria)
# ---------------------------------------------------------------------------

class TestRecentDecisionsEmptyBufferReportsZero:
    """test_recent_decisions_empty_buffer_reports_zero — Bug Class #29"""

    def test_recent_decisions_empty_buffer_reports_zero(self):
        """Empty buffer → count_24h=0, decisions=[], last_action_at_iso=None."""
        coord = _build_coordinator()
        data = coord.get_recent_decisions()

        assert data["count_24h"] == 0, f"Expected 0, got {data['count_24h']}"
        assert data["decisions"] == [], f"Expected [], got {data['decisions']}"
        assert data["last_action_at_iso"] is None

    def test_empty_buffer_state_is_int_not_string(self):
        """count_24h must be int, not str or None."""
        coord = _build_coordinator()
        data = coord.get_recent_decisions()
        assert isinstance(data["count_24h"], int)

    def test_empty_buffer_decisions_is_list(self):
        """decisions must be list (not None) on empty buffer."""
        coord = _build_coordinator()
        data = coord.get_recent_decisions()
        assert isinstance(data["decisions"], list)


class TestRecentDecisionsCapsAt20:
    """test_recent_decisions_caps_at_20 — Bug Class #25"""

    def test_recent_decisions_caps_at_20(self):
        """Adding 25 entries keeps only the 20 most recent (deque cap)."""
        coord = _build_coordinator()
        for i in range(25):
            coord._record_decision(
                action=f"battery_self_consumption_{i}",
                reason=f"reason_{i}",
                target_entity=None,
            )
        data = coord.get_recent_decisions()
        assert len(data["decisions"]) <= 20, (
            f"Expected ≤20 decisions, got {len(data['decisions'])}"
        )

    def test_cap_at_20_evicts_oldest(self):
        """After 25 inserts, the first 5 are evicted; decision 24 is newest."""
        coord = _build_coordinator()
        for i in range(25):
            coord._record_decision(
                action=f"action_{i}",
                reason=f"reason_{i}",
                target_entity=None,
            )
        data = coord.get_recent_decisions()
        # newest-first → first item is action_24
        assert data["decisions"][0]["action"] == "action_24", (
            f"Expected action_24 as newest, got {data['decisions'][0]['action']}"
        )
        # oldest retained should be action_5
        assert data["decisions"][-1]["action"] == "action_5", (
            f"Expected action_5 as oldest retained, got {data['decisions'][-1]['action']}"
        )

    def test_deque_maxlen_is_20_in_source(self):
        """Bug Class #25: source must declare deque(maxlen=20)."""
        src = ENERGY_PY.read_text()
        assert "deque(maxlen=20)" in src


class TestRecentDecisionsAttrsShapeFlat:
    """test_recent_decisions_attrs_shape_flat — Bug Class #37"""

    def test_recent_decisions_attrs_shape_flat(self):
        """get_recent_decisions() returns a flat dict with exactly 3 keys."""
        coord = _build_coordinator()
        coord._record_decision(action="battery_self_consumption", reason="normal", target_entity=None)
        data = coord.get_recent_decisions()

        required_keys = {"decisions", "count_24h", "last_action_at_iso"}
        assert required_keys.issubset(data.keys()), (
            f"Missing keys: {required_keys - data.keys()}"
        )

    def test_each_decision_entry_has_all_required_keys(self):
        """Each entry in decisions list must have the 5 plan-specified keys."""
        coord = _build_coordinator()
        coord._record_decision(
            action="battery_self_consumption",
            reason="peak TOU",
            target_entity="select.battery_mode",
        )
        data = coord.get_recent_decisions()
        assert len(data["decisions"]) == 1
        entry = data["decisions"][0]

        required = {"timestamp_iso", "action", "reason", "tou_period", "target_entity"}
        assert required.issubset(entry.keys()), (
            f"Missing entry keys: {required - entry.keys()}"
        )

    def test_no_nested_dicts_in_entry(self):
        """Bug Class #37: each decision entry must be a flat dict."""
        coord = _build_coordinator()
        coord._record_decision(action="tou_transition_peak", reason="transition", target_entity=None)
        data = coord.get_recent_decisions()
        for entry in data["decisions"]:
            for key, val in entry.items():
                assert not isinstance(val, dict), (
                    f"Entry key {key!r} must not be a nested dict; got {type(val)}"
                )

    def test_all_entries_json_serializable(self):
        """All entry values must be JSON-serializable (no Decimal, no datetime obj)."""
        from decimal import Decimal
        coord = _build_coordinator()
        coord._record_decision(
            action="hvac_constraint_coast",
            reason="peak TOU",
            target_entity=None,
        )
        data = coord.get_recent_decisions()
        # Must not raise
        json.dumps(data["decisions"])
        # No datetime objects
        for entry in data["decisions"]:
            for val in entry.values():
                assert not isinstance(val, datetime), (
                    f"datetime object found in entry — must use ISO str (Bug Class #11)"
                )
            assert not isinstance(val, Decimal)

    def test_target_entity_none_serializes_as_null(self):
        """target_entity=None must round-trip through JSON as null."""
        coord = _build_coordinator()
        coord._record_decision(action="tou_transition_off_peak", reason="off-peak", target_entity=None)
        data = coord.get_recent_decisions()
        serialized = json.dumps(data["decisions"])
        parsed = json.loads(serialized)
        assert parsed[0]["target_entity"] is None

    def test_target_entity_str_preserved(self):
        """target_entity str is preserved through the buffer."""
        coord = _build_coordinator()
        coord._record_decision(
            action="battery_charge",
            reason="arbitrage",
            target_entity="select.enphase_storage_mode",
        )
        data = coord.get_recent_decisions()
        assert data["decisions"][0]["target_entity"] == "select.enphase_storage_mode"


class TestRecentDecisionsTimestampIsoUtc:
    """test_recent_decisions_timestamp_iso_utc — Bug Class #11"""

    def test_recent_decisions_timestamp_iso_utc(self):
        """Each decision entry's timestamp_iso must be a UTC-aware ISO 8601 string."""
        coord = _build_coordinator()
        coord._record_decision(action="battery_self_consumption", reason="normal", target_entity=None)
        data = coord.get_recent_decisions()

        assert len(data["decisions"]) == 1
        ts_str = data["decisions"][0]["timestamp_iso"]
        assert isinstance(ts_str, str), f"timestamp_iso must be str, got {type(ts_str)}"

        # Must parse as ISO 8601
        parsed = datetime.fromisoformat(ts_str)
        assert parsed.tzinfo is not None, (
            "timestamp_iso must be UTC-aware (has tzinfo), got naive datetime"
        )

    def test_last_action_at_iso_is_str_or_none(self):
        """last_action_at_iso is str when buffer has entries, None when empty."""
        coord_empty = _build_coordinator()
        assert coord_empty.get_recent_decisions()["last_action_at_iso"] is None

        coord_populated = _build_coordinator()
        coord_populated._record_decision(action="battery_charge", reason="arb", target_entity=None)
        val = coord_populated.get_recent_decisions()["last_action_at_iso"]
        assert isinstance(val, str), f"Expected str, got {type(val)}"
        parsed = datetime.fromisoformat(val)
        assert parsed.tzinfo is not None

    def test_timestamp_is_iso_parseable(self):
        """datetime.fromisoformat() must not raise on timestamp_iso."""
        coord = _build_coordinator()
        coord._record_decision(action="load_shed_escalate", reason="sustained import", target_entity=None)
        data = coord.get_recent_decisions()
        ts = data["decisions"][0]["timestamp_iso"]
        # Must not raise
        datetime.fromisoformat(ts)

    def test_timestamp_not_datetime_object(self):
        """Bug Class #11: timestamp_iso must not be a datetime object."""
        coord = _build_coordinator()
        coord._record_decision(action="hvac_constraint_normal", reason="normal", target_entity=None)
        data = coord.get_recent_decisions()
        ts = data["decisions"][0]["timestamp_iso"]
        assert not isinstance(ts, datetime), (
            "timestamp_iso must be str, not datetime object (Bug Class #11)"
        )


# ---------------------------------------------------------------------------
# Additional behavioral tests
# ---------------------------------------------------------------------------

class TestRecordDecisionAppendsToBuffer:
    """test_record_decision_appends_to_buffer"""

    def test_record_decision_appends_to_buffer(self):
        """A _record_decision call adds exactly one entry to the buffer."""
        coord = _build_coordinator()
        assert len(coord._decision_buffer) == 0

        coord._record_decision(action="battery_self_consumption", reason="off-peak", target_entity=None)

        assert len(coord._decision_buffer) == 1

    def test_multiple_calls_grow_buffer(self):
        """Three calls → three entries (up to cap)."""
        coord = _build_coordinator()
        for i in range(3):
            coord._record_decision(action=f"action_{i}", reason=f"r{i}", target_entity=None)
        assert len(coord._decision_buffer) == 3

    def test_entry_action_field_preserved(self):
        """The action string passed to _record_decision is stored verbatim."""
        coord = _build_coordinator()
        coord._record_decision(action="battery_arbitrage_charge", reason="arb window", target_entity=None)
        entry = list(coord._decision_buffer)[0]
        assert entry["action"] == "battery_arbitrage_charge"

    def test_entry_reason_field_preserved(self):
        """The reason string is stored verbatim in the buffer entry."""
        coord = _build_coordinator()
        coord._record_decision(action="tou_transition_peak", reason="entering peak period", target_entity=None)
        entry = list(coord._decision_buffer)[0]
        assert entry["reason"] == "entering peak period"

    def test_tou_period_from_engine(self):
        """tou_period in entry comes from self._tou.get_current_period()."""
        coord = _build_coordinator()
        coord._tou.get_current_period.return_value = "peak"
        coord._record_decision(action="battery_backup", reason="peak", target_entity=None)
        entry = list(coord._decision_buffer)[0]
        assert entry["tou_period"] == "peak"

    def test_tou_period_values_are_from_valid_set(self):
        """tou_period must be one of peak | mid_peak | off_peak (Bug Class #22)."""
        valid_periods = {"peak", "mid_peak", "off_peak"}
        coord = _build_coordinator()
        for p in valid_periods:
            coord._tou.get_current_period.return_value = p
            coord._record_decision(action=f"tou_{p}", reason="test", target_entity=None)

        for entry in coord._decision_buffer:
            assert entry["tou_period"] in valid_periods, (
                f"tou_period {entry['tou_period']!r} not in valid set {valid_periods}"
            )


class Test24hCountFiltersOldEntries:
    """test_24h_count_filters_old_entries — entries older than 24h not counted in state."""

    def test_24h_count_filters_old_entries(self):
        """Entries older than 24h are excluded from count_24h but stay in buffer."""
        now = datetime.now(timezone.utc)
        # Use 30h so there's no boundary ambiguity (cutoff is now-24h; old entry
        # is now-30h, clearly before cutoff; recent entry is now-1h, clearly after)
        old_time = now - timedelta(hours=30)
        recent_time = now - timedelta(hours=1)

        # Record the old entry using a coordinator anchored to old_time
        coord_old = _build_coordinator(now_override=old_time)
        coord_old._record_decision(action="old_battery_action", reason="old", target_entity=None)
        old_entry = list(coord_old._decision_buffer)[0]

        # Build a coordinator anchored to "now" to evaluate with a real cutoff
        coord_eval = _build_coordinator(now_override=now)
        # Manually inject old entry first, then a recent entry
        coord_eval._decision_buffer.append(old_entry)
        coord_eval._record_decision(action="recent_battery_action", reason="recent", target_entity=None)

        data = coord_eval.get_recent_decisions()

        # Buffer has 2 entries
        assert len(data["decisions"]) == 2, f"Expected 2 entries, got {len(data['decisions'])}"

        # count_24h should only count the recent entry (within 24h of now)
        assert data["count_24h"] == 1, (
            f"Expected count_24h=1 (only recent entry), got {data['count_24h']}"
        )

    def test_all_entries_within_24h_all_counted(self):
        """All recent entries are counted in count_24h."""
        now = datetime.now(timezone.utc)
        coord = _build_coordinator(now_override=now)
        for i in range(5):
            coord._record_decision(action=f"action_{i}", reason=f"r{i}", target_entity=None)
        data = coord.get_recent_decisions()
        assert data["count_24h"] == 5

    def test_all_entries_old_count_is_zero(self):
        """All entries older than 24h → count_24h=0, but decisions list still has entries."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=30)
        real_now = datetime.now(timezone.utc)

        # Build a coordinator that records entries with an old timestamp
        coord_old = _build_coordinator(now_override=old_time)
        coord_old._record_decision(action="old_action", reason="old", target_entity=None)

        # Build a second coordinator anchored to real_now to evaluate the buffer
        coord_now = _build_coordinator(now_override=real_now)
        # Transfer the old entry into the new coordinator's buffer
        coord_now._decision_buffer.extend(coord_old._decision_buffer)

        data = coord_now.get_recent_decisions()
        assert data["count_24h"] == 0, (
            f"Expected count_24h=0 for entries older than 24h, got {data['count_24h']}"
        )
        # Entry still in buffer (not evicted — eviction only at maxlen)
        assert len(data["decisions"]) == 1


class TestDecisionsOrderedNewestFirst:
    """test_decisions_ordered_newest_first — list is reversed so newest is index 0."""

    def test_decisions_ordered_newest_first(self):
        """decisions list must be newest-first (reverse chronological)."""
        coord = _build_coordinator()
        for i in range(3):
            coord._record_decision(action=f"action_{i}", reason=f"r{i}", target_entity=None)

        data = coord.get_recent_decisions()
        decisions = data["decisions"]

        assert len(decisions) == 3
        # newest first — action_2 was added last
        assert decisions[0]["action"] == "action_2", (
            f"Expected action_2 as newest (index 0), got {decisions[0]['action']}"
        )
        assert decisions[-1]["action"] == "action_0", (
            f"Expected action_0 as oldest (last), got {decisions[-1]['action']}"
        )

    def test_newest_first_after_cap(self):
        """After cap rollover, newest is still at index 0."""
        coord = _build_coordinator()
        for i in range(22):
            coord._record_decision(action=f"a_{i}", reason="r", target_entity=None)
        data = coord.get_recent_decisions()
        assert data["decisions"][0]["action"] == "a_21"
        assert data["decisions"][-1]["action"] == "a_2"

    def test_last_action_at_iso_matches_newest_entry(self):
        """last_action_at_iso must equal the timestamp of the newest decision."""
        coord = _build_coordinator()
        coord._record_decision(action="first", reason="r", target_entity=None)
        coord._record_decision(action="second", reason="r", target_entity=None)
        data = coord.get_recent_decisions()
        # decisions[0] is newest
        assert data["last_action_at_iso"] == data["decisions"][0]["timestamp_iso"]

    def test_single_entry_is_both_first_and_last(self):
        """With one entry, decisions[0] is both newest and oldest."""
        coord = _build_coordinator()
        coord._record_decision(action="only_action", reason="r", target_entity=None)
        data = coord.get_recent_decisions()
        assert len(data["decisions"]) == 1
        assert data["decisions"][0]["action"] == "only_action"
        assert data["last_action_at_iso"] == data["decisions"][0]["timestamp_iso"]


class TestTouPeriodVocabularyBugClass22:
    """Bug Class #22: tou_period must come from existing TOURateEngine vocab."""

    def test_all_three_valid_periods_stored_correctly(self):
        """peak, mid_peak, off_peak each store correctly in the buffer."""
        valid = ["peak", "mid_peak", "off_peak"]
        coord = _build_coordinator()
        for p in valid:
            coord._tou.get_current_period.return_value = p
            coord._record_decision(action=f"action_{p}", reason="test", target_entity=None)

        stored = {e["tou_period"] for e in coord._decision_buffer}
        assert stored == set(valid)

    def test_tou_engine_exception_falls_back_to_off_peak(self):
        """If TOU engine raises, _record_decision falls back to 'off_peak'."""
        coord = _build_coordinator()
        coord._tou.get_current_period.side_effect = Exception("TOU engine error")
        coord._record_decision(action="battery_unknown", reason="fallback test", target_entity=None)
        entry = list(coord._decision_buffer)[0]
        assert entry["tou_period"] == "off_peak", (
            f"Expected fallback 'off_peak', got {entry['tou_period']!r}"
        )
