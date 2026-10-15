"""SAFETY-HAZARD-NEVER-CLEARS-1 (rev 4): hazards clear on recovery.

Drives the REAL SafetyCoordinator: ``evaluate`` (intent pipeline →
``_process_sensor`` → handlers → ``_respond_to_hazard``), ``_async_periodic_check``
(the sweep wire-in), ``_async_sensor_state_changed`` (unavailable writer).

Boundaries use hardcoded literals (independent oracles), never the imported
constants: freeze clears at >=48, overheat <=97, normal-room high humidity
<=75 (78-3), low humidity >=33, CO2 <=1400, TVOC <=200, CO <=23, hold 300 s,
unavailable window 900 s, ROC stale 900 s.
"""
from __future__ import annotations

import test_safety_coordinator  # noqa: F401  (installs HA stubs + imports safety)
from test_safety_coordinator import make_hass

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from custom_components.universal_room_automation.domain_coordinators import (
    safety as safety_mod,
)
from custom_components.universal_room_automation.domain_coordinators import (
    _nm_cycle_a,
)
from custom_components.universal_room_automation.domain_coordinators.base import (
    Intent,
    Severity,
)
from custom_components.universal_room_automation.domain_coordinators.safety import (
    Hazard,
    HazardType,
    SafetyCoordinator,
)

T0 = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)  # cooling season
LOC = "Garage"
VALVE = "valve.main_water"


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(safety_mod.dt_util, "utcnow", c)
    _nm_cycle_a.invalidate_knob_cache()
    yield c
    _nm_cycle_a.invalidate_knob_cache()


@pytest.fixture
def signals():
    sent: list = []
    with patch(
        "homeassistant.helpers.dispatcher.async_dispatcher_send",
        # Count SIGNAL_SAFETY_HAZARD only (entity-update signals ignored).
        side_effect=lambda hass, sig, payload=None: (
            sent.append(payload) if sig == safety_mod.SIGNAL_SAFETY_HAZARD else None
        ),
    ):
        yield sent


def _coord(sensors: dict[str, str], binary: dict[str, str] | None = None,
           room_type: str = "normal"):
    """sensors: entity_id -> sensor_type. All located at LOC."""
    hass = make_hass()
    states: dict[str, SimpleNamespace] = {}
    hass.states.get.side_effect = lambda eid: states.get(eid)
    coord = SafetyCoordinator(hass, water_shutoff_valve=VALVE)
    for eid, stype in sensors.items():
        coord._numeric_sensors[eid] = stype
        coord._sensor_locations[eid] = LOC
        coord._sensor_room_types[eid] = room_type
        coord._sensor_units[eid] = "°F"
        states[eid] = SimpleNamespace(state="1", attributes={})
    for eid, htype in (binary or {}).items():
        coord._binary_sensors[eid] = htype
        coord._sensor_locations[eid] = LOC
        states[eid] = SimpleNamespace(state="off", attributes={})
    coord._test_states = states
    return coord


async def _feed(coord, eid, value):
    """Drive the production intent pipeline for one state change."""
    coord._test_states[eid] = SimpleNamespace(state=str(value), attributes={})
    return await coord.evaluate(
        [Intent(source="state_change", entity_id=eid,
                data={"state": str(value)}, coordinator_id="safety")],
        {},
    )


def _tick(coord, clock, seconds=0):
    clock.advance(seconds)
    coord._async_periodic_check()


def _valve_closes(actions):
    return [a for a in actions if getattr(a, "service", None) == "valve.close"]


# ---------------------------------------------------------------------------
# D1 — temperature
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_freeze_clear_on_recovery_with_hysteresis(clock, signals):
    c = _coord({"sensor.t": "temperature"})
    await _feed(c, "sensor.t", 44.0)
    assert "freeze_risk:Garage" in c._active_hazards
    clock.advance(10)
    await _feed(c, "sensor.t", 48.5)
    assert "freeze_risk:Garage" in c._active_hazards  # hold not elapsed
    _tick(c, clock, 299)
    assert "freeze_risk:Garage" in c._active_hazards  # 299 s < 300 s
    _tick(c, clock, 1)
    assert "freeze_risk:Garage" not in c._active_hazards
    assert c.get_safety_status() == "normal"
    assert len(signals) == 1


@pytest.mark.asyncio
async def test_safety_freeze_clear_line_boundary(clock):
    c = _coord({"sensor.t": "temperature"})
    await _feed(c, "sensor.t", 44.0)
    await _feed(c, "sensor.t", 47.9)  # just inside band (clear line 48)
    _tick(c, clock, 400)
    assert "freeze_risk:Garage" in c._active_hazards
    await _feed(c, "sensor.t", 48.0)  # exactly the clear line
    _tick(c, clock, 300)
    assert "freeze_risk:Garage" not in c._active_hazards


@pytest.mark.asyncio
async def test_safety_overheat_clear_on_recovery_with_hysteresis(clock, signals):
    c = _coord({"sensor.t": "temperature"})
    await _feed(c, "sensor.t", 101.0)
    assert "overheat:Garage" in c._active_hazards
    await _feed(c, "sensor.t", 98.0)  # band (clear line 97)
    _tick(c, clock, 600)
    assert "overheat:Garage" in c._active_hazards
    await _feed(c, "sensor.t", 97.0)
    _tick(c, clock, 300)
    assert "overheat:Garage" not in c._active_hazards
    assert len(signals) == 1


@pytest.mark.asyncio
async def test_safety_temp_clear_blocked_inside_offset_band(clock):
    c = _coord({"sensor.t": "temperature"})
    await _feed(c, "sensor.t", 44.0)
    await _feed(c, "sensor.t", 46.0)
    _tick(c, clock, 3600)
    assert "freeze_risk:Garage" in c._active_hazards


@pytest.mark.asyncio
async def test_safety_temp_clear_waits_for_all_contributing_sensors(clock):
    c = _coord({"sensor.a": "temperature", "sensor.b": "temperature"})
    await _feed(c, "sensor.a", 44.0)
    await _feed(c, "sensor.b", 42.0)
    await _feed(c, "sensor.a", 48.5)
    _tick(c, clock, 600)
    assert "freeze_risk:Garage" in c._active_hazards
    await _feed(c, "sensor.b", 48.5)
    _tick(c, clock, 299)
    assert "freeze_risk:Garage" in c._active_hazards
    _tick(c, clock, 1)
    assert "freeze_risk:Garage" not in c._active_hazards


@pytest.mark.asyncio
async def test_safety_second_raise_registers_sensor_even_when_not_is_new(clock, signals):
    c = _coord({"sensor.a": "temperature", "sensor.b": "temperature"})
    await _feed(c, "sensor.a", 44.0)
    await _feed(c, "sensor.b", 44.0)  # same severity → not is_new (early return)
    assert len(signals) == 1
    assert c._hazard_raising_sensors["freeze_risk:Garage"] == {"sensor.a", "sensor.b"}
    await _feed(c, "sensor.a", 48.5)
    _tick(c, clock, 600)
    assert "freeze_risk:Garage" in c._active_hazards
    await _feed(c, "sensor.b", 48.5)
    _tick(c, clock, 300)
    assert "freeze_risk:Garage" not in c._active_hazards


@pytest.mark.asyncio
async def test_safety_raise_cancels_pending_clear(clock):
    c = _coord({"sensor.t": "temperature"})
    await _feed(c, "sensor.t", 44.0)
    await _feed(c, "sensor.t", 48.5)
    clock.advance(200)
    await _feed(c, "sensor.t", 44.0)  # same severity, not is_new
    assert "freeze_risk:Garage" not in c._hazard_clear_pending
    _tick(c, clock, 200)
    assert "freeze_risk:Garage" in c._active_hazards


@pytest.mark.asyncio
async def test_safety_temp_no_flap_signal_count_under_oscillation(clock, signals):
    c = _coord({"sensor.t": "temperature"})
    for i in range(60):  # 10 min at 10 s cadence
        await _feed(c, "sensor.t", 44.5 if i % 2 == 0 else 46.0)
        _tick(c, clock, 10)
    assert len(signals) == 1
    assert "freeze_risk:Garage" in c._active_hazards


@pytest.mark.asyncio
async def test_safety_temp_cross_without_hold_does_not_clear(clock, signals):
    c = _coord({"sensor.t": "temperature"})
    await _feed(c, "sensor.t", 44.0)
    await _feed(c, "sensor.t", 48.5)
    _tick(c, clock, 120)
    await _feed(c, "sensor.t", 44.0)
    _tick(c, clock, 600)
    assert "freeze_risk:Garage" in c._active_hazards
    assert len(signals) == 1
    await _feed(c, "sensor.t", 48.5)
    _tick(c, clock, 300)
    assert "freeze_risk:Garage" not in c._active_hazards
    await _feed(c, "sensor.t", 44.0)
    assert len(signals) == 2  # exactly one new signal after a real clear


@pytest.mark.asyncio
async def test_safety_hold_zero_clears_immediately(clock, monkeypatch):
    monkeypatch.setattr(safety_mod, "HAZARD_MIN_HOLD_S", 0)
    c = _coord({"sensor.t": "temperature"})
    await _feed(c, "sensor.t", 44.0)
    await _feed(c, "sensor.t", 48.0)
    assert "freeze_risk:Garage" not in c._active_hazards


# ---------------------------------------------------------------------------
# D1 / D6 / I2 — life-safety response never suppressed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_leak_rewet_during_hold_reissues_response(clock, signals):
    c = _coord({}, binary={"binary_sensor.leak": HazardType.WATER_LEAK.value})
    first = await _feed(c, "binary_sensor.leak", "on")
    assert len(_valve_closes(first)) == 1
    clock.advance(30)
    await _feed(c, "binary_sensor.leak", "off")
    assert "water_leak:Garage" in c._hazard_clear_pending  # held
    clock.advance(60)  # inside the 300 s hold
    second = await _feed(c, "binary_sensor.leak", "on")
    assert len(_valve_closes(second)) == 1
    assert len(signals) == 2
    # NM page cadence still governed by AlertDeduplicator (HIGH = 5 min):
    assert any(type(a).__name__ == "NotificationAction" for a in first)
    assert not any(type(a).__name__ == "NotificationAction" for a in second)


@pytest.mark.asyncio
async def test_safety_smoke_retrigger_during_hold_reissues_response(clock, signals):
    c = SafetyCoordinator(make_hass(), emergency_lights=["light.hall"])
    c._binary_sensors["binary_sensor.smoke"] = HazardType.SMOKE.value
    c._sensor_locations["binary_sensor.smoke"] = LOC
    c.hass.states.get.side_effect = lambda eid: SimpleNamespace(state="on", attributes={})

    async def feed(v):
        return await c.evaluate([Intent(source="state_change",
                                        entity_id="binary_sensor.smoke",
                                        data={"state": v})], {})
    lights = lambda acts: [a for a in acts if getattr(a, "service", None) == "light.turn_on"]  # noqa: E731
    assert len(lights(await feed("on"))) == 1
    await feed("off")
    clock.advance(60)
    assert len(lights(await feed("on"))) == 1
    assert len(signals) == 2


@pytest.mark.asyncio
async def test_safety_co_relapse_during_hold_reissues_response(clock, signals):
    c = _coord({"sensor.co": "co"})
    first = await _feed(c, "sensor.co", 60.0)  # HIGH
    assert c._active_hazards["carbon_monoxide:Garage"].severity == Severity.HIGH
    assert len(signals) == 1
    clock.advance(30)
    await _feed(c, "sensor.co", 20.0)  # through the clear line (23)
    assert "carbon_monoxide:Garage" in c._hazard_clear_pending
    clock.advance(60)
    second = await _feed(c, "sensor.co", 60.0)  # same severity HIGH
    assert len(signals) == 2  # full response re-ran
    assert c._hazard_occurrences["carbon_monoxide:Garage"] == 1
    assert c._hazards_detected_24h == 2  # response path entered twice
    # Page cadence: AlertDeduplicator (HIGH 5 min) suppresses the 2nd page.
    assert any(type(a).__name__ == "NotificationAction" for a in first)
    assert not any(type(a).__name__ == "NotificationAction" for a in second)


@pytest.mark.asyncio
async def test_safety_comfort_relapse_during_hold_does_not_refire(clock, signals):
    """Discriminator for I2: only life-safety types re-arm on pending."""
    c = _coord({"sensor.co2": "co2"})
    await _feed(c, "sensor.co2", 1510.0)
    await _feed(c, "sensor.co2", 1390.0)
    assert "high_co2:Garage" in c._hazard_clear_pending
    clock.advance(60)
    await _feed(c, "sensor.co2", 1510.0)
    assert len(signals) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("hold", [0, 1, 300, 86400])
async def test_safety_life_safety_response_never_suppressed_at_hold_extremes(
    clock, signals, monkeypatch, hold
):
    """I2 at config extremes: every re-wet runs valve close, whatever the hold."""
    monkeypatch.setattr(safety_mod, "HAZARD_MIN_HOLD_S", hold)
    c = _coord({}, binary={"binary_sensor.leak": HazardType.WATER_LEAK.value})
    for _ in range(3):
        acts = await _feed(c, "binary_sensor.leak", "on")
        assert len(_valve_closes(acts)) == 1
        clock.advance(5)
        await _feed(c, "binary_sensor.leak", "off")
        clock.advance(5)
        _tick(c, clock, 0)


# ---------------------------------------------------------------------------
# D2 — humidity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_high_humidity_clear_uses_resolved_normal_thresholds(clock, signals):
    c = _coord({"sensor.h": "humidity"})
    await _feed(c, "sensor.h", 86.0)
    clock.advance(2 * 3600 + 1)
    await _feed(c, "sensor.h", 86.0)
    assert "high_humidity:Garage" in c._active_hazards
    await _feed(c, "sensor.h", 76.0)  # below low 78 but above 75
    _tick(c, clock, 600)
    assert "high_humidity:Garage" in c._active_hazards
    await _feed(c, "sensor.h", 75.0)
    _tick(c, clock, 300)
    assert "high_humidity:Garage" not in c._active_hazards
    assert len(signals) == 1


@pytest.mark.asyncio
async def test_safety_high_humidity_clear_follows_operator_override(clock):
    c = _coord({"sensor.h": "humidity"})
    from custom_components.universal_room_automation import const
    _nm_cycle_a._KNOB_CACHE[const.CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT] = 70.0
    await _feed(c, "sensor.h", 86.0)
    clock.advance(2 * 3600 + 1)
    await _feed(c, "sensor.h", 86.0)
    await _feed(c, "sensor.h", 68.0)  # above override 70-3=67
    _tick(c, clock, 600)
    assert "high_humidity:Garage" in c._active_hazards
    await _feed(c, "sensor.h", 67.0)
    _tick(c, clock, 300)
    assert "high_humidity:Garage" not in c._active_hazards


@pytest.mark.asyncio
async def test_safety_high_humidity_swing_clear_shares_key(clock):
    c = _coord({"sensor.h": "humidity"})
    c._active_hazards["high_humidity:Garage"] = Hazard(
        type=HazardType.HIGH_HUMIDITY, severity=Severity.MEDIUM, confidence=0.7,
        location=LOC, sensor_id="sensor.h", value=70, threshold=15,
        detected_at=T0, message="swing")
    c._hazard_raising_sensors["high_humidity:Garage"] = {"sensor.h"}
    await _feed(c, "sensor.h", 75.0)
    _tick(c, clock, 300)
    assert "high_humidity:Garage" not in c._active_hazards


@pytest.mark.asyncio
async def test_safety_low_humidity_clear_on_recovery_with_hysteresis(clock, signals):
    c = _coord({"sensor.h": "humidity"})
    await _feed(c, "sensor.h", 29.0)
    assert "low_humidity:Garage" in c._active_hazards
    await _feed(c, "sensor.h", 32.9)
    _tick(c, clock, 600)
    assert "low_humidity:Garage" in c._active_hazards
    await _feed(c, "sensor.h", 33.0)
    _tick(c, clock, 300)
    assert "low_humidity:Garage" not in c._active_hazards
    assert len(signals) == 1


@pytest.mark.asyncio
async def test_safety_low_humidity_replay_garage_a_episode_single_signal(clock, signals):
    trace = [30.0, 30.0, 31.0, 30.0, 32.0, 31.0, 30.0, 34.0, 35.0, 35.0]
    c = _coord({"sensor.h": "humidity"})
    for v in trace:
        await _feed(c, "sensor.h", v)
        _tick(c, clock, 60)
    _tick(c, clock, 300)
    assert c._active_hazards == {}
    assert len(signals) == 1


@pytest.mark.asyncio
async def test_safety_humidity_clear_ignored_below_plausibility_floor(clock, signals):
    c = _coord({"sensor.h": "humidity"})
    await _feed(c, "sensor.h", 0.0)  # junk: no raise
    assert c._active_hazards == {}
    await _feed(c, "sensor.h", 25.0)
    assert "low_humidity:Garage" in c._active_hazards
    await _feed(c, "sensor.h", 40.0)
    clock.advance(100)
    await _feed(c, "sensor.h", 0.0)  # junk: neither relapse nor recovery
    assert "low_humidity:Garage" in c._hazard_clear_pending
    _tick(c, clock, 200)
    assert "low_humidity:Garage" not in c._active_hazards
    assert len(signals) == 1


@pytest.mark.asyncio
async def test_safety_humidity_outdoor_room_returns_early_before_clear_block(clock):
    c = _coord({"sensor.h": "humidity"}, room_type="outdoor")
    await _feed(c, "sensor.h", 10.0)
    assert c._active_hazards == {}


# ---------------------------------------------------------------------------
# D3 — flooding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_flooding_clears_when_last_leak_sensor_dries(clock):
    c = _coord({}, binary={"binary_sensor.l1": HazardType.WATER_LEAK.value,
                           "binary_sensor.l2": HazardType.WATER_LEAK.value})
    await _feed(c, "binary_sensor.l1", "on")
    acts = await _feed(c, "binary_sensor.l2", "on")
    assert any(k.startswith("flooding:") for k in c._active_hazards)
    assert _valve_closes(acts)
    await _feed(c, "binary_sensor.l1", "off")
    assert any(k.startswith("flooding:") for k in c._active_hazards)
    await _feed(c, "binary_sensor.l2", "off")
    assert not any(k.startswith("flooding:") for k in c._active_hazards)
    assert not any(k.startswith("flooding:") for k in c._hazard_raising_sensors)


# ---------------------------------------------------------------------------
# D4 / D5 — ROC + sweep
# ---------------------------------------------------------------------------

def _roc_raise(c, clock, eid="sensor.t"):
    """Two samples exactly 1800 s apart, +25 F → learning-mode OVERHEAT ROC."""
    c._rate_detector.record(eid, clock.now - timedelta(seconds=1800), 70.0)
    return eid


@pytest.mark.asyncio
async def test_safety_roc_overheat_uses_roc_suffix_key(clock):
    c = _coord({"sensor.t": "temperature"})
    _roc_raise(c, clock)
    await _feed(c, "sensor.t", 95.0)  # rate +25/30min, below overheat 100
    h = c._active_hazards["overheat:Garage:roc"]
    assert h.from_roc and h.raise_rate == pytest.approx(25.0) and h.raise_z is None
    assert "overheat:Garage" not in c._active_hazards


@pytest.mark.asyncio
async def test_safety_roc_type_clear_does_not_pop_roc_key(clock):
    c = _coord({"sensor.t": "temperature"})
    _roc_raise(c, clock)
    await _feed(c, "sensor.t", 101.0)  # both overheat and ROC
    assert {"overheat:Garage", "overheat:Garage:roc"} <= set(c._active_hazards)
    c._rate_detector._history["sensor.t"].append((clock.now, 101.0))
    clock.advance(1)
    await _feed(c, "sensor.t", 96.0)
    # Freeze the ROC evidence so only the type-wise path can act.
    with patch.object(c, "_roc_sensor_recovered", return_value=False):
        _tick(c, clock, 300)
    assert "overheat:Garage" not in c._active_hazards
    assert "overheat:Garage:roc" in c._active_hazards


@pytest.mark.asyncio
async def test_safety_roc_does_not_collide_with_binary_water_leak(clock):
    c = _coord({"sensor.h": "humidity"},
               binary={"binary_sensor.leak": HazardType.WATER_LEAK.value})
    c._rate_detector.record("sensor.h", clock.now - timedelta(seconds=1800), 40.0)
    await _feed(c, "sensor.h", 82.0)  # +42/30min → WATER_LEAK roc
    assert "water_leak:Garage:roc" in c._active_hazards
    await _feed(c, "binary_sensor.leak", "on")
    await _feed(c, "binary_sensor.leak", "off")
    with patch.object(c, "_roc_sensor_recovered", return_value=False):
        _tick(c, clock, 300)
    assert "water_leak:Garage" not in c._active_hazards
    assert "water_leak:Garage:roc" in c._active_hazards


def test_safety_is_hazard_active_ignores_roc_suffix():
    c = SafetyCoordinator(make_hass())
    h = Hazard(type=HazardType.OVERHEAT, severity=Severity.MEDIUM, confidence=1,
               location=LOC, sensor_id="s", value=1, threshold=1,
               detected_at=T0, message="m")
    c._active_hazards["overheat:Garage:roc"] = h
    assert c.is_hazard_active("overheat", "Garage") is True
    assert c.is_hazard_active("overheat", "Garag") is False
    c._active_hazards = {"high_co2:Garage": h}
    assert c.is_hazard_active("co", "Garage") is False  # no substring match
    assert c.is_hazard_active("high_co2", "Garage") is True


@pytest.mark.asyncio
async def test_safety_roc_clears_on_get_rate_none(clock):
    c = _coord({"sensor.t": "temperature"})
    _roc_raise(c, clock)
    await _feed(c, "sensor.t", 95.0)
    assert "overheat:Garage:roc" in c._active_hazards
    _tick(c, clock, 60)  # window no longer spans 1800 s → get_rate None
    assert c._rate_detector.get_rate("sensor.t", clock.now) is None
    assert "overheat:Garage:roc" in c._hazard_clear_pending
    _tick(c, clock, 300)
    assert "overheat:Garage:roc" not in c._active_hazards


test_safety_roc_clear_after_quiet_window = test_safety_roc_clears_on_get_rate_none


@pytest.mark.asyncio
async def test_safety_roc_clears_on_recomputed_rate_below_fraction(clock):
    c = _coord({"sensor.t": "temperature"})
    _roc_raise(c, clock)
    await _feed(c, "sensor.t", 95.0)  # raise_rate 25
    hist = c._rate_detector._history["sensor.t"]
    hist.clear()
    # Recomputed rate 12 (< 25 x 0.5) over an exact 1800 s window ending now.
    clock.advance(60)
    hist.append((clock.now - timedelta(seconds=1800), 83.0))
    hist.append((clock.now, 95.0))
    _tick(c, clock, 0)
    assert "overheat:Garage:roc" in c._hazard_clear_pending
    # Rate 13 (>= 12.5) would NOT have recovered — boundary discriminator.
    c2 = _coord({"sensor.t": "temperature"})
    _roc_raise(c2, clock)
    await _feed(c2, "sensor.t", 95.0)
    h2 = c2._rate_detector._history["sensor.t"]
    h2.clear()
    h2.append((clock.now - timedelta(seconds=1800), 82.0))
    h2.append((clock.now, 95.0))
    _tick(c2, clock, 0)
    assert "overheat:Garage:roc" not in c2._hazard_clear_pending


@pytest.mark.asyncio
async def test_safety_roc_clears_on_z_score_below_fraction(clock):
    c = _coord({"sensor.t": "temperature"})
    b = c._rate_detector._get_rate_baseline("sensor.t")
    for i in range(80):
        b.update(0.0 if i % 2 else 2.0)  # mean 1, std ~1
    _roc_raise(c, clock)
    await _feed(c, "sensor.t", 82.0)  # rate 12 → z ~11 → CRITICAL ROC
    h = c._active_hazards["overheat:Garage:roc"]
    assert h.raise_z is not None and h.raise_rate is None
    hist = c._rate_detector._history["sensor.t"]
    hist.clear()
    hist.append((clock.now - timedelta(seconds=1800), 80.0))
    hist.append((clock.now, 83.0))  # rate 3 → z ~2 < raise_z/2
    _tick(c, clock, 0)
    assert "overheat:Garage:roc" in c._hazard_clear_pending
    # Still-high z (rate 12 again) does not recover.
    c._hazard_clear_pending.clear()
    c._hazard_raising_sensors["overheat:Garage:roc"] = {"sensor.t"}
    hist.clear()
    hist.append((clock.now - timedelta(seconds=1800), 70.0))
    hist.append((clock.now, 82.0))
    _tick(c, clock, 0)
    assert "overheat:Garage:roc" not in c._hazard_clear_pending


@pytest.mark.asyncio
async def test_safety_roc_clears_on_stale_sample_safety_net(clock):
    c = _coord({"sensor.t": "temperature"})
    _roc_raise(c, clock)
    await _feed(c, "sensor.t", 95.0)
    last = clock.now
    # get_rate keeps returning a high (aged) rate; only staleness can clear.
    with patch.object(c._rate_detector, "get_rate", return_value=25.0):
        clock.advance(899)
        _tick(c, clock, 0)
        assert "overheat:Garage:roc" not in c._hazard_clear_pending
        _tick(c, clock, 1)
        assert (clock.now - last).total_seconds() == 900
        assert "overheat:Garage:roc" in c._hazard_clear_pending


@pytest.mark.asyncio
async def test_safety_periodic_sweep_clears_steady_in_range_sensor(clock):
    c = _coord({"sensor.t": "temperature"})
    await _feed(c, "sensor.t", 44.0)
    await _feed(c, "sensor.t", 48.5)  # final state change, never changes again
    _tick(c, clock, 299)
    assert "freeze_risk:Garage" in c._active_hazards
    _tick(c, clock, 1)  # only the periodic check runs
    assert "freeze_risk:Garage" not in c._active_hazards


@pytest.mark.asyncio
async def test_safety_sweep_runs_while_leak_sensor_active(clock):
    """Sweep sits OUTSIDE the `if self._active_leak_sensors` guard."""
    c = _coord({"sensor.t": "temperature"},
               binary={"binary_sensor.leak": HazardType.WATER_LEAK.value})
    await _feed(c, "binary_sensor.leak", "on")
    await _feed(c, "sensor.t", 44.0)
    await _feed(c, "sensor.t", 48.5)
    _tick(c, clock, 300)
    assert "freeze_risk:Garage" not in c._active_hazards
    assert "water_leak:Garage" in c._active_hazards


# ---------------------------------------------------------------------------
# D6 — CO2 / TVOC / CO
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_co2_hysteresis_single_signal_under_threshold_flap(clock, signals):
    c = _coord({"sensor.co2": "co2"})
    for i in range(42):  # 00:04-00:11 at 10 s
        await _feed(c, "sensor.co2", [1500.0, 1502.0, 1499.0, 1501.0][i % 4])
        assert "high_co2:Garage" in c._active_hazards
        _tick(c, clock, 10)
    assert len(signals) == 1


@pytest.mark.asyncio
async def test_safety_co2_log_only_rung_does_not_pop_inside_hysteresis_band(clock, signals):
    c = _coord({"sensor.co2": "co2"})
    for _ in range(4):
        await _feed(c, "sensor.co2", 1510.0)
        clock.advance(10)
        await _feed(c, "sensor.co2", 1490.0)
        assert "high_co2:Garage" in c._active_hazards
        clock.advance(10)
    _tick(c, clock, 3600)
    assert "high_co2:Garage" in c._active_hazards
    assert len(signals) == 1


@pytest.mark.asyncio
async def test_safety_co2_clear_via_log_only_recovery_below_offset(clock):
    c = _coord({"sensor.co2": "co2"})
    await _feed(c, "sensor.co2", 1510.0)
    await _feed(c, "sensor.co2", 1401.0)
    _tick(c, clock, 600)
    assert "high_co2:Garage" in c._active_hazards
    await _feed(c, "sensor.co2", 1400.0)
    _tick(c, clock, 300)
    assert "high_co2:Garage" not in c._active_hazards


@pytest.mark.asyncio
async def test_safety_co2_clear_via_severity_none_path(clock):
    c = _coord({"sensor.co2": "co2"})
    await _feed(c, "sensor.co2", 1510.0)
    await _feed(c, "sensor.co2", 950.0)
    _tick(c, clock, 299)
    assert "high_co2:Garage" in c._active_hazards
    _tick(c, clock, 1)
    assert "high_co2:Garage" not in c._active_hazards


@pytest.mark.asyncio
async def test_safety_tvoc_clear_requires_offset_and_hold(clock):
    c = _coord({"sensor.v": "tvoc"})
    await _feed(c, "sensor.v", 1600.0)
    assert "high_tvoc:Garage" in c._active_hazards
    await _feed(c, "sensor.v", 201.0)  # severity None, inside band (200)
    _tick(c, clock, 600)
    assert "high_tvoc:Garage" in c._active_hazards
    await _feed(c, "sensor.v", 200.0)
    _tick(c, clock, 300)
    assert "high_tvoc:Garage" not in c._active_hazards


@pytest.mark.asyncio
async def test_safety_co_clear_requires_offset_and_hold(clock):
    c = _coord({"sensor.co": "co"})
    await _feed(c, "sensor.co", 30.0)
    await _feed(c, "sensor.co", 24.0)  # inside band (23)
    _tick(c, clock, 600)
    assert "carbon_monoxide:Garage" in c._active_hazards
    await _feed(c, "sensor.co", 23.0)
    _tick(c, clock, 299)
    assert "carbon_monoxide:Garage" in c._active_hazards
    _tick(c, clock, 1)
    assert "carbon_monoxide:Garage" not in c._active_hazards


# ---------------------------------------------------------------------------
# D8 — unavailable / removed contributors
# ---------------------------------------------------------------------------

def _unavail_event(eid, state="unavailable"):
    return SimpleNamespace(data={"entity_id": eid,
                                 "new_state": SimpleNamespace(state=state),
                                 "old_state": SimpleNamespace(state="on")})


@pytest.mark.asyncio
async def test_safety_smoke_keeps_key_when_sensor_unavailable(clock):
    c = _coord({}, binary={"binary_sensor.smoke": HazardType.SMOKE.value})
    await _feed(c, "binary_sensor.smoke", "on")
    c._test_states["binary_sensor.smoke"] = SimpleNamespace(state="unavailable")
    c._async_sensor_state_changed(_unavail_event("binary_sensor.smoke"))
    for _ in range(31):
        _tick(c, clock, 60)
    assert "smoke:Garage" in c._active_hazards
    assert c.is_hazard_active("smoke", "Garage")


@pytest.mark.asyncio
async def test_safety_humidity_drops_contributor_after_unavailable_window(clock):
    c = _coord({"sensor.a": "humidity", "sensor.b": "humidity"})
    await _feed(c, "sensor.a", 29.0)
    await _feed(c, "sensor.b", 29.0)
    await _feed(c, "sensor.b", 40.0)
    c._test_states["sensor.a"] = SimpleNamespace(state="unavailable")
    c._async_sensor_state_changed(_unavail_event("sensor.a"))
    _tick(c, clock, 899)
    assert c._hazard_raising_sensors["low_humidity:Garage"] == {"sensor.a"}
    _tick(c, clock, 1)
    assert c._hazard_raising_sensors["low_humidity:Garage"] == set()
    _tick(c, clock, 299)
    assert "low_humidity:Garage" in c._active_hazards
    _tick(c, clock, 1)
    assert "low_humidity:Garage" not in c._active_hazards


@pytest.mark.asyncio
async def test_safety_unavailable_contributor_restored_before_window_resumes_normally(clock):
    c = _coord({"sensor.a": "humidity"})
    await _feed(c, "sensor.a", 29.0)
    c._test_states["sensor.a"] = SimpleNamespace(state="unavailable")
    c._async_sensor_state_changed(_unavail_event("sensor.a"))
    _tick(c, clock, 600)
    assert "sensor.a" in c._sensor_unavailable_since
    await _feed(c, "sensor.a", 29.0)  # back, still in hazard
    assert "sensor.a" not in c._sensor_unavailable_since
    _tick(c, clock, 600)  # 1200 s since first unavailable
    assert c._hazard_raising_sensors["low_humidity:Garage"] == {"sensor.a"}
    assert "low_humidity:Garage" in c._active_hazards


@pytest.mark.asyncio
async def test_safety_unavailable_since_stamped_at_state_handler_early_return(clock):
    c = _coord({"sensor.a": "humidity", "sensor.x": "humidity"})
    await _feed(c, "sensor.a", 29.0)
    c._async_sensor_state_changed(_unavail_event("sensor.a"))
    assert c._sensor_unavailable_since["sensor.a"] == T0
    c._async_sensor_state_changed(_unavail_event("sensor.x"))  # not contributing
    assert "sensor.x" not in c._sensor_unavailable_since


@pytest.mark.asyncio
async def test_safety_unavailable_since_stamped_by_sweep_when_entity_removed(clock):
    c = _coord({"sensor.b": "humidity"})
    await _feed(c, "sensor.b", 29.0)
    del c._test_states["sensor.b"]  # removed, no state_changed emitted
    _tick(c, clock, 60)
    assert c._sensor_unavailable_since["sensor.b"] == T0 + timedelta(seconds=60)


# ---------------------------------------------------------------------------
# §4-K / §5 — manual clear + teardown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_clear_hazard_pops_roc_and_bookkeeping(clock):
    c = _coord({"sensor.t": "temperature"})
    _roc_raise(c, clock)
    await _feed(c, "sensor.t", 101.0)
    c._sensor_unavailable_since["sensor.t"] = T0
    assert {"overheat:Garage", "overheat:Garage:roc"} <= set(c._active_hazards)
    c.clear_hazard(HazardType.OVERHEAT, LOC)
    left = [k for k in (*c._active_hazards, *c._hazard_raising_sensors)
            if k.startswith("overheat:")]
    assert left == []
    assert "sensor.t" not in c._sensor_unavailable_since


@pytest.mark.asyncio
async def test_safety_clear_all_and_teardown_clear_new_dicts(clock):
    c = _coord({"sensor.t": "temperature"})
    await _feed(c, "sensor.t", 44.0)
    await _feed(c, "sensor.t", 48.5)
    c._sensor_unavailable_since["sensor.t"] = T0
    c.clear_all_hazards()
    assert not (c._hazard_raising_sensors or c._hazard_clear_pending
                or c._sensor_unavailable_since)
    await _feed(c, "sensor.t", 44.0)
    await _feed(c, "sensor.t", 48.5)
    c._sensor_unavailable_since["sensor.t"] = T0
    await c.async_teardown()
    assert not (c._hazard_raising_sensors or c._hazard_clear_pending
                or c._sensor_unavailable_since)


# ---------------------------------------------------------------------------
# Per-site anchors (drill-driven)
# ---------------------------------------------------------------------------

def _return_from_unavailable(c, eid, value):
    """Recovery-event path: handler runs via _evaluate_sensor_on_recovery
    with NO _respond_to_hazard (no manager in hass.data)."""
    c._test_states[eid] = SimpleNamespace(state=str(value), attributes={})
    c._async_sensor_state_changed(SimpleNamespace(data={
        "entity_id": eid,
        "new_state": SimpleNamespace(state=str(value)),
        "old_state": SimpleNamespace(state="unavailable"),
    }))


@pytest.mark.asyncio
async def test_safety_co2_band_reading_cancels_pending_clear(clock):
    c = _coord({"sensor.co2": "co2"})
    await _feed(c, "sensor.co2", 1510.0)
    await _feed(c, "sensor.co2", 1390.0)
    assert "high_co2:Garage" in c._hazard_clear_pending
    clock.advance(100)
    await _feed(c, "sensor.co2", 1450.0)  # log-only rung, inside band
    assert "high_co2:Garage" not in c._hazard_clear_pending
    _tick(c, clock, 300)
    assert "high_co2:Garage" in c._active_hazards


@pytest.mark.asyncio
async def test_safety_co2_below_log_only_ceiling_clears_via_medium_anchor(clock):
    c = _coord({"sensor.co2": "co2"})
    await _feed(c, "sensor.co2", 1510.0)
    await _feed(c, "sensor.co2", 1150.0)  # < co2_low 1200 → severity None
    _tick(c, clock, 300)
    assert "high_co2:Garage" not in c._active_hazards


@pytest.mark.asyncio
async def test_safety_freeze_relapse_on_recovery_event_cancels_pending(clock):
    c = _coord({"sensor.t": "temperature"})
    await _feed(c, "sensor.t", 44.0)
    await _feed(c, "sensor.t", 48.5)
    clock.advance(100)
    _return_from_unavailable(c, "sensor.t", 44.0)
    assert "freeze_risk:Garage" not in c._hazard_clear_pending
    _tick(c, clock, 300)
    assert "freeze_risk:Garage" in c._active_hazards


@pytest.mark.asyncio
async def test_safety_low_humidity_relapse_on_recovery_event_cancels_pending(clock):
    c = _coord({"sensor.h": "humidity"})
    await _feed(c, "sensor.h", 29.0)
    await _feed(c, "sensor.h", 35.0)
    clock.advance(100)
    _return_from_unavailable(c, "sensor.h", 28.0)
    _tick(c, clock, 300)
    assert "low_humidity:Garage" in c._active_hazards


@pytest.mark.asyncio
async def test_safety_high_humidity_back_above_low_cancels_pending(clock):
    c = _coord({"sensor.h": "humidity"})
    await _feed(c, "sensor.h", 86.0)
    clock.advance(2 * 3600 + 1)
    await _feed(c, "sensor.h", 86.0)
    await _feed(c, "sensor.h", 75.0)
    clock.advance(100)
    await _feed(c, "sensor.h", 80.0)  # >= low 78, no hazard returned
    _tick(c, clock, 300)
    assert "high_humidity:Garage" in c._active_hazards


@pytest.mark.asyncio
async def test_safety_leak_rewet_keeps_key_after_hold(clock):
    c = _coord({}, binary={"binary_sensor.leak": HazardType.WATER_LEAK.value})
    await _feed(c, "binary_sensor.leak", "on")
    await _feed(c, "binary_sensor.leak", "off")
    clock.advance(60)
    await _feed(c, "binary_sensor.leak", "on")
    _tick(c, clock, 600)
    assert "water_leak:Garage" in c._active_hazards


@pytest.mark.asyncio
async def test_safety_repeated_clear_readings_do_not_restart_hold(clock):
    c = _coord({"sensor.t": "temperature"})
    await _feed(c, "sensor.t", 44.0)
    for v in (48.5, 49.0, 49.5, 50.0, 50.5, 51.0):
        await _feed(c, "sensor.t", v)
        _tick(c, clock, 60)
    assert "freeze_risk:Garage" not in c._active_hazards


@pytest.mark.asyncio
async def test_safety_in_band_return_from_unavailable_is_not_dropped(clock):
    c = _coord({"sensor.t": "temperature"})
    await _feed(c, "sensor.t", 44.0)
    c._test_states["sensor.t"] = SimpleNamespace(state="unavailable")
    c._async_sensor_state_changed(_unavail_event("sensor.t"))
    clock.advance(60)
    _return_from_unavailable(c, "sensor.t", 46.0)  # band: no recovery/relapse
    for _ in range(25):
        _tick(c, clock, 60)
    assert c._hazard_raising_sensors["freeze_risk:Garage"] == {"sensor.t"}
    assert "freeze_risk:Garage" in c._active_hazards


# ---------------------------------------------------------------------------
# Review fix-up (A MED + C must/should-fix)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_flooding_escalation_on_rewet_keeps_water_leak_key(clock):
    """Review A repro: B dry→pending, A wet, B re-wets in hold → FLOODING."""
    c = _coord({}, binary={"binary_sensor.b": HazardType.WATER_LEAK.value,
                           "binary_sensor.a": HazardType.WATER_LEAK.value})
    c._sensor_locations["binary_sensor.b"] = "laundry"
    c._sensor_locations["binary_sensor.a"] = "kitchen"
    await _feed(c, "binary_sensor.b", "on")
    await _feed(c, "binary_sensor.b", "off")
    assert "water_leak:laundry" in c._hazard_clear_pending
    await _feed(c, "binary_sensor.a", "on")
    clock.advance(60)
    await _feed(c, "binary_sensor.b", "on")  # escalates to FLOODING
    assert any(k.startswith("flooding:") for k in c._active_hazards)
    assert "water_leak:laundry" not in c._hazard_clear_pending
    _tick(c, clock, 600)
    assert "water_leak:laundry" in c._active_hazards


@pytest.mark.asyncio
@pytest.mark.parametrize("htype", [HazardType.SMOKE, HazardType.WATER_LEAK])
async def test_safety_binary_two_sensors_first_dry_keeps_key(clock, htype):
    c = _coord({}, binary={"binary_sensor.x": htype.value,
                           "binary_sensor.y": htype.value})
    key = f"{htype.value}:Garage"
    await _feed(c, "binary_sensor.x", "on")
    await _feed(c, "binary_sensor.y", "on")  # same severity / flooding
    await _feed(c, "binary_sensor.x", "off")
    _tick(c, clock, 600)
    assert key in c._active_hazards
    assert c._hazard_raising_sensors[key] == {"binary_sensor.y"}


@pytest.mark.asyncio
async def test_safety_rewet_then_dry_holds_full_window_from_second_dry(clock):
    c = _coord({}, binary={"binary_sensor.leak": HazardType.WATER_LEAK.value})
    await _feed(c, "binary_sensor.leak", "on")
    await _feed(c, "binary_sensor.leak", "off")
    clock.advance(200)
    await _feed(c, "binary_sensor.leak", "on")
    clock.advance(50)
    await _feed(c, "binary_sensor.leak", "off")
    _tick(c, clock, 299)
    assert "water_leak:Garage" in c._active_hazards
    _tick(c, clock, 1)
    assert "water_leak:Garage" not in c._active_hazards


@pytest.mark.asyncio
async def test_safety_life_safety_repeat_raise_without_pending_does_not_rerun(clock, signals):
    c = _coord({"sensor.co": "co"},
               binary={"binary_sensor.leak": HazardType.WATER_LEAK.value})
    assert len(_valve_closes(await _feed(c, "binary_sensor.leak", "on"))) == 1
    clock.advance(30)
    assert _valve_closes(await _feed(c, "binary_sensor.leak", "on")) == []
    await _feed(c, "sensor.co", 60.0)
    await _feed(c, "sensor.co", 61.0)  # same severity, no pending
    assert len(signals) == 2  # leak once + CO once
    s = SafetyCoordinator(make_hass(), emergency_lights=["light.hall"])
    s._binary_sensors["binary_sensor.smoke"] = HazardType.SMOKE.value
    s._sensor_locations["binary_sensor.smoke"] = LOC
    lights = []
    for _ in range(2):
        acts = await s.evaluate([Intent(source="state_change",
                                        entity_id="binary_sensor.smoke",
                                        data={"state": "on"})], {})
        lights += [a for a in acts if getattr(a, "service", None) == "light.turn_on"]
    assert len(lights) == 1


@pytest.mark.asyncio
async def test_safety_overheat_relapse_on_recovery_event_cancels_pending(clock):
    c = _coord({"sensor.t": "temperature"})
    await _feed(c, "sensor.t", 101.0)
    await _feed(c, "sensor.t", 96.0)
    assert "overheat:Garage" in c._hazard_clear_pending
    clock.advance(100)
    _return_from_unavailable(c, "sensor.t", 101.0)
    _tick(c, clock, 300)
    assert "overheat:Garage" in c._active_hazards


@pytest.mark.asyncio
@pytest.mark.parametrize("type_value,drops", [
    ("high_humidity", True), ("low_humidity", True), ("freeze_risk", True),
    ("overheat", True), ("high_co2", True), ("high_tvoc", True),
    ("hvac_failure", True), ("smoke", False), ("carbon_monoxide", False),
    ("water_leak", False), ("flooding", False),
])
async def test_safety_unavailable_drop_policy_per_type(clock, type_value, drops):
    c = _coord({})
    key = f"{type_value}:Garage"
    c._active_hazards[key] = Hazard(
        type=HazardType(type_value), severity=Severity.MEDIUM, confidence=1,
        location=LOC, sensor_id="sensor.gone", value=1, threshold=1,
        detected_at=T0, message="m")
    c._hazard_raising_sensors[key] = {"sensor.gone"}  # not in state machine
    _tick(c, clock, 0)
    _tick(c, clock, 899)
    assert c._hazard_raising_sensors[key] == {"sensor.gone"}
    _tick(c, clock, 1)
    assert (c._hazard_raising_sensors[key] == set()) is drops
    _tick(c, clock, 300)
    assert (key not in c._active_hazards) is drops
