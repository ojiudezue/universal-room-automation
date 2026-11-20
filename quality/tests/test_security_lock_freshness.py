"""SECURITY-LOCK-STALE-STATE-1: swept-lock freshness check (D1-D4).

Drives the real SecurityCoordinator._evaluate_lock_check with the real
LockFreshnessTracker. The entity/device registries are faked at the HA
helper functions the tracker calls. Times are patched, never slept on.
Knob values in assertions are hardcoded literals (12 h, 6 h, 20 min, 600 s).
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_SAVED = {k: v for k, v in sys.modules.items() if k.startswith("custom_components")}
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    security as security_mod,
    security_lock_freshness as fresh_mod,
    manager as manager_mod,
)
for _k in [k for k in sys.modules if k.startswith("custom_components")]:
    del sys.modules[_k]
sys.modules.update(_SAVED)
NotificationAction = security_mod.NotificationAction
ServiceCallAction = security_mod.ServiceCallAction
Severity = security_mod.Severity

from homeassistant.helpers import device_registry as dr  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402

GARAGE = "lock.garage_hallway_doorlock"
FRONT = "lock.front_door"
MASTER = "lock.master_bedroom_lock"
LS_GARAGE = "sensor.node_10_last_seen"
LS_FRONT = "sensor.node_3_last_seen"
NS_GARAGE = "sensor.node_10_node_status"
BOOT = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
REPORT = datetime(2026, 11, 16, 7, 37, tzinfo=timezone.utc)


def H(h: float) -> timedelta:
    return timedelta(hours=h)


# --------------------------------------------------------------------- fakes
class _States:
    def __init__(self):
        self._d = {}

    def set(self, eid, state, *, changed=None, reported=None, name=None):
        attrs = {"friendly_name": name} if name else {}
        self._d[eid] = SimpleNamespace(
            state=state, last_changed=changed, last_reported=reported,
            attributes=attrs,
        )

    def get(self, eid):
        return self._d.get(eid)

    def async_all(self, _domain=None):
        return []


class _Reg:
    def __init__(self):
        self.entries = {}

    def add(self, eid, platform, device_id, tkey=None, disabled=False):
        self.entries[eid] = SimpleNamespace(
            entity_id=eid, platform=platform, device_id=device_id,
            translation_key=tkey, disabled_by="integration" if disabled else None,
            name=None, original_name=None,
        )

    def async_get(self, eid):
        return self.entries.get(eid)


def _entries_for_device(reg, device_id, include_disabled_entities=False):
    return [
        e for e in reg.entries.values()
        if e.device_id == device_id
        and (include_disabled_entities or e.disabled_by is None)
    ]


class _Store:
    def __init__(self, data=None):
        self.data = data
        self.saves = 0

    async def async_load(self):
        return self.data

    def async_delay_save(self, fn, delay):
        self.data = fn()
        self.saves += 1


def _registry(*, garage_ls_disabled=False, with_front=False):
    reg = _Reg()
    reg.add(GARAGE, "zwave_js", "dev_garage")
    reg.add(LS_GARAGE, "zwave_js", "dev_garage", "last_seen", disabled=garage_ls_disabled)
    reg.add(NS_GARAGE, "zwave_js", "dev_garage", "node_status")
    if with_front:
        reg.add(FRONT, "zwave_js", "dev_front")
        reg.add(LS_FRONT, "zwave_js", "dev_front", "last_seen")
    return reg


def _make(locks=(GARAGE,), reg=None, store=None, cm_opts=None, boot=BOOT):
    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    entries = []
    if cm_opts is not None:
        entries = [SimpleNamespace(
            data={"entry_type": "coordinator_manager"}, options=dict(cm_opts),
        )]
    hass.config_entries.async_entries = lambda *_a, **_k: entries
    states = _States()
    hass.states = states
    coord = security_mod.SecurityCoordinator(hass, lock_entities=list(locks))
    coord.compliance_tracker = None
    coord.anomaly_detector = None
    store = store if store is not None else _Store()
    tracker = fresh_mod.LockFreshnessTracker(
        hass, store, boot, boot_grace_s=600, dead_debounce_min=20,
    )
    asyncio.run(tracker.async_load())
    coord._lock_freshness = tracker
    coord._test_reg = reg if reg is not None else _registry()
    return coord, states, store


def _run(coord, now):
    reg = coord._test_reg
    with patch.object(security_mod, "async_dispatcher_send", lambda *a, **k: None), \
            patch.object(security_mod.dt_util, "utcnow", lambda: now), \
            patch.object(er, "async_get", lambda _h: reg), \
            patch.object(er, "async_entries_for_device", _entries_for_device), \
            patch.object(dr, "async_get", lambda _h: MagicMock(async_get=lambda _d: None)):
        acts = asyncio.run(coord._evaluate_lock_check())
    _execute(coord, acts)
    return acts


class _NM:
    def __init__(self):
        self.deliver = True
        self.sent = []

    async def async_notify(self, **kw):
        if self.deliver:
            self.sent.append(kw)
        return self.deliver


def _execute(coord, acts):
    """Run every action through the REAL CoordinatorManager._execute_action
    (NM delivery result reaches on_notify_result; service calls recorded)."""
    nm = getattr(coord, "_test_nm", None)
    if nm is None:
        nm = coord._test_nm = _NM()
    calls = coord.__dict__.setdefault("_test_calls", [])

    async def _call(domain, service, data, blocking=True, **_k):
        calls.append((f"{domain}.{service}", dict(data), blocking))

    async def _noop(*_a, **_k):
        return None

    fake = SimpleNamespace(
        hass=SimpleNamespace(data={}, services=SimpleNamespace(async_call=_call)),
        _notification_manager=nm, _log_decision=_noop,
    )

    async def _go():
        for a in acts:
            await manager_mod.CoordinatorManager._execute_action(fake, coord, a)
    asyncio.run(_go())


def _is(a, cls):
    # Class NAME: a fresh relative import (setup path) may build its own
    # copy of base.py, and isinstance against another copy is False.
    return type(a).__name__ == cls.__name__


def _pages(actions, title="Lock not verified"):
    return [a for a in actions if _is(a, NotificationAction) and a.description == title]


def _lock_cmds(actions, eid):
    return [a for a in actions if _is(a, ServiceCallAction)
            and a.service in ("lock.lock", "lock.unlock")
            and a.service_data.get("entity_id") == eid]


def _refreshes(actions):
    return [a for a in actions if _is(a, ServiceCallAction)
            and a.service == "zwave_js.refresh_value"]


def _healthy_garage(states, report=REPORT, state="locked"):
    states.set(GARAGE, state, changed=report, reported=report,
               name="Garage hallway lock")
    states.set(LS_GARAGE, report.isoformat())
    states.set(NS_GARAGE, "alive")


# ----------------------------------------------------------------- D1 tests
def test_freshness_uses_max_of_stamps():
    coord, states, store = _make()
    # Lock stamps old; last_seen VALUE is the newest -> it wins.
    states.set(GARAGE, "locked", changed=REPORT, reported=REPORT + H(1))
    states.set(LS_GARAGE, (REPORT + H(3)).isoformat())
    states.set(NS_GARAGE, "alive")
    _run(coord, REPORT + H(4))
    rec = coord._lock_freshness.record(GARAGE)
    assert rec["real_report_ts"] == (REPORT + H(3)).isoformat()
    assert coord.last_lock_sweep["freshness_age_h"][GARAGE] == 1.0
    # last_reported newest -> it wins.
    states.set(GARAGE, "locked", changed=REPORT, reported=REPORT + H(5))
    _run(coord, REPORT + H(6))
    assert coord._lock_freshness.record(GARAGE)["real_report_ts"] == (REPORT + H(5)).isoformat()


def test_boot_stamp_not_real_report():
    boot = datetime(2026, 11, 17, 3, 0, tzinfo=timezone.utc)
    store = _Store({"locks": {GARAGE: {"real_report_ts": REPORT.isoformat()}}})
    coord, states, _ = _make(store=store, boot=boot)
    in_grace = boot + timedelta(seconds=599)
    states.set(GARAGE, "locked", changed=in_grace, reported=in_grace)
    states.set(LS_GARAGE, in_grace.isoformat())
    states.set(NS_GARAGE, "alive")
    _run(coord, boot + timedelta(seconds=700))
    assert coord._lock_freshness.record(GARAGE)["real_report_ts"] == REPORT.isoformat()
    # One second after grace end counts.
    after = boot + timedelta(seconds=601)
    states.set(LS_GARAGE, after.isoformat())
    _run(coord, boot + timedelta(seconds=800))
    assert coord._lock_freshness.record(GARAGE)["real_report_ts"] == after.isoformat()


def test_last_seen_resolved_by_registry_not_name():
    reg = _registry()
    # Misleadingly named sensor on ANOTHER device: must be ignored.
    reg.add("sensor.garage_hallway_doorlock_last_seen", "zwave_js", "dev_other", "last_seen")
    coord, states, _ = _make(reg=reg)
    _healthy_garage(states)
    states.set("sensor.garage_hallway_doorlock_last_seen", (REPORT + H(12)).isoformat())
    _run(coord, REPORT + H(13))
    assert coord._lock_freshness.record(GARAGE)["real_report_ts"] == REPORT.isoformat()
    assert coord.last_lock_sweep["stale"] == [GARAGE]


def test_disabled_last_seen_reported_as_disabled():
    coord, states, _ = _make(reg=_registry(garage_ls_disabled=True))
    _healthy_garage(states)
    _run(coord, BOOT + H(1))
    assert coord.last_lock_sweep["freshness_signal"] == {GARAGE: "disabled"}


def test_store_round_trip():
    coord, states, store = _make()
    _healthy_garage(states)
    _run(coord, REPORT + H(13))
    saved = store.data
    assert saved["locks"][GARAGE]["real_report_ts"] == REPORT.isoformat()
    assert saved["locks"][GARAGE]["paged_kind"] == "stale"
    t2 = fresh_mod.LockFreshnessTracker(
        MagicMock(), _Store(saved), BOOT, boot_grace_s=600, dead_debounce_min=20)
    asyncio.run(t2.async_load())
    assert t2.record(GARAGE) == saved["locks"][GARAGE]


# ----------------------------------------------------------------- D2 tests
def test_stale_locked_pages_and_refreshes():
    coord, states, _ = _make()
    _healthy_garage(states)
    acts = _run(coord, REPORT + H(13))
    pages = _pages(acts)
    assert len(pages) == 1
    p = pages[0]
    assert p.severity == Severity.HIGH and p.hazard_type == "lock_unverified"
    assert p.channels == ["security"]
    assert "Garage hallway lock" in p.message and "13 h" in p.message
    assert GARAGE not in p.message
    refs = _refreshes(acts)
    assert len(refs) == 1 and refs[0].service_data == {"entity_id": GARAGE}
    assert refs[0].target_device == ""
    assert _lock_cmds(acts, GARAGE) == []
    assert coord._lock_compliance[GARAGE] == "stale"
    assert coord.last_lock_sweep["stale"] == [GARAGE]
    # Counted on delivery; the next sweep's sensor snapshot shows it.
    assert coord._lock_freshness.stale_pages_total == 1
    _run(coord, REPORT + H(13.1))
    assert coord.last_lock_sweep["stale_pages_total"] == 1
    assert coord.last_lock_sweep["last_stale_page"] == (REPORT + H(13)).isoformat()
    # Refresh executed NON-blocking (review B LOW).
    assert ("zwave_js.refresh_value", {"entity_id": GARAGE}, False) in coord._test_calls


def test_fresh_locked_byte_identical():
    coord, states, _ = _make()
    _healthy_garage(states)
    acts = _run(coord, REPORT + H(11))
    ref, rstates, _ = _make()
    ref._lock_freshness = None
    _healthy_garage(rstates)
    assert acts == _run(ref, REPORT + H(11))
    assert coord._lock_compliance[GARAGE] == "locked"
    assert coord.last_lock_sweep["stale"] == []


def test_stale_boundary_literals():
    coord, states, _ = _make()
    _healthy_garage(states)
    assert _pages(_run(coord, REPORT + H(12) - timedelta(seconds=1))) == []
    assert _pages(_run(coord, REPORT + H(12))) == []
    assert len(_pages(_run(coord, REPORT + H(12) + timedelta(seconds=1)))) == 1


def test_stale_unlocked_pages_and_still_commanded():
    coord, states, _ = _make()
    _healthy_garage(states, state="unlocked")
    acts = _run(coord, REPORT + H(13))
    assert len(_pages(acts)) == 1
    cmds = _lock_cmds(acts, GARAGE)
    assert len(cmds) == 1 and cmds[0].service == "lock.lock"
    assert cmds[0].target_device == GARAGE
    # Retry cap unchanged: 3 commands total over many sweeps.
    total = 1
    for i in range(1, 8):
        total += len(_lock_cmds(_run(coord, REPORT + H(13) + timedelta(minutes=15 * i)), GARAGE))
    assert total == 3


def test_refresh_never_displaces_lock_command_in_resolver():
    from custom_components.universal_room_automation.domain_coordinators.manager import (
        ConflictResolver,
    )
    coord, states, _ = _make()
    _healthy_garage(states, state="unlocked")
    acts = _run(coord, REPORT + H(13))
    pairs = [(SimpleNamespace(priority=60, coordinator_id="security"), a) for a in acts]
    resolved = [a for _c, a in ConflictResolver().resolve(pairs)]
    # Both survive: the refresh never competes with lock.lock for the device.
    assert sorted(a.service for a in resolved if _is(a, ServiceCallAction)) == [
        "lock.lock", "zwave_js.refresh_value"]


def test_excluded_lock_not_stale_paged():
    coord, states, _ = _make(cm_opts={"security_lock_sweep_exclude": [GARAGE]})
    _healthy_garage(states)
    acts = _run(coord, REPORT + H(13))
    assert _pages(acts) == [] and _refreshes(acts) == []
    assert coord.last_lock_sweep["excluded"] == [GARAGE]


def test_none_unavailable_sibling_is_no_signal():
    coord, states, _ = _make()
    _healthy_garage(states)
    for val in ("unavailable", None):
        if val is None:
            states._d.pop(LS_GARAGE, None)
        else:
            states.set(LS_GARAGE, val)
        acts = _run(coord, REPORT + H(11))
        # Not age 0 (no advance) and not stale (11 h < 12 h).
        assert coord._lock_freshness.record(GARAGE)["real_report_ts"] == REPORT.isoformat()
        assert _pages(acts) == []


def test_n_zero_golden_byte_identical():
    scen = {}
    for label, opts, tracker in (("off", {"security_lock_stale_hours": 0}, True),
                                 ("none", None, False)):
        coord, states, store = _make(locks=(GARAGE, FRONT), cm_opts=opts,
                                     reg=_registry(with_front=True))
        if not tracker:
            coord._lock_freshness = None
        _healthy_garage(states)
        states.set(FRONT, "unlocked", changed=REPORT, reported=REPORT)
        states.set(LS_FRONT, REPORT.isoformat())
        out = [_run(coord, REPORT + H(30) + timedelta(minutes=30 * i)) for i in range(4)]
        scen[label] = (out, dict(coord.last_lock_sweep), dict(coord._lock_compliance))
        if tracker:
            assert store.saves == 0
    a, b = scen["off"], scen["none"]
    assert a[0] == b[0]
    a[1].pop("timestamp"), b[1].pop("timestamp")
    assert a[1] == b[1] and "stale" not in a[1]
    assert a[2] == b[2]


# ----------------------------------------------------------------- D3 tests
def test_unavailable_blip_under_debounce_no_page():
    coord, states, _ = _make()
    _healthy_garage(states)
    t = REPORT + H(1)
    states.set(GARAGE, "unavailable")
    acts = []
    for m in (0, 5, 10, 15, 19):
        acts += _run(coord, t + timedelta(minutes=m))
    assert _pages(acts) == []
    assert len(_pages(_run(coord, t + timedelta(minutes=20)))) == 1


def test_all_locks_unavailable_single_common_mode_page():
    coord, states, _ = _make(locks=(GARAGE, FRONT), reg=_registry(with_front=True))
    t = REPORT + H(1)
    states.set(GARAGE, "unavailable", name="Garage hallway lock")
    states.set(FRONT, "unavailable", name="Front door lock")
    acts = []
    for m in (0, 10, 21, 30, 40):
        acts += _run(coord, t + timedelta(minutes=m))
    common = _pages(acts, "Locks offline together")
    assert len(common) == 1
    assert "Garage hallway lock" in common[0].message and "Front door lock" in common[0].message
    assert "Z-Wave or Home Assistant" in common[0].message
    assert common[0].severity == Severity.HIGH
    assert _pages(acts) == []


def test_one_of_two_unavailable_is_per_lock_page():
    coord, states, _ = _make(locks=(GARAGE, FRONT), reg=_registry(with_front=True))
    _healthy_garage(states)
    states.set(LS_FRONT, REPORT.isoformat())
    states.set(FRONT, "unavailable", name="Front door lock")
    acts = _run(coord, REPORT + H(1)) + _run(coord, REPORT + H(1) + timedelta(minutes=21))
    assert _pages(acts, "Locks offline together") == []
    assert len(_pages(acts)) == 1 and "Front door lock" in _pages(acts)[0].message


def test_cache_restore_not_a_report():
    coord, states, _ = _make()
    _healthy_garage(states)
    _run(coord, REPORT + H(1))
    restore = REPORT + H(2)
    old = SimpleNamespace(state="unavailable", last_changed=REPORT + H(1))
    states.set(GARAGE, "locked", changed=restore, reported=restore)
    coord._lock_freshness.note_state_change(GARAGE, old, states.get(GARAGE))
    _run(coord, restore + timedelta(minutes=5))
    assert coord._lock_freshness.record(GARAGE)["real_report_ts"] == REPORT.isoformat()
    # Still pages at 12 h after the REAL report, not after the restore.
    assert len(_pages(_run(coord, REPORT + H(13)))) == 1
    # A later lock stamp after the restore IS a report.
    states.set(GARAGE, "locked", changed=restore, reported=REPORT + H(13.5))
    _run(coord, REPORT + H(14))
    assert coord._lock_freshness.record(GARAGE)["real_report_ts"] == (REPORT + H(13.5)).isoformat()


def test_cache_restore_detected_between_sweeps_without_listener():
    coord, states, _ = _make()
    _healthy_garage(states)
    states.set(GARAGE, "unavailable")
    _run(coord, REPORT + H(1))
    restore = REPORT + H(2)
    states.set(GARAGE, "locked", changed=restore, reported=restore)
    _run(coord, restore + timedelta(minutes=5))
    assert coord._lock_freshness.record(GARAGE)["real_report_ts"] == REPORT.isoformat()


def test_dead_lock_pages_high_persistent_dedup():
    coord, states, store = _make()
    _healthy_garage(states)
    states.set(NS_GARAGE, "dead")
    t = REPORT + H(1)
    acts = _run(coord, t) + _run(coord, t + timedelta(minutes=21))
    pages = _pages(acts)
    assert len(pages) == 1 and "node dead" in pages[0].message
    assert pages[0].hazard_type == "lock_unverified"
    # Restart inside R: same Store -> no re-page after grace.
    boot2 = t + H(1)
    c2, s2, _ = _make(store=store, boot=boot2)
    _healthy_garage(s2)
    s2.set(NS_GARAGE, "dead")
    later = []
    for m in (0, 11, 32, 60):
        later += _run(c2, boot2 + timedelta(minutes=m))
    assert _pages(later) == []
    assert c2._lock_freshness.record(GARAGE)["paged_kind"] == "dead"


def test_repage_after_interval():
    coord, states, _ = _make()
    _healthy_garage(states)
    t = REPORT + H(13)
    assert len(_pages(_run(coord, t))) == 1
    assert _pages(_run(coord, t + H(6) - timedelta(seconds=1))) == []
    again = _run(coord, t + H(6))
    assert len(_pages(again)) == 1 and len(_refreshes(again)) == 1


def test_repage_zero_pages_once():
    coord, states, _ = _make(cm_opts={"security_lock_dead_repage_hours": 0})
    _healthy_garage(states)
    acts = []
    for h in (13, 20, 40, 60):
        acts += _run(coord, REPORT + H(h))
    assert len(_pages(acts)) == 1


def test_clear_on_report():
    coord, states, _ = _make()
    _healthy_garage(states)
    _run(coord, REPORT + H(13))
    states.set(LS_GARAGE, (REPORT + H(13.5)).isoformat())
    acts = _run(coord, REPORT + H(14))
    clear = _pages(acts, "Lock reporting again")
    assert len(clear) == 1 and clear[0].severity == Severity.MEDIUM
    assert "paged_ts" not in coord._lock_freshness.record(GARAGE)
    assert _pages(_run(coord, REPORT + H(15)), "Lock reporting again") == []


def test_no_page_within_boot_grace():
    boot = REPORT + H(20)
    store = _Store({"locks": {GARAGE: {"real_report_ts": REPORT.isoformat()}}})
    coord, states, _ = _make(store=store, boot=boot)
    states.set(GARAGE, "locked", changed=boot, reported=boot)
    states.set(LS_GARAGE, REPORT.isoformat())
    states.set(NS_GARAGE, "dead")
    assert _pages(_run(coord, boot + timedelta(seconds=599))) == []
    assert coord.last_lock_sweep["stale"] == []
    assert len(_pages(_run(coord, boot + timedelta(seconds=601)))) == 1


def _offline(acts):
    return [a for a in acts if _is(a, NotificationAction)
            and a.description == "Lock check unavailable device notification"]


def test_offline_medium_notice_owned_by_dead_page():
    coord, states, _ = _make()
    states.set(GARAGE, "unavailable")
    acts = _run(coord, REPORT + H(1)) + _run(coord, REPORT + H(1) + timedelta(minutes=20))
    # One notice per incident: the HIGH dead page, no MEDIUM digest notice.
    assert _offline(acts) == []
    assert len(_pages(acts)) == 1


def test_offline_medium_notice_kept_for_cover_and_in_grace():
    coord, states, _ = _make(boot=REPORT + H(1))
    states.set(GARAGE, "unavailable")
    acts = _run(coord, REPORT + H(1) + timedelta(seconds=60))
    assert len(_offline(acts)) == 1


# ----------------------------------------------------------------- D4 tests
def test_signal_disabled_pages_and_anomaly_once_per_r():
    coord, states, _ = _make(reg=_registry(garage_ls_disabled=True))
    stored = []

    async def _store_event(ev):
        stored.append(ev)

    coord.anomaly_detector = SimpleNamespace(store_event=_store_event)
    _healthy_garage(states)
    acts = []
    for h in (1, 2, 3):
        acts += _run(coord, BOOT + H(h))
    sig = _pages(acts, "Lock freshness signal disabled")
    assert len(sig) == 1 and sig[0].severity == Severity.HIGH
    assert "Garage hallway lock" in sig[0].message
    assert len(stored) == 1 and stored[0].type == "security.lock_freshness_signal_disabled"
    assert stored[0].entity_id == GARAGE
    assert len(_pages(_run(coord, BOOT + H(7)), "Lock freshness signal disabled")) == 1
    assert len(stored) == 1


def test_non_zwave_lock_no_signal_page_no_stale():
    reg = _Reg()
    reg.add(MASTER, "philips_home_access", "dev_master")
    coord, states, _ = _make(locks=(MASTER,), reg=reg)
    states.set(MASTER, "locked", changed=REPORT, reported=REPORT)
    acts = _run(coord, REPORT + H(40))
    assert acts == []
    assert coord.last_lock_sweep["freshness_signal"] == {MASTER: "none"}


def test_non_zwave_excluded_lock_gets_dead_page():
    reg = _Reg()
    reg.add(MASTER, "philips_home_access", "dev_master")
    coord, states, _ = _make(locks=(MASTER,), reg=reg,
                             cm_opts={"security_lock_sweep_exclude": [MASTER]})
    states.set(MASTER, "unavailable", name="Master bedroom lock")
    acts = _run(coord, REPORT + H(1)) + _run(coord, REPORT + H(1) + timedelta(minutes=20))
    assert len(_pages(acts)) == 1 and "Master bedroom lock is offline" in _pages(acts)[0].message


# ------------------------------------------------------- incident replays
def test_replay_1116_silence_last_seen_enabled():
    coord, states, _ = _make()
    _healthy_garage(states)
    first = None
    pages = 0
    t = REPORT + timedelta(minutes=23)  # 08:00
    end = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
    while t <= end:
        acts = _run(coord, t)
        assert _lock_cmds(acts, GARAGE) == []
        if _pages(acts):
            pages += len(_pages(acts))
            first = first or t
        t += H(1)
    assert first == datetime(2026, 11, 16, 20, 0, tzinfo=timezone.utc)
    # 11-16 20:00 then every 6 h through 11-18 14:00 = 8 pages.
    assert pages == 8


def test_replay_1116_silence_last_seen_disabled():
    coord, states, _ = _make(reg=_registry(garage_ls_disabled=True))
    _healthy_garage(states)
    sig = unver = 0
    t = REPORT + timedelta(minutes=23)
    dead_at = datetime(2026, 11, 18, 15, 34, tzinfo=timezone.utc)
    first_dead = None
    while t <= datetime(2026, 11, 18, 16, 30, tzinfo=timezone.utc):
        if t >= dead_at:
            states.set(GARAGE, "unavailable", name="Garage hallway lock")
        acts = _run(coord, t)
        sig += len(_pages(acts, "Lock freshness signal disabled"))
        if _pages(acts):
            unver += 1
            first_dead = first_dead or t
        fine = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
        t += timedelta(minutes=5) if t >= fine else H(1)
    # Signal page at 08:00 then every 6 h: 08, 14, 20, 02, 08, 14 on 11-17,
    # 20, 02, 08, 14 on 11-18 = 10. No staleness page in this class (D0).
    assert sig == 10
    assert unver == 1
    # First unavailable sweep 15:35, debounce 20 min -> 15:55.
    assert first_dead == datetime(2026, 11, 18, 15, 55, tzinfo=timezone.utc)


# ------------------------------------------------------------- wire-in
def test_setup_wires_store_listener_and_sweep():
    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    hass.config_entries.async_entries = lambda *_a, **_k: []
    states = _States()
    hass.states = states
    coord = security_mod.SecurityCoordinator(hass, lock_entities=[GARAGE])
    coord.compliance_tracker = None
    store = _Store({"locks": {GARAGE: {"real_report_ts": REPORT.isoformat()}}})
    captured = {}

    def _track(_h, ids, cb):
        captured["ids"], captured["cb"] = ids, cb
        return lambda: None

    import homeassistant.helpers.storage as storage_mod
    with patch.object(storage_mod, "Store", lambda *_a, **_k: store), \
            patch.object(security_mod, "async_track_state_change_event", _track), \
            patch.object(security_mod.dt_util, "utcnow", lambda: BOOT):
        asyncio.run(coord._async_setup_lock_freshness())
    assert captured["ids"] == [GARAGE]
    assert coord._lock_freshness.record(GARAGE)["real_report_ts"] == REPORT.isoformat()
    # Listener routes to note_state_change.
    restore = REPORT + H(2)
    new = SimpleNamespace(state="locked", last_changed=restore)
    captured["cb"](SimpleNamespace(data={
        "entity_id": GARAGE, "old_state": SimpleNamespace(state="unavailable"),
        "new_state": new}))
    assert coord._lock_freshness._recovery_ts[GARAGE] == restore
    coord._test_reg = _registry()
    _healthy_garage(states)
    assert len(_pages(_run(coord, REPORT + H(13)))) == 1


def test_evaluate_path_carries_page():
    coord, states, _ = _make()
    _healthy_garage(states)
    intent = security_mod.Intent(source="periodic_lock_check", entity_id="", data={},
                                 coordinator_id="security")
    reg = coord._test_reg
    with patch.object(security_mod, "async_dispatcher_send", lambda *a, **k: None), \
            patch.object(security_mod.dt_util, "utcnow", lambda: REPORT + H(13)), \
            patch.object(er, "async_get", lambda _h: reg), \
            patch.object(er, "async_entries_for_device", _entries_for_device):
        acts = asyncio.run(coord.evaluate([intent], {}))
    assert len(_pages(acts)) == 1


def test_stale_locked_keeps_retry_episode():
    coord, states, _ = _make()
    _healthy_garage(states, state="unlocked")
    _run(coord, REPORT + H(1))
    assert coord._lock_retry_episodes[GARAGE]["attempts"] == 1
    _healthy_garage(states, state="locked")
    _run(coord, REPORT + H(13))
    assert coord._lock_retry_episodes[GARAGE]["attempts"] == 1
    # Fresh locked clears it, as before.
    states.set(LS_GARAGE, (REPORT + H(13.5)).isoformat())
    _run(coord, REPORT + H(14))
    assert GARAGE not in coord._lock_retry_episodes


def test_unavailable_with_old_report_waits_for_debounce():
    coord, states, _ = _make()
    _healthy_garage(states)
    states.set(GARAGE, "unavailable")
    t = REPORT + H(13)
    assert _pages(_run(coord, t)) == []
    assert coord.last_lock_sweep["stale"] == []
    pages = _pages(_run(coord, t + timedelta(minutes=20)))
    assert len(pages) == 1 and "offline" in pages[0].message


def test_async_setup_builds_tracker_before_sweep_timer():
    hass = MagicMock()
    hass.data = {"universal_room_automation": {}}
    hass.config_entries.async_entries = lambda *_a, **_k: []
    hass.states = _States()
    coord = security_mod.SecurityCoordinator(hass, lock_entities=[GARAGE])
    order = []

    def _track(_h, ids, _cb):
        order.append(("listen", list(ids)))
        return lambda: None

    def _interval(*_a, **_k):
        order.append(("timer", coord._lock_freshness is not None))
        return lambda: None

    async def _noop(*_a, **_k):
        return None

    import homeassistant.helpers.storage as storage_mod
    with patch.object(storage_mod, "Store", lambda *_a, **_k: _Store()), \
            patch.object(security_mod, "async_track_state_change_event", _track), \
            patch.object(security_mod, "async_track_time_interval", _interval), \
            patch.object(security_mod, "async_dispatcher_connect",
                         lambda *a, **k: (lambda: None)), \
            patch.object(coord, "_async_setup_lock_regime", _noop), \
            patch.object(security_mod.dt_util, "utcnow", lambda: BOOT):
        asyncio.run(coord.async_setup())
    assert coord._lock_freshness is not None
    assert ("listen", [GARAGE]) in order
    assert ("timer", True) in order


def test_no_signal_page_within_boot_grace():
    boot = REPORT + H(20)
    coord, states, _ = _make(reg=_registry(garage_ls_disabled=True), boot=boot)
    _healthy_garage(states)
    sig = "Lock freshness signal disabled"
    assert _pages(_run(coord, boot + timedelta(seconds=599)), sig) == []
    assert len(_pages(_run(coord, boot + timedelta(seconds=601)), sig)) == 1


# ------------------------------------------------ fix pass: review B / A / C
def test_quiet_hours_drop_leaves_page_pending_then_delivers_once():
    coord, states, _ = _make()
    _healthy_garage(states)
    coord._test_nm = nm = _NM()
    nm.deliver = False  # NM drops it (quiet hours)
    first = _run(coord, REPORT + H(13))
    assert len(_pages(first)) == 1
    assert "paged_ts" not in coord._lock_freshness.record(GARAGE)
    second = _run(coord, REPORT + H(13.5))
    assert len(_pages(second)) == 1  # retried, not deduped
    assert _refreshes(second) == []  # radio refresh bounded to once per R
    nm.deliver = True  # quiet hours over
    third = _run(coord, REPORT + H(14))
    assert len(_pages(third)) == 1
    assert coord._lock_freshness.record(GARAGE)["paged_ts"] == (REPORT + H(14)).isoformat()
    assert [k["title"] for k in nm.sent].count("Lock not verified") == 1
    assert _pages(_run(coord, REPORT + H(15))) == []


def _restore(coord, states, eid, at, name):
    old = SimpleNamespace(state="unavailable", last_changed=at - H(1))
    states.set(eid, "locked", changed=at, reported=at, name=name)
    coord._lock_freshness.note_state_change(eid, old, states.get(eid))


def test_restored_dead_philips_stays_unverified_and_repages():
    reg = _Reg()
    reg.add(MASTER, "philips_home_access", "dev_master")
    coord, states, _ = _make(locks=(MASTER,), reg=reg,
                             cm_opts={"security_lock_sweep_exclude": [MASTER]})
    t = REPORT + H(1)
    states.set(MASTER, "unavailable", name="Master bedroom lock")
    assert len(_pages(_run(coord, t) + _run(coord, t + timedelta(minutes=20)))) == 1
    _restore(coord, states, MASTER, t + H(1), "Master bedroom lock")
    assert _pages(_run(coord, t + H(2))) == []  # inside R
    again = _pages(_run(coord, t + timedelta(minutes=20) + H(6)))
    assert len(again) == 1 and "back online" in again[0].message
    # A real report after the re-page clears it.
    states.set(MASTER, "locked", changed=t + H(1), reported=t + H(6.5),
               name="Master bedroom lock")
    acts = _run(coord, t + H(7))
    assert len(_pages(acts, "Lock reporting again")) == 1


def test_restored_dead_zwave_disabled_class_not_compliant():
    coord, states, _ = _make(reg=_registry(garage_ls_disabled=True))
    t = REPORT + H(1)
    states.set(GARAGE, "unavailable", name="Garage hallway lock")
    states.set(NS_GARAGE, "alive")
    _run(coord, t)
    _run(coord, t + timedelta(minutes=20))
    _restore(coord, states, GARAGE, t + H(1), "Garage hallway lock")
    acts = _run(coord, t + H(2))
    assert coord._lock_compliance[GARAGE] == "unverified"
    assert coord.last_lock_sweep["unverified"] == [GARAGE]
    assert _lock_cmds(acts, GARAGE) == []
    again = _pages(_run(coord, t + timedelta(minutes=20) + H(6)))
    assert len(again) == 1 and "back online" in again[0].message


def test_future_stamp_ignored():
    coord, states, _ = _make()
    _healthy_garage(states)
    states.set(LS_GARAGE, (REPORT + H(20)).isoformat())
    _run(coord, REPORT + H(13))
    assert coord._lock_freshness.record(GARAGE)["real_report_ts"] == REPORT.isoformat()


def test_disabled_node_status_sibling_skipped():
    reg = _Reg()
    reg.add(GARAGE, "zwave_js", "dev_garage")
    reg.add(LS_GARAGE, "zwave_js", "dev_garage", "last_seen")
    reg.add(NS_GARAGE, "zwave_js", "dev_garage", "node_status", disabled=True)
    coord, states, _ = _make(reg=reg)
    _healthy_garage(states)
    states.set(NS_GARAGE, "dead")
    t = REPORT + H(1)
    assert _pages(_run(coord, t) + _run(coord, t + timedelta(minutes=30))) == []


def test_non_zwave_sibling_platform_ignored():
    reg = _Reg()
    reg.add(GARAGE, "zwave_js", "dev_garage")
    reg.add("sensor.other_last_seen", "other_platform", "dev_garage", "last_seen")
    coord, states, _ = _make(reg=reg)
    _healthy_garage(states)
    states.set("sensor.other_last_seen", (REPORT + H(12)).isoformat())
    _run(coord, REPORT + H(1))
    assert coord.last_lock_sweep["freshness_signal"] == {GARAGE: "none"}


def test_no_real_report_ages_from_grace_end():
    boot = REPORT
    coord, states, _ = _make(boot=boot)
    states.set(GARAGE, "locked", changed=boot, reported=boot, name="Garage hallway lock")
    states.set(LS_GARAGE, boot.isoformat())
    states.set(NS_GARAGE, "alive")
    grace_end = boot + timedelta(seconds=600)
    assert _pages(_run(coord, grace_end + H(12) - timedelta(seconds=1))) == []
    assert len(_pages(_run(coord, grace_end + H(12) + timedelta(seconds=1)))) == 1


def test_common_mode_clears_when_one_lock_returns():
    coord, states, _ = _make(locks=(GARAGE, FRONT), reg=_registry(with_front=True))
    t = REPORT + H(1)
    states.set(GARAGE, "unavailable", name="Garage hallway lock")
    states.set(FRONT, "unavailable", name="Front door lock")
    _run(coord, t)
    assert len(_pages(_run(coord, t + timedelta(minutes=20)), "Locks offline together")) == 1
    _healthy_garage(states)
    _run(coord, t + timedelta(minutes=30))
    assert "paged_ts" not in coord._lock_freshness.record(fresh_mod.COMMON_KEY)
    states.set(GARAGE, "unavailable", name="Garage hallway lock")
    _run(coord, t + timedelta(minutes=40))
    acts = _run(coord, t + timedelta(minutes=60))
    assert len(_pages(acts, "Locks offline together")) == 1


def test_common_mode_restore_leaves_each_lock_unverified():
    coord, states, _ = _make(locks=(GARAGE, FRONT), reg=_registry(with_front=True))
    t = REPORT + H(1)
    states.set(GARAGE, "unavailable", name="Garage hallway lock")
    states.set(FRONT, "unavailable", name="Front door lock")
    states.set(NS_GARAGE, "alive")
    states.set(LS_GARAGE, REPORT.isoformat())
    states.set(LS_FRONT, REPORT.isoformat())
    _run(coord, t)
    assert len(_pages(_run(coord, t + timedelta(minutes=20)), "Locks offline together")) == 1
    _restore(coord, states, GARAGE, t + H(1), "Garage hallway lock")
    _restore(coord, states, FRONT, t + H(1), "Front door lock")
    acts = _run(coord, t + H(2))
    assert _pages(acts) == []  # inside R
    assert coord.last_lock_sweep["unverified"] == [FRONT, GARAGE]
    assert _lock_cmds(acts, GARAGE) == [] and _lock_cmds(acts, FRONT) == []
    again = _pages(_run(coord, t + timedelta(minutes=20) + H(6)))
    assert len(again) == 2 and all("back online" in p.message for p in again)
    # A real report clears that lock only.
    states.set(LS_GARAGE, (t + H(6.5)).isoformat())
    acts = _run(coord, t + H(7))
    clear = _pages(acts, "Lock reporting again")
    assert len(clear) == 1 and "Garage hallway lock" in clear[0].message
    assert coord.last_lock_sweep["unverified"] == [FRONT]


def test_signal_page_record_clears_when_enabled():
    reg = _registry(garage_ls_disabled=True)
    coord, states, _ = _make(reg=reg)
    _healthy_garage(states)
    _run(coord, BOOT + H(1))
    assert "signal_paged_ts" in coord._lock_freshness.record(GARAGE)
    reg.entries[LS_GARAGE].disabled_by = None
    _run(coord, BOOT + H(2))
    assert "signal_paged_ts" not in coord._lock_freshness.record(GARAGE)


def test_clear_requires_lock_not_dead():
    coord, states, _ = _make()
    _healthy_garage(states)
    _run(coord, REPORT + H(13))
    states.set(GARAGE, "unavailable")
    states.set(LS_GARAGE, (REPORT + H(13.5)).isoformat())
    acts = _run(coord, REPORT + H(14))
    assert _pages(acts, "Lock reporting again") == []
    assert coord._lock_freshness.record(GARAGE)["paged_kind"] == "stale"


def test_clear_pops_paged_kind():
    coord, states, _ = _make()
    _healthy_garage(states)
    _run(coord, REPORT + H(13))
    states.set(LS_GARAGE, (REPORT + H(13.5)).isoformat())
    _run(coord, REPORT + H(14))
    assert "paged_kind" not in coord._lock_freshness.record(GARAGE)


def test_excluded_zwave_lock_no_signal_page():
    coord, states, _ = _make(reg=_registry(garage_ls_disabled=True),
                             cm_opts={"security_lock_sweep_exclude": [GARAGE]})
    _healthy_garage(states)
    assert _pages(_run(coord, BOOT + H(1)), "Lock freshness signal disabled") == []


def test_naive_stamp_rejected():
    coord, states, _ = _make()
    _healthy_garage(states)
    states.set(LS_GARAGE, "2026-11-16T19:00:00")
    _run(coord, REPORT + H(13))
    assert coord._lock_freshness.record(GARAGE)["real_report_ts"] == REPORT.isoformat()


def test_negative_knob_falls_back_to_default():
    coord, states, _ = _make(cm_opts={"security_lock_stale_hours": -5})
    _healthy_garage(states)
    assert _pages(_run(coord, REPORT + H(11))) == []
    assert len(_pages(_run(coord, REPORT + H(13)))) == 1


def _scoped_import(name):
    saved = {k: v for k, v in sys.modules.items() if k.startswith("custom_components")}
    try:
        import importlib
        # Another file may have installed a stub package: import the real one.
        for k in [k for k in sys.modules if k.startswith("custom_components")]:
            del sys.modules[k]
        return importlib.import_module(name)
    finally:
        for k in [k for k in sys.modules if k.startswith("custom_components")]:
            del sys.modules[k]
        sys.modules.update(saved)


def test_numbers_wiring():
    number_mod = _scoped_import("custom_components.universal_room_automation.number")
    entry = SimpleNamespace(data={}, options={})
    nums = {n.entity_id: n for n in
            number_mod._build_security_lockout_numbers(MagicMock(), entry)}
    n = nums["number.ura_security_lock_stale_hours"]
    assert n._conf_key == "security_lock_stale_hours"
    assert n.native_value == 12.0 and n._attr_native_min_value == 0.0
    r = nums["number.ura_security_lock_dead_repage_hours"]
    assert r._conf_key == "security_lock_dead_repage_hours" and r.native_value == 6.0
    assert r._attr_native_min_value == 0.0


def test_knobs_on_both_reload_suppression_lists():
    pkg = _scoped_import("custom_components.universal_room_automation")
    for key in ("security_lock_stale_hours", "security_lock_dead_repage_hours"):
        assert key in pkg._NO_LIVE_ATTR_KEYS
        assert key in pkg.OPTIONS_RELOAD_SUPPRESS_KEYS


def test_sweep_sensor_exposes_freshness_attrs():
    coord, states, _ = _make()
    _healthy_garage(states)
    _run(coord, REPORT + H(13))
    sensor_mod = _scoped_import("custom_components.universal_room_automation.sensor")
    ent = sensor_mod.SecurityLastLockSweepSensor.__new__(
        sensor_mod.SecurityLastLockSweepSensor)
    ent.hass = SimpleNamespace(data={"universal_room_automation": {
        "coordinator_manager": SimpleNamespace(coordinators={"security": coord})}})
    attrs = ent.extra_state_attributes
    assert attrs["stale"] == [GARAGE]
    assert attrs["freshness_age_h"] == {GARAGE: 13.0}
    assert attrs["freshness_signal"] == {GARAGE: "last_seen"}


# ------------------------------------- SECURITY-LOCK-PAGE-LAST-SEEN-1 (display)
# Restart 10 h after the lock last reported; last_seen holds the genuine
# pre-boot Z-Wave stamp (REPORT). Lock stamps are boot-time restores.
BOOT_LS = REPORT + H(10)
GRACE_END_LS = BOOT_LS + timedelta(seconds=600)


def _preboot_garage(states, ls_value=REPORT.isoformat(), lock_state="locked"):
    states.set(GARAGE, lock_state, changed=BOOT_LS, reported=BOOT_LS,
               name="Garage hallway lock")
    states.set(LS_GARAGE, ls_value)
    states.set(NS_GARAGE, "alive")


def test_stale_page_shows_preboot_last_seen_age():
    coord, states, _ = _make(boot=BOOT_LS)
    _preboot_garage(states)
    now = GRACE_END_LS + H(13)          # REPORT + 23 h 10 min
    pages = _pages(_run(coord, now))
    assert len(pages) == 1
    assert "last seen 23 h ago (before restart)" in pages[0].message
    assert "since restart" in pages[0].message


def test_dead_page_shows_preboot_last_seen_age():
    coord, states, _ = _make(boot=BOOT_LS)
    _preboot_garage(states)
    states.set(NS_GARAGE, "dead")
    t = GRACE_END_LS + timedelta(minutes=1)
    acts = _run(coord, t) + _run(coord, t + timedelta(minutes=21))
    pages = _pages(acts)
    assert len(pages) == 1 and "node dead" in pages[0].message
    # Page at REPORT + 10 h 32 min -> "11 h".
    assert "last seen 11 h ago (before restart)" in pages[0].message
    assert "unknown. State" not in pages[0].message


def test_offline_page_shows_preboot_last_seen_age():
    coord, states, _ = _make(boot=BOOT_LS)
    _preboot_garage(states, lock_state="unavailable")
    t = GRACE_END_LS + timedelta(minutes=1)
    acts = _run(coord, t) + _run(coord, t + timedelta(minutes=21))
    pages = _pages(acts)
    assert len(pages) == 1 and "is offline" in pages[0].message
    assert "last seen 11 h ago (before restart)" in pages[0].message


@pytest.mark.parametrize(
    "case", ["disabled", "missing", "unparseable", "naive", "future"]
)
def test_offline_page_keeps_unknown_without_usable_last_seen(case):
    reg = _registry(garage_ls_disabled=(case == "disabled"))
    coord, states, _ = _make(boot=BOOT_LS, reg=reg)
    val = {
        "disabled": REPORT.isoformat(),
        "missing": "unknown",
        "unparseable": "not-a-date",
        "naive": "2026-11-16T07:37:00",
        # Review L1: a future-dated stamp must not word "last seen -N h ago".
        "future": (GRACE_END_LS + timedelta(days=1)).isoformat(),
    }[case]
    _preboot_garage(states, ls_value=val, lock_state="unavailable")
    t = GRACE_END_LS + timedelta(minutes=1)
    acts = _run(coord, t) + _run(coord, t + timedelta(minutes=21))
    pages = _pages(acts)
    assert len(pages) == 1
    assert "last report unknown. State unknown" in pages[0].message
    assert "last seen" not in pages[0].message


def test_preboot_last_seen_does_not_feed_freshness():
    """The display value must not leak into real_report_ts / age_h / stale."""
    def _snap(ls_value, now):
        coord, states, _ = _make(boot=BOOT_LS)
        _preboot_garage(states, ls_value=ls_value)
        _run(coord, now)
        sweep = coord.last_lock_sweep
        return (
            coord._lock_freshness.record(GARAGE).get("real_report_ts"),
            sweep["freshness_age_h"][GARAGE],
            sweep["stale"],
        )
    # grace_end + 11 h: a 21 h old pre-boot last_seen must NOT make it stale.
    early = GRACE_END_LS + H(11)
    assert _snap(REPORT.isoformat(), early) == (None, None, [])
    assert _snap(REPORT.isoformat(), early) == _snap("unavailable", early)
    late = GRACE_END_LS + H(13)
    assert _snap(REPORT.isoformat(), late) == (None, None, [GARAGE])
    assert _snap(REPORT.isoformat(), late) == _snap("unavailable", late)


def test_grace_window_last_seen_not_labelled_before_restart():
    """Review L2: a last_seen stamp after boot but inside the grace window is
    not a real report (real stays None) and is NOT before the restart."""
    coord, states, _ = _make(boot=BOOT_LS)
    _preboot_garage(
        states,
        ls_value=(BOOT_LS + timedelta(seconds=60)).isoformat(),
        lock_state="unavailable",
    )
    t = GRACE_END_LS + timedelta(minutes=1)
    acts = _run(coord, t) + _run(coord, t + timedelta(minutes=21))
    pages = _pages(acts)
    assert len(pages) == 1 and "last seen 1 h ago." in pages[0].message
    assert "(before restart)" not in pages[0].message
