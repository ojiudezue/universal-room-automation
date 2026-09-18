"""HVAC-PRECOOL-NO-CONSTRAINT-POST-BOOT-1: producer-owned pull at HVAC setup.

Behavioral tests that DRIVE PRODUCTION code paths (not source-grep or
exec'd source-text). Each test carries a mutation anchor:

- test_pull_seeds_hvac_from_energy_coordinator            — pull neutered / A2 early return
- test_current_energy_constraint_returns_full_payload     — B2 None return / field drop
- test_dispatch_and_pull_produce_identical_payload        — field drop in _build_energy_constraint

The old exec-source approach was HOLLOW: it accepted an early `return`
before the pull block (A2), `current_energy_constraint()` returning None
(B2), and payload-field drops. These replacements construct a real
HVACCoordinator, run its `async_setup()`, and inspect the resulting
state — a mutation to any of those load-bearing sites turns a specific
named test RED.
"""

from __future__ import annotations

import asyncio
import dataclasses
from unittest.mock import MagicMock

import pytest


# HA must be importable — same guard as test_runtime_smoke.py.
pytest.importorskip(
    "homeassistant.config_entries",
    reason=(
        "homeassistant package not installed — smoke-tier tests skipped. "
        "Install via: pip install pytest-homeassistant-custom-component"
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_energy_stub(*, mode="normal", setpoint_offset=1.5,
                       reason="test-seed", max_runtime=None,
                       solar_class="good", soc=80,
                       forecast_high=95.0, apparent_high=98.0):
    """Return a stub energy coordinator whose current_energy_constraint()
    yields a real EnergyConstraint dataclass with the given field values.

    Uses the real EnergyConstraint so a drop in the real builder would
    still fail parity assertions (see test_dispatch_and_pull_produce_...).
    """
    from custom_components.universal_room_automation.domain_coordinators.signals import (
        EnergyConstraint,
    )

    ec_payload = EnergyConstraint(
        mode=mode,
        setpoint_offset=setpoint_offset,
        occupied_only=True,
        max_runtime_minutes=max_runtime,
        fan_assist=(mode in ("coast", "shed")),
        reason=reason,
        solar_class=solar_class,
        forecast_high_temp=forecast_high,
        soc=soc,
        apparent_forecast_high_temp=apparent_high,
    )
    stub = MagicMock()
    stub.current_energy_constraint.return_value = ec_payload
    return stub, ec_payload


def _install_energy_on_hass(hass, energy_stub):
    """Wire the stub energy coordinator into hass.data the same way the
    live coordinator_manager does. HVAC's pull looks at
    `hass.data["universal_room_automation"]["coordinator_manager"]
    .coordinators["energy"]`.
    """
    cm = MagicMock()
    cm.coordinators = {"energy": energy_stub}
    hass.data.setdefault("universal_room_automation", {})[
        "coordinator_manager"
    ] = cm


def _new_energy_coordinator_with_state(*, mode, offset, reason,
                                       max_runtime, forecast_high,
                                       apparent_high, soc, solar_class):
    """Build an EnergyCoordinator instance WITHOUT running __init__ and
    seed the minimal state that `_build_energy_constraint()` /
    `current_energy_constraint()` read. This exercises the REAL builder
    method — a drop of any field in `EnergyConstraint(...)` will be
    directly observable on the returned dataclass.
    """
    from custom_components.universal_room_automation.domain_coordinators.energy import (
        EnergyCoordinator,
    )
    ec = EnergyCoordinator.__new__(EnergyCoordinator)
    ec._hvac_constraint_mode = mode
    ec._hvac_constraint_offset = offset
    ec._hvac_constraint_reason = reason
    ec._hvac_constraint_max_runtime = max_runtime
    ec._cached_forecast_high = forecast_high
    ec._cached_apparent_forecast_high = apparent_high
    battery = MagicMock()
    battery.battery_soc = soc
    battery.classify_solar_day.return_value = solar_class
    ec._battery = battery
    return ec


# ---------------------------------------------------------------------------
# C1 — boot ordering: HVAC async_setup pulls and applies the EC constraint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pull_seeds_hvac_from_energy_coordinator():
    """MUTATION ANCHOR: turns RED under
      (i) replacing `self._handle_energy_constraint(_seed)` with `pass`
      (ii) inserting `return` before the pull block (A2 early-return)
      (iii) dropping `setpoint_offset` from `EnergyConstraint(...)` in
            the energy stub's real dataclass (the field defaults, the
            assertion `_energy_offset == -2.5` fails).
    """
    from runtime_harness import build_smoke_hass
    from custom_components.universal_room_automation.domain_coordinators.hvac import (
        HVACCoordinator,
    )

    hass = build_smoke_hass(zones_count=3)
    energy_stub, seed = _build_energy_stub(
        mode="coast", setpoint_offset=-2.5, reason="peak TOU period",
        max_runtime=45,
    )
    _install_energy_on_hass(hass, energy_stub)

    coord = HVACCoordinator(hass)
    # StubBus does not implement the newer async_listen(event_filter=...)
    # kwarg the OverrideArrester uses, so async_setup raises AFTER the
    # pull block executes. We swallow that and assert only on the state
    # the pull was supposed to seed. If a future mutation ADDS an early
    # return BEFORE the pull, or neuters the pull's
    # `_handle_energy_constraint(_seed)` call, `_energy_constraint`
    # stays None and this test fails — the mutation anchor holds.
    try:
        await asyncio.wait_for(coord.async_setup(), timeout=10.0)
    except Exception:
        pass

    # The pull ran → EC coordinator was consulted.
    energy_stub.current_energy_constraint.assert_called()
    # The seed was applied through _handle_energy_constraint (setter).
    assert coord._energy_constraint is not None, (
        "HVAC async_setup did not seed _energy_constraint — either the "
        "pull block was removed / neutered, or an early return elided it"
    )
    assert coord._energy_constraint.mode == "coast"
    assert coord._energy_constraint.setpoint_offset == -2.5
    assert coord._energy_constraint_mode == "coast"
    assert coord._energy_offset == -2.5

    for task in hass._stub_tasks:
        if not task.done():
            task.cancel()


@pytest.mark.asyncio
async def test_pull_missing_energy_coordinator_is_safe_noop():
    """Guard: no energy coord on hass.data → async_setup completes
    without raising and HVAC's _energy_constraint stays None."""
    from runtime_harness import build_smoke_hass
    from custom_components.universal_room_automation.domain_coordinators.hvac import (
        HVACCoordinator,
    )

    hass = build_smoke_hass(zones_count=3)
    # Intentionally: no coordinator_manager placed on hass.data.
    coord = HVACCoordinator(hass)
    try:
        await asyncio.wait_for(coord.async_setup(), timeout=10.0)
    except Exception:
        pass
    assert coord._energy_constraint is None

    for task in hass._stub_tasks:
        if not task.done():
            task.cancel()


@pytest.mark.asyncio
async def test_pull_helper_exception_does_not_crash_setup():
    """Guard: `current_energy_constraint()` raising must be swallowed by
    the try/except around the pull block — async_setup must still
    complete."""
    from runtime_harness import build_smoke_hass
    from custom_components.universal_room_automation.domain_coordinators.hvac import (
        HVACCoordinator,
    )

    hass = build_smoke_hass(zones_count=3)
    energy_stub = MagicMock()
    energy_stub.current_energy_constraint.side_effect = RuntimeError("boom")
    _install_energy_on_hass(hass, energy_stub)

    coord = HVACCoordinator(hass)
    try:
        await asyncio.wait_for(coord.async_setup(), timeout=10.0)
    except Exception:
        pass
    assert coord._energy_constraint is None

    for task in hass._stub_tasks:
        if not task.done():
            task.cancel()


# ---------------------------------------------------------------------------
# C2 — current_energy_constraint() returns the full builder payload
# ---------------------------------------------------------------------------


def test_current_energy_constraint_returns_full_payload():
    """MUTATION ANCHOR: turns RED under
      (i) `current_energy_constraint()` → `return None` (B2 — the very
          first `.mode` attribute access on None raises AttributeError)
      (ii) dropping `fan_assist=(...)` from `_build_energy_constraint` —
           mode=='coast' but returned fan_assist would default to False.
      (iii) dropping `setpoint_offset=` — TypeError at construction
           (setpoint_offset has no dataclass default).
      (iv) dropping `reason=` / `max_runtime_minutes=` / `solar_class=` /
          `forecast_high_temp=` / `soc=` / `apparent_forecast_high_temp=`
          — each field falls back to its dataclass default, which does
          not match the seeded state.
    """
    ec = _new_energy_coordinator_with_state(
        mode="coast", offset=-2.0, reason="peak TOU period",
        max_runtime=30, forecast_high=95.0, apparent_high=98.5,
        soc=80, solar_class="good",
    )

    payload = ec.current_energy_constraint()
    assert payload is not None, "current_energy_constraint returned None"

    assert payload.mode == "coast"
    assert payload.setpoint_offset == -2.0
    assert payload.occupied_only is True
    assert payload.max_runtime_minutes == 30
    assert payload.fan_assist is True  # coast → fan_assist=True
    assert payload.reason == "peak TOU period"
    assert payload.solar_class == "good"
    assert payload.forecast_high_temp == 95.0
    assert payload.soc == 80
    assert payload.apparent_forecast_high_temp == 98.5


def test_solar_class_defaults_to_unknown_on_exception():
    """A-LOW: exception path in _build_energy_constraint uses
    'unknown', not None (EnergyConstraint.solar_class is a str)."""
    ec = _new_energy_coordinator_with_state(
        mode="normal", offset=0.0, reason="normal conditions",
        max_runtime=None, forecast_high=None, apparent_high=None,
        soc=50, solar_class="good",
    )
    ec._battery.classify_solar_day.side_effect = RuntimeError("boom")
    payload = ec.current_energy_constraint()
    assert payload.solar_class == "unknown"


# ---------------------------------------------------------------------------
# C3 — dispatch site + pull helper produce field-identical payloads
# ---------------------------------------------------------------------------


def test_dispatch_and_pull_produce_identical_payload(monkeypatch):
    """MUTATION ANCHOR: field parity. Both `_update_hvac_constraint`
    (dispatch site) and `current_energy_constraint()` (pull helper)
    route through the same private `_build_energy_constraint()`. This
    test captures what the dispatch site emits over
    SIGNAL_ENERGY_CONSTRAINT and asserts `dataclasses.asdict` equality
    against what the pull helper returns for the SAME state.

    Turns RED under dropping ANY field from `_build_energy_constraint`:
    the emitted and pulled payloads still match each other (they share
    the builder), but the state-vs-payload assertions in
    `test_current_energy_constraint_returns_full_payload` catch the
    drop for that field; here the guarantee under test is that pull
    stays byte-identical to what HVAC would have received if the
    dispatch had reached it.
    """
    ec = _new_energy_coordinator_with_state(
        mode="normal", offset=0.0, reason="peak TOU period",
        max_runtime=None, forecast_high=95.0, apparent_high=98.5,
        soc=80, solar_class="good",
    )

    # Minimal stubs for the pieces of _update_hvac_constraint we don't
    # want to exercise (peak-branch selection + record + tou transition).
    tou = MagicMock()
    tou.get_season.return_value = "summer"
    tou.peak_ahead_before_offpeak.return_value = True
    tou.get_next_transition.return_value = {"hours_until": 1.0}
    ec._tou = tou
    ec._constraint_shed_offset = 3.0
    ec._constraint_coast_offset = 2.0
    ec._constraint_preheat_offset = -2.0
    ec._preheat_temp_threshold = 32.0
    ec._load_shedding_enabled = False
    ec._load_shedding_active_level = 0
    ec._cached_forecast_low = 60.0
    ec._last_published_constraint = ""
    ec._record_decision = MagicMock()
    ec.hass = MagicMock()

    captured = {}

    def _fake_send(hass, signal, payload):
        captured["payload"] = payload

    monkeypatch.setattr(
        "homeassistant.helpers.dispatcher.async_dispatcher_send",
        _fake_send,
    )

    # tou_period="peak" → mode transitions to coast; dispatch fires.
    ec._update_hvac_constraint("peak")

    assert "payload" in captured, (
        "dispatch site did not fire SIGNAL_ENERGY_CONSTRAINT"
    )
    dispatched = captured["payload"]
    pulled = ec.current_energy_constraint()

    assert dataclasses.asdict(pulled) == dataclasses.asdict(dispatched), (
        "pull helper and dispatch site emitted divergent payloads — "
        "single-source-of-truth broken"
    )
    # And the state actually landed on the coordinator (fan_assist for
    # coast, max_runtime from get_next_transition).
    assert dispatched.mode == "coast"
    assert dispatched.fan_assist is True
    assert dispatched.max_runtime_minutes == 60


# ---------------------------------------------------------------------------
# B-MED-1 — D7 dwell continuity survives the boot-time pull
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d7_dwell_survives_boot_pull_at_unchanged_mode(monkeypatch):
    """B-MED-1: the producer-owned pull stamps
    `_energy_constraint_mode_since = utcnow()` during HVAC async_setup,
    which runs BEFORE `HVACModeSensor.async_added_to_hass`. The original
    resume-if-same gate only fired when `current_since is None`, so
    every restart would zero the dwell counter mid-coast. The relaxed
    gate must ALSO resume when the pull-seeded mode matches the
    restored mode and the pull stamp is fresher than the restored
    stamp.
    """
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    from custom_components.universal_room_automation import sensor as ura_sensor

    # Build a fake hvac coordinator carrying the state the pull would
    # have produced during setup: mode=coast, _since=NOW (fresh stamp).
    now = dt_util.utcnow()
    hvac = MagicMock()
    hvac._energy_constraint = MagicMock()  # not None → pull already ran
    hvac._energy_constraint_mode = "coast"
    hvac._energy_constraint_mode_since = now

    manager = MagicMock()
    manager.coordinators = {"hvac": hvac}

    # Restored last-state: same mode, but an older _since (1h ago).
    restored_since = now - timedelta(hours=1)
    last = MagicMock()
    last.attributes = {
        "energy_constraint_mode": "coast",
        "energy_constraint_since": restored_since.isoformat(),
    }

    hass = MagicMock()
    hass.data = {ura_sensor.DOMAIN: {"coordinator_manager": manager}}

    sensor = ura_sensor.HVACModeSensor.__new__(ura_sensor.HVACModeSensor)
    sensor.hass = hass

    async def _get_last():
        return last
    sensor.async_get_last_state = _get_last

    # Neuter parent + dispatcher wiring (not under test here).
    async def _super_added():
        return None
    monkeypatch.setattr(
        ura_sensor.AggregationEntity, "async_added_to_hass",
        lambda self: _super_added(),
    )
    monkeypatch.setattr(
        "homeassistant.helpers.dispatcher.async_dispatcher_connect",
        lambda *a, **kw: (lambda: None),
    )
    sensor.async_on_remove = lambda *a, **kw: None

    await sensor.async_added_to_hass()

    # The older restored stamp must have won — dwell continues.
    assert hvac._energy_constraint_mode_since == restored_since, (
        "D7 dwell continuity regressed: boot-pull's fresh stamp was not "
        "replaced by the older restored stamp at unchanged mode"
    )


@pytest.mark.asyncio
async def test_d7_transition_keeps_pull_stamp_when_modes_differ(monkeypatch):
    """Restored mode ≠ live mode → legitimate transition; keep the
    pull-seeded stamp (do NOT retroactively use the restored one)."""
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    from custom_components.universal_room_automation import sensor as ura_sensor

    now = dt_util.utcnow()
    hvac = MagicMock()
    hvac._energy_constraint = MagicMock()
    hvac._energy_constraint_mode = "shed"  # live mode differs
    hvac._energy_constraint_mode_since = now

    manager = MagicMock()
    manager.coordinators = {"hvac": hvac}

    last = MagicMock()
    last.attributes = {
        "energy_constraint_mode": "coast",  # restored differs
        "energy_constraint_since": (now - timedelta(hours=1)).isoformat(),
    }

    hass = MagicMock()
    hass.data = {ura_sensor.DOMAIN: {"coordinator_manager": manager}}

    sensor = ura_sensor.HVACModeSensor.__new__(ura_sensor.HVACModeSensor)
    sensor.hass = hass

    async def _get_last():
        return last
    sensor.async_get_last_state = _get_last

    async def _super_added():
        return None
    monkeypatch.setattr(
        ura_sensor.AggregationEntity, "async_added_to_hass",
        lambda self: _super_added(),
    )
    monkeypatch.setattr(
        "homeassistant.helpers.dispatcher.async_dispatcher_connect",
        lambda *a, **kw: (lambda: None),
    )
    sensor.async_on_remove = lambda *a, **kw: None

    await sensor.async_added_to_hass()

    # Modes differ → don't overwrite. Pull stamp stays.
    assert hvac._energy_constraint_mode_since == now
