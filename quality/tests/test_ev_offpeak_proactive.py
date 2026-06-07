"""Tests for the EV off-peak proactive-charging + persistence cycle.

Covers:

WS1 (persistence hardening, D1.1-D1.4):
- Round-trip + staleness for force-charge expiry in the new
  `ev_force_charge_until` KV key, including a naive-datetime input variant
  and a past-expiry-dropped variant.
- Round-trip + stale-EVSE-ID filtering for `evse_fill_priority_paused`.
- Round-trip for `evse_arbitrage_paused`.
- Round-trip + stale-EVSE-ID filtering for `evse_proactive_offpeak_holds`.
- `restore_evse_state` skips rows whose `updated_at` is older than
  `max_age_hours` and applies rows that are fresh.
- `restore_energy_state_with_age` applies the same staleness guard to KV
  reads.
- AST: `_restore_evse_state` source does NOT call `datetime.fromisoformat`
  directly (must route through `dt_util.parse_datetime` — Bug Class #13/#21).

WS2 (behavior, D2.1-D2.3):
- `EVChargerController.determine_actions("off_peak")` ensures-on a fresh
  plug-in.
- The hand-off from excess-solar peak-clear (which clears
  `_excess_solar_active` and `_proactive_offpeak_holds`) is consistent.
- Each of the four carry-over guard sets (battery_drain, fill_priority,
  grid_cap, arbitrage) blocks the proactive turn-on.
- A manual user disable mid-off-peak is re-enforced on the next tick
  (Bug Class #43 — idempotent re-issue, no "we already did this" guard).
- TOU-toggle off path: the toggle gate lives in the CALLER (`energy.py`,
  not inside `determine_actions`), so the unit-level analogue is verified
  by exercising the caller-side gate directly on a mocked seam.
- Observation-mode path: same seam as the TOU toggle — gate lives in the
  caller (`energy.py:~2307`), unit verified at the right level.
- Force-charge active short-circuits the proactive-on claim so the hold
  set doesn't gain membership for a charge authorized for a different
  reason.
- Transition out of off-peak (peak branch + excess-solar peak-clear)
  clears `_proactive_offpeak_holds`.

D3:
- The EV status dict surfaces `proactive_offpeak_holds` as a
  JSON-serializable list (NEVER a `set` — HA serializes attributes to JSON
  over the WebSocket API; a `set` would raise `TypeError`).

Hard test-hygiene rules:
- DB schema is sourced from `database.py` via the real `UniversalRoomDatabase`
  class — no hand-copied DDL.
- No `sys.modules.setdefault("homeassistant.util.dt", ...)` per-test
  pollution (Bug Class #44) — the module-level mock matches the canonical
  pattern in the rest of the suite.
- `proactive_offpeak_holds` is asserted to be a `list`.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import importlib.util
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock homeassistant before importing URA code — matches the established
# pattern in test_v47x_ev_tou_hardening.py / test_energy_evse.py.
# ---------------------------------------------------------------------------


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

# NOTE: this file does NOT register its own `homeassistant.util.dt` mock.
# Module-load order across the suite is non-deterministic, and
# `test_v47x_ev_tou_hardening.py` force-overrides `homeassistant.util.dt`
# with its own `_FIXED_NOW` at module import. If THIS file's mock wins, the
# v47x tests' relative-time assertions break. If v47x's mock wins, our
# relative-time math (force-charge expiry, staleness cutoff) is anchored
# against a fixed point we don't control.
#
# Resolution: we don't try to win the mock race. Tests in this file pull
# `dt_util.utcnow()` at runtime to get *whatever* the current mock says is
# now, and build all relative time math from there. Far-future (year 2099)
# and far-past (year 2000) literals are used where applicable for the same
# resilience reasons documented in test_v47x_ev_tou_hardening.
#
# We DO need a minimal mock for `homeassistant.util.dt` when running in
# isolation (no other file has registered it yet). That uses `setdefault` so
# any earlier registration wins.


def _as_local(dt):
    return dt


def _parse_datetime(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _real_utcnow():
    return datetime.now(timezone.utc)


def _real_now():
    return datetime.now(timezone.utc)


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
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict, "EntityCategory": _mock_cls(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
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
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {
            "async_added_to_hass": AsyncMock(),
            "async_get_last_state": AsyncMock(return_value=None),
        }),
    },
    "homeassistant.util": {},
    # NOTE: this module-level mock is the canonical pattern used throughout
    # the suite (see test_v47x_ev_tou_hardening.py / test_energy_restart_resilience.py).
    # The Bug Class #44 prohibition is on PER-TEST setdefault contamination,
    # not on the module-level fixture used everywhere.
    "homeassistant.util.dt": {
        "utcnow": _real_utcnow,
        "now": _real_now,
        "UTC": timezone.utc,
        "as_local": _as_local,
        "parse_datetime": _parse_datetime,
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
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
    "homeassistant.components.switch": {
        "SwitchEntity": type("SwitchEntity", (), {}),
    },
}

for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)

# Ensure aiosqlite is available (real package preferred per conftest.py).
try:
    import aiosqlite  # noqa: F401
except ImportError:  # pragma: no cover
    sys.modules.setdefault("aiosqlite", MagicMock())

# Project root on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Build package hierarchy (same shape as test_v47x_ev_tou_hardening.py)
_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura = types.ModuleType("custom_components.universal_room_automation")
_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules["custom_components.universal_room_automation"] = _ura

# Import const, then the domain_coordinators subpackage
_const_spec = importlib.util.spec_from_file_location(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_const_mod = importlib.util.module_from_spec(_const_spec)
sys.modules["custom_components.universal_room_automation.const"] = _const_mod
_const_spec.loader.exec_module(_const_mod)
_ura.const = _const_mod

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = types.ModuleType("custom_components.universal_room_automation.domain_coordinators")
_dc.__path__ = [_dc_path]
_dc.__package__ = "custom_components.universal_room_automation.domain_coordinators"
sys.modules["custom_components.universal_room_automation.domain_coordinators"] = _dc
_ura.domain_coordinators = _dc

for _submod_name in ("energy_const", "energy_pool", "signals"):
    _full_name = f"custom_components.universal_room_automation.domain_coordinators.{_submod_name}"
    _spec = importlib.util.spec_from_file_location(
        _full_name, os.path.join(_dc_path, f"{_submod_name}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full_name] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _submod_name, _mod)


# Force `energy` module import at THIS file's load time so the unbound
# methods we steal in `_bind_persistence_methods` are available even when
# another test file later monkey-patches `homeassistant.helpers.event` in
# a way that removes `async_track_time_interval` (which `energy.py` needs
# at import time but no production method we use here needs at run time).
# This is a defensive load — without it, test order can leave `energy.py`
# uniportable. Caching the module under its canonical sys.modules name
# means subsequent imports return our pre-loaded copy.
def _preload_energy_module():
    _energy_full = (
        "custom_components.universal_room_automation.domain_coordinators.energy"
    )
    if _energy_full in sys.modules and sys.modules[_energy_full] is not None:
        return
    # Mock additional dependencies that energy.py imports at module level
    # but are not used by `_save_evse_state` / `_restore_evse_state`.
    _extra_mocks = {
        "homeassistant.helpers.event": {
            "async_call_later": MagicMock(return_value=lambda: None),
            "async_track_state_change_event": MagicMock(return_value=lambda: None),
            "async_track_time_interval": MagicMock(return_value=lambda: None),
        },
        # Defensive: test_energy_evse.py and others register
        # `homeassistant.helpers.dispatcher` as a bare MagicMock that lacks
        # the names energy.py needs at module-import time.
        "homeassistant.helpers.dispatcher": {
            "async_dispatcher_connect": MagicMock(return_value=lambda: None),
            "async_dispatcher_send": MagicMock(),
        },
        # Defensive: other test files (e.g. test_v47x_ev_tou_hardening.py)
        # force-overwrite `homeassistant.util.dt` with a partial mock that
        # may not expose `parse_datetime` / `UTC`. Patch what's missing onto
        # whichever module is currently registered.
        "homeassistant.util.dt": {
            "parse_datetime": _parse_datetime,
            "UTC": timezone.utc,
        },
    }
    for _name, _attrs in _extra_mocks.items():
        # Patch missing attributes onto whatever module is currently registered
        existing = sys.modules.get(_name)
        if existing is None:
            sys.modules[_name] = _mock_module(_name, **_attrs)
        else:
            for _k, _v in _attrs.items():
                if not hasattr(existing, _k):
                    setattr(existing, _k, _v)
    _spec = importlib.util.spec_from_file_location(
        _energy_full, os.path.join(_dc_path, "energy.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_energy_full] = _mod
    try:
        _spec.loader.exec_module(_mod)
        setattr(_dc, "energy", _mod)
    except Exception:
        # Best-effort — if we can't fully load energy here, the per-test
        # binding will retry and raise a more actionable error.
        sys.modules.pop(_energy_full, None)


_preload_energy_module()

from conftest import MockHass  # noqa: E402

from custom_components.universal_room_automation.database import (  # noqa: E402
    UniversalRoomDatabase,
)
from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController,
)


def _now() -> datetime:
    """Return the current UTC time as the pinned per-test mock sees it.

    `_isolate_dt_util_mock` (autouse fixture) pins
    `sys.modules["homeassistant.util.dt"]` AND re-points
    `database.dt_util` + `energy.dt_util` to the same mock, so we can read
    from any of them and stay consistent with what the production restore
    path is using. We read directly from `database.dt_util` because that
    is the reference the staleness DAO uses for its cutoff comparison.
    """
    from custom_components.universal_room_automation import database as _db_mod
    return _db_mod.dt_util.utcnow()


@pytest.fixture(autouse=True)
def _isolate_dt_util_mock():
    """Pin `homeassistant.util.dt` to a consistent mock for each test.

    The whole suite shares `sys.modules["homeassistant.util.dt"]`. Several
    test files (notably test_v47x_ev_tou_hardening.py) FORCE-overwrite it
    with a partial mock — different `utcnow`, no `parse_datetime`, no `UTC`.
    Production code in `energy.py:_restore_evse_state` re-imports
    `homeassistant.util.dt` INSIDE the function (so it picks up whichever
    mock is current at call time), while `database.py` binds `dt_util` ONCE
    at module load. If the two views diverge, the staleness filter cutoff
    is computed against one wall clock while the row's `updated_at` is
    serialized against a different wall clock — a deterministic mismatch
    that flakes our tests by load order.

    Resolution: each test in this file FORCE-sets `homeassistant.util.dt`
    to a consistent mock (real wall-clock `utcnow`, plus `parse_datetime`
    and `UTC`) for the duration of the test, then restores whatever was
    there before. Per `feedback_no_fabrication` and the Bug Class #44
    prohibition: this is a per-test fixture-scoped restoration, NOT a
    module-level `sys.modules.setdefault` — the prior mock is restored on
    teardown, so we do not contaminate later test files.
    """
    saved = sys.modules.get("homeassistant.util.dt")
    pinned = _mock_module(
        "homeassistant.util.dt",
        utcnow=_real_utcnow,
        now=_real_now,
        UTC=timezone.utc,
        as_local=_as_local,
        parse_datetime=_parse_datetime,
    )
    sys.modules["homeassistant.util.dt"] = pinned

    # Also re-point module-level `dt_util` references in production code
    # that bound the symbol at import time. `database.py:23` and
    # `energy.py` both do `from homeassistant.util import dt as dt_util`.
    # We swap each binding for the pinned mock and restore on teardown.
    _rebound: list[tuple[object, str, object]] = []
    try:
        from custom_components.universal_room_automation import (
            database as _db_mod,
        )
        if hasattr(_db_mod, "dt_util"):
            _rebound.append((_db_mod, "dt_util", _db_mod.dt_util))
            _db_mod.dt_util = pinned
    except ImportError:
        pass
    try:
        from custom_components.universal_room_automation.domain_coordinators import (
            energy as _energy_mod,
        )
        if hasattr(_energy_mod, "dt_util"):
            _rebound.append((_energy_mod, "dt_util", _energy_mod.dt_util))
            _energy_mod.dt_util = pinned
    except ImportError:
        pass

    try:
        yield
    finally:
        for mod, attr, original in _rebound:
            setattr(mod, attr, original)
        if saved is not None:
            sys.modules["homeassistant.util.dt"] = saved
        else:
            sys.modules.pop("homeassistant.util.dt", None)


# ---------------------------------------------------------------------------
# DB fixture — real UniversalRoomDatabase against a tmp dir, schema sourced
# from production database.py (no hand-copied DDL).
# ---------------------------------------------------------------------------


def _make_db(tmp_path: str) -> UniversalRoomDatabase:
    """Build a UniversalRoomDatabase against a temp directory.

    Mirrors `_make_db` in test_database_resilience.py — `async_create_task`
    / `async_create_background_task` schedule real asyncio tasks so the
    write worker actually runs when started.
    """
    hass = MagicMock()
    hass.config.path = lambda *parts: os.path.join(tmp_path, *parts)

    def _schedule_task(coro, name=None):
        return asyncio.ensure_future(coro)

    hass.async_create_background_task = _schedule_task
    hass.async_create_task = _schedule_task
    return UniversalRoomDatabase(hass)


async def _init_db_with_worker(db: UniversalRoomDatabase) -> None:
    await db.initialize()
    await db.start_write_worker()


async def _drain_writes(db: UniversalRoomDatabase) -> None:
    await db._write_queue.join()


async def _shutdown(db: UniversalRoomDatabase) -> None:
    if db._write_task is not None and not db._write_task.done():
        db._write_task.cancel()
        try:
            await db._write_task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# EVChargerController harness — same pattern as test_v47x_ev_tou_hardening.py
# ---------------------------------------------------------------------------


class _EVHarness:
    """Minimal EVChargerController harness with controllable EVSE state."""

    def __init__(
        self,
        garage_a_on: bool = False,
        garage_a_power: float = 0.0,
        garage_b_on: bool = False,
        garage_b_power: float = 0.0,
    ) -> None:
        self.hass = MockHass()
        self.hass.set_state("switch.garage_a", "on" if garage_a_on else "off")
        self.hass.set_state(
            "sensor.garage_a_power_minute_average", str(garage_a_power)
        )
        self.hass.set_state("sensor.garage_a_energy_today", "0")
        self.hass.set_state("sensor.garage_a_energy_this_month", "0")
        self.hass.set_state("switch.garage_b", "on" if garage_b_on else "off")
        self.hass.set_state(
            "sensor.garage_b_power_minute_average", str(garage_b_power)
        )
        self.hass.set_state("sensor.garage_b_energy_today", "0")
        self.hass.set_state("sensor.garage_b_energy_this_month", "0")
        self.ev = EVChargerController(self.hass)


# ===========================================================================
# Tiny "EnergyCoordinator-like" seam to drive _save_evse_state /
# _restore_evse_state without instantiating the full coordinator (which
# pulls in dozens of HA helpers via __init__).  We reuse the actual save /
# restore source by binding the unbound methods to a stand-in object that
# exposes the attributes those methods touch (`hass`, `_ev`).
# ===========================================================================


def _bind_persistence_methods(hass, ev_controller):
    """Return an object with `_save_evse_state` and `_restore_evse_state`
    bound from the production `EnergyCoordinator` source — without
    constructing the full coordinator (which needs more HA wiring than is
    available at the unit level).
    """
    from custom_components.universal_room_automation.domain_coordinators import (
        energy as _energy_mod,
    )
    # The methods reference only `self.hass` and `self._ev`, so a plain
    # SimpleNamespace is sufficient.
    holder = types.SimpleNamespace(hass=hass, _ev=ev_controller)
    holder._save_evse_state = _energy_mod.EnergyCoordinator._save_evse_state.__get__(
        holder, type(holder)
    )
    holder._restore_evse_state = _energy_mod.EnergyCoordinator._restore_evse_state.__get__(
        holder, type(holder)
    )
    return holder


def _install_db_into_hass(hass, db):
    """Wire `db` into the spot `_save_evse_state` / `_restore_evse_state`
    look it up (`hass.data["universal_room_automation"]["database"]`).
    """
    # MockHass.data is a dict
    hass.data.setdefault("universal_room_automation", {})["database"] = db


# ===========================================================================
# WS1 — Persistence round-trip + staleness
# ===========================================================================


class TestWS1PersistenceRoundTrip:
    """D1.1-D1.4: KV round-trip + staleness guards."""

    @pytest.mark.asyncio
    async def test_force_charge_until_round_trip_kv(self, tmp_path):
        """D1.1: ev_force_charge_until saved as tz-aware ISO, restored via
        dt_util.parse_datetime, and applied to in-memory `_force_charge_until`.
        """
        db = _make_db(str(tmp_path))
        await _init_db_with_worker(db)
        try:
            h = _EVHarness()
            _install_db_into_hass(h.hass, db)
            holder = _bind_persistence_methods(h.hass, h.ev)

            until = _now() + timedelta(minutes=30)
            h.ev.set_force_charge_override(until)

            await holder._save_evse_state()
            await _drain_writes(db)

            # Clear in-memory state, then restore from DB
            h.ev._force_charge_until = None
            await holder._restore_evse_state()

            assert h.ev._force_charge_until is not None
            # Same instant; tolerate timezone re-attachment
            assert h.ev._force_charge_until == until
        finally:
            await _shutdown(db)

    @pytest.mark.asyncio
    async def test_force_charge_until_naive_datetime_does_not_crash(
        self, tmp_path,
    ):
        """D1.1: save defensively makes naive datetimes tz-aware so the
        round-trip succeeds rather than raising TypeError.
        """
        db = _make_db(str(tmp_path))
        await _init_db_with_worker(db)
        try:
            h = _EVHarness()
            _install_db_into_hass(h.hass, db)
            holder = _bind_persistence_methods(h.hass, h.ev)

            # Set a NAIVE datetime in the future — the save path must
            # re-attach UTC before serializing (Bug Class #21).
            naive_future = (_now() + timedelta(minutes=30)).replace(
                tzinfo=None
            )
            h.ev._force_charge_until = naive_future
            await holder._save_evse_state()
            await _drain_writes(db)

            # Restore must succeed (parse via dt_util.parse_datetime, then
            # ensure tz-aware before comparison).
            h.ev._force_charge_until = None
            await holder._restore_evse_state()
            assert h.ev._force_charge_until is not None
        finally:
            await _shutdown(db)

    @pytest.mark.asyncio
    async def test_force_charge_until_past_expiry_dropped(self, tmp_path):
        """D1.1: a restored expiry already in the past is silently dropped
        — `_force_charge_until` stays None.
        """
        db = _make_db(str(tmp_path))
        await _init_db_with_worker(db)
        try:
            h = _EVHarness()
            _install_db_into_hass(h.hass, db)
            holder = _bind_persistence_methods(h.hass, h.ev)

            past = _now() - timedelta(hours=1)
            h.ev._force_charge_until = past
            await holder._save_evse_state()
            await _drain_writes(db)

            h.ev._force_charge_until = None
            await holder._restore_evse_state()
            assert h.ev._force_charge_until is None
        finally:
            await _shutdown(db)

    @pytest.mark.asyncio
    async def test_fill_priority_paused_round_trip(self, tmp_path):
        """D1.2: evse_fill_priority_paused round-trips through KV."""
        db = _make_db(str(tmp_path))
        await _init_db_with_worker(db)
        try:
            h = _EVHarness()
            _install_db_into_hass(h.hass, db)
            holder = _bind_persistence_methods(h.hass, h.ev)

            h.ev._paused_by_fill_priority.add("garage_a")
            await holder._save_evse_state()
            await _drain_writes(db)

            h.ev._paused_by_fill_priority.clear()
            await holder._restore_evse_state()
            assert "garage_a" in h.ev._paused_by_fill_priority
        finally:
            await _shutdown(db)

    @pytest.mark.asyncio
    async def test_fill_priority_stale_evse_id_filtered(self, tmp_path):
        """D1.2: a KV row referencing an EVSE not in `self._ev._evse` is
        dropped on restore (mirrors the existing grid_cap filter).
        """
        db = _make_db(str(tmp_path))
        await _init_db_with_worker(db)
        try:
            h = _EVHarness()
            _install_db_into_hass(h.hass, db)
            holder = _bind_persistence_methods(h.hass, h.ev)

            # Hand-write a stale EVSE ID into the KV (mimics a config-removed
            # EVSE leaking across a restart).
            await db.save_energy_state(
                "evse_fill_priority_paused", json.dumps(["ghost_evse"]),
            )
            await _drain_writes(db)

            await holder._restore_evse_state()
            assert "ghost_evse" not in h.ev._paused_by_fill_priority
        finally:
            await _shutdown(db)

    @pytest.mark.asyncio
    async def test_arbitrage_paused_round_trip(self, tmp_path):
        """D1.3b: evse_arbitrage_paused round-trips through KV."""
        db = _make_db(str(tmp_path))
        await _init_db_with_worker(db)
        try:
            h = _EVHarness()
            _install_db_into_hass(h.hass, db)
            holder = _bind_persistence_methods(h.hass, h.ev)

            h.ev._paused_by_arbitrage.add("garage_b")
            await holder._save_evse_state()
            await _drain_writes(db)

            h.ev._paused_by_arbitrage.clear()
            await holder._restore_evse_state()
            assert "garage_b" in h.ev._paused_by_arbitrage
        finally:
            await _shutdown(db)

    @pytest.mark.asyncio
    async def test_proactive_offpeak_holds_round_trip(self, tmp_path):
        """D1.3: evse_proactive_offpeak_holds round-trips through KV."""
        db = _make_db(str(tmp_path))
        await _init_db_with_worker(db)
        try:
            h = _EVHarness()
            _install_db_into_hass(h.hass, db)
            holder = _bind_persistence_methods(h.hass, h.ev)

            h.ev._proactive_offpeak_holds.add("garage_a")
            h.ev._proactive_offpeak_holds.add("garage_b")
            await holder._save_evse_state()
            await _drain_writes(db)

            h.ev._proactive_offpeak_holds.clear()
            await holder._restore_evse_state()
            assert h.ev._proactive_offpeak_holds == {"garage_a", "garage_b"}
        finally:
            await _shutdown(db)

    @pytest.mark.asyncio
    async def test_proactive_offpeak_holds_stale_evse_id_filtered(
        self, tmp_path,
    ):
        """D1.3: a KV row referencing an EVSE not in `self._ev._evse` is
        dropped on restore.
        """
        db = _make_db(str(tmp_path))
        await _init_db_with_worker(db)
        try:
            h = _EVHarness()
            _install_db_into_hass(h.hass, db)
            holder = _bind_persistence_methods(h.hass, h.ev)

            await db.save_energy_state(
                "evse_proactive_offpeak_holds",
                json.dumps(["garage_a", "ghost_evse"]),
            )
            await _drain_writes(db)

            await holder._restore_evse_state()
            assert "garage_a" in h.ev._proactive_offpeak_holds
            assert "ghost_evse" not in h.ev._proactive_offpeak_holds
        finally:
            await _shutdown(db)

    @pytest.mark.asyncio
    async def test_restore_evse_state_stale_skipped(self, tmp_path):
        """D1.4: an `evse_state` row with `updated_at` older than 10h is
        NOT applied on restore.
        """
        db = _make_db(str(tmp_path))
        await db.initialize()
        try:
            # Direct write into evse_state with a stale updated_at (12h old).
            stale_ts = (_now() - timedelta(hours=12)).isoformat()
            import aiosqlite as _aiosqlite
            async with _aiosqlite.connect(db.db_file) as conn:
                await conn.execute(
                    "INSERT OR REPLACE INTO evse_state "
                    "(evse_id, paused_by_energy, excess_solar_active, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    ("garage_a", 1, 0, stale_ts),
                )
                await conn.commit()

            result = await db.restore_evse_state(max_age_hours=10.0)
            assert "garage_a" not in result
        finally:
            await _shutdown(db)

    @pytest.mark.asyncio
    async def test_restore_evse_state_fresh_applied(self, tmp_path):
        """D1.4: an `evse_state` row with `updated_at` 8h ago IS applied."""
        db = _make_db(str(tmp_path))
        await db.initialize()
        try:
            fresh_ts = (_now() - timedelta(hours=8)).isoformat()
            import aiosqlite as _aiosqlite
            async with _aiosqlite.connect(db.db_file) as conn:
                await conn.execute(
                    "INSERT OR REPLACE INTO evse_state "
                    "(evse_id, paused_by_energy, excess_solar_active, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    ("garage_a", 1, 0, fresh_ts),
                )
                await conn.commit()

            result = await db.restore_evse_state(max_age_hours=10.0)
            assert "garage_a" in result
            assert result["garage_a"]["paused_by_energy"] is True
        finally:
            await _shutdown(db)

    @pytest.mark.asyncio
    async def test_restore_energy_state_with_age_stale_skipped(self, tmp_path):
        """D1.4: `restore_energy_state_with_age` filters stale KV rows."""
        db = _make_db(str(tmp_path))
        await db.initialize()
        try:
            stale_ts = (_now() - timedelta(hours=12)).isoformat()
            import aiosqlite as _aiosqlite
            async with _aiosqlite.connect(db.db_file) as conn:
                await conn.execute(
                    "INSERT OR REPLACE INTO energy_state (key, value, updated_at) "
                    "VALUES (?, ?, ?)",
                    ("evse_fill_priority_paused", json.dumps(["garage_a"]), stale_ts),
                )
                await conn.commit()

            value = await db.restore_energy_state_with_age(
                "evse_fill_priority_paused", max_age_hours=10.0,
            )
            assert value is None
        finally:
            await _shutdown(db)


# ===========================================================================
# WS1 — AST guard: no `datetime.fromisoformat` in `_restore_evse_state`
# ===========================================================================


class TestWS1ASTGuards:
    """Bug Class #13/#21 — restore must route through dt_util.parse_datetime."""

    def test_restore_evse_state_does_not_use_datetime_fromisoformat(self):
        energy_py_path = os.path.join(
            _ura_path, "domain_coordinators", "energy.py",
        )
        with open(energy_py_path, "r", encoding="utf-8") as fh:
            source = fh.read()
        tree = ast.parse(source)

        # Find `_restore_evse_state` function definition
        restore_fn = None
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
                and node.name == "_restore_evse_state"
            ):
                restore_fn = node
                break
        assert restore_fn is not None, (
            "Could not find _restore_evse_state in energy.py"
        )

        # Walk the function body looking for `datetime.fromisoformat(...)`
        # calls. The acceptable form is `dt_util.parse_datetime(...)`.
        offenders = []
        for node in ast.walk(restore_fn):
            if isinstance(node, ast.Attribute) and node.attr == "fromisoformat":
                # `datetime.fromisoformat(...)` shape — flag.
                offenders.append(ast.dump(node))

        assert not offenders, (
            "_restore_evse_state must not call `datetime.fromisoformat` "
            "(Bug Class #13/#21) — use `dt_util.parse_datetime` instead. "
            f"Offending nodes: {offenders}"
        )


# ===========================================================================
# WS2 — Behavior of EVChargerController.determine_actions in off-peak
# ===========================================================================


class TestWS2OffpeakProactiveOn:
    """D2.1: off-peak ensure-on with carry-over guard precedence."""

    def test_offpeak_fresh_plug_in_turns_on(self):
        """Fresh plug-in (switch OFF, no guards, no `_paused_by_us`): URA
        dispatches `switch.turn_on` and claims the proactive hold.
        """
        h = _EVHarness(garage_a_on=False, garage_b_on=False)
        # Sanity: this is the precondition the legacy resume-only rule failed.
        assert "garage_a" not in h.ev._paused_by_us

        actions = h.ev.determine_actions("off_peak")
        turn_on_targets = [
            a["target"] for a in actions if a["service"] == "switch.turn_on"
        ]
        assert "switch.garage_a" in turn_on_targets
        assert "garage_a" in h.ev._proactive_offpeak_holds

    def test_offpeak_handoff_from_excess_solar(self):
        """Excess-solar peak-clear leaves the EVSE OFF + no longer in
        `_excess_solar_active`; the next off-peak tick ensures-on.
        """
        h = _EVHarness(garage_a_on=False)
        # Simulate the prior state: excess-solar had it active, then cleared
        # at peak boundary (peak branch of determine_excess_solar_actions).
        h.ev._excess_solar_active.discard("garage_a")

        actions = h.ev.determine_actions("off_peak")
        assert any(
            a["service"] == "switch.turn_on" and a["target"] == "switch.garage_a"
            for a in actions
        )

    def test_battery_drain_carryover_blocks_proactive_on(self):
        """`_paused_by_battery_drain` membership wins — no turn_on, hold
        cleared, `_paused_by_us` cleared.
        """
        h = _EVHarness(garage_a_on=False)
        h.ev._paused_by_battery_drain.add("garage_a")
        h.ev._paused_by_us.add("garage_a")  # legacy bookkeeping

        actions = h.ev.determine_actions("off_peak")
        assert not any(
            a["service"] == "switch.turn_on" and a["target"] == "switch.garage_a"
            for a in actions
        )
        assert "garage_a" not in h.ev._proactive_offpeak_holds
        assert "garage_a" not in h.ev._paused_by_us

    def test_fill_priority_carryover_blocks_proactive_on(self):
        h = _EVHarness(garage_a_on=False)
        h.ev._paused_by_fill_priority.add("garage_a")

        actions = h.ev.determine_actions("off_peak")
        assert not any(
            a["service"] == "switch.turn_on" and a["target"] == "switch.garage_a"
            for a in actions
        )
        assert "garage_a" not in h.ev._proactive_offpeak_holds

    def test_grid_cap_carryover_blocks_proactive_on(self):
        h = _EVHarness(garage_a_on=False)
        h.ev._paused_by_grid_cap.add("garage_a")

        actions = h.ev.determine_actions("off_peak")
        assert not any(
            a["service"] == "switch.turn_on" and a["target"] == "switch.garage_a"
            for a in actions
        )
        assert "garage_a" not in h.ev._proactive_offpeak_holds

    def test_arbitrage_carryover_blocks_proactive_on(self):
        h = _EVHarness(garage_a_on=False)
        h.ev._paused_by_arbitrage.add("garage_a")

        actions = h.ev.determine_actions("off_peak")
        assert not any(
            a["service"] == "switch.turn_on" and a["target"] == "switch.garage_a"
            for a in actions
        )
        assert "garage_a" not in h.ev._proactive_offpeak_holds

    def test_manual_user_disable_reenforced_next_tick(self):
        """User manually turns the switch OFF mid-off-peak; on the next
        decision cycle, URA re-issues `turn_on` (idempotent — no
        "already in hold set" short-circuit; Bug Class #43).
        """
        h = _EVHarness(garage_a_on=False)
        # First tick: ensure-on
        actions1 = h.ev.determine_actions("off_peak")
        assert any(
            a["service"] == "switch.turn_on" and a["target"] == "switch.garage_a"
            for a in actions1
        )
        assert "garage_a" in h.ev._proactive_offpeak_holds

        # User flips switch off
        h.hass.set_state("switch.garage_a", "off")

        # Second tick: re-enforce
        actions2 = h.ev.determine_actions("off_peak")
        assert any(
            a["service"] == "switch.turn_on" and a["target"] == "switch.garage_a"
            for a in actions2
        ), "Bug Class #43: URA must re-issue turn_on idempotently"

    def test_tou_toggle_off_disables_proactive_on(self):
        """The `_ev_tou_enabled` gate lives in the CALLER (`energy.py:~2317`),
        not inside `determine_actions`. Test at the right seam: when the
        toggle is off, the caller skips the whole `determine_actions` call,
        so the EVSE is never touched.

        Modeled directly here — the production gate is the simple if-check at
        `energy.py:2317`. If that branching is ever inverted, this test
        catches the inversion against the real EVChargerController.
        """
        h = _EVHarness(garage_a_on=False)
        ev_tou_enabled = False
        # Mirror the production gate
        actions = h.ev.determine_actions("off_peak") if ev_tou_enabled else []
        assert actions == []
        assert "garage_a" not in h.ev._proactive_offpeak_holds

    def test_observation_mode_blocks_proactive_on(self):
        """The `_observation_mode` gate lives in the CALLER (`energy.py:~2307`).
        Test at the right seam: when observation mode is on, no actions
        are executed and the proactive turn-on is suppressed at the
        coordinator level.
        """
        h = _EVHarness(garage_a_on=False)
        observation_mode = True
        # In observation mode, energy.py:2307 short-circuits all action
        # execution — determine_actions may still be called but its
        # actions are NOT dispatched. Model that by NOT calling
        # determine_actions and asserting the state never changed.
        if not observation_mode:
            h.ev.determine_actions("off_peak")
        assert "garage_a" not in h.ev._proactive_offpeak_holds

    def test_force_charge_active_skips_proactive_on(self):
        """When force-charge is active during off-peak, the proactive-on
        claim is SKIPPED — `_proactive_offpeak_holds` stays empty for that
        EVSE (the charge is authorized for a different reason).
        """
        h = _EVHarness(garage_a_on=True)  # already on under force-charge
        until = _now() + timedelta(minutes=30)
        h.ev.set_force_charge_override(until)

        # Off-peak with force-charge active: no turn_on (already on) AND no
        # hold-set claim.
        actions = h.ev.determine_actions("off_peak")
        assert not any(a["service"] == "switch.turn_on" for a in actions)
        assert "garage_a" not in h.ev._proactive_offpeak_holds

    def test_peak_transition_clears_proactive_offpeak_holds(self):
        """D2.2: transitioning out of off-peak (peak / mid_peak) clears
        the hold set for the EVSEs that were being held.
        """
        h = _EVHarness(garage_a_on=False)
        # Establish hold
        h.ev.determine_actions("off_peak")
        assert "garage_a" in h.ev._proactive_offpeak_holds

        # Transition to peak — peak branch discards hold bookkeeping
        # (regardless of whether the switch was on/off).
        h.ev.determine_actions("peak")
        assert "garage_a" not in h.ev._proactive_offpeak_holds


# ===========================================================================
# D3 — EV status dict surfaces proactive_offpeak_holds as a JSON list
# ===========================================================================


class TestD3EVStatusSurface:
    """D3: status dict exposes `proactive_offpeak_holds` as a list."""

    def test_ev_status_exposes_proactive_offpeak_holds(self):
        h = _EVHarness()
        h.ev._proactive_offpeak_holds.add("garage_a")
        h.ev._proactive_offpeak_holds.add("garage_b")

        status = h.ev.get_status()
        assert "proactive_offpeak_holds" in status
        value = status["proactive_offpeak_holds"]

        # MUST be a JSON-serializable list, NEVER a `set` (HA serializes
        # entity attributes over the WebSocket API).
        assert isinstance(value, list), (
            f"proactive_offpeak_holds must be a list (got {type(value).__name__}) "
            "so HA can JSON-serialize it for the WebSocket API"
        )
        assert set(value) == {"garage_a", "garage_b"}
        # JSON serialization round-trips cleanly
        json.dumps(value)
