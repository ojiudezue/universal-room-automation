"""SAFETY-NM-REFIRE-UNWIRED-1 (plan Rev 4 / 4.1): D1 + D2 + D6.

D1  Safety's single NotificationAction carries hazard_type + location.
D2  SafetyCoordinator.is_hazard_active is hold-aware (post-ACK gate only).
D6  Multi-sensor flooding location is deterministic (sorted).

Drives REAL code: SafetyCoordinator.evaluate (intent pipeline ->
_respond_to_hazard), CoordinatorManager._execute_action (the production
Safety->NM forward), NotificationManager.async_notify / async_acknowledge /
_cooldown_expired (-> _re_evaluate_hazard -> is_hazard_active), and the real
_check_flooding_escalation in seeded subprocesses.

Oracles are hardcoded literals (independent): smoke/CO cooldown 120 s
(2 min), life-safety repeat cadence 30 s, clear hold 300 s, sorted
location "Garage, Kitchen".
"""
from __future__ import annotations

# Install both stub universes BEFORE importing URA modules (order matters
# for HA stubs only; module identities are reconciled per-test below).
import test_notification_manager as _tnm  # noqa: F401
import test_safety_coordinator  # noqa: F401
from test_safety_coordinator import make_hass

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.universal_room_automation.domain_coordinators import (
    safety as safety_mod,
)
from custom_components.universal_room_automation.domain_coordinators import (
    manager as manager_mod,
)
from custom_components.universal_room_automation.domain_coordinators.base import (
    Intent,
)

T0 = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
LOC = "Garage"
SMOKE = "binary_sensor.smoke_garage"
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

# NM module captured at import (the object test_notification_manager loaded).
nm_mod = _tnm._nm_mod
AlertState = nm_mod.AlertState


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _knob_mod():
    import importlib
    return importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators._nm_cycle_a"
    )


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(safety_mod.dt_util, "utcnow", c)
    monkeypatch.setattr(nm_mod.dt_util, "utcnow", c)
    _knob_mod().invalidate_knob_cache()
    yield c
    _knob_mod().invalidate_knob_cache()


def _safety() -> "safety_mod.SafetyCoordinator":
    c = safety_mod.SafetyCoordinator(make_hass())
    c._binary_sensors[SMOKE] = safety_mod.HazardType.SMOKE.value
    c._sensor_locations[SMOKE] = LOC
    states = {SMOKE: SimpleNamespace(state="off", attributes={})}
    c.hass.states.get.side_effect = lambda eid: states.get(eid)
    c._test_states = states
    return c


async def _feed(c, value: str):
    c._test_states[SMOKE] = SimpleNamespace(state=value, attributes={})
    return await c.evaluate(
        [Intent(source="state_change", entity_id=SMOKE,
                data={"state": value}, coordinator_id="safety")],
        {},
    )


def _notifications(actions):
    return [a for a in actions if type(a).__name__ == "NotificationAction"]


# ---------------------------------------------------------------------------
# NM rig: real NotificationManager + real CoordinatorManager._execute_action
# ---------------------------------------------------------------------------

# database.log_notification positional order (database.py log_notification).
_LOG_FIELDS = ("coordinator_id", "severity", "title", "message", "hazard_type",
               "location", "person_id", "channel", "delivered")


class Rig:
    def __init__(self, monkeypatch, clock):
        self.clock = clock
        self.safety = _safety()
        hass = _tnm._make_hass()
        self.db = AsyncMock()
        self.db.get_active_critical = AsyncMock(return_value={"id": 1})
        self.db.get_active_cooldown = AsyncMock(return_value=None)
        hass.data[_tnm.DOMAIN]["database"] = self.db
        hass.data[_tnm.DOMAIN]["coordinator_manager"] = SimpleNamespace(
            coordinators={"safety": self.safety}
        )
        # Pushover enabled for person.test (channel enabled -> per-channel
        # notification_log rows are actually written; plan Rev 4.1 S2).
        self.nm = nm_mod.NotificationManager(hass, _tnm._make_config())
        self.later: list[tuple[float, object]] = []
        monkeypatch.setattr(
            nm_mod, "async_call_later",
            lambda _h, delay, cb: (self.later.append((delay, cb)), lambda: None)[1],
        )
        monkeypatch.setattr(nm_mod, "async_dispatcher_send", lambda *a, **k: None)
        monkeypatch.setattr(self.nm, "_is_quiet_hours", lambda: False)
        # Real manager forward (manager.py NOTIFICATION branch). Reconcile
        # the manager module's base-class globals with the ones Safety's
        # actions are built from (stub files may re-exec base in any order);
        # scoped via monkeypatch, restored after the test.
        na_cls = safety_mod.NotificationAction
        monkeypatch.setattr(manager_mod, "NotificationAction", na_cls)
        monkeypatch.setattr(
            manager_mod, "ActionType",
            type(na_cls.__dataclass_fields__["action_type"].default),
        )
        monkeypatch.setattr(manager_mod, "ServiceCallAction",
                            safety_mod.ServiceCallAction)
        self.mgr = manager_mod.CoordinatorManager.__new__(
            manager_mod.CoordinatorManager
        )
        self.mgr.hass = hass
        self.mgr._notification_manager = self.nm
        # Pass-through spy on async_notify (real method still runs).
        self.notify_calls: list[dict] = []
        real = self.nm.async_notify

        async def _spy(**kwargs):
            self.notify_calls.append(kwargs)
            return await real(**kwargs)

        monkeypatch.setattr(self.nm, "async_notify", _spy)

    async def raise_smoke(self):
        actions = await _feed(self.safety, "on")
        notes = _notifications(actions)
        assert len(notes) == 1
        await self.mgr._execute_action(self.safety, notes[0])
        return notes[0]

    def log_rows(self):
        """Every notification_log write, normalised to a field dict."""
        out = []
        for c in self.db.log_notification.await_args_list:
            row = dict(zip(_LOG_FIELDS, c.args))
            row.update(c.kwargs)
            out.append(row)
        return out

    def channel_rows(self):
        """Per-channel delivery rows (not audit rows)."""
        return [r for r in self.log_rows()
                if r.get("channel") and r.get("delivered", 1) == 1
                and not r.get("route_reason")]


@pytest.fixture
def rig(monkeypatch, clock):
    return Rig(monkeypatch, clock)


# ---------------------------------------------------------------------------
# T1 — D1 producer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_notification_action_carries_hazard_type_location(clock):
    c = _safety()
    notes = _notifications(await _feed(c, "on"))
    assert len(notes) == 1
    assert notes[0].hazard_type == "smoke"
    assert notes[0].location == "Garage"


# ---------------------------------------------------------------------------
# T2 / T3 / T4 / T5 — D2 predicate (driven through evaluate where reachable)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_is_hazard_active_true_when_active(clock):
    c = _safety()
    await _feed(c, "on")
    assert c.is_hazard_active("smoke", "Garage") is True
    assert c.is_hazard_active("smoke", "Garag") is False


def _bare_hazard():
    return safety_mod.Hazard(
        type=safety_mod.HazardType.SMOKE, severity=safety_mod.Severity.CRITICAL,
        confidence=1, location=LOC, sensor_id=SMOKE, value="on",
        threshold="on", detected_at=T0, message="m",
    )


def test_safety_is_hazard_active_hold_branch_needs_both_conjuncts():
    """D2 compound guard: inactive iff pending AND no raising contributor."""
    c = safety_mod.SafetyCoordinator(make_hass())
    c._active_hazards["smoke:Garage"] = _bare_hazard()
    # Not pending, no raising set recorded -> still ACTIVE.
    assert c.is_hazard_active("smoke", "Garage") is True
    # Pending but a contributor is still raising -> still ACTIVE.
    c._hazard_clear_pending["smoke:Garage"] = T0
    c._hazard_raising_sensors["smoke:Garage"] = {SMOKE}
    assert c.is_hazard_active("smoke", "Garage") is True
    # Pending AND no contributor -> INACTIVE.
    c._hazard_raising_sensors["smoke:Garage"] = set()
    assert c.is_hazard_active("smoke", "Garage") is False


def test_safety_is_hazard_active_roc_key_pending_is_inactive():
    """D2 keeps :roc stripping and applies the hold check to the roc key."""
    c = safety_mod.SafetyCoordinator(make_hass())
    c._active_hazards["smoke:Garage:roc"] = _bare_hazard()
    assert c.is_hazard_active("smoke", "Garage") is True
    c._hazard_clear_pending["smoke:Garage:roc"] = T0
    c._hazard_raising_sensors["smoke:Garage:roc"] = set()
    assert c.is_hazard_active("smoke", "Garage") is False


@pytest.mark.asyncio
async def test_safety_is_hazard_active_false_when_cleared(clock):
    c = _safety()
    await _feed(c, "on")
    await _feed(c, "off")
    clock.advance(301)
    c._async_periodic_check()
    assert "smoke:Garage" not in c._active_hazards
    assert c.is_hazard_active("smoke", "Garage") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("hold_s", [300, 86400])
async def test_safety_is_hazard_active_false_during_clear_hold(clock, monkeypatch, hold_s):
    monkeypatch.setattr(safety_mod, "HAZARD_MIN_HOLD_S", hold_s)
    c = _safety()
    await _feed(c, "on")
    await _feed(c, "off")
    clock.advance(130)
    c._async_periodic_check()
    # Hold still running: key retained (dashboard may read ON) ...
    assert "smoke:Garage" in c._active_hazards
    assert "smoke:Garage" in c._hazard_clear_pending
    # ... but the post-ACK gate reports it inactive.
    assert c.is_hazard_active("smoke", "Garage") is False


@pytest.mark.asyncio
async def test_safety_is_hazard_active_true_on_relapse_during_hold(clock):
    c = _safety()
    await _feed(c, "on")
    await _feed(c, "off")
    clock.advance(60)
    actions = await _feed(c, "on")  # relapse via _respond_to_hazard
    assert "smoke:Garage" not in c._hazard_clear_pending
    assert c.is_hazard_active("smoke", "Garage") is True
    # I2 re-arm still re-runs the response (emergency path unchanged).
    assert actions


# ---------------------------------------------------------------------------
# T6 — D1 blast-radius anchor: smoke CRITICAL repeats on life-safety cadence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_smoke_repeat_phase_is_life_safety(rig):
    await rig.raise_smoke()
    nm = rig.nm
    assert nm.alert_state == AlertState.REPEATING
    assert nm._active_alert_data["hazard_type"] == "smoke"
    assert nm._active_alert_data["location"] == "Garage"
    assert nm._repeat_phase() == "life_safety"
    assert nm._repeat_interval_for_active_alert() == 30
    # The scheduled repeat timer actually uses the 30 s cadence.
    assert rig.later and rig.later[-1][0] == 30


# ---------------------------------------------------------------------------
# T7 / T7-neg — post-ACK round trip through _re_evaluate_hazard
# ---------------------------------------------------------------------------

async def _ack_and_get_cooldown_cb(rig):
    rig.later.clear()
    await rig.nm.async_acknowledge()
    assert rig.nm.alert_state == AlertState.COOLDOWN
    cds = [(d, cb) for d, cb in rig.later
           if getattr(cb, "__name__", "") == "_cooldown_expired"]
    assert len(cds) == 1
    return cds[0]


@pytest.mark.asyncio
async def test_nm_re_evaluates_safety_hazard_round_trip(rig):
    await rig.raise_smoke()
    assert rig.channel_rows(), "fixture must enable a channel (rows are per channel)"
    delay, cb = await _ack_and_get_cooldown_cb(rig)
    assert delay == 120  # smoke cooldown 2 min (COOLDOWN_CONFIG keyed on hazard)
    rows_before = len(rig.channel_rows())
    rig.notify_calls.clear()
    rig.clock.advance(120)
    await cb()  # detector still ON, no clear pending
    assert len(rig.notify_calls) == 1, rig.notify_calls
    call = rig.notify_calls[0]
    assert call["hazard_type"] == "smoke"
    assert call["location"] == "Garage"
    assert call["severity"].name == "CRITICAL"
    new_rows = rig.channel_rows()[rows_before:]
    assert new_rows, "re-fire must write a per-channel notification_log row"
    assert all(r["hazard_type"] == "smoke" and r["location"] == "Garage"
               and r["severity"] == "CRITICAL" for r in new_rows)
    assert rig.nm.alert_state == AlertState.REPEATING


@pytest.mark.asyncio
async def test_nm_re_evaluate_no_refire_during_pending_clear(rig):
    await rig.raise_smoke()
    _delay, cb = await _ack_and_get_cooldown_cb(rig)
    rig.clock.advance(60)
    await _feed(rig.safety, "off")  # hold pending, no raising contributor
    assert "smoke:Garage" in rig.safety._hazard_clear_pending
    rig.clock.advance(70)  # t=130: cooldown expired, hold still running
    rig.safety._async_periodic_check()
    assert "smoke:Garage" in rig.safety._active_hazards
    rig.notify_calls.clear()
    await cb()
    assert rig.notify_calls == []
    assert rig.nm.alert_state == AlertState.IDLE


# ---------------------------------------------------------------------------
# T9 — D6 deterministic flooding location (real _check_flooding_escalation)
# ---------------------------------------------------------------------------

_T9_SCRIPT = r"""
import sys
from datetime import datetime, timezone
sys.path.insert(0, sys.argv[1])
import homeassistant.core  # noqa: F401  (real HA, as under pytest)
import test_safety_coordinator  # installs stubs + loads safety
from custom_components.universal_room_automation.domain_coordinators.safety import (
    SafetyCoordinator,
)
c = SafetyCoordinator.__new__(SafetyCoordinator)
c._active_leak_sensors = {"binary_sensor.leak_kitchen", "binary_sensor.leak_garage"}
c._sensor_locations = {
    "binary_sensor.leak_kitchen": "Kitchen",
    "binary_sensor.leak_garage": "Garage",
}
now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
c._leak_start_times = {eid: now for eid in c._active_leak_sensors}
h = c._check_flooding_escalation(now)
print(h.location)
print(h.message)
"""


def test_safety_flooding_location_is_deterministic():
    outs = []
    for seed in ("0", "1"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run(
            [sys.executable, "-c", _T9_SCRIPT, TESTS_DIR],
            capture_output=True, text=True, env=env, timeout=120,
            cwd=os.path.dirname(TESTS_DIR),
        )
        assert r.returncode == 0, r.stderr
        lines = r.stdout.strip().splitlines()
        outs.append((lines[-2], lines[-1]))
    for location, message in outs:
        assert location == "Garage, Kitchen"
        assert message.endswith("Garage, Kitchen!")
