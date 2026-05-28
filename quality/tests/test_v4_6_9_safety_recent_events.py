"""Tests for v4.6.9 D5 — SafetyRecentEventsSensor (recent-events ring buffer).

Mandatory test names from plan acceptance criteria:
  - test_recent_events_empty_returns_zero_state
  - test_recent_events_caps_at_20
  - test_recent_events_severity_breakdown_sums_match
  - test_recent_events_attrs_shape_flat

Additional behavioral tests:
  - test_record_event_appends_to_buffer
  - test_24h_filter_excludes_old_from_count
  - test_events_ordered_newest_first
  - test_severity_breakdown_all_four_keys_present

Bug-class guards exercised:
  #11  (timezone — all timestamps UTC ISO 8601)
  #22  (severity from EventSeverity StrEnum — info|advisory|alert|critical)
  #25  (bounded list — deque(maxlen=20) hard cap)
  #29  (empty-buffer branch: state=0, events=[], last_event_at_iso=None)
  #37  (stable attribute shape — events, last_event_at_iso, severity_breakdown
        always present)
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys
import types
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path setup — run from quality/ with PYTHONPATH=quality
# ---------------------------------------------------------------------------
ROOT = pathlib.Path(__file__).parents[2]
SAFETY_PY = (
    ROOT
    / "custom_components"
    / "universal_room_automation"
    / "domain_coordinators"
    / "safety.py"
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

# Configure dt_util stub so _record_event gets a real UTC timestamp
_dt_stub = sys.modules["homeassistant.util.dt"]
_dt_stub.utcnow = lambda: datetime.now(timezone.utc)
_dt_stub.now = lambda: datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Minimal Severity enum (mirrors base.py) for use in tests without importing
# the full integration.
# ---------------------------------------------------------------------------
from enum import IntEnum


class _Severity(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


# ---------------------------------------------------------------------------
# Helpers: build a minimal SafetyCoordinator-like object with the real methods
# ---------------------------------------------------------------------------

def _build_coordinator(now_override: datetime | None = None) -> MagicMock:
    """Build a mock that runs the real _record_event / get_recent_events
    method bodies from safety.py source.

    Strategy mirrors the D3 test pattern:
    - Extract method source text from the file.
    - Strip class-body indent.
    - exec() into an isolated globals dict.
    - Patch dt_util in sys.modules for the duration of each call so the
      correct "now" is used without polluting other tests.
    """
    import logging

    src = SAFETY_PY.read_text()

    # ── Extract EventSeverity class body ──────────────────────────────────
    # We need EventSeverity.from_severity() to be available in exec_globals.
    ev_start = src.index("class EventSeverity(StrEnum):")
    ev_end = src.index("\nclass HazardType(StrEnum):", ev_start)
    ev_src = src[ev_start:ev_end]

    # ── Extract _record_event ─────────────────────────────────────────────
    rec_start = src.index("    def _record_event(")
    rec_end = src.index("\n    def get_recent_events(", rec_start)
    rec_src = src[rec_start:rec_end]

    # ── Extract get_recent_events ─────────────────────────────────────────
    get_start = src.index("    def get_recent_events(")
    get_end = src.index("\n    # =========================================================================\n    # Setup", get_start)
    get_src = src[get_start:get_end]

    def _strip_indent(method_src: str) -> str:
        """Strip 4-space class-body indent."""
        lines = method_src.splitlines()
        return "\n".join(l[4:] if len(l) >= 4 else l for l in lines) + "\n"

    rec_func_src = _strip_indent(rec_src)
    get_func_src = _strip_indent(get_src)

    # Fixed "now" for this coordinator instance
    effective_now = now_override or datetime.now(timezone.utc)

    # dt_util shim — self-contained, does not modify sys.modules persistently
    class _DtUtil:
        @staticmethod
        def utcnow() -> datetime:
            return effective_now

        @staticmethod
        def now() -> datetime:
            return effective_now

    dt_mod = types.ModuleType("homeassistant.util.dt")
    dt_mod.utcnow = _DtUtil.utcnow
    dt_mod.now = _DtUtil.now

    ha_util_mod = types.ModuleType("homeassistant.util")
    ha_util_mod.dt = dt_mod

    def _with_shim(fn, *args, **kwargs):
        """Install dt shim for the duration of a call, then restore."""
        old_dt = sys.modules.get("homeassistant.util.dt")
        old_util = sys.modules.get("homeassistant.util")
        sys.modules["homeassistant.util.dt"] = dt_mod
        sys.modules["homeassistant.util"] = ha_util_mod
        try:
            return fn(*args, **kwargs)
        finally:
            if old_dt is not None:
                sys.modules["homeassistant.util.dt"] = old_dt
            elif "homeassistant.util.dt" in sys.modules:
                del sys.modules["homeassistant.util.dt"]
            if old_util is not None:
                sys.modules["homeassistant.util"] = old_util
            elif "homeassistant.util" in sys.modules:
                del sys.modules["homeassistant.util"]

    # Build a minimal StrEnum for exec_globals
    try:
        from enum import StrEnum as _StrEnum
    except ImportError:
        from enum import Enum

        class _StrEnum(str, Enum):  # type: ignore[no-redef]
            pass

    # Severity stub matching the base.py IntEnum (needed by from_severity)
    class _SevStub(IntEnum):
        LOW = 1
        MEDIUM = 2
        HIGH = 3
        CRITICAL = 4

    exec_globals: dict = {
        "StrEnum": _StrEnum,
        "Severity": _SevStub,
        "datetime": datetime,
        "timezone": timezone,
        "timedelta": timedelta,
        "deque": collections.deque,
        "Any": object,
        "dt_util": dt_mod,
        "_LOGGER": logging.getLogger("test.safety"),
    }

    # Install shim while exec'ing so any import inside the method body resolves
    old_dt = sys.modules.get("homeassistant.util.dt")
    old_util = sys.modules.get("homeassistant.util")
    sys.modules["homeassistant.util.dt"] = dt_mod
    sys.modules["homeassistant.util"] = ha_util_mod
    try:
        exec(compile(ev_src, "<EventSeverity>", "exec"), exec_globals)
        exec(compile(rec_func_src, "<_record_event>", "exec"), exec_globals)
        exec(compile(get_func_src, "<get_recent_events>", "exec"), exec_globals)
    finally:
        if old_dt is not None:
            sys.modules["homeassistant.util.dt"] = old_dt
        elif "homeassistant.util.dt" in sys.modules:
            del sys.modules["homeassistant.util.dt"]
        if old_util is not None:
            sys.modules["homeassistant.util"] = old_util
        elif "homeassistant.util" in sys.modules:
            del sys.modules["homeassistant.util"]

    EventSeverity = exec_globals["EventSeverity"]
    _rec_fn = exec_globals["_record_event"]
    _get_fn = exec_globals["get_recent_events"]

    coord = MagicMock()
    coord._event_buffer = collections.deque(maxlen=20)
    coord._LOGGER = exec_globals["_LOGGER"]

    coord._record_event = lambda event_type, room, severity: (
        _with_shim(_rec_fn, coord, event_type, room, severity)
    )
    coord.get_recent_events = lambda: _with_shim(_get_fn, coord)

    # Expose EventSeverity and the internal Severity stub on the coord for test assertions
    coord._EventSeverity = EventSeverity
    coord._Severity = _SevStub

    return coord


# ---------------------------------------------------------------------------
# Structural tests: source file shape
# ---------------------------------------------------------------------------

class TestSourceStructure:
    """Confirm class, method, and registration exist in source."""

    def _safety_src(self) -> str:
        return SAFETY_PY.read_text()

    def _sensor_src(self) -> str:
        return SENSOR_PY.read_text()

    def test_safety_recent_events_sensor_class_defined(self):
        assert "class SafetyRecentEventsSensor" in self._sensor_src()

    def test_sensor_registered_in_cm_block(self):
        src = self._sensor_src()
        assert "SafetyRecentEventsSensor(hass, entry)" in src

    def test_get_recent_events_method_defined(self):
        assert "def get_recent_events" in self._safety_src()

    def test_record_event_method_defined(self):
        assert "def _record_event" in self._safety_src()

    def test_event_buffer_is_deque_maxlen_20(self):
        """Bug Class #25: ring buffer must use deque(maxlen=20)."""
        src = self._safety_src()
        assert "_event_buffer" in src
        # The deque(maxlen=20) declaration must be present
        assert "deque(maxlen=20)" in src

    def test_event_severity_strenum_defined(self):
        """Bug Class #22: EventSeverity StrEnum must define the four PWA values."""
        src = self._safety_src()
        assert "class EventSeverity(StrEnum):" in src
        for val in ("info", "advisory", "alert", "critical"):
            assert f'"{val}"' in src, f"EventSeverity missing value {val!r}"

    def test_timestamp_uses_utcnow(self):
        """Bug Class #11: timestamps must come from dt_util.utcnow()."""
        src = self._safety_src()
        start = src.index("def _record_event(")
        end = src.index("\n    def get_recent_events(", start)
        block = src[start:end]
        assert "dt_util.utcnow()" in block, (
            "_record_event must use dt_util.utcnow() for timestamps (Bug Class #11)"
        )

    def test_timestamp_uses_isoformat(self):
        """Bug Class #11: timestamp stored as ISO string, not datetime object."""
        src = self._safety_src()
        start = src.index("def _record_event(")
        end = src.index("\n    def get_recent_events(", start)
        block = src[start:end]
        assert ".isoformat()" in block

    def test_severity_uses_event_severity_from_severity(self):
        """Bug Class #22: _record_event must use EventSeverity.from_severity()."""
        src = self._safety_src()
        start = src.index("def _record_event(")
        end = src.index("\n    def get_recent_events(", start)
        block = src[start:end]
        assert "EventSeverity.from_severity(" in block, (
            "_record_event must convert severity via EventSeverity.from_severity() "
            "(Bug Class #22 — never redefine vocabulary at call sites)"
        )

    def test_respond_to_hazard_calls_record_event(self):
        """_respond_to_hazard must instrument the ring buffer on new hazards."""
        src = self._safety_src()
        start = src.index("async def _respond_to_hazard(")
        end = src.index("\n    def _critical_response(", start)
        block = src[start:end]
        assert "self._record_event(" in block, (
            "_respond_to_hazard must call self._record_event() to populate "
            "the ring buffer (D5 instrumentation)"
        )

    def test_attr_keys_in_sensor_extra_state_attributes(self):
        """Bug Class #37: stable shape — all contract keys always present."""
        src = self._sensor_src()
        start = src.index("class SafetyRecentEventsSensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        for key in ("events", "last_event_at_iso", "severity_breakdown"):
            assert f'"{key}"' in block, f"Contract key {key!r} missing from sensor attrs"

    def test_native_value_returns_int_zero_on_empty(self):
        """Bug Class #29: state returns int 0 (not None/unknown/str) when empty."""
        src = self._sensor_src()
        start = src.index("class SafetyRecentEventsSensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        assert "return 0" in block, (
            "native_value must return literal 0 when data is None (empty buffer)"
        )

    def test_async_added_to_hass_calls_super(self):
        """Bug Class #1: lifecycle super() call must be present."""
        src = self._sensor_src()
        start = src.index("class SafetyRecentEventsSensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        assert "await super().async_added_to_hass()" in block

    def test_signal_safety_entities_update_subscribed(self):
        """Sensor must subscribe to SIGNAL_SAFETY_ENTITIES_UPDATE for live updates."""
        src = self._sensor_src()
        start = src.index("class SafetyRecentEventsSensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        assert "SIGNAL_SAFETY_ENTITIES_UPDATE" in block

    def test_no_async_create_task_in_sensor(self):
        """Bug Class #19: no untracked background tasks in sensor."""
        src = self._sensor_src()
        start = src.index("class SafetyRecentEventsSensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        assert "async_create_task" not in block

    def test_severity_breakdown_all_four_keys_in_default_fallback(self):
        """Bug Class #37: the empty fallback breakdown dict has exactly 4 int keys."""
        src = self._sensor_src()
        start = src.index("class SafetyRecentEventsSensor")
        end = src.index("\nclass ", start + 1)
        block = src[start:end]
        for key in ("info", "advisory", "alert", "critical"):
            assert f'"{key}"' in block, (
                f"Sensor fallback breakdown missing key {key!r} (Bug Class #37)"
            )


# ---------------------------------------------------------------------------
# Mandatory behavioral tests (plan acceptance criteria)
# ---------------------------------------------------------------------------

class TestRecentEventsEmptyReturnsZeroState:
    """test_recent_events_empty_returns_zero_state — Bug Class #29"""

    def test_recent_events_empty_returns_zero_state(self):
        """Empty buffer → count_24h=0, events=[], last_event_at_iso=None."""
        coord = _build_coordinator()
        data = coord.get_recent_events()

        assert data["count_24h"] == 0, f"Expected 0, got {data['count_24h']}"
        assert data["events"] == [], f"Expected [], got {data['events']}"
        assert data["last_event_at_iso"] is None

    def test_empty_buffer_count_is_int(self):
        """count_24h must be int (not str or None) on empty buffer."""
        coord = _build_coordinator()
        data = coord.get_recent_events()
        assert isinstance(data["count_24h"], int)

    def test_empty_buffer_events_is_list(self):
        """events must be list (not None) on empty buffer."""
        coord = _build_coordinator()
        data = coord.get_recent_events()
        assert isinstance(data["events"], list)

    def test_empty_buffer_severity_breakdown_present(self):
        """severity_breakdown must be present even when buffer is empty."""
        coord = _build_coordinator()
        data = coord.get_recent_events()
        assert "severity_breakdown" in data
        assert isinstance(data["severity_breakdown"], dict)


class TestRecentEventsCapsAt20:
    """test_recent_events_caps_at_20 — Bug Class #25"""

    def test_recent_events_caps_at_20(self):
        """Adding 25 entries keeps only the 20 most recent (deque cap)."""
        coord = _build_coordinator()
        Severity = coord._Severity
        for i in range(25):
            coord._record_event(
                event_type=f"smoke_{i}",
                room=f"room_{i}",
                severity=Severity.LOW,
            )
        data = coord.get_recent_events()
        assert len(data["events"]) <= 20, (
            f"Expected ≤20 events, got {len(data['events'])}"
        )

    def test_cap_at_20_evicts_oldest(self):
        """After 25 inserts, the first 5 are evicted; event 24 is newest."""
        coord = _build_coordinator()
        Severity = coord._Severity
        for i in range(25):
            coord._record_event(
                event_type=f"event_{i}",
                room="kitchen",
                severity=Severity.LOW,
            )
        data = coord.get_recent_events()
        # newest-first → first item is event_24
        assert data["events"][0]["type"] == "event_24", (
            f"Expected event_24 as newest, got {data['events'][0]['type']}"
        )
        # oldest retained should be event_5
        assert data["events"][-1]["type"] == "event_5", (
            f"Expected event_5 as oldest retained, got {data['events'][-1]['type']}"
        )

    def test_deque_maxlen_is_20_in_source(self):
        """Bug Class #25: source must declare deque(maxlen=20) for _event_buffer."""
        src = SAFETY_PY.read_text()
        # Find the _event_buffer deque declaration
        idx = src.index("_event_buffer")
        surrounding = src[idx:idx + 100]
        assert "deque(maxlen=20)" in surrounding, (
            "_event_buffer must be deque(maxlen=20)"
        )


class TestRecentEventsSeverityBreakdownSumsMatch:
    """test_recent_events_severity_breakdown_sums_match — Bug Class #22 + #37"""

    def test_recent_events_severity_breakdown_sums_match(self):
        """Sum of severity_breakdown values must equal count_24h."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("smoke", "kitchen", Severity.CRITICAL)
        coord._record_event("water_leak", "bathroom", Severity.HIGH)
        coord._record_event("high_co2", "living room", Severity.MEDIUM)
        coord._record_event("low_humidity", "bedroom", Severity.LOW)

        data = coord.get_recent_events()
        breakdown = data["severity_breakdown"]
        total = sum(breakdown.values())
        assert total == data["count_24h"], (
            f"severity_breakdown sum {total} != count_24h {data['count_24h']}"
        )

    def test_severity_breakdown_has_exactly_four_keys(self):
        """Bug Class #37: severity_breakdown always has exactly 4 int keys."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("smoke", "kitchen", Severity.HIGH)
        data = coord.get_recent_events()
        breakdown = data["severity_breakdown"]
        assert set(breakdown.keys()) == {"info", "advisory", "alert", "critical"}, (
            f"Expected keys {{info, advisory, alert, critical}}, got {set(breakdown.keys())}"
        )

    def test_severity_values_all_ints(self):
        """All values in severity_breakdown must be int."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("overheat", "attic", Severity.MEDIUM)
        data = coord.get_recent_events()
        for key, val in data["severity_breakdown"].items():
            assert isinstance(val, int), (
                f"severity_breakdown[{key!r}] must be int, got {type(val)}"
            )

    def test_severity_breakdown_empty_buffer_all_zeros(self):
        """Empty buffer → all severity_breakdown values are 0."""
        coord = _build_coordinator()
        data = coord.get_recent_events()
        breakdown = data["severity_breakdown"]
        for key in ("info", "advisory", "alert", "critical"):
            assert breakdown[key] == 0, (
                f"Expected breakdown[{key!r}]=0 on empty buffer, got {breakdown[key]}"
            )


class TestRecentEventsAttrsShapeFlat:
    """test_recent_events_attrs_shape_flat — Bug Class #37"""

    def test_recent_events_attrs_shape_flat(self):
        """get_recent_events() returns a dict with exactly 4 top-level keys."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("smoke", "kitchen", Severity.CRITICAL)
        data = coord.get_recent_events()

        required_keys = {"events", "count_24h", "last_event_at_iso", "severity_breakdown"}
        assert required_keys.issubset(data.keys()), (
            f"Missing keys: {required_keys - data.keys()}"
        )

    def test_each_event_entry_has_all_required_keys(self):
        """Each entry in events list must have the 4 plan-specified keys."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("water_leak", "bathroom", Severity.HIGH)
        data = coord.get_recent_events()
        assert len(data["events"]) == 1
        entry = data["events"][0]

        required = {"timestamp_iso", "type", "room", "severity"}
        assert required.issubset(entry.keys()), (
            f"Missing entry keys: {required - entry.keys()}"
        )

    def test_no_nested_dicts_in_entry(self):
        """Bug Class #37: each event entry must be a flat dict (no nested objects)."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("high_co2", "living room", Severity.MEDIUM)
        data = coord.get_recent_events()
        for entry in data["events"]:
            for key, val in entry.items():
                assert not isinstance(val, dict), (
                    f"Entry key {key!r} must not be a nested dict; got {type(val)}"
                )

    def test_all_entries_json_serializable(self):
        """All entry values must be JSON-serializable (no Decimal, no datetime obj)."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("freeze_risk", "garage", Severity.HIGH)
        data = coord.get_recent_events()
        # Must not raise
        json.dumps(data)
        # No datetime objects in entries
        for entry in data["events"]:
            for val in entry.values():
                assert not isinstance(val, datetime), (
                    f"datetime object found in entry — must use ISO str (Bug Class #11)"
                )

    def test_room_none_serializes_as_json_null(self):
        """room=None must round-trip through JSON as null."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("overheat", None, Severity.HIGH)
        data = coord.get_recent_events()
        serialized = json.dumps(data["events"])
        parsed = json.loads(serialized)
        assert parsed[0]["room"] is None

    def test_room_str_preserved(self):
        """room string is preserved verbatim through the buffer."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("smoke", "Master Bedroom", Severity.CRITICAL)
        data = coord.get_recent_events()
        assert data["events"][0]["room"] == "Master Bedroom"


# ---------------------------------------------------------------------------
# Additional behavioral tests
# ---------------------------------------------------------------------------

class TestRecordEventAppendsToBuffer:
    """test_record_event_appends_to_buffer"""

    def test_record_event_appends_to_buffer(self):
        """A _record_event call adds exactly one entry to the buffer."""
        coord = _build_coordinator()
        Severity = coord._Severity
        assert len(coord._event_buffer) == 0

        coord._record_event("smoke", "kitchen", Severity.CRITICAL)

        assert len(coord._event_buffer) == 1

    def test_multiple_calls_grow_buffer(self):
        """Three calls → three entries (up to cap)."""
        coord = _build_coordinator()
        Severity = coord._Severity
        for i in range(3):
            coord._record_event(f"event_{i}", f"room_{i}", Severity.LOW)
        assert len(coord._event_buffer) == 3

    def test_entry_type_field_preserved(self):
        """The event_type string passed to _record_event is stored verbatim."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("carbon_monoxide", "garage", Severity.HIGH)
        entry = list(coord._event_buffer)[0]
        assert entry["type"] == "carbon_monoxide"

    def test_entry_room_field_preserved(self):
        """The room string is stored verbatim in the buffer entry."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("smoke", "Living Room", Severity.CRITICAL)
        entry = list(coord._event_buffer)[0]
        assert entry["room"] == "Living Room"

    def test_severity_mapping_critical(self):
        """Severity.CRITICAL maps to 'critical' in the buffer."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("smoke", "kitchen", Severity.CRITICAL)
        entry = list(coord._event_buffer)[0]
        assert entry["severity"] == "critical"

    def test_severity_mapping_high_to_alert(self):
        """Severity.HIGH maps to 'alert' in the buffer (PWA vocab)."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("water_leak", "bathroom", Severity.HIGH)
        entry = list(coord._event_buffer)[0]
        assert entry["severity"] == "alert", (
            f"Severity.HIGH must map to 'alert', got {entry['severity']!r}"
        )

    def test_severity_mapping_medium_to_advisory(self):
        """Severity.MEDIUM maps to 'advisory' in the buffer."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("high_co2", "living room", Severity.MEDIUM)
        entry = list(coord._event_buffer)[0]
        assert entry["severity"] == "advisory", (
            f"Severity.MEDIUM must map to 'advisory', got {entry['severity']!r}"
        )

    def test_severity_mapping_low_to_info(self):
        """Severity.LOW maps to 'info' in the buffer."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("low_humidity", "bedroom", Severity.LOW)
        entry = list(coord._event_buffer)[0]
        assert entry["severity"] == "info", (
            f"Severity.LOW must map to 'info', got {entry['severity']!r}"
        )

    def test_severity_value_is_in_valid_set(self):
        """severity field must be one of info|advisory|alert|critical (Bug Class #22)."""
        valid = {"info", "advisory", "alert", "critical"}
        coord = _build_coordinator()
        Severity = coord._Severity
        for sev in (Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL):
            coord._record_event("test_event", "test_room", sev)
        for entry in coord._event_buffer:
            assert entry["severity"] in valid, (
                f"severity {entry['severity']!r} not in valid set {valid}"
            )


class Test24hFilterExcludesOldFromCount:
    """test_24h_filter_excludes_old_from_count"""

    def test_24h_filter_excludes_old_from_count(self):
        """Entries older than 24h are excluded from count_24h but stay in buffer."""
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(hours=30)
        recent_time = now - timedelta(hours=1)

        # Record an old entry using a coordinator anchored to old_time
        coord_old = _build_coordinator(now_override=old_time)
        coord_old._record_event("smoke", "kitchen", coord_old._Severity.HIGH)
        old_entry = list(coord_old._event_buffer)[0]

        # Build a coordinator anchored to real "now" for evaluation
        coord_eval = _build_coordinator(now_override=now)
        # Inject the old entry first, then a recent one
        coord_eval._event_buffer.append(old_entry)
        coord_eval._record_event("water_leak", "bathroom", coord_eval._Severity.HIGH)

        data = coord_eval.get_recent_events()

        # Buffer has 2 entries
        assert len(data["events"]) == 2, f"Expected 2 entries, got {len(data['events'])}"

        # count_24h should only count the recent entry
        assert data["count_24h"] == 1, (
            f"Expected count_24h=1 (only recent entry), got {data['count_24h']}"
        )

    def test_all_entries_within_24h_all_counted(self):
        """All recent entries are reflected in count_24h."""
        now = datetime.now(timezone.utc)
        coord = _build_coordinator(now_override=now)
        Severity = coord._Severity
        for i in range(5):
            coord._record_event(f"event_{i}", "room", Severity.LOW)
        data = coord.get_recent_events()
        assert data["count_24h"] == 5

    def test_all_entries_old_count_is_zero(self):
        """All entries older than 24h → count_24h=0, but events list still has entries."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=30)
        real_now = datetime.now(timezone.utc)

        coord_old = _build_coordinator(now_override=old_time)
        coord_old._record_event("smoke", "attic", coord_old._Severity.CRITICAL)

        coord_now = _build_coordinator(now_override=real_now)
        coord_now._event_buffer.extend(coord_old._event_buffer)

        data = coord_now.get_recent_events()
        assert data["count_24h"] == 0, (
            f"Expected count_24h=0 for entries older than 24h, got {data['count_24h']}"
        )
        # Entry still in buffer (deque only evicts at maxlen, not by age)
        assert len(data["events"]) == 1

    def test_old_entries_excluded_from_severity_breakdown(self):
        """Entries older than 24h must NOT contribute to severity_breakdown counts."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=30)
        real_now = datetime.now(timezone.utc)

        coord_old = _build_coordinator(now_override=old_time)
        coord_old._record_event("smoke", "kitchen", coord_old._Severity.CRITICAL)
        old_entry = list(coord_old._event_buffer)[0]

        coord_now = _build_coordinator(now_override=real_now)
        coord_now._event_buffer.append(old_entry)
        # Add one recent advisory event
        coord_now._record_event("high_co2", "living room", coord_now._Severity.MEDIUM)

        data = coord_now.get_recent_events()
        breakdown = data["severity_breakdown"]
        # Only the recent MEDIUM→"advisory" event is within 24h
        assert breakdown["critical"] == 0, (
            "Old CRITICAL event must not appear in severity_breakdown"
        )
        assert breakdown["advisory"] == 1


class TestEventsOrderedNewestFirst:
    """test_events_ordered_newest_first"""

    def test_events_ordered_newest_first(self):
        """events list must be newest-first (reverse chronological)."""
        coord = _build_coordinator()
        Severity = coord._Severity
        for i in range(3):
            coord._record_event(f"event_{i}", "room", Severity.LOW)

        data = coord.get_recent_events()
        events = data["events"]

        assert len(events) == 3
        # newest first — event_2 was added last
        assert events[0]["type"] == "event_2", (
            f"Expected event_2 as newest (index 0), got {events[0]['type']}"
        )
        assert events[-1]["type"] == "event_0", (
            f"Expected event_0 as oldest (last), got {events[-1]['type']}"
        )

    def test_newest_first_after_cap(self):
        """After cap rollover, newest is still at index 0."""
        coord = _build_coordinator()
        Severity = coord._Severity
        for i in range(22):
            coord._record_event(f"e_{i}", "room", Severity.LOW)
        data = coord.get_recent_events()
        assert data["events"][0]["type"] == "e_21"
        assert data["events"][-1]["type"] == "e_2"

    def test_last_event_at_iso_matches_newest_entry(self):
        """last_event_at_iso must equal the timestamp of the newest event."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("first", "room", Severity.LOW)
        coord._record_event("second", "room", Severity.HIGH)
        data = coord.get_recent_events()
        # events[0] is newest
        assert data["last_event_at_iso"] == data["events"][0]["timestamp_iso"]

    def test_single_entry_is_both_first_and_last(self):
        """With one entry, events[0] is both newest and oldest."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("smoke", "kitchen", Severity.CRITICAL)
        data = coord.get_recent_events()
        assert len(data["events"]) == 1
        assert data["events"][0]["type"] == "smoke"
        assert data["last_event_at_iso"] == data["events"][0]["timestamp_iso"]


class TestSeverityBreakdownAllFourKeysPresent:
    """test_severity_breakdown_all_four_keys_present — Bug Class #22 + #37"""

    def test_severity_breakdown_all_four_keys_present(self):
        """severity_breakdown must always have exactly info, advisory, alert, critical."""
        coord = _build_coordinator()
        data = coord.get_recent_events()
        breakdown = data["severity_breakdown"]
        assert set(breakdown.keys()) == {"info", "advisory", "alert", "critical"}

    def test_severity_breakdown_present_with_entries(self):
        """severity_breakdown has all four keys even when buffer is populated."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("smoke", "kitchen", Severity.CRITICAL)
        data = coord.get_recent_events()
        assert set(data["severity_breakdown"].keys()) == {
            "info", "advisory", "alert", "critical"
        }

    def test_severity_breakdown_counts_correct_for_mixed_severities(self):
        """Each severity bucket is counted correctly for a mixed event set."""
        coord = _build_coordinator()
        Severity = coord._Severity
        # 2 critical, 1 alert (HIGH), 2 advisory (MEDIUM), 1 info (LOW)
        coord._record_event("smoke", "k", Severity.CRITICAL)
        coord._record_event("fire", "l", Severity.CRITICAL)
        coord._record_event("water_leak", "b", Severity.HIGH)
        coord._record_event("high_co2", "lr", Severity.MEDIUM)
        coord._record_event("high_tvoc", "br", Severity.MEDIUM)
        coord._record_event("low_humidity", "bed", Severity.LOW)

        data = coord.get_recent_events()
        bd = data["severity_breakdown"]
        assert bd["critical"] == 2
        assert bd["alert"] == 1
        assert bd["advisory"] == 2
        assert bd["info"] == 1
        assert sum(bd.values()) == data["count_24h"]


class TestTimestampBugClass11:
    """Bug Class #11: timestamps must be UTC ISO 8601 strings."""

    def test_timestamp_iso_is_string(self):
        """timestamp_iso must be str, not datetime object."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("smoke", "kitchen", Severity.CRITICAL)
        data = coord.get_recent_events()
        ts = data["events"][0]["timestamp_iso"]
        assert isinstance(ts, str), f"timestamp_iso must be str, got {type(ts)}"

    def test_timestamp_iso_is_utc_aware(self):
        """timestamp_iso must parse as a UTC-aware datetime."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("smoke", "kitchen", Severity.CRITICAL)
        data = coord.get_recent_events()
        ts_str = data["events"][0]["timestamp_iso"]
        parsed = datetime.fromisoformat(ts_str)
        assert parsed.tzinfo is not None, (
            "timestamp_iso must be UTC-aware (has tzinfo), got naive datetime"
        )

    def test_last_event_at_iso_is_str_or_none(self):
        """last_event_at_iso is str when buffer has entries, None when empty."""
        coord_empty = _build_coordinator()
        assert coord_empty.get_recent_events()["last_event_at_iso"] is None

        coord_pop = _build_coordinator()
        coord_pop._record_event("smoke", "kitchen", coord_pop._Severity.CRITICAL)
        val = coord_pop.get_recent_events()["last_event_at_iso"]
        assert isinstance(val, str), f"Expected str, got {type(val)}"
        parsed = datetime.fromisoformat(val)
        assert parsed.tzinfo is not None

    def test_timestamp_not_datetime_object(self):
        """Bug Class #11: timestamp_iso must not be a datetime object."""
        coord = _build_coordinator()
        Severity = coord._Severity
        coord._record_event("carbon_monoxide", "garage", Severity.HIGH)
        data = coord.get_recent_events()
        ts = data["events"][0]["timestamp_iso"]
        assert not isinstance(ts, datetime), (
            "timestamp_iso must be str, not datetime object (Bug Class #11)"
        )
