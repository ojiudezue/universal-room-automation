"""Halo S1b — NM wall-panel channel (WALLPANEL-URA-NOTIFY-1).

Plan: docs/planning/PLANNING_wallpanel_integration.md §S1b + "Plan review
(S1b), 2026-10-24" (H1, H2, M1-M4, L1-L5).

Drives the REAL NotificationManager (async_notify, _repeat_alert,
_enter_alerting, async_acknowledge, _re_evaluate_hazard,
async_suppress_messaging, async_teardown) against a fake hass whose
``services`` play Halo: ``halo.indicate`` answers per area exactly like
Halo's ``async_indicate`` (accepted / no_surface / unavailable), and every
call lands in an ordered call log that all ordering assertions read.

Oracles are literals from the plan / Halo contract (area ids, lease ids
``ura:safety:water_leak:kitchen``, level names, TTL 1800 s), never re-derived
from the code under test.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_safety_nm_refire import (  # noqa: F401  (clock is a fixture)
    AlertState,
    clock,
    nm_mod,
)
import test_notification_manager as _tnm

Severity = nm_mod.Severity
DOMAIN = _tnm.DOMAIN


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class ServiceNotFound(Exception):
    """Name-matched like homeassistant.exceptions.ServiceNotFound."""


class FakeServices:
    """Plays Halo. ``surfaces`` = areas with a panel; others -> no_surface."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.has_service_calls: list[tuple[str, str]] = []
        self.halo_installed = True
        self.surfaces: set[str] = set()
        self.unavailable: set[str] = set()
        self.gate: asyncio.Event | None = None  # block halo calls until set
        self.gate_service: str | None = None

    def has_service(self, domain, service):
        self.has_service_calls.append((domain, service))
        return domain == "halo" and self.halo_installed

    async def async_call(self, domain, service, data=None, blocking=False,
                         return_response=False, **_kw):
        data = dict(data or {})
        self.calls.append((domain, service, data))
        if domain != "halo":
            return None
        assert blocking is True and return_response is True
        if not self.halo_installed:
            raise ServiceNotFound(f"{domain}.{service}")
        if self.gate is not None and (
            self.gate_service is None or self.gate_service == service
        ):
            await self.gate.wait()
        if service == "indicate":
            out = {}
            for a in data["area_id"]:
                if a in self.unavailable:
                    out[a] = "unavailable"
                elif a in self.surfaces:
                    out[a] = "accepted"
                else:
                    out[a] = "no_surface"
            return out
        return {"released": 1}

    def halo(self, service=None):
        return [(s, d) for (dom, s, d) in self.calls
                if dom == "halo" and (service is None or s == service)]


class FakeBus:
    def __init__(self) -> None:
        self.listeners: dict[str, list] = {}

    def async_listen(self, event, cb):
        self.listeners.setdefault(event, []).append(cb)

        def _unsub():
            self.listeners[event].remove(cb)
        return _unsub

    def fire(self, event, data=None):
        for cb in list(self.listeners.get(event, [])):
            cb(SimpleNamespace(event_type=event, data=data or {}))


class FakeRoom:
    def __init__(self, title, area, occupied=False, room_name=None, entry_id=None):
        self.entry = SimpleNamespace(
            title=title,
            # MappingProxyType like a real ConfigEntry.data.
            data=MappingProxyType({
                "entry_type": "room",
                "room_name": title if room_name is None else room_name,
            }),
            entry_id=entry_id or f"eid_{title.lower().replace(' ', '_')}",
        )
        self._area = area
        self.data = {"occupied": occupied}

    def _get_room_area(self):
        return self._area


class FakePresence:
    """Forward-only adjacency (like _rebuild_adjacency_cache) + zone map."""

    def __init__(self, adjacency=None, zones=None):
        self.adjacency = adjacency or {}
        self.zones = zones or {}

    def get_adjacent_rooms(self, room):
        return list(self.adjacency.get(room, []))

    def get_room_zone(self, room):
        return self.zones.get(room)


class Hass:
    def __init__(self) -> None:
        self.services = FakeServices()
        self.bus = FakeBus()
        self.data = {DOMAIN: {}}
        self.states = SimpleNamespace(get=lambda _e: None)
        self.tasks: list[asyncio.Task] = []

    def async_create_background_task(self, coro, name, eager_start=True):
        t = asyncio.get_running_loop().create_task(coro, name=name)
        self.tasks.append(t)
        return t

    def async_create_task(self, coro, *a, **k):
        # Non-panel NM tasks (cooldown countdown loop) are out of scope here.
        coro.close()
        return None

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


def _panel_pending(hass):
    return [t for t in hass.tasks
            if t.get_name().startswith("ura_nm_panel") and not t.done()]


async def settle(hass, rounds=50):
    """Drain panel tasks only (NM's cooldown countdown loops forever).

    Tasks are awaited directly (no exception swallowing): a crash inside a
    panel task fails the test.
    """
    for _ in range(rounds):
        await asyncio.sleep(0)
        pending = _panel_pending(hass)
        if not pending:
            await asyncio.sleep(0)
            if not _panel_pending(hass):
                break
            continue
        await asyncio.wait_for(asyncio.gather(*pending), timeout=5)
    for t in hass.tasks:
        if t.get_name().startswith("ura_nm_panel") and t.done() and not t.cancelled():
            exc = t.exception()
            if exc is not None:
                raise exc


# Standard house: Kitchen (zone A), Breakfast Nook (zone A), Media (adjacent
# listed only on Media -> Kitchen), Master (zone B, not adjacent), Garage
# (no area).
def standard_rooms(**occ):
    return [
        FakeRoom("Kitchen", "kitchen", occ.get("Kitchen", False)),
        FakeRoom("Breakfast Nook", "breakfast_nook", occ.get("Breakfast Nook", False)),
        FakeRoom("Media", "media", occ.get("Media", False)),
        FakeRoom("Master", "master", occ.get("Master", False)),
        FakeRoom("Garage", None, occ.get("Garage", False)),
    ]


STANDARD_PRESENCE = dict(
    adjacency={"Media": ["Kitchen"]},
    zones={"Kitchen": "A", "Breakfast Nook": "A", "Master": "B", "Media": "C"},
)


class PanelRig:
    def __init__(self, monkeypatch, clock, rooms=None, presence=None,
                 house_state="home_day", config=None):
        self.clock = clock
        self.hass = Hass()
        self.db = AsyncMock()
        self.db.get_active_critical = AsyncMock(return_value={"id": 1})
        self.db.get_active_cooldown = AsyncMock(return_value=None)
        self.db.acknowledge_notification = AsyncMock(return_value=None)
        self.hass.data[DOMAIN]["database"] = self.db
        self.presence = FakePresence(**(presence or STANDARD_PRESENCE))
        self.hazard_active = True
        self.cm = SimpleNamespace(
            house_state=house_state,
            coordinators={
                "presence": self.presence,
                "safety": SimpleNamespace(
                    is_hazard_active=lambda h, l: self.hazard_active),
            },
        )
        self.hass.data[DOMAIN]["coordinator_manager"] = self.cm
        self.rooms = rooms if rooms is not None else standard_rooms(Kitchen=True)
        for r in self.rooms:
            self.hass.data[DOMAIN][r.entry.entry_id] = r
        self.hass.services.surfaces = {"kitchen", "breakfast_nook", "media", "master"}
        self.nm = nm_mod.NotificationManager(self.hass, config or _tnm._make_config())
        self.later: list[tuple[float, object]] = []
        monkeypatch.setattr(
            nm_mod, "async_call_later",
            lambda _h, delay, cb: (self.later.append((delay, cb)), lambda: None)[1],
        )
        monkeypatch.setattr(nm_mod, "async_dispatcher_send", lambda *a, **k: None)
        monkeypatch.setattr(self.nm, "_refresh_config", lambda: None)

    def set_occupied(self, **occ):
        for r in self.rooms:
            r.data["occupied"] = occ.get(r.entry.title, False)

    async def enable(self):
        await self.nm.async_set_panel_channel_enabled(True)
        await settle(self.hass)

    async def notify(self, coordinator_id="safety", severity=Severity.CRITICAL,
                     hazard_type="water_leak", location="Kitchen", title="Leak"):
        await self.nm.async_notify(
            coordinator_id=coordinator_id, severity=severity, title=title,
            message=f"{title} msg", hazard_type=hazard_type, location=location,
        )
        await settle(self.hass)

    def indicates(self):
        return [d for s, d in self.hass.services.halo("indicate")]

    def releases(self):
        return [d for s, d in self.hass.services.halo("release")]

    def panel_rows(self):
        out = []
        for c in self.db.log_notification.await_args_list:
            kw = dict(c.kwargs)
            ch = c.args[7] if len(c.args) > 7 else kw.get("channel")
            if ch == "panels":
                out.append((c.args, kw))
        return out


@pytest.fixture
def rig(monkeypatch, clock):
    return PanelRig(monkeypatch, clock)


def areas(rig, **kw):
    return rig.nm._panel_target_areas(
        kw.get("coordinator_id", "safety"), kw.get("hazard_type", "water_leak"),
        kw.get("location", None),
    )


# ---------------------------------------------------------------------------
# D-S1b-1 targeting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_target_own_room(monkeypatch, clock):
    r = PanelRig(monkeypatch, clock, rooms=standard_rooms(Master=True),
                 presence=dict(adjacency={}, zones={}))
    assert areas(r, coordinator_id="security", hazard_type="intruder") == ["master"]


@pytest.mark.asyncio
async def test_target_occupied_zone(monkeypatch, clock):
    r = PanelRig(monkeypatch, clock, rooms=standard_rooms(Kitchen=True),
                 presence=dict(adjacency={}, zones=STANDARD_PRESENCE["zones"]))
    assert areas(r, coordinator_id="security", hazard_type="intruder") == [
        "breakfast_nook", "kitchen"]
    # Kill switch drops the zone term.
    monkeypatch.setattr(nm_mod, "NM_PANEL_TARGET_ZONE_ENABLED", False)
    assert areas(r, coordinator_id="security", hazard_type="intruder") == ["kitchen"]


@pytest.mark.asyncio
async def test_target_adjacent_both_directions(monkeypatch, clock):
    # Adjacency configured only on Media -> Kitchen.
    r = PanelRig(monkeypatch, clock, rooms=standard_rooms(Kitchen=True),
                 presence=dict(adjacency={"Media": ["Kitchen"]}, zones={}))
    # Kitchen occupied -> Media targeted (reverse direction: Media lists Kitchen).
    assert areas(r, coordinator_id="security", hazard_type="intruder") == [
        "kitchen", "media"]
    # Forward direction: Media occupied -> Kitchen targeted.
    r.set_occupied(Media=True)
    assert areas(r, coordinator_id="security", hazard_type="intruder") == [
        "kitchen", "media"]
    # Master is never targeted.
    monkeypatch.setattr(nm_mod, "NM_PANEL_TARGET_ADJACENT_ENABLED", False)
    assert areas(r, coordinator_id="security", hazard_type="intruder") == ["media"]


@pytest.mark.asyncio
async def test_target_plan_example_audience(monkeypatch, clock):
    """Plan D-S1b-1 Verify #1: kitchen, nook, media; never master."""
    r = PanelRig(monkeypatch, clock, rooms=standard_rooms(Kitchen=True))
    assert areas(r, coordinator_id="security", hazard_type="intruder") == [
        "breakfast_nook", "kitchen", "media"]


@pytest.mark.asyncio
async def test_target_source_room_safety_only(monkeypatch, clock):
    r = PanelRig(monkeypatch, clock, rooms=standard_rooms(),  # nobody home
                 presence=dict(adjacency={}, zones={}))
    assert areas(r, coordinator_id="safety", location="Master") == ["master"]
    # Multi-room ", " location (safety.py joins with ", ").
    assert areas(r, coordinator_id="safety", location="Kitchen, Master") == [
        "kitchen", "master"]
    # Security never gets T4.
    assert areas(r, coordinator_id="security", hazard_type="intruder",
                 location="Master") == []
    monkeypatch.setattr(nm_mod, "NM_PANEL_TARGET_SOURCE_ROOM_ENABLED", False)
    assert areas(r, coordinator_id="safety", location="Master") == []


@pytest.mark.asyncio
async def test_housewide_ignores_occupancy(monkeypatch, clock):
    r = PanelRig(monkeypatch, clock, rooms=standard_rooms())  # nobody home
    await r.enable()
    await r.notify(hazard_type="smoke", location="Garage", title="Smoke")
    assert r.indicates()[0]["area_id"] == [
        "breakfast_nook", "kitchen", "master", "media"]
    assert r.indicates()[0]["level"] == "critical"
    assert r.indicates()[0]["id"] == "ura:safety:smoke:garage"


@pytest.mark.asyncio
async def test_empty_audience_no_call(monkeypatch, clock):
    r = PanelRig(monkeypatch, clock, rooms=standard_rooms())  # nobody home
    await r.enable()
    await r.notify(coordinator_id="security", hazard_type="intruder",
                   location="house", title="Intruder")
    # Safety leak in a room with no area + nobody home -> also nothing.
    await r.notify(hazard_type="water_leak", location="Garage")
    assert r.indicates() == []
    assert r.panel_rows() == []


@pytest.mark.asyncio
async def test_room_name_differs_from_title(monkeypatch, clock):
    # room_name "Den" vs title "Den (Office)"; adjacency/zone keyed by
    # room_name. Third room has an EMPTY room_name -> keyed by title for
    # adjacency, and its zone is keyed by entry_id (L3 fallback).
    den = FakeRoom("Den (Office)", "den", True, room_name="Den")
    hall = FakeRoom("Hall", "hall", False)
    loft = FakeRoom("Loft", "loft", False, room_name="", entry_id="eid_loft")
    r = PanelRig(monkeypatch, clock, rooms=[den, hall, loft], presence=dict(
        adjacency={"Hall": ["Den"]}, zones={"Den": "Z", "eid_loft": "Z"}))
    assert areas(r, coordinator_id="security", hazard_type="intruder") == [
        "den", "hall", "loft"]


@pytest.mark.asyncio
async def test_room_without_area_dropped(monkeypatch, clock):
    r = PanelRig(monkeypatch, clock, rooms=standard_rooms(Garage=True),
                 presence=dict(adjacency={"Garage": ["Media"]}, zones={}))
    assert areas(r, coordinator_id="security", hazard_type="intruder") == ["media"]


# ---------------------------------------------------------------------------
# D-S1b-2 sender, gating, placement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_panel_channel_off_is_noop(rig):
    await rig.notify()  # switch never turned on
    assert rig.hass.services.halo() == []
    assert rig.hass.services.has_service_calls == []
    assert rig.hass.bus.listeners.get("halo_ready", []) == []
    assert rig.panel_rows() == []
    # Only the pre-existing pushover channel wrote a delivery row.
    chans = {c.args[7] for c in rig.db.log_notification.await_args_list
             if len(c.args) > 7}
    assert chans == {"pushover"}
    # No panel task was even spawned, and dry-run (which short-circuits
    # before targeting) writes no panels row while the switch is off.
    assert not [t for t in rig.hass.tasks if t.get_name().startswith("ura_nm_panel")]
    rig.nm._dry_run_active = True
    await rig.notify(hazard_type="h2")
    assert not [c for c in rig.db.log_notification.await_args_list
                if c.kwargs.get("channel") == "panels"]
    # Release sites are silent too while off: ack, re-eval, kill switch.
    await rig.nm.async_acknowledge()
    rig.hazard_active = False
    await rig.nm._re_evaluate_hazard()
    await rig.nm.async_suppress_messaging()
    await settle(rig.hass)
    assert rig.hass.services.halo() == []
    assert not [t for t in rig.hass.tasks if t.get_name().startswith("ura_nm_panel")]


@pytest.mark.asyncio
async def test_switch_off_while_delivery_queued_sends_nothing(rig):
    await rig.enable()
    await rig.nm._panel_lock.acquire()  # a delivery is "in front"
    try:
        assert rig.nm._schedule_panel_delivery(
            "safety", Severity.CRITICAL, "Leak", "m", "water_leak", "Kitchen")
        rig.hass.bus.fire("halo_ready", {})  # a queued re-assert too
        await asyncio.sleep(0)
        rig.nm._panel_channel_enabled = False
    finally:
        rig.nm._panel_lock.release()
    await settle(rig.hass)
    assert rig.indicates() == []
    assert rig.nm._panel_leases == {}


@pytest.mark.asyncio
async def test_halo_ready_queued_then_switch_off_sends_nothing(rig):
    await rig.enable()
    await rig.notify()  # ledger holds the leak lease; NM REPEATING
    rig.hass.services.calls.clear()
    await rig.nm._panel_lock.acquire()
    try:
        rig.hass.bus.fire("halo_ready", {})
        await asyncio.sleep(0)
        rig.nm._panel_channel_enabled = False
    finally:
        rig.nm._panel_lock.release()
    await settle(rig.hass)
    assert rig.indicates() == []


@pytest.mark.asyncio
async def test_panels_bypass_quiet_hours(monkeypatch, clock):
    r = PanelRig(monkeypatch, clock, house_state="home_night")
    await r.enable()
    # Non-life-safety safety HIGH: quiet hours suppress push/TTS for it.
    await r.notify(severity=Severity.HIGH, hazard_type="high_humidity",
                   location="Kitchen")
    assert [d["id"] for d in r.indicates()] == ["ura:safety:high_humidity:kitchen"]
    assert r.indicates()[0]["level"] == "alert"
    # TTS/push suppressed by quiet hours (HIGH, no bypass): no notify.* call.
    assert [c for c in r.hass.services.calls if c[0] != "halo"] == []


@pytest.mark.asyncio
async def test_night_gate_safety_only(monkeypatch, clock):
    r = PanelRig(monkeypatch, clock, house_state="home_night")
    await r.enable()
    # Security lock-check MEDIUM at night -> nothing.
    await r.notify(coordinator_id="security", severity=Severity.MEDIUM,
                   hazard_type="lock_check", location=None, title="Lock")
    assert r.indicates() == []
    # Intruder (life-safety) at night -> alert.
    await r.notify(coordinator_id="security", severity=Severity.HIGH,
                   hazard_type="intruder", location=None, title="Intruder")
    assert [(d["id"], d["level"]) for d in r.indicates()] == [
        ("ura:security:intruder:house", "alert")]
    # Same lock-check by day -> sent at warn.
    r.cm.house_state = "home_day"
    await r.notify(coordinator_id="security", severity=Severity.MEDIUM,
                   hazard_type="lock_check", location=None, title="Lock")
    assert r.indicates()[-1]["level"] == "warn"


@pytest.mark.asyncio
async def test_night_gate_sleep_state_and_safety_coordinator(monkeypatch, clock):
    r = PanelRig(monkeypatch, clock, house_state="SLEEP")  # coercion (L5)
    await r.enable()
    await r.notify(coordinator_id="security", severity=Severity.HIGH,
                   hazard_type="door_ajar", location=None, title="Door")
    assert r.indicates() == []
    # Safety coordinator passes at night even for a non-life-safety hazard.
    await r.notify(coordinator_id="safety", severity=Severity.HIGH,
                   hazard_type="high_humidity", location="Kitchen", title="Hum")
    assert [d["id"] for d in r.indicates()] == [
        "ura:safety:high_humidity:kitchen"]


@pytest.mark.asyncio
async def test_coordinator_allowlist(rig, monkeypatch):
    await rig.enable()
    for coord in ("hvac", "perimeter", "perimeter_alert", "energy", "optimization"):
        for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM):
            await rig.notify(coordinator_id=coord, severity=sev,
                             hazard_type="intruder", location="Kitchen")
    assert rig.indicates() == []
    # The allowlist gates on its own: even with a level mapped for hvac, an
    # hvac notify never reaches a panel.
    monkeypatch.setattr(nm_mod, "NM_PANEL_LEVEL_MAP", {
        **nm_mod.NM_PANEL_LEVEL_MAP, "hvac": {"CRITICAL": "critical"}})
    await rig.notify(coordinator_id="hvac", hazard_type="intruder", location="Kitchen")
    assert rig.indicates() == []
    # ...while a listed coordinator still does (the map patch is live).
    await rig.notify(coordinator_id="safety", hazard_type="h1", location="Kitchen")
    assert [d["id"] for d in rig.indicates()] == ["ura:safety:h1:kitchen"]


@pytest.mark.asyncio
async def test_level_map(rig):
    await rig.enable()
    expected = [
        ("safety", Severity.CRITICAL, "critical"),
        ("safety", Severity.HIGH, "alert"),
        ("safety", Severity.MEDIUM, "alert"),
        ("security", Severity.CRITICAL, "alert"),
        ("security", Severity.HIGH, "alert"),
        ("security", Severity.MEDIUM, "warn"),
    ]
    for i, (coord, sev, level) in enumerate(expected):
        await rig.notify(coordinator_id=coord, severity=sev,
                         hazard_type=f"h{i}", location="Kitchen")
        assert rig.indicates()[-1]["level"] == level, (coord, sev)
    n = len(rig.indicates())
    for coord in ("safety", "security"):
        await rig.notify(coordinator_id=coord, severity=Severity.LOW,
                         hazard_type="low", location="Kitchen")
    assert len(rig.indicates()) == n


@pytest.mark.asyncio
async def test_indicate_payload_contract(rig):
    await rig.enable()
    await rig.notify()
    assert rig.indicates() == [{
        "area_id": ["breakfast_nook", "kitchen", "media"],
        "owner": "ura",
        "id": "ura:safety:water_leak:kitchen",
        "level": "critical",
        "ttl_s": 1800,
    }]
    rows = rig.panel_rows()
    assert len(rows) == 1
    args, kw = rows[0]
    assert args[:9] == ("safety", "CRITICAL", "Leak", "Leak msg", "water_leak",
                        "Kitchen", None, "panels", 1)
    assert kw == {"acknowledged": 1}


@pytest.mark.asyncio
async def test_ttl_number_and_clamp(rig):
    await rig.enable()
    rig.nm.set_panel_lease_ttl_min(5)
    await rig.notify()
    assert rig.indicates()[-1]["ttl_s"] == 300
    rig.nm.set_panel_lease_ttl_min(0.05)  # 3 s -> Halo floor 10
    await rig.notify(hazard_type="h2")
    assert rig.indicates()[-1]["ttl_s"] == 10
    rig.nm.set_panel_lease_ttl_min(100000)  # -> Halo ceiling 86400
    await rig.notify(hazard_type="h3")
    assert rig.indicates()[-1]["ttl_s"] == 86400


@pytest.mark.asyncio
async def test_dry_run_panels(rig):
    await rig.enable()
    rig.nm._dry_run_active = True
    await rig.notify()
    assert rig.hass.services.halo() == []
    dry = [c for c in rig.db.log_notification.await_args_list
           if c.kwargs.get("channel") == "panels"]
    assert len(dry) == 1
    assert dry[0].kwargs["dry_run"] == 1
    assert dry[0].kwargs["acknowledged"] == 1
    assert dry[0].kwargs["hazard_type"] == "water_leak"


@pytest.mark.asyncio
async def test_sender_does_not_block_other_channels(rig, monkeypatch):
    monkeypatch.setattr(nm_mod, "NM_PANEL_CALL_TIMEOUT_S", 30)
    await rig.enable()
    rig.hass.services.gate = asyncio.Event()  # Halo hangs
    await asyncio.wait_for(rig.nm.async_notify(
        coordinator_id="safety", severity=Severity.CRITICAL, title="Leak",
        message="m", hazard_type="water_leak", location="Kitchen",
    ), timeout=2)
    # Pushover went out while the halo indicate is still pending.
    assert any(c[0] == "notify" for c in rig.hass.services.calls)
    pending = _panel_pending(rig.hass)
    assert pending
    rig.hass.services.gate.set()
    await settle(rig.hass)


@pytest.mark.asyncio
async def test_call_timeout_marks_health(rig, monkeypatch):
    monkeypatch.setattr(nm_mod, "NM_PANEL_CALL_TIMEOUT_S", 0.05)
    await rig.enable()
    rig.hass.services.gate = asyncio.Event()  # never set
    await rig.nm.async_notify(
        coordinator_id="safety", severity=Severity.CRITICAL, title="Leak",
        message="m", hazard_type="water_leak", location="Kitchen",
    )
    await asyncio.sleep(0.2)
    await settle(rig.hass)
    h = rig.nm.channel_status["panels"]
    assert h["status"] == "error"
    assert "timeout" in h["detail"]
    assert rig.panel_rows() == []


@pytest.mark.asyncio
async def test_panels_respect_operator_silence(rig):
    await rig.enable()
    rig.nm._silence_until = rig.clock() + timedelta(minutes=30)
    await rig.notify(coordinator_id="security", severity=Severity.HIGH,
                     hazard_type="door_ajar", location=None)
    assert rig.indicates() == []
    # CRITICAL still passes during silence (same predicate as async_notify).
    await rig.notify(coordinator_id="security", severity=Severity.CRITICAL,
                     hazard_type="intruder", location=None)
    assert [d["id"] for d in rig.indicates()] == ["ura:security:intruder:house"]
    # Expired silence -> HIGH passes.
    rig.clock.advance(31 * 60)
    await rig.notify(coordinator_id="security", severity=Severity.HIGH,
                     hazard_type="door_ajar", location=None)
    assert rig.indicates()[-1]["id"] == "ura:security:door_ajar:house"


# ---------------------------------------------------------------------------
# D-S1b-3 ledger, retarget, release, re-assert
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retarget_releases_dropped_areas(rig):
    await rig.enable()
    rig.set_occupied(Kitchen=True)
    await rig.notify()
    assert rig.indicates()[-1]["area_id"] == ["breakfast_nook", "kitchen", "media"]
    # Media no longer adjacent-to-occupied: occupant moved to the nook.
    rig.set_occupied(**{"Breakfast Nook": True})
    rig.hass.services.calls.clear()
    await rig.notify()
    halo = rig.hass.services.halo()
    assert [s for s, _ in halo] == ["indicate", "release"]
    assert halo[0][1]["area_id"] == ["breakfast_nook", "kitchen"]
    assert halo[1][1] == {"owner": "ura", "id": "ura:safety:water_leak:kitchen",
                          "area_id": ["media"]}


@pytest.mark.asyncio
async def test_repeat_renews_panel_lease(rig):
    await rig.enable()
    await rig.notify()
    assert rig.nm.alert_state == AlertState.REPEATING
    rig.set_occupied(Master=True)  # audience moved upstairs
    rig.hass.services.calls.clear()
    rows_before = len(rig.panel_rows())
    await rig.nm._repeat_alert()
    await settle(rig.hass)
    halo = rig.hass.services.halo()
    assert halo[0] == ("indicate", {
        "area_id": ["kitchen", "master"], "owner": "ura",
        "id": "ura:safety:water_leak:kitchen", "level": "critical",
        "ttl_s": 1800,
    })
    assert halo[1] == ("release", {"owner": "ura",
                                   "id": "ura:safety:water_leak:kitchen",
                                   "area_id": ["breakfast_nook", "media"]})
    assert len(rig.panel_rows()) == rows_before  # no row per repeat


@pytest.mark.asyncio
async def test_release_on_ack(rig):
    await rig.enable()
    await rig.notify()
    rig.hass.services.calls.clear()
    await rig.nm.async_acknowledge()
    await settle(rig.hass)
    assert rig.releases() == [{"owner": "ura", "id": "ura:safety:water_leak:kitchen"}]
    assert rig.nm._panel_leases == {}


@pytest.mark.asyncio
async def test_release_on_reeval_cleared(rig):
    await rig.enable()
    await rig.notify()
    await rig.nm.async_acknowledge()
    await settle(rig.hass)
    rig.hass.services.calls.clear()
    rig.hazard_active = False
    await rig.nm._re_evaluate_hazard()
    await settle(rig.hass)
    assert rig.nm._active_alert_data is None
    assert rig.releases() == [{"owner": "ura", "id": "ura:safety:water_leak:kitchen"}]


@pytest.mark.asyncio
async def test_reeval_still_active_renews_not_releases(rig):
    await rig.enable()
    await rig.notify()
    await rig.nm.async_acknowledge()
    await settle(rig.hass)
    rig.hass.services.calls.clear()
    rig.hazard_active = True
    await rig.nm._re_evaluate_hazard()
    await settle(rig.hass)
    assert [s for s, _ in rig.hass.services.halo()] == ["indicate"]


@pytest.mark.asyncio
async def test_killswitch_owner_wide_release(rig):
    await rig.enable()
    await rig.notify()
    rig.hass.services.calls.clear()
    await rig.nm.async_suppress_messaging()
    await settle(rig.hass)
    assert rig.releases() == [{"owner": "ura"}]
    assert rig.nm._panel_leases == {}
    # Suppressed: further notifies send nothing.
    await rig.notify(hazard_type="h9")
    assert rig.indicates() == []


@pytest.mark.asyncio
async def test_switch_off_releases_and_unsubscribes(rig):
    await rig.enable()
    assert len(rig.hass.bus.listeners["halo_ready"]) == 1
    await rig.notify()
    rig.hass.services.calls.clear()
    await rig.nm.async_set_panel_channel_enabled(False)
    await settle(rig.hass)
    assert rig.releases() == [{"owner": "ura"}]
    assert rig.hass.bus.listeners["halo_ready"] == []
    assert rig.nm.channel_status["panels"]["status"] == "off"
    rig.hass.services.calls.clear()
    await rig.notify(hazard_type="h2")
    rig.hass.bus.fire("halo_ready", {"areas": ["kitchen"]})
    await settle(rig.hass)
    assert rig.hass.services.halo() == []


@pytest.mark.asyncio
async def test_never_release_all(rig):
    """I2 across every path: owner is always "ura", never release_all, and
    every id was minted by URA."""
    await rig.enable()
    await rig.notify()
    await rig.nm._repeat_alert()
    await settle(rig.hass)
    rig.hass.bus.fire("halo_ready", {})
    await settle(rig.hass)
    await rig.notify(coordinator_id="security", severity=Severity.CRITICAL,
                     hazard_type="intruder", location=None)
    await rig.nm.async_acknowledge()
    await settle(rig.hass)
    await rig.nm.async_suppress_messaging()
    await settle(rig.hass)
    await rig.nm.async_resume_messaging()
    await rig.nm.async_set_panel_channel_enabled(False)
    await settle(rig.hass)
    halo = rig.hass.services.halo()
    assert halo
    assert {s for s, _ in halo} <= {"indicate", "release"}
    assert all(d["owner"] == "ura" for _, d in halo)
    assert all(d.get("id", "ura:").startswith("ura:") for _, d in halo)


@pytest.mark.asyncio
async def test_reassert_on_halo_ready_remaining_ttl(rig):
    await rig.enable()
    await rig.notify()
    rig.clock.advance(10 * 60)
    rig.hass.services.calls.clear()
    rig.hass.bus.fire("halo_ready", {"areas": ["kitchen"]})
    await settle(rig.hass)
    assert rig.indicates() == [{
        "area_id": ["breakfast_nook", "kitchen", "media"], "owner": "ura",
        "id": "ura:safety:water_leak:kitchen", "level": "critical",
        "ttl_s": 1200,
    }]


@pytest.mark.asyncio
async def test_reassert_skips_expired_and_released(rig):
    await rig.enable()
    await rig.notify(coordinator_id="security", severity=Severity.HIGH,
                     hazard_type="door_ajar", location=None)      # no episode
    await rig.notify(coordinator_id="security", severity=Severity.HIGH,
                     hazard_type="window_open", location=None)
    await rig.notify()  # CRITICAL leak episode
    await rig.nm.async_acknowledge()  # releases the leak lease
    await settle(rig.hass)
    # door_ajar expires; window_open still live.
    rig.nm._panel_leases["ura:security:door_ajar:house"]["expires_at"] = (
        rig.clock().timestamp() - 1)
    rig.hass.services.calls.clear()
    rig.hass.bus.fire("halo_ready", {})
    await settle(rig.hass)
    assert [d["id"] for d in rig.indicates()] == ["ura:security:window_open:house"]
    assert "ura:security:door_ajar:house" not in rig.nm._panel_leases


@pytest.mark.asyncio
async def test_reassert_after_restart_from_restored_alert_state(monkeypatch, clock):
    r = PanelRig(monkeypatch, clock)
    # Restored episode (as after HA restart): NM REPEATING, ledger empty.
    r.nm._alert_state = AlertState.REPEATING
    r.nm._active_alert_data = {
        "coordinator_id": "safety", "severity": "CRITICAL", "title": "Leak",
        "message": "m", "hazard_type": "water_leak", "location": "Kitchen",
    }
    await r.enable()  # switch restored ON, Halo already loaded
    assert [d["id"] for d in r.indicates()] == ["ura:safety:water_leak:kitchen"]
    # A later halo_ready does not double-send: the ledger now has it.
    r.hass.services.calls.clear()
    r.hass.bus.fire("halo_ready", {})
    await settle(r.hass)
    assert [d["id"] for d in r.indicates()] == ["ura:safety:water_leak:kitchen"]
    assert r.indicates()[0]["ttl_s"] == 1800


@pytest.mark.asyncio
async def test_reassert_after_restart_waits_for_halo(monkeypatch, clock):
    r = PanelRig(monkeypatch, clock)
    r.hass.services.halo_installed = False
    r.nm._alert_state = AlertState.REPEATING
    r.nm._active_alert_data = {
        "coordinator_id": "safety", "title": "Leak", "message": "m",
        "hazard_type": "water_leak", "location": "Kitchen",
    }
    await r.enable()
    assert r.hass.services.halo() == []
    assert r.nm.channel_status["panels"]["status"] == "absent"
    r.hass.services.halo_installed = True
    r.hass.bus.fire("halo_ready", {})
    await settle(r.hass)
    assert [d["id"] for d in r.indicates()] == ["ura:safety:water_leak:kitchen"]


@pytest.mark.asyncio
async def test_async_stop_does_not_release(rig):
    await rig.enable()
    await rig.notify()
    rig.hass.services.calls.clear()
    await rig.nm.async_teardown()
    await settle(rig.hass)
    assert rig.hass.services.halo() == []
    assert rig.hass.bus.listeners["halo_ready"] == []


@pytest.mark.asyncio
async def test_preempted_episode_lease_released(rig):
    await rig.enable()
    # Non-life-safety security CRITICAL takes the slot...
    await rig.notify(coordinator_id="security", severity=Severity.CRITICAL,
                     hazard_type="door_forced", location=None, title="Door")
    rig.hass.services.calls.clear()
    # ...then a life-safety leak preempts it.
    await rig.notify()
    assert rig.nm._active_alert_data["hazard_type"] == "water_leak"
    assert {"owner": "ura", "id": "ura:security:door_forced:house"} in rig.releases()
    assert "ura:security:door_forced:house" not in rig.nm._panel_leases
    assert "ura:safety:water_leak:kitchen" in rig.nm._panel_leases


@pytest.mark.asyncio
async def test_same_episode_renotify_does_not_release(rig):
    await rig.enable()
    await rig.notify()
    rig.hass.services.calls.clear()
    rig.clock.advance(120)  # past the 60 s CRITICAL dedup -> _enter_alerting runs
    episode = rig.nm._active_episode_id
    await rig.notify()  # same leak re-notified -> same id -> renew only
    assert rig.nm._active_episode_id != episode  # slot was re-entered
    assert rig.releases() == []
    assert [d["id"] for d in rig.indicates()] == ["ura:safety:water_leak:kitchen"]


@pytest.mark.asyncio
async def test_held_slot_newcomer_does_not_release_holder(rig):
    await rig.enable()
    await rig.notify()  # leak holds the slot (life-safety)
    rig.hass.services.calls.clear()
    await rig.notify(coordinator_id="security", severity=Severity.CRITICAL,
                     hazard_type="door_forced", location=None, title="Door")
    assert rig.releases() == []
    assert "ura:safety:water_leak:kitchen" in rig.nm._panel_leases


@pytest.mark.asyncio
async def test_concurrent_same_id_deliveries_serialize(rig):
    """M3 trace: task1 {A,B,C}->{A,B} awaits indicate; task2 sees C occupied
    again -> {A,B,C}. Without the lock task1's late release(C) darkens C."""
    await rig.enable()
    await rig.notify()  # ledger: nook, kitchen, media
    rig.set_occupied(**{"Breakfast Nook": True})  # media drops
    rig.hass.services.calls.clear()
    rig.hass.services.gate = asyncio.Event()
    rig.hass.services.gate_service = "indicate"
    assert rig.nm._schedule_panel_delivery(
        "safety", Severity.CRITICAL, "Leak", "m", "water_leak", "Kitchen",
        log_row=False)
    await asyncio.sleep(0)
    rig.set_occupied(Kitchen=True)  # media back in the audience
    assert rig.nm._schedule_panel_delivery(
        "safety", Severity.CRITICAL, "Leak", "m", "water_leak", "Kitchen",
        log_row=False)
    for _ in range(5):
        await asyncio.sleep(0)
    rig.hass.services.gate.set()
    await settle(rig.hass)
    halo = rig.hass.services.halo()
    # Final state: the last call for this id is an indicate covering media.
    assert halo[-1][0] == "indicate"
    assert "media" in halo[-1][1]["area_id"]
    assert rig.nm._panel_leases["ura:safety:water_leak:kitchen"]["areas"] == [
        "breakfast_nook", "kitchen", "media"]


@pytest.mark.asyncio
async def test_switch_off_mid_delivery_takes_lease_back(rig):
    await rig.enable()
    rig.hass.services.gate = asyncio.Event()
    rig.hass.services.gate_service = "indicate"
    await rig.nm.async_notify(
        coordinator_id="safety", severity=Severity.CRITICAL, title="Leak",
        message="m", hazard_type="water_leak", location="Kitchen",
    )
    for _ in range(3):
        await asyncio.sleep(0)
    rig.nm._panel_channel_enabled = False  # flipped while indicate in flight
    rig.hass.services.gate.set()
    await settle(rig.hass)
    assert rig.releases()[-1] == {"owner": "ura",
                                  "id": "ura:safety:water_leak:kitchen"}
    assert rig.nm._panel_leases == {}
    assert rig.panel_rows() == []


# ---------------------------------------------------------------------------
# D-S1b-4 health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_no_surface_when_halo_unconfigured(rig):
    rig.hass.services.surfaces = set()  # Halo installed, no entry loaded
    await rig.enable()
    assert rig.nm.channel_status["panels"]["status"] == "enabled"
    await rig.notify()
    assert rig.nm.channel_status["panels"]["status"] == "no_surface"
    (args, kw), = rig.panel_rows()
    assert args[8] == 0  # delivered=0: nothing was shown


@pytest.mark.asyncio
async def test_health_unavailable_mapping(rig):
    await rig.enable()
    rig.hass.services.unavailable = {"media"}
    await rig.notify()
    assert rig.nm.channel_status["panels"]["status"] == "unavailable"
    rig.hass.services.unavailable = set()
    await rig.notify()
    assert rig.nm.channel_status["panels"]["status"] == "ok"


@pytest.mark.asyncio
async def test_health_absent_when_service_missing(rig):
    await rig.enable()
    rig.hass.services.halo_installed = False
    await rig.notify()
    assert rig.nm.channel_status["panels"]["status"] == "absent"


# ---------------------------------------------------------------------------
# H2 — panels row never resurrects as the active critical (real DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_panels_row_never_active_critical(monkeypatch, clock, tmp_path):
    from test_imsg_audit_fix_1 import _drain, _make_db

    db = _make_db(str(tmp_path))
    await db.initialize()
    await db.start_write_worker()
    try:
        r = PanelRig(monkeypatch, clock)
        r.hass.data[DOMAIN]["database"] = db
        holder = await db.log_notification(
            coordinator_id="safety", severity="CRITICAL", title="Leak",
            message="leak in kitchen", hazard_type="water_leak",
            location="Kitchen", delivered=1,
        )
        await asyncio.sleep(0.01)
        await r.enable()
        # Held-slot newcomer delivered on panels after its rows were acked.
        assert r.nm._schedule_panel_delivery(
            "security", Severity.CRITICAL, "Door", "door forced",
            "door_forced", None, log_row=True)
        await settle(r.hass)
        active = await db.get_active_critical()
        assert active["id"] == holder
        import sqlite3
        conn = sqlite3.connect(db.db_file)
        rows = conn.execute(
            "SELECT acknowledged FROM notification_log WHERE channel='panels'"
        ).fetchall()
        conn.close()
        assert rows == [(1,)]
    finally:
        await _drain(db)
