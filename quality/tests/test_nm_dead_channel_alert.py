"""NM-IMESSAGE-OUTBOUND-DEAD-1: dead message-channel alert.

Plan: docs/planning/PLANNING_nm_dead_channel_alert.md (INV-1/2/3).

Drives the real ``_update_channel_health`` producer and the real
``fire_stuck_signal`` helper; only the NM's own ``async_notify`` (the
delivery) is stubbed, plus the HA Store (a shared in-memory fake so a
"restart" is a new NotificationManager over the same backing dict).
Every test injects a fake clock (``nm._dead_now``); no wall time.
"""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from test_notification_manager import _make_hass, _make_config  # noqa: F401

from custom_components.universal_room_automation.const import (  # noqa: E402
    CONF_NM_COMPANION_ENABLED,
    CONF_NM_IMESSAGE_ENABLED,
    CONF_NM_PUSHOVER_ENABLED,
    CONF_NM_WHATSAPP_ENABLED,
    DOMAIN,
)
import custom_components.universal_room_automation.domain_coordinators.notification_manager as nm_mod  # noqa: E402
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    _stuck_signal_nm as ss,
)
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    _nm_cycle_a,
)

T0 = datetime(2026, 11, 22, 17, 12, tzinfo=timezone.utc)
CHANNELS = ("pushover", "companion", "whatsapp", "imessage")


class _Clock:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


class _FakeStore:
    """Models HA Store write semantics (helpers/storage.py async_save +
    _async_handle_write_data): per-INSTANCE write lock, the writer takes the
    instance's latest data once it holds the lock. ``io_delays`` (shared via
    backing) lets a test make one write's I/O slower than the next."""

    def __init__(self, backing: dict) -> None:
        self.b = backing
        self._lock = asyncio.Lock()
        self._data = None

    async def async_load(self):
        return copy.deepcopy(self.b.get("data"))

    async def async_save(self, data):
        self._data = copy.deepcopy(data)
        async with self._lock:
            if self._data is None:
                return  # another write already consumed the latest data
            data, self._data = self._data, None
            delays = self.b.get("io_delays") or []
            for _ in range(delays.pop(0) if delays else 0):
                await asyncio.sleep(0)
            self.b["saves"] = self.b.get("saves", 0) + 1
            self.b["data"] = data


class _FakeDB:
    def __init__(self) -> None:
        self.anomalies: list = []

    async def save_anomaly_event(self, event):
        self.anomalies.append(event)

    async def prune_notification_log(self, _days):
        return 0

    async def prune_inbound_log(self, _days):
        return 0


@pytest.fixture(autouse=True)
def _clean_latches():
    ss.reset_latches_for_tests()
    try:
        _nm_cycle_a.invalidate_knob_cache()
    except Exception:  # noqa: BLE001
        pass
    yield
    ss.reset_latches_for_tests()


@pytest.fixture
def backing(monkeypatch):
    b: dict = {"saves": 0, "data": None}
    monkeypatch.setattr(nm_mod, "_dead_channel_store", lambda _h: _FakeStore(b))
    return b


def _cfg(**over):
    cfg = _make_config(**{
        CONF_NM_PUSHOVER_ENABLED: True,
        CONF_NM_COMPANION_ENABLED: True,
        CONF_NM_WHATSAPP_ENABLED: True,
        CONF_NM_IMESSAGE_ENABLED: True,
    })
    cfg.update(over)
    return cfg


def _make_nm(clock: _Clock, cfg=None, notify_result=True, db=None):
    hass = _make_hass()
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[])

    def _bg(coro, name, *a, **kw):
        return asyncio.get_running_loop().create_task(coro, name=name)

    hass.async_create_background_task = _bg
    nm = nm_mod.NotificationManager(hass, cfg or _cfg())
    nm._dead_now = clock
    nm.async_notify = AsyncMock(return_value=notify_result)
    hass.data[DOMAIN]["notification_manager"] = nm
    hass.data[DOMAIN]["database"] = db if db is not None else _FakeDB()
    return nm


async def _drain(nm) -> None:
    for _ in range(20):
        tasks = [t for t in nm._dead_tasks if not t.done()]
        if not tasks:
            await asyncio.sleep(0)
            if not [t for t in nm._dead_tasks if not t.done()]:
                return
            continue
        await asyncio.gather(*tasks, return_exceptions=True)


async def _fail(nm, clock, ch, at: datetime) -> None:
    clock.t = at
    nm._update_channel_health(ch, False)
    await _drain(nm)


async def _ok(nm, clock, ch, at: datetime) -> None:
    clock.t = at
    nm._update_channel_health(ch, True)
    await _drain(nm)


def _pn_calls(nm, action="create", ch=None):
    out = []
    for c in nm.hass.services.async_call.await_args_list:
        args = c.args
        if len(args) >= 2 and args[0] == "persistent_notification" and args[1] == action:
            nid = args[2].get("notification_id")
            if ch is None or nid == f"ura_nm_channel_dead_{ch}":
                out.append(nid)
    return out


def _dead_rows(nm):
    db = nm.hass.data[DOMAIN]["database"]
    return [e for e in db.anomalies if e.type == "nm.channel_dead"]


async def _loaded(clock, cfg=None, notify_result=True, db=None):
    nm = _make_nm(clock, cfg, notify_result, db)
    await nm._dead_load()
    await _drain(nm)
    return nm


async def _outage(nm, clock, ch, start, hours, n):
    """n evenly spaced failures from start to start+hours (inclusive)."""
    step = timedelta(hours=hours) / (n - 1)
    for i in range(n):
        await _fail(nm, clock, ch, start + step * i)


# ---------------------------------------------------------------------------
# D2: threshold, discriminating (fake clock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dead_channel_alert_at_threshold(backing):
    clock = _Clock(T0)
    nm = await _loaded(clock)
    # failures spanning 6 h minus 1 min: nothing
    await _outage(nm, clock, "imessage", T0, 6 - 1 / 60, 5)
    assert nm.async_notify.await_count == 0
    assert _pn_calls(nm) == []
    assert _dead_rows(nm) == []
    # one more at 6 h + 1 min: exactly one of each
    await _fail(nm, clock, "imessage", T0 + timedelta(hours=6, minutes=1))
    assert nm.async_notify.await_count == 1
    kw = nm.async_notify.await_args.kwargs
    assert kw["title"] == "Notification channel dead: imessage"
    assert kw["severity"].name == "HIGH"
    assert _pn_calls(nm) == ["ura_nm_channel_dead_imessage"]
    assert len(_dead_rows(nm)) == 1
    # more failures in the same episode: no more
    for m in range(1, 4):
        await _fail(nm, clock, "imessage", T0 + timedelta(hours=7, minutes=m))
    assert nm.async_notify.await_count == 1
    assert _pn_calls(nm) == ["ura_nm_channel_dead_imessage"]
    assert len(_dead_rows(nm)) == 1


@pytest.mark.asyncio
async def test_dead_channel_min_failures_gate(backing):
    """Span >= 6 h but only 2 consecutive failures: no episode."""
    clock = _Clock(T0)
    nm = await _loaded(clock)
    await _fail(nm, clock, "imessage", T0)
    await _fail(nm, clock, "imessage", T0 + timedelta(hours=7))
    assert nm.async_notify.await_count == 0
    assert _pn_calls(nm) == []
    await _fail(nm, clock, "imessage", T0 + timedelta(hours=7, minutes=1))
    assert nm.async_notify.await_count == 1


@pytest.mark.asyncio
async def test_transient_2h_outage_no_alert(backing):
    """The 10-18 shape: 11 failures in 2 h, then success, then later
    failures restart the clock from zero."""
    clock = _Clock(T0)
    nm = await _loaded(clock)
    await _outage(nm, clock, "imessage", T0, 2, 11)
    await _ok(nm, clock, "imessage", T0 + timedelta(hours=2, minutes=5))
    # 5 more failures from hour 3 to hour 7.5: span 4.5 h from the NEW start
    await _outage(nm, clock, "imessage", T0 + timedelta(hours=3), 4.5, 5)
    assert nm.async_notify.await_count == 0
    assert _pn_calls(nm) == []
    assert _dead_rows(nm) == []


@pytest.mark.asyncio
async def test_idle_channel_never_dead(backing):
    clock = _Clock(T0)
    nm = await _loaded(clock)
    # another channel is busy and healthy for 48 h; imessage never sends
    for h in range(0, 49, 6):
        await _ok(nm, clock, "pushover", T0 + timedelta(hours=h))
    assert nm._dead_clock == {}
    assert nm.async_notify.await_count == 0
    assert _pn_calls(nm) == []
    assert backing["saves"] == 0


@pytest.mark.asyncio
async def test_non_message_channel_ignored(backing):
    """tts / lights are not message channels: no clock, no episode."""
    clock = _Clock(T0)
    nm = await _loaded(clock)
    for h in range(0, 10):
        await _fail(nm, clock, "tts", T0 + timedelta(hours=h))
    assert nm._dead_clock == {}
    assert nm.async_notify.await_count == 0


# ---------------------------------------------------------------------------
# D1: persisted clock
# ---------------------------------------------------------------------------


async def _setup_nm(monkeypatch, clock, cfg=None, db=None):
    """A NotificationManager brought up through the real async_setup."""
    import homeassistant.helpers.dispatcher as disp

    monkeypatch.setattr(disp, "async_dispatcher_connect",
                        lambda *_a, **_k: MagicMock())
    monkeypatch.setattr(nm_mod, "async_track_time_change",
                        lambda *_a, **_k: MagicMock())
    nm = _make_nm(clock, cfg, db=db)
    nm._recover_state_from_db = AsyncMock()
    nm._setup_digest_timers = MagicMock()
    nm.hass.data[DOMAIN]["database"] = db if db is not None else _FakeDB()
    await nm.async_setup()
    await _drain(nm)
    return nm


@pytest.mark.asyncio
async def test_dead_channel_clock_survives_restart(backing, monkeypatch):
    clock = _Clock(T0)
    nm1 = await _setup_nm(monkeypatch, clock)
    for i in range(5):
        await _fail(nm1, clock, "imessage", T0 + timedelta(minutes=10 * i))
    await nm1.async_teardown()
    # restart: new NM over the same Store
    nm2 = await _setup_nm(monkeypatch, clock)
    await _fail(nm2, clock, "imessage", T0 + timedelta(hours=1))
    st = nm2._dead_clock["imessage"]
    assert st["failing_since"] == "2026-11-22T17:12:00+00:00"
    assert st["consecutive_failures"] == 6
    assert nm2.channel_status["imessage"]["failing_since"] == "2026-11-22T17:12:00+00:00"


@pytest.mark.asyncio
async def test_dead_channel_success_clears_and_rearms(backing):
    clock = _Clock(T0)
    nm = await _loaded(clock)
    for i in range(4):
        await _fail(nm, clock, "imessage", T0 + timedelta(minutes=i))
    saves_before = backing["saves"]
    await _ok(nm, clock, "imessage", T0 + timedelta(minutes=10))
    assert "imessage" not in nm._dead_clock
    assert nm.channel_status["imessage"]["failing_since"] is None
    assert backing["saves"] == saves_before + 1
    assert backing["data"] == {"channels": {}}
    # re-armed: a new failure starts a fresh clock
    await _fail(nm, clock, "imessage", T0 + timedelta(hours=1))
    assert nm._dead_clock["imessage"]["failing_since"] == (
        "2026-11-22T18:12:00+00:00")
    assert nm._dead_clock["imessage"]["consecutive_failures"] == 1


@pytest.mark.asyncio
async def test_dead_channel_store_writes_only_on_transition(backing):
    clock = _Clock(T0)
    nm = await _loaded(clock)
    assert backing["saves"] == 0
    await _fail(nm, clock, "imessage", T0)            # first failure: 1 write
    assert backing["saves"] == 1
    for i in range(1, 20):                             # same episode: 0 writes
        await _fail(nm, clock, "imessage", T0 + timedelta(minutes=i))
    assert backing["saves"] == 1
    await _ok(nm, clock, "imessage", T0 + timedelta(hours=1))   # 1 write
    assert backing["saves"] == 2
    for i in range(100):                               # healthy: 0 writes
        await _ok(nm, clock, "imessage", T0 + timedelta(hours=1, seconds=i))
    assert backing["saves"] == 2


@pytest.mark.asyncio
async def test_failure_before_store_load_merges(backing):
    clock = _Clock(T0 + timedelta(hours=4))
    backing["data"] = {"channels": {"imessage": {
        "failing_since": T0.isoformat(), "consecutive_failures": 7,
        "opened_at": None, "alerted_at": None,
    }}}
    nm = _make_nm(clock)
    # a send fails before the Store has loaded: buffered, nothing written
    nm._update_channel_health("imessage", False)
    await _drain(nm)
    assert backing["saves"] == 0
    assert nm._dead_clock == {}
    await nm._dead_load()
    await _drain(nm)
    st = nm._dead_clock["imessage"]
    assert st["failing_since"] == T0.isoformat()
    assert st["consecutive_failures"] == 8


@pytest.mark.asyncio
async def test_success_before_store_load_closes_persisted_episode(backing):
    clock = _Clock(T0 + timedelta(hours=8))
    backing["data"] = {"channels": {"imessage": {
        "failing_since": T0.isoformat(), "consecutive_failures": 9,
        "opened_at": T0.isoformat(), "alerted_at": None,
    }}}
    nm = _make_nm(clock)
    nm._update_channel_health("imessage", True)
    await nm._dead_load()
    await _drain(nm)
    assert "imessage" not in nm._dead_clock
    assert backing["data"] == {"channels": {}}
    assert _pn_calls(nm, "dismiss", "imessage") == ["ura_nm_channel_dead_imessage"]
    assert nm.async_notify.await_count == 0


@pytest.mark.asyncio
async def test_dead_channel_disabled_channel_cleared_on_reload(backing):
    clock = _Clock(T0)
    nm = await _loaded(clock)
    await _outage(nm, clock, "whatsapp", T0, 1, 4)
    assert "whatsapp" in nm._dead_clock
    # operator turns whatsapp off in options; NM re-reads its config
    entry = MagicMock()
    entry.data = {"entry_type": "coordinator_manager"}
    entry.options = {**_cfg(), CONF_NM_WHATSAPP_ENABLED: False}
    nm.hass.config_entries.async_entries = MagicMock(return_value=[entry])
    nm._refresh_config()
    await _drain(nm)
    assert "whatsapp" not in nm._dead_clock
    assert "whatsapp" not in backing["data"]["channels"]
    assert _pn_calls(nm, "dismiss", "whatsapp") == ["ura_nm_channel_dead_whatsapp"]


@pytest.mark.asyncio
async def test_dead_channel_disabled_channel_cleared_on_setup(backing, monkeypatch):
    backing["data"] = {"channels": {"pushover": {
        "failing_since": T0.isoformat(), "consecutive_failures": 9,
        "opened_at": T0.isoformat(), "alerted_at": None,
    }}}
    clock = _Clock(T0 + timedelta(hours=9))
    nm = await _setup_nm(monkeypatch, clock,
                         cfg=_cfg(**{CONF_NM_PUSHOVER_ENABLED: False}))
    assert "pushover" not in nm._dead_clock
    assert backing["data"] == {"channels": {}}
    assert _pn_calls(nm, "dismiss", "pushover") == ["ura_nm_channel_dead_pushover"]


# ---------------------------------------------------------------------------
# D2: restart, storms, quiet hours, self-route, multi-channel, same-day
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dead_channel_alert_across_restart(backing, monkeypatch):
    clock = _Clock(T0)
    nm1 = await _setup_nm(monkeypatch, clock)
    await _outage(nm1, clock, "imessage", T0, 3, 4)          # restart at N/2
    await nm1.async_teardown()
    nm2 = await _setup_nm(monkeypatch, clock)
    await _fail(nm2, clock, "imessage", T0 + timedelta(hours=5, minutes=59))
    assert nm2.async_notify.await_count == 0
    await _fail(nm2, clock, "imessage", T0 + timedelta(hours=6, minutes=1))
    assert nm2.async_notify.await_count == 1


@pytest.mark.asyncio
async def test_dead_channel_no_storm_across_restarts(backing, monkeypatch):
    clock = _Clock(T0)
    nm = await _loaded(clock)
    await _outage(nm, clock, "imessage", T0, 6.1, 5)
    assert nm.async_notify.await_count == 1
    total_notify = 1
    total_pn = len(_pn_calls(nm))
    for r in range(5):
        await nm.async_teardown()
        ss.reset_latches_for_tests()        # restart wipes the RAM day latch
        nm = await _setup_nm(monkeypatch, clock)
        for m in range(3):
            await _fail(nm, clock, "imessage",
                        T0 + timedelta(hours=7 + r, minutes=m))
        total_notify += nm.async_notify.await_count
        total_pn += len(_pn_calls(nm))
    assert total_notify == 1
    assert total_pn == 1


@pytest.mark.asyncio
async def test_dead_channel_quiet_hours_retry(backing):
    clock = _Clock(T0)
    nm = await _loaded(clock, notify_result=False)    # NM drops it (quiet)
    await _outage(nm, clock, "imessage", T0, 6.1, 5)
    assert nm.async_notify.await_count == 1
    assert _pn_calls(nm) == ["ura_nm_channel_dead_imessage"]
    assert nm._dead_clock["imessage"]["alerted_at"] is None
    # quiet hours end: the next failure retries and delivers, once
    nm.async_notify.return_value = True
    await _fail(nm, clock, "imessage", T0 + timedelta(hours=14))
    assert nm.async_notify.await_count == 2
    assert nm._dead_clock["imessage"]["alerted_at"] is not None
    await _fail(nm, clock, "imessage", T0 + timedelta(hours=15))
    assert nm.async_notify.await_count == 2
    assert _pn_calls(nm) == ["ura_nm_channel_dead_imessage"]   # idempotent


@pytest.mark.asyncio
async def test_dead_channel_anomaly_row_written_when_emit_dropped(backing):
    clock = _Clock(T0)
    nm = await _loaded(clock, notify_result=False)
    await _outage(nm, clock, "imessage", T0, 6.1, 5)
    rows = _dead_rows(nm)
    assert len(rows) == 1
    assert rows[0].coordinator == "notification"
    assert rows[0].payload["extra"]["channel"] == "imessage"
    assert rows[0].payload["extra"]["failing_since"] == T0.isoformat()
    # the stuck-signal helper wrote nothing (it writes only on delivery)
    assert [e for e in nm.hass.data[DOMAIN]["database"].anomalies
            if e.type == "nm_channel_dead"] == []


@pytest.mark.asyncio
async def test_dead_channel_self_route_no_recursion(backing):
    """C = companion: the alert's own companion send fails and re-enters
    _update_channel_health. async_notify must be called exactly once."""
    clock = _Clock(T0)
    nm = await _loaded(clock)
    calls = {"n": 0}

    async def _notify(**kw):
        calls["n"] += 1
        if calls["n"] <= 5:          # bound the drill if the guard is gone
            nm._update_channel_health("companion", False)
        for _ in range(5):
            await asyncio.sleep(0)   # real async_notify awaits many times
        return True

    nm.async_notify = AsyncMock(side_effect=_notify)
    await _outage(nm, clock, "companion", T0, 6.1, 5)
    for _ in range(5):
        await _drain(nm)
    assert nm.async_notify.await_count == 1
    assert len(_dead_rows(nm)) == 1
    assert _pn_calls(nm) == ["ura_nm_channel_dead_companion"]


@pytest.mark.asyncio
async def test_dead_channel_all_dead_persistent_only(backing):
    clock = _Clock(T0)
    nm = await _loaded(clock, notify_result=False)   # delivers nowhere
    for ch in CHANNELS:
        await _outage(nm, clock, ch, T0, 6.1, 5)
    assert sorted(_pn_calls(nm)) == sorted(
        f"ura_nm_channel_dead_{c}" for c in CHANNELS)
    assert len(_dead_rows(nm)) == 4
    titles = {c.kwargs["title"] for c in nm.async_notify.await_args_list}
    assert titles == {f"Notification channel dead: {c}" for c in CHANNELS}
    for ch in CHANNELS:
        assert nm._dead_clock[ch]["alerted_at"] is None


@pytest.mark.asyncio
async def test_dead_channel_second_episode_same_day_alerts(backing):
    clock = _Clock(T0.replace(hour=1))
    start1 = clock.t
    nm = await _loaded(clock)
    await _outage(nm, clock, "imessage", start1, 6.5, 5)          # alert ~07:30
    assert nm.async_notify.await_count == 1
    await _ok(nm, clock, "imessage", start1 + timedelta(hours=8))  # 09:00
    assert _pn_calls(nm, "dismiss", "imessage") == ["ura_nm_channel_dead_imessage"]
    start2 = start1 + timedelta(hours=8, minutes=30)               # 09:30
    await _outage(nm, clock, "imessage", start2, 6.1, 5)           # ~15:36
    assert nm.async_notify.await_count == 2


@pytest.mark.asyncio
async def test_dead_channel_recovery_dismisses_and_rearms(backing):
    clock = _Clock(T0)
    nm = await _loaded(clock)
    await _outage(nm, clock, "whatsapp", T0, 6.1, 5)
    assert nm.async_notify.await_count == 1
    await _ok(nm, clock, "whatsapp", T0 + timedelta(hours=7))
    assert _pn_calls(nm, "dismiss", "whatsapp") == ["ura_nm_channel_dead_whatsapp"]
    assert "whatsapp" not in nm._dead_clock
    ss.reset_latches_for_tests()
    await _outage(nm, clock, "whatsapp", T0 + timedelta(days=2), 6.1, 5)
    assert nm.async_notify.await_count == 2
    assert len(_pn_calls(nm, "create", "whatsapp")) == 2


@pytest.mark.asyncio
async def test_dead_channel_kill_switch_zero(backing, monkeypatch):
    monkeypatch.setattr(nm_mod, "NM_CHANNEL_DEAD_ALERT_H", 0)
    clock = _Clock(T0)
    nm = await _loaded(clock)
    await _outage(nm, clock, "imessage", T0, 10, 6)
    assert nm._dead_clock == {}
    assert backing["saves"] == 0
    assert nm.async_notify.await_count == 0
    assert _pn_calls(nm) == []
    assert _dead_rows(nm) == []


@pytest.mark.asyncio
async def test_dead_channel_teardown_flushes_and_cancels(backing, monkeypatch):
    """A save still pending at teardown is flushed; emit tasks cancelled."""
    clock = _Clock(T0)
    nm = await _loaded(clock)
    started = asyncio.Event()
    gate = asyncio.Event()
    real_save = _FakeStore.async_save

    async def _slow_save(self, data):
        started.set()
        await gate.wait()
        await real_save(self, data)

    monkeypatch.setattr(_FakeStore, "async_save", _slow_save)
    clock.t = T0
    nm._update_channel_health("imessage", False)     # schedules a save
    await started.wait()
    assert nm._dead_dirty
    monkeypatch.setattr(_FakeStore, "async_save", real_save)
    await nm.async_teardown()                          # cancels the slow save
    assert nm._dead_tasks == set()
    assert backing["data"]["channels"]["imessage"]["consecutive_failures"] == 1


# ---------------------------------------------------------------------------
# Fix-up: corrupt restored state (review A), overlapping saves (review B)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dead_channel_corrupt_store_starts_clean(backing, monkeypatch):
    backing["data"] = {"channels": {
        "imessage": {"failing_since": "not-a-time", "consecutive_failures": 5,
                     "opened_at": None, "alerted_at": None},
        "whatsapp": {"failing_since": T0.isoformat(),
                     "consecutive_failures": "seven",
                     "opened_at": None, "alerted_at": None},
        "pushover": {"failing_since": "2026-11-22T17:12:00",   # naive
                     "consecutive_failures": 4,
                     "opened_at": None, "alerted_at": None},
        "companion": {"failing_since": T0.isoformat(),
                      "consecutive_failures": 3,
                      "opened_at": "garbage", "alerted_at": None},
    }}
    clock = _Clock(T0 + timedelta(hours=1))
    nm = await _setup_nm(monkeypatch, clock)          # setup must not raise
    assert nm._dead_clock_loaded
    assert "imessage" not in nm._dead_clock
    assert "whatsapp" not in nm._dead_clock
    assert "companion" not in nm._dead_clock
    # naive timestamp kept, normalised to UTC
    assert nm._dead_clock["pushover"]["failing_since"] == T0.isoformat()
    assert set(backing["data"]["channels"]) == {"pushover"}
    # a later outage on a dropped channel still opens a fresh episode
    start = T0 + timedelta(hours=2)
    await _outage(nm, clock, "imessage", start, 6.1, 5)
    assert nm._dead_clock["imessage"]["failing_since"] == start.isoformat()
    titles = [c.kwargs["title"] for c in nm.async_notify.await_args_list]
    assert "Notification channel dead: imessage" in titles


@pytest.mark.asyncio
async def test_dead_channel_load_exception_starts_empty(backing, monkeypatch):
    """An unexpected exception inside the load falls back to an empty
    clock and NM setup still completes."""
    backing["data"] = {"channels": {"imessage": {
        "failing_since": T0.isoformat(), "consecutive_failures": 3,
        "opened_at": None, "alerted_at": None}}}

    def _boom(self, st):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(nm_mod.NotificationManager, "_dead_validate", _boom)
    clock = _Clock(T0)
    nm = await _setup_nm(monkeypatch, clock)
    assert nm._dead_clock_loaded
    assert nm._dead_clock == {}
    await _fail(nm, clock, "imessage", T0)
    assert nm._dead_clock["imessage"]["consecutive_failures"] == 1


@pytest.mark.asyncio
async def test_dead_channel_overlapping_saves_newest_wins(backing):
    """Open-save and close-save in flight together, the first one's I/O
    slower: after a reload there is no episode."""
    clock = _Clock(T0)
    nm = await _loaded(clock)
    backing["io_delays"] = [10, 0]
    nm._update_channel_health("imessage", False)    # save #1 (episode open)
    for _ in range(3):
        await asyncio.sleep(0)                      # save #1 now in its I/O
    assert backing["data"] is None                  # ...and not landed yet
    nm._update_channel_health("imessage", True)     # save #2 (episode closed)
    await _drain(nm)
    for _ in range(30):
        await asyncio.sleep(0)
    assert backing["data"] == {"channels": {}}
    nm2 = await _loaded(clock)
    assert nm2._dead_clock == {}
