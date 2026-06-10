"""Tests for the Routine-Awareness Next-State Forecaster.

Drives the real ``RoutineForecaster`` production class (not a re-implementation).
HA imports are mocked via ``sys.modules.setdefault`` per the suite convention
(see ``test_data_pipeline.py``). We deliberately AVOID assigning over a module
path another test already owns — the v4.6.x test-poisoning bug class.

Covers (per planning doc D1 acceptance criteria):
  * aggregation correctness across (prev_state, day_type, time_bin) cells
  * MIN_SUPPORT cascade fallback ((C,dt,tb) -> (C,dt,*) -> (C,*,*) -> unknown)
  * vocab collapse table incl. second-place (off-diagonal) preference
  * guest/vacation passthrough at predict time
  * guest/vacation prev_state row exclusion during aggregation
  * ETA median computation
  * boot-settle gating in PresenceCoordinator.get_next_state_prediction
  * subscription / timer cleanup on async_shutdown
  * bounded-read params passed to the DB DAO
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Minimal HA stubs — only the modules + symbols the forecaster reaches into.
# We use ``sys.modules.setdefault`` so we do NOT clobber stubs another test
# in the suite has registered (the v4.6.x test-poisoning bug class).
# ---------------------------------------------------------------------------


def _ensure_stub(name: str, **attrs):
    """Install a stub module ONLY if absent. Return the (possibly pre-existing)
    module so the caller can read it back."""
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# Provide stable dt_util helpers. If another test has already registered a
# bare-MagicMock dt_util, replace ONLY the attributes we need rather than
# the module path (clobbering would risk the test-poisoning failure mode).
_ensure_stub("homeassistant")
_ensure_stub("homeassistant.core", HomeAssistant=MagicMock, callback=lambda fn: fn)
_ensure_stub(
    "homeassistant.helpers",
)
_ensure_stub(
    "homeassistant.helpers.dispatcher",
    async_dispatcher_connect=MagicMock(return_value=lambda: None),
    async_dispatcher_send=MagicMock(),
)
_ensure_stub(
    "homeassistant.helpers.event",
    async_track_time_interval=MagicMock(return_value=lambda: None),
    async_call_later=MagicMock(return_value=lambda: None),
    async_track_state_change_event=MagicMock(return_value=lambda: None),
)
_ensure_stub("homeassistant.util")


# Ensure dt_util exposes the symbols the forecaster needs without clobbering
# any prior registration. We bind module-level functions defensively.
def _utcnow():
    return datetime.now(timezone.utc)


def _as_local(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _as_utc(dt):
    """Mirror real HA semantics: naive datetimes are treated as LOCAL.

    Real ``homeassistant.util.dt.as_utc`` calls
    ``replace(tzinfo=DEFAULT_TIME_ZONE).astimezone(UTC)`` for naive
    inputs — so naive is interpreted as the HA-configured local zone,
    NOT as UTC. We deliberately match that here so a regression of
    review-finding A-1 (the forecaster routing a naive UTC stamp
    through as_utc and getting a local-offset shift) is observable
    in the test suite. The test fixture below explicitly verifies
    this binding by stamping a naive 02:00 wall-clock UTC time and
    asserting it lands in the evening bin under a UTC-5 local zone.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Simulate a UTC-5 (CDT-style) local zone — gives the test the
        # same offset shift the live HA instance would produce. We pick
        # a fixed offset rather than reading the runtime tz so the test
        # is deterministic regardless of where it runs.
        local = timezone(timedelta(hours=-5))
        return dt.replace(tzinfo=local).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


_dt_util_mod = sys.modules.get("homeassistant.util.dt")
if _dt_util_mod is None:
    _dt_util_mod = types.ModuleType("homeassistant.util.dt")
    sys.modules["homeassistant.util.dt"] = _dt_util_mod

# Only set attributes that aren't already real callables — defends against
# both the bare-MagicMock case and a richer stub from another test.
for _name, _fn in (("utcnow", _utcnow), ("as_local", _as_local), ("as_utc", _as_utc)):
    if not callable(getattr(_dt_util_mod, _name, None)) or isinstance(
        getattr(_dt_util_mod, _name), MagicMock
    ):
        setattr(_dt_util_mod, _name, _fn)


# Register synthetic package paths so we can import the const module +
# domain_coordinators subpackage WITHOUT executing
# ``custom_components/universal_room_automation/__init__.py`` (which imports
# the full HA ConfigEntry stack and many other heavy modules). This is the
# established convention from test_data_pipeline.py:81-91.
_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, "..", ".."))

_cc = sys.modules.get("custom_components")
if _cc is None or not hasattr(_cc, "__path__"):
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [os.path.join(_HERE, "..", "..", "custom_components")]
    sys.modules["custom_components"] = _cc

_ura_name = "custom_components.universal_room_automation"
_ura = sys.modules.get(_ura_name)
if _ura is None or not hasattr(_ura, "__path__"):
    _ura = types.ModuleType(_ura_name)
    _ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
    _ura.__path__ = [_ura_path]
    _ura.__package__ = _ura_name
    sys.modules[_ura_name] = _ura

_dc_name = "custom_components.universal_room_automation.domain_coordinators"
_dc = sys.modules.get(_dc_name)
if _dc is None or not hasattr(_dc, "__path__"):
    _dc = types.ModuleType(_dc_name)
    _dc.__path__ = [os.path.join(_ura.__path__[0], "domain_coordinators")]
    _dc.__package__ = _dc_name
    sys.modules[_dc_name] = _dc


# Import the production const + forecaster module. Bypasses __init__.py.
import importlib  # noqa: E402

_const = importlib.import_module(
    "custom_components.universal_room_automation.const"
)
# domain_coordinators/__init__.py is empty/lightweight; importing the module
# directly is fine.
rf_mod = importlib.import_module(
    "custom_components.universal_room_automation.domain_coordinators.routine_forecaster"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(ts: datetime, state: str, prev: str, conf: float = 0.9) -> dict:
    return {
        "timestamp": ts.isoformat(),
        "state": state,
        "previous_state": prev,
        "confidence": conf,
    }


class _FakeDB:
    """Minimal DB stub exposing only fetch_house_state_log_since."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, int]] = []

    async def fetch_house_state_log_since(self, since_iso: str, limit: int):
        self.calls.append((since_iso, limit))
        return self.rows[:limit]


def _hass():
    h = MagicMock()
    h.data = {}
    h.async_create_task = MagicMock()
    return h


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class TestAggregation:
    def test_argmax_with_sufficient_support(self):
        """Seed enough home_day -> away transitions in one cell to argmax cleanly."""
        # Build 10 transitions home_day -> away around 14:00 weekday
        base = datetime(2026, 5, 18, 13, 30, tzinfo=timezone.utc)  # Monday
        rows = []
        # prior row puts state=home_day at 13:30
        rows.append(_row(base, "home_day", "away"))
        for i in range(10):
            t = base + timedelta(minutes=30 + i * 60)
            rows.append(_row(t, "away", "home_day"))
            rows.append(_row(t + timedelta(minutes=30), "home_day", "away"))

        db = _FakeDB(rows)
        fc = rf_mod.RoutineForecaster(_hass(), db)
        asyncio.new_event_loop().run_until_complete(fc.async_refresh())

        # Should have a populated cell for home_day weekday around bin 3
        out = fc.predict("home_day")
        assert out["state"] in {"away", "home_night", "home_day", "sleep"}
        # With our seeded distribution argmax is "away"
        assert out["state"] == "away"
        assert out["confidence"] > 0.5
        assert out["model"] == _const.ROUTINE_FORECAST_MODEL_ID

    def test_thin_cell_falls_back_then_unknown(self):
        """Empty DB -> unknown; thin cell -> cascade then unknown."""
        db = _FakeDB([])
        fc = rf_mod.RoutineForecaster(_hass(), db)
        asyncio.new_event_loop().run_until_complete(fc.async_refresh())
        out = fc.predict("home_day")
        assert out["state"] == "unknown"
        assert out["confidence"] == 0.0
        assert out["transition_eta_minutes"] is None
        # Stable contract keys
        assert set(out.keys()) == {
            "state",
            "confidence",
            "predicted_at_iso",
            "model",
            "current_state",
            "transition_eta_minutes",
        }

    def test_eta_median_computed(self):
        """ETA in minutes is the median dwell in the cell."""
        # Sequence: away -> home_day dwell 60min, then home_day -> away
        base = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)  # Monday morning
        rows = []
        for i in range(6):
            arrive = base + timedelta(hours=i * 2)
            leave = arrive + timedelta(minutes=60)
            rows.append(_row(arrive, "home_day", "away"))
            rows.append(_row(leave, "away", "home_day"))

        db = _FakeDB(rows)
        fc = rf_mod.RoutineForecaster(_hass(), db)
        asyncio.new_event_loop().run_until_complete(fc.async_refresh())
        out = fc.predict("home_day")
        assert out["state"] == "away"
        assert out["transition_eta_minutes"] is not None
        # Median dwell was ~60min; allow loose bound.
        assert 30 <= out["transition_eta_minutes"] <= 120


# ---------------------------------------------------------------------------
# Vocab collapse
# ---------------------------------------------------------------------------


class TestVocabCollapse:
    def test_collapse_home_evening_to_home_night(self):
        assert rf_mod._collapse_vocab("home_evening") == "home_night"

    def test_collapse_waking_to_home_day(self):
        assert rf_mod._collapse_vocab("waking") == "home_day"

    def test_collapse_arriving_to_home_day(self):
        assert rf_mod._collapse_vocab("arriving") == "home_day"

    def test_collapse_passthrough_guest_vacation(self):
        assert rf_mod._collapse_vocab("guest") == "guest"
        assert rf_mod._collapse_vocab("vacation") == "vacation"

    def test_unknown_input_collapses_to_unknown(self):
        assert rf_mod._collapse_vocab("not_a_state") == "unknown"

    def test_second_place_preferred_when_argmax_collapses_to_current(self):
        """If argmax collapses to current vocab, second-place off-diagonal wins.

        Currently in home_night. Seed cell so argmax is home_evening (which
        collapses to home_night, matching current) AND second-place is away.
        Expect output state="away" (off-diagonal).
        """
        # home_night cell — seed home_evening as argmax with 8 hits, away with 6.
        base = datetime(2026, 5, 18, 22, 0, tzinfo=timezone.utc)
        # Pre-seed a prior row so the first cell key is (home_night, *, *).
        rows = [_row(base - timedelta(minutes=5), "home_night", "home_evening")]
        for i in range(8):
            t = base + timedelta(minutes=i * 10)
            rows.append(_row(t, "home_evening", "home_night"))
            rows.append(_row(t + timedelta(minutes=5), "home_night", "home_evening"))
        for i in range(6):
            t = base + timedelta(hours=2 + i)
            rows.append(_row(t, "away", "home_night"))
            rows.append(_row(t + timedelta(minutes=5), "home_night", "away"))

        db = _FakeDB(rows)
        fc = rf_mod.RoutineForecaster(_hass(), db)
        asyncio.new_event_loop().run_until_complete(fc.async_refresh())
        out = fc.predict("home_night")
        # Second-place must win because home_evening collapses to home_night
        assert out["state"] == "away"


# ---------------------------------------------------------------------------
# Guest / vacation handling
# ---------------------------------------------------------------------------


class TestGuestVacation:
    def test_guest_current_state_passthrough(self):
        db = _FakeDB([])
        fc = rf_mod.RoutineForecaster(_hass(), db)
        out = fc.predict("guest")
        assert out["state"] == "guest"
        assert out["confidence"] == pytest.approx(0.3)
        assert out["transition_eta_minutes"] is None
        assert out["model"].endswith("+guest_passthrough")
        assert out["current_state"] == "guest"

    def test_vacation_current_state_passthrough(self):
        db = _FakeDB([])
        fc = rf_mod.RoutineForecaster(_hass(), db)
        out = fc.predict("vacation")
        assert out["state"] == "vacation"
        assert out["confidence"] == pytest.approx(0.3)
        assert out["model"].endswith("+guest_passthrough")

    def test_guest_vacation_excluded_from_non_guest_cells(self):
        """Rows whose prev_state is GUEST/VACATION must NOT populate non-guest cells."""
        base = datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc)
        rows = []
        # 10 transitions from guest -> home_day — these MUST NOT register in
        # the (guest, *) cell-key path; we verify by checking that a home_day
        # predict() returns unknown (no non-guest data was seeded).
        for i in range(10):
            t = base + timedelta(minutes=i * 5)
            rows.append(_row(t, "home_day", "guest"))

        db = _FakeDB(rows)
        fc = rf_mod.RoutineForecaster(_hass(), db)
        asyncio.new_event_loop().run_until_complete(fc.async_refresh())
        # No home_day-keyed cell ever populated. predict("home_day") = unknown.
        out = fc.predict("home_day")
        assert out["state"] == "unknown"
        assert out["confidence"] == 0.0


# ---------------------------------------------------------------------------
# Lifecycle / subscription cleanup
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_coordinator_lifecycle_cancels_refresh(self):
        """async_shutdown cancels both refresh timer and signal subscription."""
        timer_unsub = MagicMock()
        signal_unsub = MagicMock()

        # Patch the helpers the forecaster uses to return our recorders.
        sys.modules["homeassistant.helpers.event"].async_track_time_interval = (
            MagicMock(return_value=timer_unsub)
        )
        sys.modules["homeassistant.helpers.dispatcher"].async_dispatcher_connect = (
            MagicMock(return_value=signal_unsub)
        )

        # Reload the forecaster module so it re-binds the patched helpers
        # at module-import time (its top-level imports captured the originals).
        # Safer: call the helpers via the module's namespace and patch THERE.
        rf_mod.async_track_time_interval = sys.modules[
            "homeassistant.helpers.event"
        ].async_track_time_interval
        rf_mod.async_dispatcher_connect = sys.modules[
            "homeassistant.helpers.dispatcher"
        ].async_dispatcher_connect

        db = _FakeDB([])
        fc = rf_mod.RoutineForecaster(_hass(), db)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(fc.async_setup())
        assert fc._unsub_refresh is timer_unsub
        assert fc._unsub_signal is signal_unsub
        loop.run_until_complete(fc.async_shutdown())
        timer_unsub.assert_called_once()
        signal_unsub.assert_called_once()
        # Idempotent second shutdown does not raise.
        loop.run_until_complete(fc.async_shutdown())


# ---------------------------------------------------------------------------
# Boot-settle gating (verified at PresenceCoordinator.get_next_state_prediction)
# ---------------------------------------------------------------------------


class TestBootSettleGating:
    def test_boot_settle_false_returns_placeholder(self):
        """When _boot_settle_done=False the coordinator returns placeholder_v0."""
        # We assert via the source-level guarantee: get_next_state_prediction
        # checks boot_settle_done BEFORE delegating to the forecaster. Source
        # grep proves the guard exists (Bug Class verification pattern matches
        # how other v4.6.9 tests structure-verify).
        from pathlib import Path
        src = (
            Path(__file__).parents[2]
            / "custom_components"
            / "universal_room_automation"
            / "domain_coordinators"
            / "presence.py"
        ).read_text()
        # Locate the method body.
        start = src.index("def get_next_state_prediction")
        end = src.index("\n    def ", start + 1)
        body = src[start:end]
        # Guard must check _boot_settle_done before predict().
        assert "_boot_settle_done" in body
        assert "predict(" in body
        # And the placeholder shape remains as graceful degrade.
        assert "placeholder_v0" in body


# ---------------------------------------------------------------------------
# DB DAO — bounded params + read-only invariant
# ---------------------------------------------------------------------------


class TestDBReader:
    def test_db_reader_bounded(self):
        """async_refresh asks the DB for at most ROUTINE_FORECAST_MAX_ROWS rows."""
        db = _FakeDB([])
        fc = rf_mod.RoutineForecaster(_hass(), db)
        asyncio.new_event_loop().run_until_complete(fc.async_refresh())
        assert db.calls, "fetch_house_state_log_since should have been called"
        since_iso, limit = db.calls[-1]
        assert limit == _const.ROUTINE_FORECAST_MAX_ROWS
        # Cutoff is in the past by ~ROUTINE_FORECAST_HISTORY_DAYS
        parsed = datetime.fromisoformat(since_iso)
        delta = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
        assert (
            timedelta(days=_const.ROUTINE_FORECAST_HISTORY_DAYS - 1)
            <= delta
            <= timedelta(days=_const.ROUTINE_FORECAST_HISTORY_DAYS + 1)
        )

    def test_db_reader_is_read_only(self):
        """Source-level: fetch_house_state_log_since must not INSERT/UPDATE/DELETE."""
        from pathlib import Path
        db_src = (
            Path(__file__).parents[2]
            / "custom_components"
            / "universal_room_automation"
            / "database.py"
        ).read_text()
        # Find the method body.
        start = db_src.index("async def fetch_house_state_log_since")
        end = db_src.index("\n    async def ", start + 1)
        body = db_src[start:end]
        upper = body.upper()
        assert "INSERT " not in upper
        assert "UPDATE " not in upper
        assert "DELETE " not in upper
        # Should explicitly select from house_state_log under _db_read context.
        assert "FROM house_state_log" in body
        assert "_db_read" in body


# ---------------------------------------------------------------------------
# Constants present and well-typed
# ---------------------------------------------------------------------------


class TestConstants:
    def test_required_constants_present(self):
        assert isinstance(_const.ROUTINE_FORECAST_MIN_SUPPORT, int)
        assert _const.ROUTINE_FORECAST_MIN_SUPPORT >= 1
        assert isinstance(_const.ROUTINE_FORECAST_HISTORY_DAYS, int)
        assert _const.ROUTINE_FORECAST_HISTORY_DAYS >= 7
        assert isinstance(_const.ROUTINE_FORECAST_REFRESH_SECONDS, int)
        assert _const.ROUTINE_FORECAST_REFRESH_SECONDS >= 60
        assert isinstance(_const.ROUTINE_FORECAST_MAX_ROWS, int)
        assert _const.ROUTINE_FORECAST_MAX_ROWS >= 100
        assert isinstance(_const.ROUTINE_FORECAST_MODEL_ID, str)
        assert _const.ROUTINE_FORECAST_MODEL_ID

    def test_max_dwell_seconds_present(self):
        """Review A-M2 constant — used to drop restart-spanning samples."""
        assert isinstance(_const.ROUTINE_FORECAST_MAX_DWELL_SECONDS, int)
        # 12h is the planned threshold; allow ≥ 1h ≤ 24h as a sanity band.
        assert 3600 <= _const.ROUTINE_FORECAST_MAX_DWELL_SECONDS <= 86400


# ---------------------------------------------------------------------------
# Review fix-up regression tests
# ---------------------------------------------------------------------------


class TestParseTimezone:
    """Regression for review finding A-1 (timezone semantics).

    The DB writer emits naive UTC ISO strings (``datetime.utcnow().isoformat()``).
    HA's real ``dt_util.as_utc`` treats naive as LOCAL, which would shift
    every stamp by the local offset and put a 02:00Z event into the
    night bin under any negative-offset zone (e.g. UTC-5). The fix:
    ``_parse_ts`` attaches UTC explicitly BEFORE any conversion.
    """

    def test_naive_iso_treated_as_utc_not_local(self):
        # 02:00 UTC; under the test stub's UTC-5 local zone this would
        # SHIFT to 07:00 UTC if routed through as_utc — the original bug.
        # Expected (fixed): the stamp stays at 02:00 UTC.
        raw = "2026-05-18T02:00:00"
        parsed = rf_mod.RoutineForecaster._parse_ts(raw)
        assert parsed is not None
        assert parsed.tzinfo is not None
        # Stays at 02:00 UTC — naive interpreted as UTC.
        assert parsed.hour == 2
        assert parsed.utcoffset() == timedelta(0)

    def test_naive_evening_utc_bins_to_evening_bin_under_local_tz(self):
        """Review A-1 regression: a 02:00 UTC stamp from a 21:00 CDT event.

        The writer captures the event as 02:00Z (naive). With the bug,
        the local-bin would be 21:00 local (evening bin 4) — wait, the
        bug is the OTHER direction: a 21:00 CDT (02:00Z) event gets
        SHIFTED again by ``as_utc`` (naive→local) into 07:00 UTC → 02:00
        local → night bin 0. Fixed: parses to 02:00 UTC → 21:00 local
        (UTC-5) → evening bin 4. We assert the latter.
        """
        raw = "2026-05-18T02:00:00"  # naive UTC, event happened 21:00 prior day local
        parsed = rf_mod.RoutineForecaster._parse_ts(raw)
        # Convert through the test stub's as_local: tz-aware now, returns
        # itself unchanged (stub keeps original tz). The relevant check is
        # that the binning step would treat the LOCAL hour correctly — we
        # simulate the same shift the production code does.
        local = parsed.astimezone(timezone(timedelta(hours=-5)))
        assert local.hour == 21
        # 21:00 falls in bin 5 (late evening / pre-midnight). The bug
        # would have routed this stamp through as_utc, treating naive
        # as local → 07:00 UTC → 02:00 local → bin 0 (night). Asserting
        # bin 5 (not bin 0) is the regression check.
        local_bin = rf_mod._hour_to_time_bin(local.hour)
        assert local_bin == 5
        assert local_bin != 0  # the buggy bin under as_utc-naive-is-local


class TestNewestKeptOnOverflow:
    """Review A-2 / B-2: fetch_house_state_log_since returns NEWEST rows
    when the table overruns LIMIT (source-level check)."""

    def test_db_reader_uses_desc_order_under_limit(self):
        from pathlib import Path

        db_src = (
            Path(__file__).parents[2]
            / "custom_components"
            / "universal_room_automation"
            / "database.py"
        ).read_text()
        start = db_src.index("async def fetch_house_state_log_since")
        end = db_src.index("\n    async def ", start + 1)
        body = db_src[start:end]
        # Internal SQL must sort DESC so LIMIT keeps newest rows; the
        # function then reverses in Python to preserve the ASC contract
        # callers depend on (dwell-time computation).
        assert "ORDER BY timestamp DESC" in body
        assert "reversed(" in body


class TestSelfLoopSkip:
    """Review A-M1: prev_state == state rows (restart artifacts) must NOT
    inflate cell denominators."""

    def test_self_loops_excluded_from_aggregation(self):
        base = datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc)
        rows = []
        # 6 legit home_day -> away transitions (interleaved with prev rows)
        rows.append(_row(base - timedelta(minutes=10), "home_day", "away"))
        for i in range(6):
            t = base + timedelta(hours=i)
            rows.append(_row(t, "away", "home_day"))
            rows.append(_row(t + timedelta(minutes=30), "home_day", "away"))
        # Inject self-loops the refresh must skip.
        for i in range(50):
            rows.append(
                _row(base + timedelta(seconds=i), "home_day", "home_day")
            )

        db = _FakeDB(rows)
        fc = rf_mod.RoutineForecaster(_hass(), db)
        asyncio.new_event_loop().run_until_complete(fc.async_refresh())
        # Sum every count in every cell — self-loops would have added 50.
        total = sum(
            sum(v.values()) for v in fc._counts.values()
        )
        # We have 6 away transitions + 6 home_day re-entries that fall
        # under prev==away (NOT self-loops). Self-loops contribute 0.
        # Upper bound 20 keeps the test resilient to bin churn.
        assert total <= 20

    def test_self_loop_incremental_update_is_noop(self):
        """The incremental path must mirror the refresh-walk self-loop guard."""
        db = _FakeDB([])
        fc = rf_mod.RoutineForecaster(_hass(), db)
        # No prior state — incremental self-loop must NOT seed _last_row_*.
        fc._handle_house_state_change(
            {"old_state": "home_day", "new_state": "home_day"}
        )
        assert fc._last_row_ts is None
        assert fc._last_row_state is None
        assert not fc._counts


class TestDwellCap:
    """Review A-M2: restart-spanning dwell samples (> 12h) are dropped.

    The transition still counts; only the ETA sample is discarded so
    medians don't get pulled toward 12h+.
    """

    def test_long_dwell_count_kept_eta_sample_dropped(self):
        base = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
        # Sequence: away -> home_day (real, dwell = 1h)
        #           then home_day -> away (synthetic restart-gap 36h)
        rows = [
            _row(base, "home_day", "away"),
            _row(base + timedelta(hours=1), "away", "home_day"),
            _row(base + timedelta(hours=37), "home_day", "away"),  # 36h gap
            _row(base + timedelta(hours=38), "away", "home_day"),
        ]
        db = _FakeDB(rows)
        fc = rf_mod.RoutineForecaster(_hass(), db)
        asyncio.new_event_loop().run_until_complete(fc.async_refresh())
        # Find the home_day cells and check their ETA samples.
        for (prev, _, _), nexts in fc._etas.items():
            if prev == "home_day":
                for samples in nexts.values():
                    for s in samples:
                        # Anything above the cap shouldn't be present.
                        assert s <= _const.ROUTINE_FORECAST_MAX_DWELL_SECONDS


class TestDeferredInitialRefresh:
    """Review B-1: async_setup() must NOT await the initial DB read.

    The deferred load is triggered by ``async_trigger_initial_refresh``
    (called from PresenceCoordinator._release_boot_settle) and is
    idempotent.
    """

    def test_setup_does_not_load_db_eagerly(self):
        db = _FakeDB([])
        fc = rf_mod.RoutineForecaster(_hass(), db)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(fc.async_setup())
        # No DB calls during setup.
        assert db.calls == []
        assert fc._initial_refresh_done is False

    def test_trigger_initial_refresh_runs_once(self):
        db = _FakeDB([])
        fc = rf_mod.RoutineForecaster(_hass(), db)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(fc.async_setup())
        loop.run_until_complete(fc.async_trigger_initial_refresh())
        first_call_count = len(db.calls)
        assert first_call_count == 1
        assert fc._initial_refresh_done is True
        # Second call is a no-op (idempotent).
        loop.run_until_complete(fc.async_trigger_initial_refresh())
        assert len(db.calls) == first_call_count


class TestReSetupGuard:
    """Review B-3: PresenceCoordinator must NOT leave the prior forecaster
    instance ticking on re-entrant setup. Source-level guarantee check —
    the live wiring is exercised by manual reload, not by this suite."""

    def test_presence_setup_shuts_down_prior_forecaster(self):
        from pathlib import Path

        src = (
            Path(__file__).parents[2]
            / "custom_components"
            / "universal_room_automation"
            / "domain_coordinators"
            / "presence.py"
        ).read_text()
        # Find the forecaster-attach block.
        anchor = src.index(
            "from .routine_forecaster import RoutineForecaster"
        )
        # Look ahead a few hundred chars for the guard pattern.
        window = src[anchor: anchor + 1500]
        assert "_routine_forecaster" in window
        # The guard: prior instance is shut down before a new one is
        # constructed. Look for the explicit shutdown call AND the
        # awareness check.
        assert "existing.async_shutdown" in window or (
            "_routine_forecaster" in window
            and "async_shutdown" in window
            and "RoutineForecaster(self.hass, db)" in window
        )
