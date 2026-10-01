"""ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1 — behavioural tests.

The pre-fix wiring persisted anomaly baselines ONLY in each coordinator's
``async_teardown`` and in the CM's ``async_stop``. Neither runs on an HA
restart (the process exits after ``EVENT_HOMEASSISTANT_STOP`` without
unloading the config entry), so presence / security / safety /
music_following learning was discarded every restart (verified live via
``metric_baselines.last_updated`` — stale by weeks while uptime cycled in
hours).

The fix wires a periodic save (``ANOMALY_BASELINE_SAVE_INTERVAL_S``) +
an ``EVENT_HOMEASSISTANT_STOP`` once-listener on the CoordinatorManager
that iterates every coordinator's ``anomaly_detector`` plus the safety
rate-baseline writer and the CM setup detector.

Each test is behavioural: it drives the production method / wiring and
observes outcomes (call counts, listener registrations, write-volume
bounds). The wire-in anchor drill is in ``TestWireInAnchor`` — it edits
the production call line in memory to a no-op and confirms a specific
test fails.

Run (targeted):
    PYTHONPATH=quality .venv-ha/bin/python -B -m pytest \
        quality/tests/test_anomaly_baseline_periodic_save.py -q -p no:cacheprovider
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

# Piggy-back on the stub prelude + CoordinatorManager import from the
# existing CM test module (same pattern test_restart_safety_doctrine_1 uses
# with test_safety_coordinator).
from test_domain_coordinators import *  # noqa: F401,F403 — stubs + imports

from custom_components.universal_room_automation.domain_coordinators.manager import (  # noqa: E402
    ANOMALY_BASELINE_SAVE_INTERVAL_S,
    CoordinatorManager,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STOP  # noqa: E402

# NOTE: sibling test files (test_safety_coordinator et al.) reload the
# manager module under its canonical sys.modules key via
# ``importlib.util.spec_from_file_location``. After that reload the
# sys.modules entry no longer matches the module that OUR
# CoordinatorManager class was defined in. Patch the globals the class's
# methods actually resolve against — which live on the method's own
# ``__globals__`` dict regardless of sys.modules churn.
_MGR_GLOBALS = CoordinatorManager._wire_anomaly_baseline_persistence.__globals__


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_manager(running: bool = True):
    """Minimal CM: MagicMock hass with bus.async_listen_once returning an
    unsub callable, and a plain dict ``hass.data``. ``running`` seeds the
    _running flag (True by default) — the B-LOW guard in
    _persist_coordinator_baselines early-returns when the CM is not running,
    so tests that drive the persist path directly need the flag set."""
    hass = MagicMock()
    hass.data = {}
    hass.services = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_listen_once = MagicMock(return_value=MagicMock())
    mgr = CoordinatorManager(hass)
    mgr._running = running
    return mgr, hass


def _make_coord_with_detector(coord_id: str):
    """A tiny fake coordinator exposing ``coordinator_id`` + a detector."""
    coord = MagicMock()
    coord.coordinator_id = coord_id
    coord.anomaly_detector = MagicMock()
    coord.anomaly_detector.save_baselines = AsyncMock()
    return coord


# ---------------------------------------------------------------------------
# (a) stop event persists each of the five detectors' baselines
# ---------------------------------------------------------------------------


class TestStopEventPersistsAllDetectors:
    """EVENT_HOMEASSISTANT_STOP must flush every detector the CM knows."""

    @pytest.mark.asyncio
    async def test_stop_listener_registered_with_correct_event(self):
        mgr, hass = _make_manager()
        mgr._wire_anomaly_baseline_persistence()
        # The once-listener MUST be registered under EVENT_HOMEASSISTANT_STOP.
        called = [
            call for call in hass.bus.async_listen_once.call_args_list
            if call.args and call.args[0] == EVENT_HOMEASSISTANT_STOP
        ]
        assert len(called) == 1, (
            "ANOMALY-BASELINES-...-1: _wire_anomaly_baseline_persistence must "
            "register exactly one EVENT_HOMEASSISTANT_STOP once-listener. "
            f"calls={hass.bus.async_listen_once.call_args_list!r}"
        )

    @pytest.mark.asyncio
    async def test_stop_callback_persists_each_of_the_five(self):
        """Fire the registered stop-callback; every target save_baselines runs."""
        mgr, hass = _make_manager()
        # Register the five live detectors + a safety rate writer + setup det.
        coords = {
            cid: _make_coord_with_detector(cid)
            for cid in ("presence", "security", "safety", "music_following", "hvac")
        }
        # safety has a parallel rate-baseline store (coordinator_id="safety_rate").
        coords["safety"]._save_rate_baselines = AsyncMock()
        for cid, c in coords.items():
            mgr._coordinators[cid] = c

        setup_det = MagicMock()
        setup_det.save_baselines = AsyncMock()
        mgr._setup_anomaly_detector = setup_det

        mgr._wire_anomaly_baseline_persistence()
        # Grab the once-listener callback and drive it.
        stop_cb = hass.bus.async_listen_once.call_args.args[1]
        await stop_cb(object())

        for cid, c in coords.items():
            assert c.anomaly_detector.save_baselines.await_count == 1, (
                f"{cid}: save_baselines must be awaited exactly once on STOP"
            )
        assert coords["safety"]._save_rate_baselines.await_count == 1, (
            "safety._save_rate_baselines must be awaited on STOP (safety_rate scope)"
        )
        assert setup_det.save_baselines.await_count == 1, (
            "CM setup_anomaly_detector must be flushed on STOP"
        )


# ---------------------------------------------------------------------------
# (b) periodic path persists them
# ---------------------------------------------------------------------------


class TestPeriodicTimerPersists:
    @pytest.mark.asyncio
    async def test_periodic_timer_registered_with_interval_constant(self):
        """The periodic timer MUST use the module constant — proves no
        inline literal snuck in and names the knob for future tuning
        (numbers-get-knobs doctrine)."""
        mgr, hass = _make_manager()
        with pytest.MonkeyPatch.context() as mp:
            fake_track = MagicMock(return_value=MagicMock())
            mp.setitem(_MGR_GLOBALS, "async_track_time_interval", fake_track)
            mgr._wire_anomaly_baseline_persistence()
            assert fake_track.called, (
                "periodic save must register async_track_time_interval"
            )
            # Second positional is the callback; third is the interval.
            call = fake_track.call_args
            interval = call.args[2] if len(call.args) >= 3 else call.kwargs.get("interval")
            assert interval == timedelta(seconds=ANOMALY_BASELINE_SAVE_INTERVAL_S), (
                f"interval must be timedelta(seconds=ANOMALY_BASELINE_SAVE_INTERVAL_S)"
                f" (={ANOMALY_BASELINE_SAVE_INTERVAL_S}s); got {interval!r}"
            )

    @pytest.mark.asyncio
    async def test_single_persist_call_touches_every_detector_once(self):
        mgr, _ = _make_manager()
        coords = {
            cid: _make_coord_with_detector(cid)
            for cid in ("presence", "security", "safety", "music_following", "hvac")
        }
        coords["safety"]._save_rate_baselines = AsyncMock()
        for cid, c in coords.items():
            mgr._coordinators[cid] = c
        mgr._setup_anomaly_detector = None

        # Periodic path (default): detectors get saved; safety_rate is
        # EXCLUDED (B-MEDIUM — Safety has its own 30-min internal writer).
        await mgr._persist_coordinator_baselines()
        for cid, c in coords.items():
            assert c.anomaly_detector.save_baselines.await_count == 1, cid
        assert coords["safety"]._save_rate_baselines.await_count == 0, (
            "periodic path must NOT invoke safety._save_rate_baselines "
            "(duplicates safety.py:1214 internal writer)"
        )

    @pytest.mark.asyncio
    async def test_stop_path_includes_safety_rate(self):
        """The STOP path (and only the STOP path) persists safety_rate."""
        mgr, _ = _make_manager()
        safety = _make_coord_with_detector("safety")
        safety._save_rate_baselines = AsyncMock()
        mgr._coordinators["safety"] = safety

        await mgr._persist_coordinator_baselines(include_safety_rate=True)
        assert safety._save_rate_baselines.await_count == 1, (
            "STOP path must invoke safety._save_rate_baselines"
        )

    @pytest.mark.asyncio
    async def test_persist_noops_when_not_running(self):
        """B-LOW: a tick scheduled before unwire must no-op after async_stop."""
        mgr, _ = _make_manager(running=False)
        coord = _make_coord_with_detector("presence")
        mgr._coordinators["presence"] = coord
        await mgr._persist_coordinator_baselines()
        assert coord.anomaly_detector.save_baselines.await_count == 0, (
            "_persist_coordinator_baselines must early-return when "
            "self._running is False"
        )


# ---------------------------------------------------------------------------
# (c) after a simulated restart the loaded sample_count equals the pre-save count
# ---------------------------------------------------------------------------


class TestRestartRoundTripSampleCount:
    """Prove that the save path we just wired ACTUALLY preserves learning:
    seed an in-memory baseline store attached to a mock detector; CM's
    persist helper routes it through save_baselines; a fresh "post-restart"
    detector loads from the same store and recovers the sample_count.
    """

    @pytest.mark.asyncio
    async def test_persist_then_simulated_restart_recovers_counts(self):
        mgr, _ = _make_manager()

        # Shared persistent store (stands in for metric_baselines).
        shared_store: dict[str, int] = {}

        def _make_detector(name: str, pre_count: int):
            det = MagicMock()
            det._samples = pre_count

            async def _save():
                shared_store[name] = det._samples
            det.save_baselines = AsyncMock(side_effect=_save)
            return det

        # Pre-save: five detectors with distinct in-memory counts.
        pre = {
            "presence": 11,
            "security": 23,
            "safety": 7,
            "music_following": 19,
            "hvac": 42,
        }
        coords = {}
        for cid, n in pre.items():
            c = MagicMock()
            c.coordinator_id = cid
            c.anomaly_detector = _make_detector(cid, n)
            coords[cid] = c
            mgr._coordinators[cid] = c
        coords["safety"]._save_rate_baselines = AsyncMock()

        # CM-driven save (our new path).
        await mgr._persist_coordinator_baselines()
        assert shared_store == pre, "pre-restart save must land every count"

        # Simulate restart: fresh detectors with sample_count=0 that "load"
        # from the shared store.
        post_counts = {}
        for cid in pre:
            fresh = MagicMock()
            fresh._samples = 0

            async def _load(name=cid, det=fresh):
                det._samples = shared_store.get(name, 0)
            fresh.load_baselines = AsyncMock(side_effect=_load)
            await fresh.load_baselines()
            post_counts[cid] = fresh._samples

        assert post_counts == pre, (
            "After simulated restart, loaded sample_count must equal the "
            f"pre-save count. pre={pre} post={post_counts}"
        )


# ---------------------------------------------------------------------------
# (d) write-volume bound: N cycles within one period produce at most ONE save
# ---------------------------------------------------------------------------


class TestWriteVolumeBounded:
    """The periodic timer is driven by HA at ``ANOMALY_BASELINE_SAVE_INTERVAL_S``
    — not per-decision-cycle. This test asserts (1) the interval constant is
    at least 30 min so a flood is impossible, and (2) a single invocation of
    the persist helper triggers exactly one save per detector (no fan-out)."""

    def test_interval_constant_is_at_least_30_minutes(self):
        assert ANOMALY_BASELINE_SAVE_INTERVAL_S >= 1800, (
            "ANOMALY_BASELINE_SAVE_INTERVAL_S must be >= 30 min to honour "
            "the write-volume guard (v4.7 flood incident)."
        )

    @pytest.mark.asyncio
    async def test_each_invocation_saves_once_per_detector(self):
        mgr, _ = _make_manager()
        for cid in ("presence", "security", "safety", "music_following", "hvac"):
            mgr._coordinators[cid] = _make_coord_with_detector(cid)
        mgr._coordinators["safety"]._save_rate_baselines = AsyncMock()
        for n in range(1, 4):
            await mgr._persist_coordinator_baselines()
            for cid, c in mgr._coordinators.items():
                assert c.anomaly_detector.save_baselines.await_count == n, (
                    f"{cid}: expected {n} saves after {n} invocations, "
                    f"got {c.anomaly_detector.save_baselines.await_count}"
                )


# ---------------------------------------------------------------------------
# Lifecycle: periodic + stop unsubs are cleared on async_stop (listener hygiene)
# ---------------------------------------------------------------------------


class TestListenerHygiene:
    @pytest.mark.asyncio
    async def test_async_stop_clears_both_unsubs(self):
        mgr, hass = _make_manager()
        # Fake unsub callables.
        periodic_unsub = MagicMock()
        stop_unsub = MagicMock()
        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(
                _MGR_GLOBALS, "async_track_time_interval",
                MagicMock(return_value=periodic_unsub),
            )
            hass.bus.async_listen_once = MagicMock(return_value=stop_unsub)
            mgr._wire_anomaly_baseline_persistence()
        assert mgr._anomaly_baseline_periodic_unsub is periodic_unsub
        assert mgr._anomaly_baseline_stop_unsub is stop_unsub
        await mgr.async_stop()
        assert mgr._anomaly_baseline_periodic_unsub is None
        assert mgr._anomaly_baseline_stop_unsub is None
        assert periodic_unsub.called, "periodic unsub must be invoked"
        assert stop_unsub.called, "stop unsub must be invoked"


# ---------------------------------------------------------------------------
# A-LOW: AnomalyDetector._baselines_loaded guard — a failed load must NOT
# allow a subsequent save to clobber the stored (mature) rows.
# ---------------------------------------------------------------------------


class TestBaselinesLoadedGuard:
    """Guards against overwriting a healthy ``metric_baselines`` row set with
    an empty / few-sample in-memory dict when ``load_baselines`` silently
    failed (its exception handler swallows to debug)."""

    def _make_detector(self, database):
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import (  # noqa: E402
            AnomalyDetector,
        )
        from custom_components.universal_room_automation.const import DOMAIN  # noqa: E402
        hass = MagicMock()
        hass.data = {DOMAIN: {"database": database}}
        return AnomalyDetector(
            hass=hass,
            coordinator_id="presence",
            metric_names=["foo"],
            minimum_samples=5,
        )

    @pytest.mark.asyncio
    async def test_default_true_detector_without_persistence_saves(self):
        """Detectors constructed without a persistence surface (database=None)
        still have ``_baselines_loaded == True`` by default, so the save path
        reaches the DB check and returns cleanly (not blocked by the guard)."""
        det = self._make_detector(database=None)
        assert det._baselines_loaded is True, (
            "default must be True so detectors that never call load_baselines "
            "can still save"
        )
        # save_baselines returns early on database=None without raising.
        await det.save_baselines()

    @pytest.mark.asyncio
    async def test_persistent_load_failure_save_skips_and_warns_once(self, caplog):
        """ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1 fix-up test (b).

        When load_baselines keeps failing, save_baselines must retry the
        load, still refuse to INSERT (so stored rows are not clobbered),
        AND log the one-shot WARNING exactly ONCE across repeated saves —
        not once per hourly periodic save.
        """
        import logging

        class ExplodingDB:
            def __init__(self):
                self.open_calls = 0

            def _db(_s):
                _s.open_calls += 1

                class _Ctx:
                    async def __aenter__(__s):
                        raise RuntimeError("simulated DB open failure")

                    async def __aexit__(__s, *a):
                        return False
                return _Ctx()

        db = ExplodingDB()
        det = self._make_detector(database=db)
        await det.load_baselines()  # swallowed to debug
        assert det._baselines_loaded is False
        open_after_initial_load = db.open_calls  # == 1

        # Seed an in-memory sample so a successful save WOULD INSERT.
        det.record_observation("foo", "house", 1.0)

        caplog.clear()
        with caplog.at_level(
            logging.WARNING,
            logger=(
                "custom_components.universal_room_automation."
                "domain_coordinators.coordinator_diagnostics"
            ),
        ):
            await det.save_baselines()
            await det.save_baselines()

        # The retry hits database._db() each save; neither save reached the
        # INSERT (ExplodingDB raises on __aenter__ for the load retry too),
        # and the flag stayed False.
        assert det._baselines_loaded is False
        assert db.open_calls == open_after_initial_load + 2, (
            "each save must retry load_baselines (one _db open per save)"
        )

        warn_hits = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "prior load_baselines failed" in r.getMessage()
        ]
        assert len(warn_hits) == 1, (
            f"WARNING must fire exactly ONCE per detector across "
            f"repeated failing saves; got {len(warn_hits)}"
        )

    @pytest.mark.asyncio
    async def test_failed_load_then_db_recovers_next_save_writes(self):
        """ANOMALY-BASELINES-NEVER-SAVED-ON-RESTART-1 fix-up test (a).

        A transient boot-time load failure must NOT permanently disable
        saves. When the DB recovers, the next save_baselines retries the
        load in-line, flips the flag True, and completes the INSERT in the
        same call. (Mutation drill: delete the ``await self.load_baselines()``
        retry in save_baselines — this test must go RED.)
        """
        import aiosqlite

        class RecoveringDB:
            def __init__(self):
                self.mode = "broken"  # start broken; flip to "live" to recover
                self.conn = None
                self.insert_count = 0
                self.open_calls = 0

            def _db(_s):
                parent = _s
                parent.open_calls += 1

                class _Ctx:
                    async def __aenter__(__s):
                        if parent.mode == "broken":
                            raise RuntimeError("simulated DB open failure")
                        if parent.conn is None:
                            parent.conn = await aiosqlite.connect(":memory:")
                            await parent.conn.execute(
                                "CREATE TABLE metric_baselines ("
                                "coordinator_id TEXT, metric_name TEXT, "
                                "scope TEXT, mean REAL, variance REAL, "
                                "sample_count INTEGER, last_updated TEXT)"
                            )
                            await parent.conn.commit()
                            # Wrap execute ONCE to count INSERTs.
                            original_execute = parent.conn.execute

                            async def _tracked_execute(sql, *a, **kw):
                                if sql.lstrip().upper().startswith("INSERT"):
                                    parent.insert_count += 1
                                return await original_execute(sql, *a, **kw)

                            parent.conn.execute = _tracked_execute
                        return parent.conn

                    async def __aexit__(__s, *a):
                        return False  # keep connection alive across calls

                return _Ctx()

        db = RecoveringDB()
        det = self._make_detector(database=db)
        await det.load_baselines()  # fails -> flag False
        assert det._baselines_loaded is False

        # Seed one in-memory baseline so recovery+save actually INSERTs.
        det.record_observation("foo", "house", 1.0)

        # DB comes back.
        db.mode = "live"

        try:
            await det.save_baselines()
        finally:
            # Close the aiosqlite connection to avoid a leaked worker thread
            # (conftest fails the test on any unrecognised thread post-run).
            if db.conn is not None:
                await db.conn.close()

        assert det._baselines_loaded is True, (
            "save_baselines must retry load_baselines and flip the flag "
            "True when the DB recovers"
        )
        assert db.insert_count >= 1, (
            "save_baselines must INSERT the in-memory baseline on the SAME "
            "call once the retry load succeeds"
        )
        # One-shot warning latch must reset so a future failure cycle warns again.
        assert det._warned_save_unloaded is False

    @pytest.mark.asyncio
    async def test_successful_load_allows_save(self):
        """A load against an empty table (no rows stored yet) is a legitimate
        cold-start and must still set the flag True so saves work."""
        import aiosqlite

        class EmptyDB:
            def _db(_s):
                class _Ctx:
                    async def __aenter__(__s):
                        # Minimal: an in-memory connection with the real schema
                        # subset we touch (coordinator_id, metric_name, scope,
                        # mean, variance, sample_count, last_updated).
                        __s._conn = await aiosqlite.connect(":memory:")
                        await __s._conn.execute(
                            "CREATE TABLE metric_baselines ("
                            "coordinator_id TEXT, metric_name TEXT, scope TEXT, "
                            "mean REAL, variance REAL, sample_count INTEGER, "
                            "last_updated TEXT)"
                        )
                        await __s._conn.commit()
                        return __s._conn

                    async def __aexit__(__s, *a):
                        await __s._conn.close()
                        return False
                return _Ctx()

        det = self._make_detector(database=EmptyDB())
        await det.load_baselines()
        assert det._baselines_loaded is True, (
            "a successful load (zero rows stored) must flip the flag to True"
        )


# ---------------------------------------------------------------------------
# A-MEDIUM: async_start() itself must invoke _wire_anomaly_baseline_persistence
# (replacing the call with `pass` must break this test).
# ---------------------------------------------------------------------------


class TestAsyncStartWiresBaselinePersistence:
    """Behavioural: drive the real ``async_start`` (with house-state restore /
    wire helpers stubbed) and prove the periodic + STOP handles are
    registered, and that firing the stop event flushes a registered
    detector. Replacing the wire call with ``pass`` in production source
    MUST turn these assertions red (that is the point)."""

    @pytest.mark.asyncio
    async def test_async_start_registers_periodic_and_stop_and_flushes(
        self, monkeypatch,
    ):
        mgr, hass = _make_manager(running=False)  # async_start sets _running True
        # Stub the house-state branches — unrelated to this cycle and they
        # touch Store I/O. The anomaly wiring runs AFTER both.
        async def _noop_restore(self):
            self._house_state_restored = False
        monkeypatch.setattr(
            CoordinatorManager, "_async_restore_house_state", _noop_restore,
        )
        monkeypatch.setattr(
            CoordinatorManager, "_wire_house_state_persistence",
            lambda self: None,
        )
        # Capture the periodic unsub by faking async_track_time_interval.
        periodic_unsub = MagicMock()
        monkeypatch.setitem(
            _MGR_GLOBALS, "async_track_time_interval",
            MagicMock(return_value=periodic_unsub),
        )
        stop_unsub = MagicMock()
        hass.bus.async_listen_once = MagicMock(return_value=stop_unsub)

        # Register a detector so the stop callback has something to flush.
        presence = _make_coord_with_detector("presence")
        mgr._coordinators["presence"] = presence

        await mgr.async_start()

        # Wiring MUST have happened as part of async_start.
        assert mgr._anomaly_baseline_periodic_unsub is periodic_unsub, (
            "async_start must register the periodic baseline-save timer. "
            "If this fails, _wire_anomaly_baseline_persistence was NOT "
            "invoked from async_start (A-MEDIUM wire-anchor regression)."
        )
        stop_calls = [
            c for c in hass.bus.async_listen_once.call_args_list
            if c.args and c.args[0] == EVENT_HOMEASSISTANT_STOP
        ]
        # One stop-listener per wiring (house-state is stubbed above).
        assert len(stop_calls) == 1, (
            "async_start must register exactly one baseline STOP once-listener; "
            f"got {hass.bus.async_listen_once.call_args_list!r}"
        )
        # Firing the stop event must flush the registered detector.
        stop_cb = stop_calls[0].args[1]
        await stop_cb(object())
        assert presence.anomaly_detector.save_baselines.await_count == 1, (
            "The STOP listener wired by async_start must flush each "
            "registered coordinator's anomaly_detector."
        )


# ---------------------------------------------------------------------------
# Wire-in anchor drill (operator rule: wire_in_anchor_mandatory).
# ---------------------------------------------------------------------------


class TestWireInAnchor:
    """Neuter the call site in-process (not just the helper) and confirm the
    oracle in this file goes red, then restore. Uses the production source
    text of ``_persist_coordinator_baselines`` as the mutation surface so
    the anchor is bound to the actual call line, not a hand-rolled fake.
    """

    @pytest.mark.asyncio
    async def test_neutering_the_call_site_breaks_the_oracle(self, monkeypatch):
        import inspect
        import textwrap

        src = inspect.getsource(CoordinatorManager._persist_coordinator_baselines)
        anchor = "await detector.save_baselines()"
        assert anchor in src, (
            "Call-site anchor missing from _persist_coordinator_baselines — "
            "update this drill."
        )
        mutated_src = src.replace(anchor, "pass  # NEUTERED by wire-in drill", 1)
        # Compile the mutated method body in the module's namespace so it
        # resolves the same symbols (await, _LOGGER, etc.).
        ns: dict = {}
        exec(textwrap.dedent(mutated_src), _MGR_GLOBALS, ns)
        mutated_method = ns["_persist_coordinator_baselines"]
        monkeypatch.setattr(
            CoordinatorManager,
            "_persist_coordinator_baselines",
            mutated_method,
        )

        # Re-run the stop-callback oracle under the mutation and confirm it
        # would fail (save never awaited).
        mgr, hass = _make_manager()
        coord = _make_coord_with_detector("presence")
        mgr._coordinators["presence"] = coord
        mgr._wire_anomaly_baseline_persistence()
        stop_cb = hass.bus.async_listen_once.call_args.args[1]
        await stop_cb(object())
        assert coord.anomaly_detector.save_baselines.await_count == 0, (
            "Mutation drill: with the call site neutered, save_baselines must "
            "NOT be awaited. If it was, the oracle in "
            "TestStopEventPersistsAllDetectors is passing on an unrelated path."
        )
