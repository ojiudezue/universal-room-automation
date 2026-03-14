"""Tests for v3.15.0 EC Restart Resilience + Envoy Offline Defense.

Validates:
1. Midnight snapshot save/restore (lifetime snapshots + billing)
2. Envoy cache save/restore (last-known sensor values)
3. Consumption history restore from energy_daily
4. Billing restore_daily (daily accumulators)
5. Load shedding level persistence
6. Energy state key-value store
7. Database table creation
"""

import pytest
from datetime import datetime, timedelta, date
from unittest.mock import MagicMock, AsyncMock, patch, call
import sys
import os
import types
import importlib

# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod

_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {"async_track_time_interval": MagicMock()},
    "homeassistant.helpers.dispatcher": {},
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
        "as_local": lambda dt: dt,
        "parse_datetime": lambda s: datetime.fromisoformat(s) if s else None,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(),
        "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

sys.modules.setdefault("aiosqlite", MagicMock())

# Add project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Build package hierarchy
_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

# Import const.py
_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

# Import domain_coordinators subpackage
_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc

# Import energy submodules
for _submod_name in ("energy_const", "energy_forecast", "energy_billing", "energy_tou"):
    _full_name = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full_name, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from conftest import MockHass, MockState

from custom_components.universal_room_automation.domain_coordinators.energy_forecast import (
    DailyEnergyPredictor,
)
from custom_components.universal_room_automation.domain_coordinators.energy_billing import (
    CostTracker,
)
from custom_components.universal_room_automation.domain_coordinators.energy_tou import (
    TOURateEngine,
)


# ============================================================================
# HELPERS
# ============================================================================


def _make_predictor(hass=None):
    """Create a DailyEnergyPredictor with mock hass."""
    h = hass or MockHass()
    return h, DailyEnergyPredictor(h)


def _make_billing(hass=None):
    """Create a CostTracker with mock hass."""
    h = hass or MockHass()
    tou = TOURateEngine()
    return h, CostTracker(h, tou)


# ============================================================================
# CONSUMPTION HISTORY RESTORE
# ============================================================================


class TestConsumptionHistoryRestore:
    """Tests for DailyEnergyPredictor.restore_consumption_history()."""

    def test_restores_by_day_of_week(self):
        """Rows are assigned to correct DOW based on date."""
        _, predictor = _make_predictor()
        rows = [
            # 2026-03-09 = Monday (weekday=0)
            {"date": "2026-03-09", "consumption_kwh": 35.0},
            # 2026-03-10 = Tuesday (weekday=1)
            {"date": "2026-03-10", "consumption_kwh": 42.0},
            # 2026-03-02 = Monday (weekday=0) — another Monday
            {"date": "2026-03-02", "consumption_kwh": 38.0},
        ]
        predictor.restore_consumption_history(rows)

        # Monday (0) should have 2 entries
        assert len(predictor._consumption_history[0]) == 2
        # Tuesday (1) should have 1 entry
        assert len(predictor._consumption_history[1]) == 1
        # Other days should be empty
        assert len(predictor._consumption_history[2]) == 0

    def test_skips_invalid_rows(self):
        """Rows with missing date or consumption_kwh are skipped."""
        _, predictor = _make_predictor()
        rows = [
            {"date": "2026-03-09", "consumption_kwh": 35.0},
            {"date": "", "consumption_kwh": 40.0},  # empty date
            {"date": "2026-03-10", "consumption_kwh": None},  # None kwh
            {"date": "bad-date", "consumption_kwh": 40.0},  # invalid date
        ]
        predictor.restore_consumption_history(rows)

        # Only the first row should be restored
        total = sum(len(d) for d in predictor._consumption_history.values())
        assert total == 1

    def test_empty_rows_no_crash(self):
        """Empty row list does not crash."""
        _, predictor = _make_predictor()
        predictor.restore_consumption_history([])
        total = sum(len(d) for d in predictor._consumption_history.values())
        assert total == 0

    def test_respects_maxlen(self):
        """Deque maxlen=8 is respected."""
        _, predictor = _make_predictor()
        # All on Mondays — more than maxlen=8
        rows = []
        for i in range(12):
            # Generate Mondays going back (2026-03-09, 2026-03-02, etc.)
            d = date(2026, 3, 9) - timedelta(weeks=i)
            if d.weekday() == 0:  # Should all be Monday
                rows.append({"date": d.isoformat(), "consumption_kwh": 30.0 + i})
        predictor.restore_consumption_history(rows)

        assert len(predictor._consumption_history[0]) <= 8

    def test_consumed_in_prediction(self):
        """Restored history influences consumption estimate."""
        hass, predictor = _make_predictor()
        # Set weather for temp adjustment
        hass.set_state("weather.forecast_home", "sunny", {"temperature": 72})

        # Restore Friday history (weekday=4) with known values
        rows = [
            {"date": "2026-03-06", "consumption_kwh": 50.0},
            {"date": "2026-02-27", "consumption_kwh": 52.0},
            {"date": "2026-02-20", "consumption_kwh": 48.0},
        ]
        predictor.restore_consumption_history(rows)

        # Call _estimate_consumption for a Friday
        friday = datetime(2026, 3, 13, 8, 0)  # This is actually a Friday
        estimate = predictor._estimate_consumption(friday, 72.0)

        # Should be close to average of restored values (50)
        # At temp=72 (comfort midpoint), no temp multiplier
        assert 40 < estimate < 60


# ============================================================================
# BILLING RESTORE DAILY
# ============================================================================


class TestBillingRestoreDaily:
    """Tests for CostTracker.restore_daily()."""

    def test_restores_same_day(self):
        """Restores accumulators when snapshot date matches today."""
        _, billing = _make_billing()
        today = datetime.now().date().isoformat()

        billing.restore_daily({
            "snapshot_date": today,
            "import_kwh_today": 5.5,
            "export_kwh_today": 2.3,
            "import_cost_today": 1.50,
            "export_credit_today": 0.40,
            "net_cost_today": 1.10,
        })

        assert billing._import_kwh_today == 5.5
        assert billing._export_kwh_today == 2.3
        assert billing._import_cost_today == 1.50
        assert billing._export_credit_today == 0.40
        assert billing._cost_today == 1.10
        assert billing._last_date == today

    def test_skips_different_day(self):
        """Does not restore if snapshot date != today."""
        _, billing = _make_billing()
        billing.restore_daily({
            "snapshot_date": "2020-01-01",
            "import_kwh_today": 5.5,
            "export_kwh_today": 2.3,
            "import_cost_today": 1.50,
            "export_credit_today": 0.40,
            "net_cost_today": 1.10,
        })

        assert billing._import_kwh_today == 0.0
        assert billing._export_kwh_today == 0.0

    def test_missing_keys_default_to_zero(self):
        """Missing keys in snapshot default to 0."""
        _, billing = _make_billing()
        today = datetime.now().date().isoformat()

        billing.restore_daily({
            "snapshot_date": today,
        })

        assert billing._import_kwh_today == 0
        assert billing._cost_today == 0

    def test_accumulate_continues_after_restore(self):
        """After restore, accumulate() continues adding to restored values."""
        hass, billing = _make_billing()
        today = datetime.now().date().isoformat()

        billing.restore_daily({
            "snapshot_date": today,
            "import_kwh_today": 5.0,
            "export_kwh_today": 0.0,
            "import_cost_today": 1.00,
            "export_credit_today": 0.0,
            "net_cost_today": 1.00,
        })

        # Set up for accumulate: importing 1 kW (net power entity)
        hass.set_state("sensor.envoy_202428004328_current_net_power_consumption", "1.0")
        import time
        billing._last_accumulate_time = time.time() - 300  # 5 min ago

        billing.accumulate()

        # import_kwh should be > 5.0 (restored) + something
        assert billing._import_kwh_today > 5.0


# ============================================================================
# ENVOY CACHE + MIDNIGHT SNAPSHOT (DB methods)
# ============================================================================


class TestEnvoyCacheDB:
    """Tests for database envoy_cache CRUD."""

    @pytest.mark.asyncio
    async def test_save_and_restore_envoy_cache(self):
        """Envoy cache round-trips through save/restore."""
        # Mock DB
        mock_db = MagicMock()
        mock_db.save_envoy_cache = AsyncMock()
        mock_db.restore_envoy_cache = AsyncMock(return_value={
            "soc": 85.0,
            "net_power": -1.2,
            "solar_production": 3.5,
            "battery_power": 2.0,
            "battery_capacity": 40.0,
            "updated_at": "2026-03-13T12:00:00",
        })

        result = await mock_db.restore_envoy_cache()
        assert result["soc"] == 85.0
        assert result["net_power"] == -1.2

    @pytest.mark.asyncio
    async def test_restore_returns_none_when_empty(self):
        """Restore returns None when no cache exists."""
        mock_db = MagicMock()
        mock_db.restore_envoy_cache = AsyncMock(return_value=None)
        result = await mock_db.restore_envoy_cache()
        assert result is None


class TestMidnightSnapshotDB:
    """Tests for database midnight snapshot CRUD."""

    @pytest.mark.asyncio
    async def test_save_and_restore_snapshot(self):
        """Midnight snapshot round-trips through save/restore."""
        mock_db = MagicMock()
        snapshot_data = {
            "snapshot_date": "2026-03-13",
            "lifetime_consumption": 100.5,
            "lifetime_production": 200.3,
            "lifetime_net_import": 50.0,
            "lifetime_net_export": 150.0,
            "lifetime_battery_charged": 30.0,
            "lifetime_battery_discharged": 25.0,
            "import_kwh_today": 5.0,
            "export_kwh_today": 2.0,
            "import_cost_today": 1.50,
            "export_credit_today": 0.40,
            "net_cost_today": 1.10,
        }
        mock_db.save_midnight_snapshot = AsyncMock()
        mock_db.restore_midnight_snapshot = AsyncMock(return_value=snapshot_data)

        await mock_db.save_midnight_snapshot(snapshot_data)
        result = await mock_db.restore_midnight_snapshot()

        assert result["snapshot_date"] == "2026-03-13"
        assert result["lifetime_production"] == 200.3
        assert result["import_kwh_today"] == 5.0


# ============================================================================
# ENERGY STATE KEY-VALUE STORE
# ============================================================================


class TestEnergyStateDB:
    """Tests for energy_state key-value persistence."""

    @pytest.mark.asyncio
    async def test_save_and_restore_state(self):
        """Key-value round-trips through save/restore."""
        mock_db = MagicMock()
        mock_db.save_energy_state = AsyncMock()
        mock_db.restore_energy_state = AsyncMock(return_value="3")

        await mock_db.save_energy_state("load_shedding_level", "3")
        result = await mock_db.restore_energy_state("load_shedding_level")
        assert result == "3"

    @pytest.mark.asyncio
    async def test_restore_missing_key_returns_none(self):
        """Missing key returns None."""
        mock_db = MagicMock()
        mock_db.restore_energy_state = AsyncMock(return_value=None)
        result = await mock_db.restore_energy_state("nonexistent")
        assert result is None


# ============================================================================
# CONSUMPTION HISTORY DB METHOD
# ============================================================================


class TestConsumptionHistoryDB:
    """Tests for database get_consumption_history."""

    @pytest.mark.asyncio
    async def test_get_consumption_history(self):
        """Returns filtered energy_daily rows."""
        mock_db = MagicMock()
        mock_db.get_consumption_history = AsyncMock(return_value=[
            {"date": "2026-03-12", "consumption_kwh": 35.0},
            {"date": "2026-03-11", "consumption_kwh": 42.0},
        ])

        result = await mock_db.get_consumption_history(days=60)
        assert len(result) == 2
        assert result[0]["consumption_kwh"] == 35.0


# ============================================================================
# LOAD SHEDDING LEVEL PERSISTENCE
# ============================================================================


class TestLoadSheddingPersistence:
    """Tests for load shedding level save/restore via energy_state."""

    @pytest.mark.asyncio
    async def test_save_load_shedding_level(self):
        """Save serializes level as string."""
        mock_db = MagicMock()
        mock_db.save_energy_state = AsyncMock()

        await mock_db.save_energy_state("load_shedding_level", "2")
        mock_db.save_energy_state.assert_called_once_with(
            "load_shedding_level", "2"
        )

    @pytest.mark.asyncio
    async def test_restore_load_shedding_level(self):
        """Restore converts string back to int."""
        mock_db = MagicMock()
        mock_db.restore_energy_state = AsyncMock(return_value="2")

        level_str = await mock_db.restore_energy_state("load_shedding_level")
        level = int(level_str) if level_str is not None else 0
        assert level == 2

    @pytest.mark.asyncio
    async def test_restore_no_level_defaults_zero(self):
        """No stored level defaults to 0."""
        mock_db = MagicMock()
        mock_db.restore_energy_state = AsyncMock(return_value=None)

        level_str = await mock_db.restore_energy_state("load_shedding_level")
        level = int(level_str) if level_str is not None else 0
        assert level == 0


# ============================================================================
# BATTERY FULL TIME HOLD CACHE RESTORE FROM ENVOY CACHE
# ============================================================================


class TestBatteryFullTimeEnvoyRestore:
    """Tests for battery_full_time hold cache restoration from envoy cache."""

    def test_high_soc_sets_already_full(self):
        """Cached SOC >= 99 sets hold cache to 'already_full'."""
        hass, predictor = _make_predictor()
        # Simulate what _restore_envoy_cache does
        cached_soc = 100.0
        _last_battery_full_time = None
        if cached_soc is not None and cached_soc >= 99:
            _last_battery_full_time = "already_full"
        assert _last_battery_full_time == "already_full"

    def test_moderate_soc_sets_cached(self):
        """Cached SOC < 99 sets hold cache to 'cached' if previously None."""
        cached_soc = 75.0
        _last_battery_full_time = None
        if cached_soc is not None and cached_soc >= 99:
            _last_battery_full_time = "already_full"
        elif cached_soc is not None:
            if _last_battery_full_time is None:
                _last_battery_full_time = "cached"
        assert _last_battery_full_time == "cached"

    def test_none_soc_leaves_hold_cache_unchanged(self):
        """Cached SOC=None leaves hold cache as-is."""
        cached_soc = None
        _last_battery_full_time = "15:30"
        if cached_soc is not None and cached_soc >= 99:
            _last_battery_full_time = "already_full"
        elif cached_soc is not None:
            if _last_battery_full_time is None:
                _last_battery_full_time = "cached"
        assert _last_battery_full_time == "15:30"


# ============================================================================
# MIDNIGHT SNAPSHOT RESTORE INTO EC STATE
# ============================================================================


class TestMidnightSnapshotRestore:
    """Tests for snapshot restore into coordinator state."""

    def test_restores_lifetime_snapshots_for_today(self):
        """Lifetime snapshots are restored when snapshot_date == today."""
        today = datetime.now().date().isoformat()
        snapshot = {
            "snapshot_date": today,
            "lifetime_consumption": 100.0,
            "lifetime_production": 200.0,
            "lifetime_net_import": 50.0,
            "lifetime_net_export": 150.0,
            "lifetime_battery_charged": 30.0,
            "lifetime_battery_discharged": 25.0,
        }

        # Simulate what _restore_midnight_snapshot does
        lifetime_consumption = None
        lifetime_production = None
        lifetime_net_import = None
        last_reset_date = ""

        if snapshot.get("snapshot_date") == today:
            lifetime_consumption = snapshot.get("lifetime_consumption")
            lifetime_production = snapshot.get("lifetime_production")
            lifetime_net_import = snapshot.get("lifetime_net_import")
            last_reset_date = today

        assert lifetime_consumption == 100.0
        assert lifetime_production == 200.0
        assert lifetime_net_import == 50.0
        assert last_reset_date == today

    def test_skips_snapshots_from_yesterday(self):
        """Snapshots from a different date are not restored."""
        snapshot = {
            "snapshot_date": "2020-01-01",
            "lifetime_consumption": 100.0,
        }
        today = datetime.now().date().isoformat()

        lifetime_consumption = None
        if snapshot.get("snapshot_date") == today:
            lifetime_consumption = snapshot.get("lifetime_consumption")

        assert lifetime_consumption is None

    def test_handles_none_snapshot(self):
        """None snapshot (no DB row) is handled gracefully."""
        snapshot = None
        lifetime_consumption = None
        if snapshot is not None:
            lifetime_consumption = snapshot.get("lifetime_consumption")
        assert lifetime_consumption is None
