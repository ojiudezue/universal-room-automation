"""NM-PERIMETER-REPEAT-STORM-1: unacked non-life-safety CRITICAL repeats stop
after the first hour when the house is home; away/vacation keep the ladder;
life-safety untouched; unknown house state keeps paging; knob 0 = legacy.

Drives the real repeat chain (async_notify -> _schedule_repeat ->
_repeat_alert) with a fake clock and a captured async_call_later.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from test_notification_manager import _make_hass, _make_config  # noqa: F401

from custom_components.universal_room_automation.const import (
    CONF_NM_PERSONS,
    CONF_NM_PERSON_DELIVERY_PREF,
    CONF_NM_PERSON_ENTITY,
    CONF_NM_PERSON_PUSHOVER_KEY,
    CONF_NM_PUSHOVER_ENABLED,
    CONF_NM_PUSHOVER_SEVERITY,
    CONF_NM_QUIET_USE_HOUSE_STATE,
    DOMAIN,
    NM_DELIVERY_IMMEDIATE,
)
from custom_components.universal_room_automation.domain_coordinators import (
    notification_manager as nm_mod,
)
from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
    AlertState,
    NotificationManager,
)
from custom_components.universal_room_automation.domain_coordinators.base import Severity

T0 = datetime(2026, 11, 16, 0, 0, 18, tzinfo=timezone.utc)


class _FakeDB:
    """Records log_notification kwargs; every other DB call is a no-op."""

    def __init__(self, active_row=None):
        self.rows: list[dict] = []
        self.cooldowns: list[tuple] = []
        self.acked = False
        self._active = active_row

    async def log_notification(self, *args, **kwargs):
        names = ["coordinator_id", "severity", "title", "message",
                 "hazard_type", "location", "person_id", "channel", "delivered"]
        row = dict(zip(names, args))
        row.update(kwargs)
        self.rows.append(row)
        if (row.get("severity") == "CRITICAL" and row.get("message") != "[audit]"
                and not row.get("acknowledged")):
            # an unacked page row, as get_active_critical would return it
            self._active = dict(row, id=len(self.rows),
                                timestamp=nm_mod.dt_util.utcnow().isoformat())
        return len(self.rows)

    async def get_active_critical(self):
        return self._active

    async def acknowledge_notification(self, **_kw):
        # Real DB: acks only the newest slot row; sibling per-channel rows
        # stay unacked until acknowledge_matching_notifications.
        self.acked = True
        return 7

    async def acknowledge_matching_notifications(self, *_a):
        self._active = None

    async def set_cooldown(self, row_id, expires):
        self.cooldowns.append((row_id, expires))

    async def get_active_cooldown(self):
        if not self.cooldowns:
            return None
        return {"id": self.cooldowns[-1][0], "cooldown_expires": self.cooldowns[-1][1],
                "hazard_type": "exterior_person", "location": "front_yard"}

    async def get_notifications_today(self):
        return []

    def __getattr__(self, name):
        return AsyncMock(return_value=None)


def _cfg():
    return _make_config(**{
        CONF_NM_PUSHOVER_ENABLED: True,
        CONF_NM_PUSHOVER_SEVERITY: "LOW",
        CONF_NM_QUIET_USE_HOUSE_STATE: True,
        CONF_NM_PERSONS: [{
            CONF_NM_PERSON_ENTITY: "person.oji",
            CONF_NM_PERSON_PUSHOVER_KEY: "pk_oji",
            CONF_NM_PERSON_DELIVERY_PREF: NM_DELIVERY_IMMEDIATE,
        }],
    })


class _Rig:
    def __init__(self, monkeypatch, house_state, db=None):
        self.now = [T0]
        self.delays: list[float] = []
        monkeypatch.setattr(nm_mod.dt_util, "utcnow", lambda: self.now[0])

        self.handles: list[MagicMock] = []

        def _call_later(_hass, delay, _cb):
            self.delays.append(delay)
            self.handles.append(MagicMock())
            return self.handles[-1]

        monkeypatch.setattr(nm_mod, "async_call_later", _call_later)
        self.hass = _make_hass()
        if house_state is not None:
            cm = MagicMock()
            cm.house_state = house_state
            self.hass.data[DOMAIN]["coordinator_manager"] = cm
        self.db = db if db is not None else _FakeDB()
        self.hass.data[DOMAIN]["database"] = self.db
        nm = NotificationManager(self.hass, _cfg())
        nm._send_pushover = AsyncMock()
        nm._send_companion = AsyncMock()
        nm._send_whatsapp = AsyncMock()
        nm._send_imessage = AsyncMock()
        nm._send_tts = AsyncMock()
        self.nm = nm

    async def arm(self, hazard="exterior_person"):
        await self.nm.async_notify(
            "perimeter_alert", Severity.CRITICAL, "Perimeter Alert",
            "Person on porch", hazard_type=hazard, location="front_yard",
        )
        self.nm._send_pushover.reset_mock()

    async def tick(self):
        """Advance the fake clock by the scheduled delay and fire it."""
        self.now[0] = self.now[0] + timedelta(seconds=self.delays[-1])
        await self.nm._repeat_alert()

    def resends(self):
        return self.nm._send_pushover.await_count

    def rows(self, reason):
        return [r for r in self.db.rows if r.get("route_reason") == reason]


@pytest.mark.asyncio
async def test_home_stops_after_first_hour(monkeypatch):
    rig = _Rig(monkeypatch, "home_day")
    await rig.arm()
    for _ in range(11):  # ticks at 300 .. 3300 s
        await rig.tick()
    assert rig.resends() == 11
    assert rig.nm.alert_state == AlertState.REPEATING
    await rig.tick()  # t = 3600 s -> cap
    assert rig.resends() == 11
    # same end state as an ack: COOLDOWN, exterior_person default 10 min
    assert rig.nm.alert_state == AlertState.COOLDOWN
    assert rig.nm._cooldown_remaining == 600
    assert rig.delays[-1] == 600  # cooldown expiry timer, not a repeat
    assert rig.db.acked is True
    assert rig.db.cooldowns == [(7, (T0 + timedelta(seconds=4200)).isoformat())]
    # the pending repeat handle is cancelled (no timer left armed)
    rig.handles[-2].assert_called_once_with()
    assert rig.nm._repeat_unsub is None
    # a stray repeat tick is a no-op (state is not REPEATING)
    await rig.nm._repeat_alert()
    assert rig.resends() == 11
    capped = rig.rows("repeat_capped_home")
    assert len(capped) == 1
    assert capped[0]["bucket_outcome"] == "repeat_capped_home"
    assert capped[0]["acknowledged"] == 1
    digest = [r for r in rig.db.rows if r.get("channel") == "digest"]
    assert len(digest) == 1
    assert digest[0]["person_id"] == "person.oji"
    assert digest[0]["severity"] == "MEDIUM"
    assert digest[0]["delivered"] == 0
    assert "home_day" in digest[0]["message"]


@pytest.mark.asyncio
async def test_home_boundary_3599_sends_3600_caps(monkeypatch):
    rig = _Rig(monkeypatch, "home_evening")
    await rig.arm()
    rig.now[0] = T0 + timedelta(seconds=3599)
    await rig.nm._repeat_alert()
    assert rig.resends() == 1
    assert rig.nm.alert_state == AlertState.REPEATING
    rig.now[0] = T0 + timedelta(seconds=3600)
    await rig.nm._repeat_alert()
    assert rig.resends() == 1
    assert rig.nm.alert_state == AlertState.COOLDOWN


@pytest.mark.parametrize("state", ["away", "vacation"])
@pytest.mark.asyncio
async def test_away_continues_at_1800(monkeypatch, state):
    rig = _Rig(monkeypatch, state)
    await rig.arm()
    for _ in range(12):
        await rig.tick()
    assert rig.resends() == 12
    assert rig.delays[-1] == 1800
    for _ in range(3):
        await rig.tick()
    assert rig.resends() == 15
    assert rig.nm.alert_state == AlertState.REPEATING
    assert rig.rows("repeat_capped_home") == []


@pytest.mark.parametrize("state", [None, "", "unknown"])
@pytest.mark.asyncio
async def test_unknown_house_state_keeps_paging(monkeypatch, state):
    rig = _Rig(monkeypatch, state)
    await rig.arm()
    for _ in range(14):
        await rig.tick()
    assert rig.resends() == 14
    assert rig.delays[-1] == 1800
    assert rig.nm.alert_state == AlertState.REPEATING
    assert rig.rows("repeat_capped_home") == []


@pytest.mark.parametrize("hazard,interval", [("intruder", 30), ("smoke", 1800)])
@pytest.mark.asyncio
async def test_life_safety_never_capped_at_home(monkeypatch, hazard, interval):
    rig = _Rig(monkeypatch, "home_day")
    await rig.arm(hazard)
    # jump the page to 2 h old, home: life-safety still pages
    rig.now[0] = T0 + timedelta(seconds=7200)
    await rig.nm._repeat_alert()
    await rig.nm._repeat_alert()
    assert rig.resends() == 2
    assert rig.delays[-1] == interval
    assert rig.nm.alert_state == AlertState.REPEATING
    assert rig.rows("repeat_capped_home") == []


@pytest.mark.asyncio
async def test_knob_zero_is_legacy(monkeypatch):
    monkeypatch.setattr(nm_mod, "NM_REPEAT_HOME_CAP_S", 0)
    rig = _Rig(monkeypatch, "home_day")
    await rig.arm()
    for _ in range(14):
        await rig.tick()
    assert rig.resends() == 14
    assert rig.delays[-1] == 1800
    assert rig.nm.alert_state == AlertState.REPEATING


@pytest.mark.asyncio
async def test_each_resend_logs_one_numbered_row(monkeypatch):
    rig = _Rig(monkeypatch, "away")
    await rig.arm()
    for _ in range(3):
        await rig.tick()
    rows = rig.rows("repeat")
    assert [r["matrix_branch"] for r in rows] == ["repeat_1", "repeat_2", "repeat_3"]
    assert all(r["acknowledged"] == 1 for r in rows)
    assert all(r["channel"] == "pushover" for r in rows)
    assert all(r["delivered"] == 1 for r in rows)
    assert all(r["message"] == "[audit]" for r in rows)


@pytest.mark.asyncio
async def test_ack_still_ends_repeat(monkeypatch):
    rig = _Rig(monkeypatch, "away")
    await rig.arm()
    await rig.tick()
    await rig.nm.async_acknowledge(safe_word_verified=True)
    assert rig.nm.alert_state != AlertState.REPEATING
    before = rig.resends()
    await rig.nm._repeat_alert()
    assert rig.resends() == before


@pytest.mark.parametrize("state,capped", [("home_day", True), ("away", False)])
@pytest.mark.asyncio
async def test_restored_page_follows_same_rule(monkeypatch, state, capped):
    row = {
        "id": 7,
        "coordinator_id": "perimeter_alert", "title": "Perimeter Alert",
        "message": "Person on porch", "hazard_type": "exterior_person",
        "location": "front_yard", "timestamp": T0.isoformat(),
    }
    rig = _Rig(monkeypatch, state, db=_FakeDB(active_row=row))
    rig.now[0] = T0 + timedelta(seconds=7200)
    await rig.nm._recover_state_from_db()
    assert rig.nm.alert_state == AlertState.REPEATING
    await rig.tick()
    if capped:
        assert rig.resends() == 0
        assert rig.nm.alert_state == AlertState.COOLDOWN
        assert len(rig.rows("repeat_capped_home")) == 1
    else:
        assert rig.resends() == 1
        assert rig.nm.alert_state == AlertState.REPEATING


@pytest.mark.asyncio
async def test_restart_after_cap_does_not_recap_or_resend(monkeypatch):
    rig = _Rig(monkeypatch, "home_day")
    await rig.arm()
    rig.now[0] = T0 + timedelta(seconds=3600)
    await rig.nm._repeat_alert()
    assert rig.nm.alert_state == AlertState.COOLDOWN
    # restart: fresh NM on the same DB, 5 min into the cooldown
    rig.now[0] = T0 + timedelta(seconds=3900)
    nm2 = NotificationManager(rig.hass, _cfg())
    nm2._send_pushover = AsyncMock()
    await nm2._recover_state_from_db()
    assert nm2.alert_state == AlertState.COOLDOWN
    await nm2._repeat_alert()
    assert nm2._send_pushover.await_count == 0
    assert len(rig.rows("repeat_capped_home")) == 1


@pytest.mark.asyncio
async def test_new_critical_in_cooldown_follows_existing_rule(monkeypatch):
    """Existing rule (notification_manager.py _enter_alerting, "Cancel any
    existing cooldown/countdown from a previous alert"): COOLDOWN does not
    block a new CRITICAL; it cancels the cooldown and starts a new chain.
    The cap inherits exactly what an ack does today."""
    rig = _Rig(monkeypatch, "home_day")
    await rig.arm()
    rig.now[0] = T0 + timedelta(seconds=3600)
    await rig.nm._repeat_alert()
    assert rig.nm.alert_state == AlertState.COOLDOWN
    rig.now[0] = T0 + timedelta(seconds=3700)  # past the 60 s CRITICAL dedup
    await rig.arm()
    assert rig.nm.alert_state == AlertState.REPEATING
    assert rig.nm._cooldown_remaining == 0
    assert rig.delays[-1] == 300
