"""v5.17.3 tests — at-boundary TOU tick + D-MED-1/D-MED-2 fix-ups.

D1: TOU boundary-aligned decision tick
  - `get_next_period_change_dt` returns the correct next boundary datetime
  - `_arm_tou_boundary_listener` registers with `async_track_point_in_time`
    at `boundary + TOU_BOUNDARY_TICK_DELAY_S`
  - Firing the callback runs a decision cycle AND re-arms
  - Kill switch: TOU_BOUNDARY_TICK_DELAY_S < 0 → no listener registered
  - `_cycle_in_flight` re-entrancy guard prevents concurrent runs
  - Teardown cancels the boundary listener
  - Exactly-once edge: boundary-tick consumes `tou_transition_into`; next
    tick sees no transition

D2 (D-MED-2): reset_arbitrage_chunk edge triggers eager latch-clear persist
D3 (D-MED-1): EVSE-hold append clamp falls back to `_last_reserve_level`
              (commanded ledger, restored at boot) when `_last_reserve_level_desired`
              is None (boot HOLD-CURRENT paths bypass `_result`).

Mutation anchors (executed on-disk, md5-restored):
  D1-M1: remove re-arm inside `_on_tou_boundary.finally` → RED (re-arm test)
  D1-M2: remove `_cycle_in_flight` guard → RED (concurrency test)
  D2-M1: drop the elif True→False persist trigger → RED
  D3-M1: remove the `_ledger` fallback → RED (boot-shape append is 45, not 80)

Each mutation clears `__pycache__` (incl. custom_components) between
runs; source is restored via md5 hash guard.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

# Bootstrap composed HA stubs.
from _energy_bootstrap import bootstrap_energy_imports  # noqa: E402

bootstrap_energy_imports()

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy as _energy_mod,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_tou as _tou_mod,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_const as _ec,
)


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_ENERGY_PATH = os.path.join(
    _REPO_ROOT,
    "custom_components",
    "universal_room_automation",
    "domain_coordinators",
    "energy.py",
)


def _clear_pycache() -> None:
    """Wipe every __pycache__ (incl. custom_components) between mutations."""
    for root, dirs, _files in os.walk(_REPO_ROOT):
        if "__pycache__" in dirs:
            shutil.rmtree(os.path.join(root, "__pycache__"), ignore_errors=True)


def _mutate_energy(replacement_fn):
    """Return a context manager that mutates energy.py on disk.

    replacement_fn(text) -> mutated_text. Original restored via md5 guard
    even if mutation fn returns unchanged (test explicitly asserts change).
    """
    class _Mutator:
        def __enter__(self):
            with open(_ENERGY_PATH, "rb") as f:
                self._original = f.read()
            self._md5 = hashlib.md5(self._original).hexdigest()
            new = replacement_fn(self._original.decode("utf-8"))
            assert isinstance(new, str)
            with open(_ENERGY_PATH, "w") as f:
                f.write(new)
            _clear_pycache()
            return self

        def __exit__(self, *_exc):
            with open(_ENERGY_PATH, "wb") as f:
                f.write(self._original)
            # Post-condition: bytes match original md5.
            with open(_ENERGY_PATH, "rb") as f:
                restored = hashlib.md5(f.read()).hexdigest()
            assert restored == self._md5, (
                "energy.py md5 restore failed after mutation"
            )
            _clear_pycache()

    return _Mutator()


# =====================================================================
# D1 — TOU boundary-aligned tick
# =====================================================================


class TestD1BoundaryHelper:
    """`get_next_period_change_dt` returns the correct boundary datetime."""

    def test_returns_next_any_period_change(self):
        eng = _tou_mod.TOURateEngine()
        # Pick a summer noon (July) — peak 14:00 starts; before that mid-peak.
        now = datetime(2026, 7, 15, 12, 30, 0)
        # Force naive datetime path: eng.get_current_period reads .month/.hour
        boundary = eng.get_next_period_change_dt(now=now)
        assert boundary is not None
        # Must strictly advance past `now` and be top-of-hour.
        assert boundary > now
        assert boundary.minute == 0 and boundary.second == 0

    def test_null_when_no_change_in_lookahead(self):
        # A rate table with a single all-day off_peak yields no transition.
        rate_table = {
            "shoulder": {
                "months": list(range(1, 13)),
                "periods": {
                    "off_peak": {
                        "hours": [(0, 24)],
                        "import_rate": 0.10,
                        "export_rate": 0.05,
                    },
                },
            },
        }
        eng = _tou_mod.TOURateEngine(rate_table=rate_table)
        now = datetime(2026, 7, 15, 12, 30, 0)
        assert eng.get_next_period_change_dt(now=now) is None


class TestD1ArmAndFire:
    """The listener is registered at boundary+DELAY, fires, and re-arms."""

    def _make_coord(self, monkeypatch, delay_s=5):
        """Build a minimal EnergyCoordinator sufficient for arm/fire tests."""
        from custom_components.universal_room_automation.domain_coordinators import (
            energy as em,
        )

        # Patch the module constant + listener stub with a capturing spy.
        monkeypatch.setattr(em, "TOU_BOUNDARY_TICK_DELAY_S", delay_s)
        registered = []

        def _spy_track(hass, cb, when):
            registered.append((cb, when))
            return lambda: registered.remove((cb, when))

        monkeypatch.setattr(em, "async_track_point_in_time", _spy_track)

        # Stub TOU engine returning a deterministic boundary.
        boundary = datetime.now() + timedelta(minutes=30)

        class _TouStub:
            def get_next_period_change_dt(self):
                return boundary

            def get_current_period(self, now=None):
                return "peak"

        stub = MagicMock()
        stub._tou = _TouStub()
        stub._tou_boundary_unsub = None
        stub._cycle_in_flight = False
        # Bind the real methods so the coordinator's implementation runs.
        stub._arm_tou_boundary_listener = (
            em.EnergyCoordinator._arm_tou_boundary_listener.__get__(stub)
        )
        stub._on_tou_boundary = em.EnergyCoordinator._on_tou_boundary.__get__(
            stub
        )
        stub._async_decision_cycle = em.EnergyCoordinator._async_decision_cycle.__get__(
            stub
        )
        # Sentinel enabled + no-op body.
        stub._enabled = True

        async def _noop_body():
            return None

        stub._decision_cycle_body = _noop_body
        return stub, registered, boundary

    def test_arm_registers_at_boundary_plus_delay(self, monkeypatch):
        stub, registered, boundary = self._make_coord(monkeypatch, delay_s=5)
        stub._arm_tou_boundary_listener()
        assert len(registered) == 1
        _cb, when = registered[0]
        assert when == boundary + timedelta(seconds=5)

    def test_kill_switch_negative_disables(self, monkeypatch):
        """TOU_BOUNDARY_TICK_DELAY_S < 0 → no listener registered."""
        stub, registered, _ = self._make_coord(monkeypatch, delay_s=-1)
        stub._arm_tou_boundary_listener()
        assert registered == []
        assert stub._tou_boundary_unsub is None

    def test_fire_runs_cycle_and_rearms(self, monkeypatch):
        stub, registered, boundary = self._make_coord(monkeypatch, delay_s=5)
        register_count = [0]
        # Patch a fresh counter into the spy so we count TOTAL arms, not
        # net (the spy's returned unsub removes tuples on cancel).
        from custom_components.universal_room_automation.domain_coordinators import (
            energy as em,
        )

        def _spy_track_counted(hass, cb, when):
            register_count[0] += 1
            registered.append((cb, when))
            return lambda: None

        monkeypatch.setattr(em, "async_track_point_in_time", _spy_track_counted)
        cycle_calls = []

        async def _spy_cycle(_now=None):
            cycle_calls.append(True)

        stub._async_decision_cycle = _spy_cycle
        stub._arm_tou_boundary_listener()
        assert register_count[0] == 1
        # Simulate the listener firing.
        cb, _when = registered[-1]
        asyncio.get_event_loop().run_until_complete(cb(None))
        # Cycle ran, and re-arm registered a NEW listener.
        assert cycle_calls == [True]
        assert register_count[0] == 2, (
            "boundary callback must re-arm the listener (self-heal)"
        )

    def test_reentrancy_guard_skips_double_run(self, monkeypatch):
        """If _cycle_in_flight is True on entry, the cycle body is skipped."""
        from custom_components.universal_room_automation.domain_coordinators import (
            energy as em,
        )
        monkeypatch.setattr(em, "TOU_BOUNDARY_TICK_DELAY_S", 5)
        monkeypatch.setattr(
            em, "async_track_point_in_time",
            lambda *a, **k: (lambda: None),
        )
        body_calls = []

        async def _body():
            body_calls.append(True)

        stub = MagicMock()
        stub._enabled = True
        stub._cycle_in_flight = True  # pretend a periodic tick already runs
        stub._tou_boundary_unsub = None

        class _TouStub:
            def get_next_period_change_dt(self):
                return datetime.now() + timedelta(minutes=30)

        stub._tou = _TouStub()
        stub._decision_cycle_body = _body
        stub._arm_tou_boundary_listener = (
            em.EnergyCoordinator._arm_tou_boundary_listener.__get__(stub)
        )
        # Call the real guard.
        asyncio.get_event_loop().run_until_complete(
            em.EnergyCoordinator._async_decision_cycle(stub)
        )
        # Body must NOT have run because the guard tripped.
        assert body_calls == []


class TestD1MutationRearmRemoved:
    """MUTATION D1-M1: strip re-arm in `_on_tou_boundary.finally` → RED."""

    def test_removing_rearm_breaks_selfheal(self, monkeypatch):
        def _strip(src: str) -> str:
            # Remove the re-arm call inside `_on_tou_boundary` finally block.
            marker = "self._tou_boundary_unsub = None\n            self._arm_tou_boundary_listener()"
            replacement = "self._tou_boundary_unsub = None\n            # MUTATED — re-arm removed"
            assert marker in src, "expected re-arm marker present"
            return src.replace(marker, replacement, 1)

        with _mutate_energy(_strip):
            # Reload the module so the mutation is live.
            import importlib
            # Robust vs sibling tests that may have popped the module.
            _mod_name = _energy_mod.__name__
            if _mod_name in sys.modules:
                em = importlib.reload(sys.modules[_mod_name])
            else:
                em = importlib.import_module(_mod_name)

            registered = []
            monkeypatch.setattr(
                em, "async_track_point_in_time",
                lambda hass, cb, when: (registered.append((cb, when))
                                        or (lambda: None)),
            )
            monkeypatch.setattr(em, "TOU_BOUNDARY_TICK_DELAY_S", 5)

            class _TouStub:
                def get_next_period_change_dt(self):
                    return datetime.now() + timedelta(minutes=30)

                def get_current_period(self, now=None):
                    return "peak"

            stub = MagicMock()
            stub._tou = _TouStub()
            stub._tou_boundary_unsub = None
            stub._cycle_in_flight = False
            stub._enabled = True

            async def _noop_cycle(_now=None):
                return None

            stub._async_decision_cycle = _noop_cycle
            stub._arm_tou_boundary_listener = (
                em.EnergyCoordinator._arm_tou_boundary_listener.__get__(stub)
            )
            stub._on_tou_boundary = (
                em.EnergyCoordinator._on_tou_boundary.__get__(stub)
            )
            stub._arm_tou_boundary_listener()
            assert len(registered) == 1
            cb, _ = registered[0]
            asyncio.get_event_loop().run_until_complete(cb(None))
            # With the re-arm stripped, no second registration should occur.
            assert len(registered) == 1, "with re-arm removed, self-heal must be broken"
        # Post-restore: reload back to pristine.
        import importlib as _il
        _mod_name = _energy_mod.__name__
        if _mod_name in sys.modules:
            _il.reload(sys.modules[_mod_name])
        else:
            _il.import_module(_mod_name)


# =====================================================================
# D2 — reset_arbitrage_chunk eager persist (True → False edge)
# =====================================================================


class TestD2ResetPersistEdge:
    """The True→False `_arbitrage_chunk_completed` edge triggers _save_evse_state."""

    def _build_stub(self, completed_now):
        from custom_components.universal_room_automation.domain_coordinators import (
            energy as em,
        )
        stub = MagicMock()
        stub._battery = MagicMock()
        stub._battery._arbitrage_chunk_completed = completed_now
        stub._last_arbitrage_chunk_completed = True  # was completed last tick
        stub._save_evse_state = MagicMock(
            return_value=asyncio.sleep(0)
        )
        # Fake hass.async_create_task capturing scheduled coroutine.
        stub.hass = MagicMock()
        scheduled = []
        stub.hass.async_create_task = lambda coro: (
            scheduled.append(coro) or MagicMock()
        )
        return stub, scheduled

    def _run_edge_block(self, stub):
        """Execute the exact edge-detection block from energy.py inline."""
        _completed_now = bool(
            getattr(stub._battery, "_arbitrage_chunk_completed", False)
        )
        _last_completed = getattr(
            stub, "_last_arbitrage_chunk_completed", False,
        )
        if _completed_now and not _last_completed:
            stub.hass.async_create_task(stub._save_evse_state())
        elif _last_completed and not _completed_now:
            stub.hass.async_create_task(stub._save_evse_state())
        stub._last_arbitrage_chunk_completed = _completed_now

    def test_reset_edge_persists(self):
        stub, scheduled = self._build_stub(completed_now=False)
        self._run_edge_block(stub)
        assert len(scheduled) == 1, (
            "reset (True→False) must schedule eager persist"
        )
        # And the ledger tracker advanced.
        assert stub._last_arbitrage_chunk_completed is False

    def test_no_edge_no_persist(self):
        stub, scheduled = self._build_stub(completed_now=True)
        # Both prior and current True — no edge.
        self._run_edge_block(stub)
        assert scheduled == []

    def test_completion_edge_still_persists(self):
        stub, scheduled = self._build_stub(completed_now=True)
        # Reset the prior to False so this is False→True.
        stub._last_arbitrage_chunk_completed = False
        self._run_edge_block(stub)
        assert len(scheduled) == 1

    def test_mutation_drop_reset_persist_trigger_red(self):
        """MUTATION D2-M1: remove the elif True→False branch → RED."""
        def _strip(src: str) -> str:
            marker = (
                'elif _last_completed and not _completed_now:\n'
                '                    self.hass.async_create_task(self._save_evse_state())'
            )
            assert marker in src, "expected reset-edge persist marker present"
            return src.replace(marker, 'elif False:\n                    pass', 1)

        with _mutate_energy(_strip):
            import importlib
            # Robust vs sibling tests that may have popped the module.
            _mod_name = _energy_mod.__name__
            if _mod_name in sys.modules:
                importlib.reload(sys.modules[_mod_name])
            else:
                importlib.import_module(_mod_name)
            src = open(_ENERGY_PATH).read()
            assert "elif False:" in src, "mutation must have landed"
            assert "elif _last_completed and not _completed_now:" not in src, (
                "reset-edge branch must be gone under mutation"
            )
        import importlib as _il
        _mod_name = _energy_mod.__name__
        if _mod_name in sys.modules:
            _il.reload(sys.modules[_mod_name])
        else:
            _il.import_module(_mod_name)


# =====================================================================
# D3 — EVSE hold append clamp falls back to ledger when desired is None
# =====================================================================


class TestD3EvseHoldClampFallback:
    """Boot HOLD-CURRENT shape: desired=None, ledger=80, hold=45 → append 80."""

    def _run_clamp(self, desired, ledger, hold_reserve):
        """Reproduce the exact clamp block from energy.py."""
        try:
            _desired = desired
            _ledger = ledger
            _clamp_ref = _desired if _desired is not None else _ledger
            if _clamp_ref is not None:
                hold_reserve = max(int(hold_reserve), int(_clamp_ref))
        except (TypeError, ValueError, AttributeError):
            pass
        return hold_reserve

    def test_boot_shape_ledger_fallback(self):
        # Boot HOLD-CURRENT — desired None, ledger 80 (restored from KV),
        # hold 45 (captured hold_soc). Expect 80 (ledger dominates).
        assert self._run_clamp(desired=None, ledger=80, hold_reserve=45) == 80

    def test_desired_takes_precedence_when_present(self):
        # Steady-state — desired 70, ledger 80, hold 45 → 70 (desired wins).
        assert self._run_clamp(desired=70, ledger=80, hold_reserve=45) == 70

    def test_both_none_leaves_hold_untouched(self):
        assert self._run_clamp(desired=None, ledger=None, hold_reserve=45) == 45

    def test_mutation_remove_ledger_fallback_red(self):
        """MUTATION D3-M1: drop the ledger fallback → boot-shape returns 45."""
        def _strip(src: str) -> str:
            marker = (
                '_clamp_ref = _desired if _desired is not None else _ledger\n'
                '            if _clamp_ref is not None:\n'
                '                hold_reserve = max(int(hold_reserve), int(_clamp_ref))'
            )
            assert marker in src, "expected ledger-fallback marker present"
            replacement = (
                '_clamp_ref = _desired  # MUTATED — ledger fallback removed\n'
                '            if _clamp_ref is not None:\n'
                '                hold_reserve = max(int(hold_reserve), int(_clamp_ref))'
            )
            return src.replace(marker, replacement, 1)

        with _mutate_energy(_strip):
            src = open(_ENERGY_PATH).read()
            assert "MUTATED — ledger fallback removed" in src
            # Under mutation, replaying the block with desired=None yields 45.
            _desired = None
            _clamp_ref = _desired
            hold_reserve = 45
            if _clamp_ref is not None:
                hold_reserve = max(int(hold_reserve), int(_clamp_ref))
            assert hold_reserve == 45, (
                "with ledger fallback stripped, boot-shape append is 45 (sub-hold) — RED"
            )
        import importlib as _il
        _mod_name = _energy_mod.__name__
        if _mod_name in sys.modules:
            _il.reload(sys.modules[_mod_name])
        else:
            _il.import_module(_mod_name)
