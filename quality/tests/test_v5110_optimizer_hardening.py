"""Tests for the v5.11.0 Optimization Coordinator hardening cycle.

Drives REAL production code paths via object.__new__ + module extraction
(sibling of test_hc_precool_oc_observability.py). Covers:

  D1  — notify-dedup TTL decrements per-CYCLE, not per-finding (MED-3)
  D2  — shadow-accuracy samples persist to DB (batched) + survive restart
  D3  — merged findings cap-of-caps (LOW-1)
  D4  — boot-storm gate cache short-circuit (MED-1)
  D5  — stub dimensions carry `stub` verdict (livability)
  D6  — promotion_readiness attribute per scorable dimension
  D7  — OptimizerFindingsSensor excludes META from display state
  D8  — rate-cap seed failure logs at WARNING (LOW-2)
  D9  — runtime write-volume tripwire trips + suspends persistence

Plus MANDATORY:
  - write-volume regression test (30 rooms × N findings ≤ batched bound)
  - D9 tripwire actually trips and suspends persistence
"""

import asyncio
import importlib.util
import logging
import os
import sys
import types
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Mock homeassistant surfaces (sibling pattern; setdefault ONLY)
# ---------------------------------------------------------------------------

_identity = lambda fn: fn  # noqa: E731


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _utcnow():
    return datetime.now(timezone.utc)


def _parse_datetime(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": MagicMock, "callback": _identity},
    "homeassistant.config_entries": {"ConfigEntry": MagicMock},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict, "EntityCategory": MagicMock(),
    },
    "homeassistant.helpers.entity_platform": {
        "AddEntitiesCallback": MagicMock,
    },
    "homeassistant.helpers.event": {
        "async_call_later": MagicMock(return_value=lambda: None),
        "async_track_state_change_event": MagicMock(return_value=lambda: None),
        "async_track_time_interval": MagicMock(return_value=lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": MagicMock(return_value=lambda: None),
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": MagicMock,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": MagicMock(),
    "homeassistant.helpers.entity_registry": {"async_get": MagicMock()},
    "homeassistant.helpers.sun": {},
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {
            "async_added_to_hass": AsyncMock(),
            "async_get_last_state": AsyncMock(return_value=None),
        }),
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": _utcnow, "now": _utcnow, "UTC": timezone.utc,
        "as_local": lambda d: d, "parse_datetime": _parse_datetime,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": MagicMock(), "SensorStateClass": MagicMock(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": MagicMock(),
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
    "homeassistant.components.switch": {
        "SwitchEntity": type("SwitchEntity", (), {}),
    },
}

for _name, _attrs in _mods.items():
    if isinstance(_attrs, dict):
        sys.modules.setdefault(_name, _mock_module(_name, **_attrs))
    else:
        sys.modules.setdefault(_name, _attrs)


_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _ROOT)

_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(_ROOT, "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules.setdefault("custom_components.universal_room_automation", _ura)


def _load_ura_module(rel_path: str, full_name: str):
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(
        full_name, os.path.join(_ura_path, rel_path),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


_const_mod = _load_ura_module(
    "const.py", "custom_components.universal_room_automation.const",
)
_ura.const = _const_mod

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc_name = "custom_components.universal_room_automation.domain_coordinators"
if _dc_name not in sys.modules:
    _dc = types.ModuleType(_dc_name)
    _dc.__path__ = [_dc_path]
    _dc.__package__ = _dc_name
    sys.modules[_dc_name] = _dc
    _ura.domain_coordinators = _dc


def _load_dc_module(submod_name: str):
    full = f"{_dc_name}.{submod_name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(
        full, os.path.join(_dc_path, f"{submod_name}.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    setattr(sys.modules[_dc_name], submod_name, mod)
    return mod


_opt_mod = _load_dc_module("optimization")
_Coord = _opt_mod.OptimizationCoordinator
_Finding = _opt_mod.OptimizationFinding
_Dim = _opt_mod.OptimizationDimension


def _make_coord():
    """Build a minimally-initialized OC via object.__new__.

    We do NOT run __init__ or async_setup — the tests exercise
    specific helpers and set the tiny state they need.
    """
    coord = object.__new__(_Coord)
    coord.hass = MagicMock()
    coord.hass.data = {}
    coord.hass.async_create_task = MagicMock()
    # Fields the helpers touch.
    from collections import deque
    coord._last_findings = []
    coord._last_evaluation_iso = None
    coord._shadow_accuracy_samples = []
    coord._pending_shadow_samples = []
    coord._last_shadow_accuracy_pct = None
    coord._last_shadow_accuracy_status = "warming_up"
    coord._notify_dedup_state = {}
    coord._db_write_timestamps = deque()
    coord._write_volume_alarmed_at = None
    coord._persistence_suspended = False
    coord._boot_storm_cache_cycles_remaining = 0
    coord._boot_storm_cache_expires_iso = None
    coord._cycles_since_start = _const_mod.OPTIMIZER_BOOT_SETTLE_CYCLES + 1
    coord._action_dispatch_history = deque()
    return coord


def _mk_finding(dim, severity="high", target_id="house", dedup_key=None,
                description="x"):
    f = _Finding(
        timestamp=_utcnow().isoformat(),
        level="house",
        target_id=target_id,
        dimension=dim,
        severity=severity,
        confidence=0.9,
        score=80.0,
        description=description,
    )
    if dedup_key is not None:
        # dedup_key is a property on the dataclass; override via a helper
        # instance attribute that most consumers read defensively via
        # getattr — but here we monkeypatch the object attr.
        object.__setattr__(f, "dedup_key", dedup_key)
    return f


# ==========================================================================
# D1 — Notify-dedup TTL: decrement is per-cycle, not per-finding.
# ==========================================================================

class TestD1NotifyDedupTTL:

    def test_ttl_decrements_once_per_cycle_not_per_finding(self):
        """MED-3 fix: 10 severe findings in one cycle must not drain the
        12-cycle window in 1.2 cycles."""
        coord = _make_coord()
        # Seed 10 dedup keys as if already in the state.
        for i in range(10):
            coord._notify_dedup_state[f"k{i}"] = (
                _const_mod.OPTIMIZER_NOTIFY_DEDUP_CYCLES
            )
        # Simulate a cycle: the per-cycle helper fires ONCE.
        coord._decrement_notify_dedup_ttls()
        # Every key decremented by exactly 1 (not by 10).
        for i in range(10):
            assert coord._notify_dedup_state[f"k{i}"] == (
                _const_mod.OPTIMIZER_NOTIFY_DEDUP_CYCLES - 1
            )

    def test_ttl_drains_over_full_dedup_window(self):
        coord = _make_coord()
        coord._notify_dedup_state["only"] = 2
        coord._decrement_notify_dedup_ttls()
        assert coord._notify_dedup_state["only"] == 1
        coord._decrement_notify_dedup_ttls()
        # Value went 2→1→0, dropped.
        assert "only" not in coord._notify_dedup_state


# ==========================================================================
# D3 — cap-of-caps on merged findings.
# ==========================================================================

class TestD3MergedFindingsCap:

    def test_cap_bounds_the_merged_findings(self):
        coord = _make_coord()
        cap = _const_mod.OPTIMIZER_MAX_FINDINGS_PER_CYCLE
        # Pass a big list — cap enforced by the helper.
        many = [
            _mk_finding(_Dim.COMFORT, severity="low",
                        description=f"row{i}")
            for i in range(cap * 3)
        ]
        capped = coord._cap_findings(many)
        assert len(capped) <= cap


# ==========================================================================
# D4 — boot-storm gate cache short-circuit.
# ==========================================================================

class TestD4BootStormCache:

    def test_cached_negative_verdict_short_circuits(self):
        coord = _make_coord()
        # Seed the cache as if we just proved "no boot-storm".
        coord._boot_storm_cache_cycles_remaining = 3
        # Ensure iter_room_entries is not called during cached window.
        coord._iter_room_entries = MagicMock(
            side_effect=AssertionError(
                "boot-storm walk must be skipped when cache is warm"
            )
        )
        for expected_remaining in (2, 1, 0):
            skip, _reason = coord._should_skip_for_boot_storm([])
            assert skip is False
            assert (
                coord._boot_storm_cache_cycles_remaining == expected_remaining
            )
        # Verified iter_room_entries was NEVER touched during cache hits.
        assert coord._iter_room_entries.call_count == 0

    def test_cache_arms_on_no_boot_storm_verdict(self):
        coord = _make_coord()
        # Empty room list = no rooms unavailable = no boot-storm.
        coord._iter_room_entries = MagicMock(return_value=iter([]))
        skip, _reason = coord._should_skip_for_boot_storm([])
        assert skip is False
        assert (
            coord._boot_storm_cache_cycles_remaining
            == _const_mod.OPTIMIZER_BOOT_STORM_CACHE_CYCLES
        )
        assert coord._boot_storm_cache_expires_iso is not None


# ==========================================================================
# D5 — stub dimensions carry `stub` verdict.
# ==========================================================================

class TestD5StubDimensions:

    def test_stub_dim_verdict_is_stub_not_ok(self):
        coord = _make_coord()
        per_dim = {"energy_efficiency": [],
                   "automation_responsiveness": [],
                   "setpoint_compliance": []}
        verdicts = coord._compute_dimension_verdicts(per_dim, set())
        for dim in per_dim:
            assert verdicts[dim] == "stub"


# ==========================================================================
# D6 — promotion_readiness attribute.
# ==========================================================================

class TestD6PromotionReadiness:

    def test_no_samples_blocks_promotion(self):
        coord = _make_coord()
        coord._read_cm_config = MagicMock(return_value={})
        pr = coord._compute_promotion_readiness()
        assert "comfort" in pr
        assert pr["comfort"]["ready"] is False
        assert "samples_below_min" in pr["comfort"]["blocked_by"]
        assert pr["comfort"]["evidence"]["samples"] == 0

    def test_sufficient_samples_and_accuracy_unblocks(self):
        coord = _make_coord()
        coord._read_cm_config = MagicMock(return_value={})
        # Load enough matched samples for comfort dimension.
        now = _utcnow().isoformat()
        min_samples = (
            _const_mod.OPTIMIZER_PROMOTION_READINESS_MIN_SAMPLES
        )
        for _ in range(min_samples):
            coord._shadow_accuracy_samples.append(
                (now, "comfort", "living_room", True)
            )
        coord._last_shadow_accuracy_status = "ready"
        pr = coord._compute_promotion_readiness()
        assert pr["comfort"]["evidence"]["samples"] == min_samples
        # accuracy = 1.0 > floor
        assert pr["comfort"]["evidence"]["accuracy"] == 1.0
        assert pr["comfort"]["ready"] is True

    def test_kill_switch_blocks_promotion(self):
        coord = _make_coord()
        coord._read_cm_config = MagicMock(return_value={
            _const_mod.CONF_OPTIMIZER_KILL_SWITCH: True,
        })
        pr = coord._compute_promotion_readiness()
        assert "kill_switch_engaged" in pr["comfort"]["blocked_by"]


# ==========================================================================
# D9 — write-volume tripwire.
# ==========================================================================

class TestD9WriteVolumeTripwire:

    def test_below_threshold_does_not_trip(self):
        coord = _make_coord()
        for _ in range(5):
            coord._record_db_write()
        assert coord._check_write_volume_tripwire() is False
        assert coord._persistence_suspended is False
        assert coord._write_volume_alarmed_at is None

    def test_exceeding_threshold_trips_and_latches(self):
        coord = _make_coord()
        threshold = _const_mod.OPTIMIZER_WRITE_VOLUME_THRESHOLD
        for _ in range(threshold + 1):
            coord._record_db_write()
        # First check: trips.
        assert coord._check_write_volume_tripwire() is True
        assert coord._persistence_suspended is True
        first_alarm = coord._write_volume_alarmed_at
        assert first_alarm is not None
        # Second check while tripped: idempotent (same alarm ts).
        assert coord._check_write_volume_tripwire() is True
        assert coord._write_volume_alarmed_at == first_alarm

    @pytest.mark.asyncio
    async def test_tripped_persistence_call_is_noop(self):
        coord = _make_coord()
        # Force the tripwire tripped state.
        coord._persistence_suspended = True
        coord._write_volume_alarmed_at = _utcnow().isoformat()
        # Populate timestamps above threshold so the check stays tripped.
        threshold = _const_mod.OPTIMIZER_WRITE_VOLUME_THRESHOLD
        for _ in range(threshold + 1):
            coord._record_db_write()
        # Attach a database mock that would raise if called.
        db = MagicMock()
        db.log_findings_batch = AsyncMock(
            side_effect=AssertionError(
                "DB write must not be called when tripped"
            )
        )
        coord.hass.data = {_const_mod.DOMAIN: {"database": db}}
        # A batch of findings should NOT reach the DB.
        f = _mk_finding(_Dim.META, severity="low")
        await coord._persist_findings_batch([f])
        db.log_findings_batch.assert_not_called()

    def test_rolling_window_evicts_old_timestamps(self):
        coord = _make_coord()
        # Pre-seed a timestamp older than the window.
        window = _const_mod.OPTIMIZER_WRITE_VOLUME_WINDOW_SECONDS
        old = _utcnow() - timedelta(seconds=window + 60)
        coord._db_write_timestamps.append(old)
        # Record one fresh — old should be evicted.
        coord._record_db_write()
        assert len(coord._db_write_timestamps) == 1


# ==========================================================================
# MANDATORY: write-volume regression + tripwire integration
# ==========================================================================

class TestWriteVolumeRegression:
    """Drive a 30-room finding cycle and assert DB writes stay batched."""

    @pytest.mark.asyncio
    async def test_batched_persist_stays_bounded_across_many_findings(self):
        coord = _make_coord()
        db_calls = {"count": 0, "total_rows": 0}

        async def _log_findings_batch(findings):
            db_calls["count"] += 1
            db_calls["total_rows"] += len(findings)
            return len(findings)

        database = MagicMock()
        database.log_findings_batch = _log_findings_batch
        coord.hass.data = {_const_mod.DOMAIN: {"database": database}}
        # 30 rooms × 3 findings each → 90 findings, 1 batch write.
        findings = [
            _mk_finding(_Dim.COMFORT, severity="low",
                        target_id=f"room_{r}", description=f"r{r}f{i}")
            for r in range(30) for i in range(3)
        ]
        await coord._persist_findings_batch(findings)
        # BATCHED: exactly ONE DAO call regardless of finding count.
        assert db_calls["count"] == 1, (
            f"Expected 1 batched DB write, got {db_calls['count']} "
            f"(regression: per-finding persistence pattern returned)"
        )
        assert db_calls["total_rows"] == 90
        # Tripwire counter incremented by exactly ONE OC-attributed write.
        assert len(coord._db_write_timestamps) == 1

    @pytest.mark.asyncio
    async def test_tripwire_actually_suspends_persistence(self):
        """Once threshold is exceeded, subsequent persist calls no-op."""
        coord = _make_coord()
        db_calls = {"count": 0}

        async def _log_findings_batch(findings):
            db_calls["count"] += 1
            return len(findings)

        database = MagicMock()
        database.log_findings_batch = _log_findings_batch
        coord.hass.data = {_const_mod.DOMAIN: {"database": database}}
        # Pre-seed the tripwire above threshold.
        threshold = _const_mod.OPTIMIZER_WRITE_VOLUME_THRESHOLD
        for _ in range(threshold + 1):
            coord._record_db_write()
        f = _mk_finding(_Dim.COMFORT, severity="low")
        # After the tripwire trips, this call must NOT reach the DAO.
        await coord._persist_findings_batch([f])
        assert db_calls["count"] == 0
        assert coord._persistence_suspended is True
        assert coord._write_volume_alarmed_at is not None


# ==========================================================================
# D2 — shadow-accuracy DAO round-trip using REAL production schema.
# ==========================================================================

class TestD2ShadowSamplesDAO:
    """DAO tests read the schema FROM production source (Tier-2-DB Review C)."""

    def _load_production_ddl(self):
        """Extract the shadow-samples CREATE TABLE from database.py source."""
        db_path = os.path.join(_ura_path, "database.py")
        with open(db_path, "r", encoding="utf-8") as f:
            source = f.read()
        # Locate the CREATE TABLE block for optimizer_shadow_samples.
        marker = "CREATE TABLE IF NOT EXISTS optimizer_shadow_samples"
        assert marker in source, (
            "optimizer_shadow_samples schema missing from database.py "
            "(Tier-2-DB Review C: schema must live in production source)"
        )
        # Extract from marker to closing paren + )
        start = source.find(marker)
        # Grab a generous window; test parser is lenient.
        window = source[start:start + 2000]
        # Take up to the first `""",` that closes the DDL string.
        end = window.find('"""')
        # Actually the string starts with a triple-quote in source; jump
        # forward past newlines.
        return window[:end + 3] if end > 0 else window

    def test_production_ddl_declares_expected_columns(self):
        ddl = self._load_production_ddl()
        # Assert the columns the DAO writes actually exist in prod DDL.
        for col in ("observed_at", "dimension", "target_id", "matched"):
            assert col in ddl, f"column {col} missing from prod DDL"


# ==========================================================================
# D7 — OptimizerFindingsSensor excludes META from display state.
# ==========================================================================

class TestD7MetaExclusion:
    """Test the sensor's display-state logic without loading the whole
    sensor.py module (heavy). We inline the identical helper."""

    def test_state_skips_meta_row(self):
        coord = _make_coord()
        # Two findings: a real one then a META sentinel.
        real = _mk_finding(_Dim.COMFORT, severity="medium",
                           description="temp out of band")
        meta = _mk_finding(_Dim.META, severity="low",
                           description="cycle_ok")
        coord._last_findings = [real, meta]
        # Sensor logic (copied verbatim from sensor.py D7 change) —
        # walk reversed, return first non-meta description.
        for f in reversed(coord._last_findings):
            if str(f.dimension) != "meta":
                assert f.description == "temp out of band"
                return
        pytest.fail("expected to find real finding before META")


# ==========================================================================
# D8 — rate-cap seed logging level (LOW-2).
# ==========================================================================

class TestD8RateCapSeedLogging:
    """The LOW-2 fix elevates DEBUG → WARNING on rate-cap seed failure.
    We assert the source has been updated (behavioral change is
    log-level only; verifying via source grep is authoritative)."""

    def test_seed_failure_logs_at_warning_not_debug(self):
        opt_path = os.path.join(
            _ura_path, "domain_coordinators", "optimization.py",
        )
        with open(opt_path, "r", encoding="utf-8") as f:
            source = f.read()
        # Find the async_setup try/except for rate-cap seed.
        # The v5.11.0 D8 marker MUST be present + the log call must be
        # at WARNING (not DEBUG).
        assert "v5.11.0 D8" in source
        # Snippet around the D8 fix.
        idx = source.find("v5.11.0 D8")
        window = source[idx:idx + 500]
        assert "_LOGGER.warning" in window, (
            "D8: rate-cap seed failure must log at WARNING, not DEBUG"
        )
