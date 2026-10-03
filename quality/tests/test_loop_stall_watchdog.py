"""Tests for BOOT-EVENT-LOOP-FREEZE-1 loop-stall watchdog.

Exercises the pure state-machine helpers with an injected clock (no wall
sleeps in the > 0.5s range), verifies single-instance install across many
config entries, and confirms the daemon thread stops on unload.

See docs/planning/AUDIT_db_write_worker_slow_2026_09_29.md (spec) and
custom_components/universal_room_automation/domain_coordinators/
_loop_stall_watchdog.py (implementation).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import time
import types
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Import the watchdog module. It only needs a real `custom_components.
# universal_room_automation.const` (for DOMAIN) and a minimal
# `homeassistant.const` / `.core` — pytest-homeassistant provides those.
# ---------------------------------------------------------------------------
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    _loop_stall_watchdog as wd_mod,
)
from custom_components.universal_room_automation.const import DOMAIN  # noqa: E402


# ---------------------------------------------------------------------------
# Fake hass with just what the watchdog touches.
# ---------------------------------------------------------------------------
class _FakeLoop:
    def call_soon_threadsafe(self, cb):
        # Run immediately on caller thread — deterministic for tests.
        cb()


class _FakeBus:
    def __init__(self):
        self.listeners: list = []

    def async_listen_once(self, event, cb):
        self.listeners.append((event, cb))
        return lambda: None


class _FakeHass:
    def __init__(self):
        self.data = {}
        self.loop = _FakeLoop()
        self.bus = _FakeBus()

    def async_create_task(self, coro):
        # Drain the coro synchronously so no lingering tasks.
        try:
            coro.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Pure state-machine tests (no thread).
# ---------------------------------------------------------------------------
def test_stall_episode_emits_one_warning_then_recovery(caplog):
    """One WARNING at episode entry + one recovery line at exit."""
    caplog.set_level(logging.WARNING)
    now = [0.0]
    hass = _FakeHass()
    w = wd_mod._LoopStallWatchdog(
        hass,
        ping_interval=0.01,
        stall_threshold=10.0,
        boot_window=0.0,  # steady state immediately
        clock=lambda: now[0],
        loop_ping=lambda cb: None,  # never ping — simulate a frozen loop
        nm_emit=lambda **kw: None,
    )
    # Establish baseline heartbeat.
    w._record_beat()
    # No stall yet.
    now[0] = 5.0
    w.check_once()
    # Cross threshold — should log ONE warning + fire (steady state).
    now[0] = 12.0
    w.check_once()
    # Still stalled — no additional entry warning.
    now[0] = 20.0
    w.check_once()
    # Loop recovers — one recovery line.
    w._record_beat()
    now[0] = 20.5
    w.check_once()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    entry = [r for r in warnings if "Event loop stalled" in r.getMessage()]
    recovery = [r for r in warnings if "Event loop recovered" in r.getMessage()]
    assert len(entry) == 1, f"expected 1 entry warning, got {len(entry)}"
    assert len(recovery) == 1, f"expected 1 recovery line, got {len(recovery)}"


def test_boot_window_suppresses_nm(caplog):
    """In boot window: warning still logs, but NM is NOT invoked."""
    caplog.set_level(logging.WARNING)
    now = [0.0]
    calls = []
    hass = _FakeHass()
    w = wd_mod._LoopStallWatchdog(
        hass,
        ping_interval=0.01,
        stall_threshold=10.0,
        boot_window=1000.0,  # long boot window
        clock=lambda: now[0],
        loop_ping=lambda cb: None,
        nm_emit=lambda **kw: calls.append(kw),
    )
    w._record_beat()
    now[0] = 15.0
    w.check_once()
    assert calls == [], "NM must NOT fire during boot window"
    # Recover, then stall again in steady state.
    w._record_beat()
    now[0] = 15.5
    w.check_once()
    # Advance past boot window.
    now[0] = 2000.0
    w._record_beat()
    now[0] = 2020.0
    w.check_once()
    assert len(calls) == 1, "NM must fire once in steady state stall"


def test_install_is_single_instance_across_many_entries():
    """43-room boot must start ONE thread, not 43."""
    hass = _FakeHass()
    threads_before = threading.active_count()
    wds = [wd_mod.install(hass) for _ in range(43)]
    try:
        assert all(w is wds[0] for w in wds), "install must return same singleton"
        # Only one new thread should exist.
        new_threads = [
            t for t in threading.enumerate()
            if t.name == "ura_loop_stall_watchdog"
        ]
        assert len(new_threads) == 1, (
            f"expected 1 watchdog thread, got {len(new_threads)}"
        )
    finally:
        wd_mod.uninstall(hass)


def test_uninstall_detaches_ha_stop_listener():
    """Tier 1 LOW fix: install() stores the HA-stop bus unsub and
    uninstall() calls it — otherwise the stale listener fires against
    a torn-down handle at HA stop.
    """
    class _UnsubTrackingBus:
        def __init__(self):
            self.listeners = []
            self.unsub_calls = 0

        def async_listen_once(self, event, cb):
            self.listeners.append((event, cb))

            def _unsub():
                self.unsub_calls += 1
            return _unsub

    hass = _FakeHass()
    hass.bus = _UnsubTrackingBus()
    w = wd_mod.install(hass)
    assert w._ha_stop_unsub is not None, "install must store the unsub"
    wd_mod.uninstall(hass)
    assert hass.bus.unsub_calls == 1, "uninstall must call the HA-stop unsub"


def test_ha_stop_fire_does_not_call_consumed_unsub():
    """LOOP-STALL-WATCHDOG-STOP-UNSUB-ERROR-1: when EVENT_HOMEASSISTANT_STOP
    fires, HA has already consumed the one-time listener; calling its
    unsub logs "Unable to remove unknown job listener". Firing the stop
    callback must tear the watchdog down WITHOUT calling the unsub.
    """
    class _UnsubTrackingBus:
        def __init__(self):
            self.listeners = []
            self.unsub_calls = 0

        def async_listen_once(self, event, cb):
            self.listeners.append((event, cb))

            def _unsub():
                self.unsub_calls += 1
            return _unsub

    hass = _FakeHass()
    hass.bus = _UnsubTrackingBus()
    w = wd_mod.install(hass)
    assert len(hass.bus.listeners) == 1
    _event, on_stop = hass.bus.listeners[0]
    on_stop(None)  # HA fires the (already self-removed) one-time listener
    assert hass.bus.unsub_calls == 0, (
        "HA-stop handler must not call the consumed one-time unsub"
    )
    assert wd_mod._DATA_KEY not in hass.data.get(DOMAIN, {})
    assert w._thread is None or not w._thread.is_alive()


def test_uninstall_stops_thread():
    """The daemon thread must exit on uninstall (no lingering threads)."""
    hass = _FakeHass()
    w = wd_mod.install(hass)
    assert w._thread is not None and w._thread.is_alive()
    wd_mod.uninstall(hass)
    # Give it a moment to join.
    for _ in range(20):
        if not w._thread or not w._thread.is_alive():
            break
        time.sleep(0.05)
    assert w._thread is None or not w._thread.is_alive(), (
        "watchdog thread must stop on uninstall"
    )
    assert wd_mod._DATA_KEY not in hass.data.get(DOMAIN, {})


# ---------------------------------------------------------------------------
# Mutation drills — restore-in-Python (never git checkout), clear __pycache__.
# ---------------------------------------------------------------------------
_SRC_PATH = wd_mod.__file__


def _mutate(replace_pairs):
    original = open(_SRC_PATH, "rb").read()
    text = original.decode("utf-8")
    for a, b in replace_pairs:
        assert a in text, f"mutation target not found: {a!r}"
        text = text.replace(a, b, 1)
    open(_SRC_PATH, "wb").write(text.encode("utf-8"))
    # Clear stale bytecode so re-import sees the mutated source.
    pkg_root = _SRC_PATH.rsplit("/", 1)[0] + "/__pycache__"
    try:
        shutil.rmtree(pkg_root)
    except FileNotFoundError:
        pass
    return original


def _restore(original):
    open(_SRC_PATH, "wb").write(original)
    pkg_root = _SRC_PATH.rsplit("/", 1)[0] + "/__pycache__"
    try:
        shutil.rmtree(pkg_root)
    except FileNotFoundError:
        pass


def _run_subtest(test_expr):
    """Run one test via a subprocess so we get a fresh import of the module."""
    env = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": "quality",
        "PATH": "/usr/bin:/bin",
    }
    p = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "quality/tests/test_loop_stall_watchdog.py::" + test_expr,
            "-q", "--no-header", "-x", "-p", "no:cacheprovider",
        ],
        cwd=".", env=env, capture_output=True, text=True, timeout=60,
    )
    return p.returncode, (p.stdout + p.stderr)


def test_mutation_drill_removes_per_episode_latch():
    """If the single-warning latch is neutered so every check_once emits,
    test_stall_episode_emits_one_warning_then_recovery MUST turn red.
    """
    original = _mutate([
        # Neuter the "we already emitted for this episode" latch: skip
        # marking the episode active so _enter_episode fires on every
        # check_once tick.
        ("self._episode_active = True\n        self._episode_started_at = now - elapsed",
         "self._episode_active = False  # MUTATION\n        self._episode_started_at = now - elapsed"),
    ])
    try:
        rc, out = _run_subtest(
            "test_stall_episode_emits_one_warning_then_recovery"
        )
        assert rc != 0, f"mutation should turn test red, got green:\n{out[-800:]}"
    finally:
        _restore(original)
        # Byte-compare: restore MUST reproduce pre-mutation content.
        after = open(_SRC_PATH, "rb").read()
        assert after == original, "restore failed to reproduce original bytes"


def test_mutation_drill_removes_single_instance_guard():
    """If the install-idempotency guard is removed, the single-instance
    test MUST turn red (many threads started).
    """
    original = _mutate([
        ("existing = data.get(_DATA_KEY)\n    if existing is not None:\n        return existing",
         "existing = None  # MUTATION\n    if False:\n        return existing"),
    ])
    try:
        rc, out = _run_subtest(
            "test_install_is_single_instance_across_many_entries"
        )
        assert rc != 0, f"mutation should turn test red, got green:\n{out[-800:]}"
    finally:
        _restore(original)


def test_mutation_drill_removes_stop():
    """If Watchdog.stop() is neutered, the uninstall-stops-thread test
    MUST turn red (thread still alive)."""
    original = _mutate([
        ("def stop(self, join_timeout: float = 3.0) -> None:\n        self._stop.set()",
         "def stop(self, join_timeout: float = 3.0) -> None:\n        pass  # MUTATION\n        self._stop.set() if False else None"),
    ])
    try:
        rc, out = _run_subtest("test_uninstall_stops_thread")
        assert rc != 0, f"mutation should turn test red, got green:\n{out[-800:]}"
    finally:
        _restore(original)
