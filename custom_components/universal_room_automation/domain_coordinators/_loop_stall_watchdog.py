"""Loop-stall watchdog — diagnostic only, no behavior change.

BOOT-EVENT-LOOP-FREEZE-1. A daemon thread pings the event loop every
``PING_INTERVAL_S`` seconds. When the loop fails to answer within
``STALL_THRESHOLD_S`` we log ONE WARNING per stall episode with the
main-thread stack (``sys._current_frames()``), and — in steady state,
after ``BOOT_WINDOW_S`` from install — also raise a per-episode NM
alert through the existing stuck-signal path
(``domain_coordinators._stuck_signal_nm.fire_stuck_signal``). When the
loop recovers we log ONE additional line with total stall duration.
Boot stalls: log only, no NM.

Single-instance across the whole HA process: ``install(hass)`` is
guarded by ``hass.data[DOMAIN]["_loop_stall_watchdog"]``, so N config
entries (~43 rooms) each calling ``install`` start ONE thread total.

Kill-switches (module constants, rung 1):
- STALL_THRESHOLD_S = 10.0  — episode entry threshold.
- PING_INTERVAL_S   = 2.0   — ping cadence.
- BOOT_WINDOW_S     = 300.0 — window after install where stalls log
  only (no NM); set to 0 to NM every episode including boot.
- STACK_TRIM_FRAMES = 40    — main-thread stack cap per WARNING.

Rung 1 (module constants) — diagnostic protocol windows, not operator
policy: raising them silently would hide real freezes.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
import traceback
from typing import Any, Callable

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# --- Knobs (rung 1) ---------------------------------------------------------
PING_INTERVAL_S: float = 2.0
STALL_THRESHOLD_S: float = 10.0
BOOT_WINDOW_S: float = 300.0
STACK_TRIM_FRAMES: int = 40

# hass.data key for the singleton handle.
_DATA_KEY = "_loop_stall_watchdog"


class _LoopStallWatchdog:
    """Thread + episode state. Public helpers are pure so tests can drive
    them without a real background thread.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        ping_interval: float = PING_INTERVAL_S,
        stall_threshold: float = STALL_THRESHOLD_S,
        boot_window: float = BOOT_WINDOW_S,
        clock: Callable[[], float] = time.monotonic,
        loop_ping: Callable[[Callable[[], None]], None] | None = None,
        nm_emit: Callable[..., Any] | None = None,
    ) -> None:
        self.hass = hass
        self._ping_interval = ping_interval
        self._stall_threshold = stall_threshold
        self._boot_window = boot_window
        self._clock = clock
        self._nm_emit = nm_emit  # injectable for tests; None => real path

        # Loop ping: default schedules a heartbeat on hass.loop from the
        # background thread. Injectable so unit tests avoid real loops.
        if loop_ping is None:
            def _default_ping(cb: Callable[[], None]) -> None:
                try:
                    self.hass.loop.call_soon_threadsafe(cb)
                except RuntimeError:
                    # Loop closed — treat as heartbeat so we don't log
                    # false stalls during shutdown.
                    cb()
            self._loop_ping = _default_ping
        else:
            self._loop_ping = loop_ping

        self._start_monotonic = self._clock()
        self._last_beat = self._start_monotonic
        self._beat_lock = threading.Lock()

        # Episode state.
        self._episode_active = False
        self._episode_started_at: float | None = None

        # Main-thread ident captured at install (setup runs on main).
        self._main_ident = threading.main_thread().ident

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Tier 1 fix: store the HA-stop bus unsub so uninstall() can
        # detach the listener if we tear down before HA stops (e.g. all
        # URA entries unloaded). Without this the listener leaks and
        # fires against a defunct watchdog handle at HA stop.
        self._ha_stop_unsub: Callable[[], None] | None = None

    # ---- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        t = threading.Thread(
            target=self._run,
            name="ura_loop_stall_watchdog",
            daemon=True,
        )
        self._thread = t
        t.start()
        _LOGGER.info(
            "Loop-stall watchdog started (ping=%.1fs, stall=%.1fs, boot_window=%.1fs)",
            self._ping_interval, self._stall_threshold, self._boot_window,
        )

    def stop(self, join_timeout: float = 3.0) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=join_timeout)
        self._thread = None
        _LOGGER.info("Loop-stall watchdog stopped")

    # ---- pure helpers (tested directly) -----------------------------------
    def _record_beat(self) -> None:
        with self._beat_lock:
            self._last_beat = self._clock()

    def _in_boot_window(self, now: float) -> bool:
        return (now - self._start_monotonic) < self._boot_window

    def _elapsed_since_beat(self, now: float) -> float:
        with self._beat_lock:
            return now - self._last_beat

    def check_once(self, now: float | None = None) -> None:
        """One tick of the state machine. Testable without a thread."""
        if now is None:
            now = self._clock()
        elapsed = self._elapsed_since_beat(now)
        if elapsed >= self._stall_threshold and not self._episode_active:
            self._enter_episode(now, elapsed)
        elif self._episode_active and elapsed < self._stall_threshold:
            self._exit_episode(now)

    def _enter_episode(self, now: float, elapsed: float) -> None:
        self._episode_active = True
        self._episode_started_at = now - elapsed
        boot = self._in_boot_window(now)
        stack_text = self._capture_main_stack()
        _LOGGER.warning(
            "Event loop stalled >= %.1fs (elapsed=%.1fs, phase=%s). "
            "Main-thread stack:\n%s",
            self._stall_threshold, elapsed,
            "boot" if boot else "steady",
            stack_text,
        )
        if not boot:
            self._fire_nm(elapsed, stack_text)

    def _exit_episode(self, now: float) -> None:
        started = self._episode_started_at or now
        total = now - started
        self._episode_active = False
        self._episode_started_at = None
        _LOGGER.warning(
            "Event loop recovered after stall (total_stall=%.1fs)",
            total,
        )

    def _capture_main_stack(self) -> str:
        try:
            frames = sys._current_frames()
            frame = frames.get(self._main_ident)
            if frame is None:
                return "<main thread frame unavailable>"
            stack = traceback.format_stack(frame)
            trimmed = stack[-STACK_TRIM_FRAMES:]
            return "".join(trimmed)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("watchdog: main-stack capture failed", exc_info=True)
            return "<stack capture failed>"

    def _fire_nm(self, elapsed: float, stack_text: str) -> None:
        if self._nm_emit is not None:
            try:
                self._nm_emit(elapsed=elapsed, stack=stack_text)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("watchdog: injected NM emit raised", exc_info=True)
            return
        # Real path — schedule fire_stuck_signal on the loop (thread-safe).
        try:
            head = "\n".join(stack_text.splitlines()[-6:])
            diagnosis = (
                f"Event loop stalled >= {self._stall_threshold:.1f}s "
                f"(elapsed={elapsed:.1f}s). Main-thread head:\n{head}"
            )

            async def _emit() -> None:
                try:
                    from ._stuck_signal_nm import fire_stuck_signal  # noqa: PLC0415
                    await fire_stuck_signal(
                        self.hass,
                        kind="event_loop_stall",
                        key=("main",),
                        diagnosis=diagnosis,
                        title_override=f"Event loop stalled ({elapsed:.0f}s)",
                    )
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("watchdog NM emit failed", exc_info=True)

            self.hass.loop.call_soon_threadsafe(
                lambda: self.hass.async_create_task(_emit())
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("watchdog: scheduling NM emit failed", exc_info=True)

    # ---- thread body -------------------------------------------------------
    def _run(self) -> None:
        # Seed heartbeat so we don't fire in the first tick.
        self._record_beat()
        while not self._stop.is_set():
            # Ping the loop; the callback re-arms the heartbeat.
            try:
                self._loop_ping(self._record_beat)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("watchdog: loop_ping raised", exc_info=True)
            # Check episode state on the current clock reading.
            try:
                self.check_once()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("watchdog: check_once raised", exc_info=True)
            # Sleep on the stop event so shutdown is fast.
            if self._stop.wait(self._ping_interval):
                return


def install(hass: HomeAssistant) -> _LoopStallWatchdog:
    """Install the single-process watchdog. Idempotent across N entries."""
    data = hass.data.setdefault(DOMAIN, {})
    existing = data.get(_DATA_KEY)
    if existing is not None:
        return existing
    wd = _LoopStallWatchdog(hass)
    data[_DATA_KEY] = wd
    wd.start()

    # Auto-teardown at HA stop so the daemon thread doesn't linger past
    # process end (test suites also check for lingering threads).
    def _on_stop(_event: Any) -> None:
        uninstall(hass)

    try:
        wd._ha_stop_unsub = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, _on_stop,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("watchdog: HA_STOP listen registration failed", exc_info=True)
    return wd


def uninstall(hass: HomeAssistant) -> None:
    """Stop and drop the watchdog. Idempotent."""
    data = hass.data.get(DOMAIN) or {}
    wd = data.pop(_DATA_KEY, None)
    if wd is None:
        return
    # Detach the HA-stop listener FIRST so it can't fire against a
    # torn-down watchdog handle. Idempotent — HA's async_listen_once
    # unsub is safe to call twice.
    unsub = getattr(wd, "_ha_stop_unsub", None)
    if unsub is not None:
        try:
            unsub()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("watchdog: HA_STOP unsub raised", exc_info=True)
        wd._ha_stop_unsub = None
    try:
        wd.stop()
    except Exception:  # noqa: BLE001
        _LOGGER.debug("watchdog: stop raised", exc_info=True)


__all__ = [
    "PING_INTERVAL_S",
    "STALL_THRESHOLD_S",
    "BOOT_WINDOW_S",
    "STACK_TRIM_FRAMES",
    "install",
    "uninstall",
    "_LoopStallWatchdog",
]
