"""EC-SELFHEAL-UNEXPLAINED-RESENDS-1 — reserve witness = Envoy sensor.

Plan: docs/planning/PLANNING_ec_reserve_witness_fix.md (rev 2 + plan review
2026-10-18, F1/F2 folded in).

The reserve verifier's local witness (`_local_entity_for(RESERVE)`) used the
Enpower `reserve_soc_number`, which reads only 10.0/unavailable since
2026-08-05. Fix: prefer `sensor` / `enphase_envoy` / `<serial>_reserve_soc`
where serial comes from the configured SOC entity's registry unique_id;
fall back to the number ONLY when the sensor is unresolvable (registry miss,
disabled entry, non-Envoy anchor, registry error) — never on state.

Registry: a fake whose two lookups mirror HA core
`homeassistant/helpers/entity_registry.py:891-906` exactly —
`async_get(entity_id)` returns the entry (or None) and
`async_get_entity_id(domain, platform, unique_id)` is keyed on the
(domain, platform, unique_id) triple and returns DISABLED entries too.
It is installed on the very `entity_registry` module object production
imports (monkeypatch, restored per test); the resolver is NOT stubbed.
Oracles are independently stated house facts (serials and unique_ids read
from the live registry 2026-10-18, see plan review §2), never re-derived.
"""
from __future__ import annotations

import test_energy_write_verification  # noqa: F401 — side-effect HA bootstrap

import logging
from datetime import timedelta
from typing import Any, Optional

import pytest

from conftest import MockHass, MockState

from custom_components.universal_room_automation.domain_coordinators import (
    energy_write_verify as ewv,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_PENDING_ATTEMPT_1_AGE_S,
    CONF_PENDING_ATTEMPT_2_AGE_S,
    CONF_PENDING_ATTEMPT_3_AGE_S,
)

SURFACE = "reserve_soc"
CFG_SURFACE = "charge_from_grid"
SM_SURFACE = "storage_mode"

# Live house facts (plan review §2).
ENVOY_SERIAL = "482543015950"
SOC_EID = "sensor.envoy_482543015950_battery"
SENSOR_EID = "sensor.envoy_482543015950_reserve_battery_level"
NUMBER_EID = "number.enpower_482348004678_reserve_battery_level"
CFG_EID = "switch.enpower_482348004678_charge_from_grid"
SM_EID = "select.enpower_482348004678_storage_mode"


# ------------------------------------------------------------------
# Registry fake mirroring HA's lookup semantics (see module docstring).
# ------------------------------------------------------------------
class _Entry:
    def __init__(self, entity_id, platform, unique_id, disabled_by=None):
        self.entity_id = entity_id
        self.domain = entity_id.split(".", 1)[0]
        self.platform = platform
        self.unique_id = unique_id
        self.disabled_by = disabled_by


class _Registry:
    def __init__(self):
        self._by_eid: dict[str, _Entry] = {}
        self._by_key: dict[tuple, str] = {}
        self.raise_on_get = False

    def add(self, entity_id, platform, unique_id, disabled_by=None):
        e = _Entry(entity_id, platform, unique_id, disabled_by)
        self._by_eid[entity_id] = e
        self._by_key[(e.domain, platform, unique_id)] = entity_id
        return e

    def async_get(self, entity_id):
        if self.raise_on_get:
            raise RuntimeError("registry boom")
        return self._by_eid.get(entity_id)

    def async_get_entity_id(self, domain, platform, unique_id):
        return self._by_key.get((domain, platform, unique_id))


def _house_registry(*, sensor=True, sensor_disabled=None, anchor_platform="enphase_envoy"):
    reg = _Registry()
    reg.add(SOC_EID, anchor_platform, f"{ENVOY_SERIAL}_battery_level")
    if sensor:
        reg.add(
            SENSOR_EID, "enphase_envoy", f"{ENVOY_SERIAL}_reserve_soc",
            disabled_by=sensor_disabled,
        )
    # Enpower number: same `_reserve_soc` suffix, different serial (live).
    reg.add(NUMBER_EID, "enphase_envoy", "482348004678_reserve_soc")
    return reg


@pytest.fixture
def install_registry(monkeypatch):
    from homeassistant.helpers import entity_registry as er

    def _install(reg):
        monkeypatch.setattr(er, "async_get", lambda hass: reg, raising=False)
        return reg
    return _install


# ------------------------------------------------------------------
# Battery / coordinator stubs
# ------------------------------------------------------------------
class _Bat:
    def __init__(self, hass):
        self.hass = hass
        self._entities = {
            "battery_soc": SOC_EID,
            "reserve_soc_number": NUMBER_EID,
            "charge_from_grid": CFG_EID,
            "storage_mode": SM_EID,
        }
        self._last_reserve_level: Optional[int] = None
        self._last_reserve_level_at = None
        self._last_reserve_level_desired: Optional[int] = None
        self._last_charge_from_grid_command = None
        self._last_charge_from_grid_command_at = None
        self._last_storage_mode_command = None
        self._last_storage_mode_command_at = None
        self._last_charge_from_grid_desired = None
        self._last_storage_mode_desired = None
        self._write_failover_by_surface: dict = {}
        self._desired_stamped_at = ewv.dt_util.utcnow()
        self._last_inclement_decision = None
        self._arbitrage_phase = "n/a"
        self.redispatches: list[str] = []

    def _get_entity(self, key, default=None, *, role="read"):
        return self._entities.get(key, default)

    async def force_redispatch(self, surface):
        self.redispatches.append(surface)


class _Coord:
    def __init__(self, hass):
        self.hass = hass
        self._battery = _Bat(hass)
        self.nm_calls: list[dict] = []
        self._evse_battery_hold_active = False
        self._evse_hold_soc = None

    async def _send_nm_alert(self, **kw):
        self.nm_calls.append(kw)


@pytest.fixture
def hass():
    h = MockHass()
    h.data["universal_room_automation"] = {}
    return h


def _set(hass, eid, value, unit="%"):
    attrs = {"unit_of_measurement": unit} if unit else {}
    hass._states[eid] = MockState(eid, str(value), attributes=attrs)


def _verifier(hass):
    coord = _Coord(hass)
    v = ewv.WriteVerifier(hass, coord)
    emitted: list[tuple[str, dict]] = []

    async def _emit(surface, type_str, extra):
        emitted.append((type_str, dict(extra)))
    v._emit_anomaly = _emit  # type: ignore[method-assign]
    return coord, coord._battery, v, emitted


# ==================================================================
# D1 — resolution
# ==================================================================
def test_reserve_witness_prefers_envoy_sensor_via_registry(hass, install_registry):
    install_registry(_house_registry())
    _, _, v, _ = _verifier(hass)
    assert v._local_entity_for(SURFACE) == SENSOR_EID


def test_reserve_witness_falls_back_when_sensor_unregistered(hass, install_registry):
    install_registry(_house_registry(sensor=False))
    _, _, v, _ = _verifier(hass)
    assert v._local_entity_for(SURFACE) == NUMBER_EID


def test_reserve_witness_disabled_sensor_treated_unresolvable(
    hass, install_registry, caplog,
):
    """F1: a disabled entry never gets a state → must fall back (and log
    INFO exactly once per instance), not abstain forever."""
    install_registry(_house_registry(sensor_disabled="user"))
    _, _, v, _ = _verifier(hass)
    with caplog.at_level(logging.INFO, logger=ewv._LOGGER.name):
        assert v._local_entity_for(SURFACE) == NUMBER_EID
        assert v._local_entity_for(SURFACE) == NUMBER_EID
    lines = [r for r in caplog.records if "reserve witness" in r.getMessage()]
    assert len(lines) == 1 and lines[0].levelno == logging.INFO


def test_reserve_witness_ignores_number_domain_same_unique_id(hass, install_registry):
    """The Enpower number carries the `_reserve_soc` suffix; here it even
    shares the Envoy serial. With no sensor registered the resolver must
    NOT pick the number by unique_id — it falls back to the configured
    reserve entity (distinct id here so the two outcomes differ)."""
    reg = _Registry()
    reg.add(SOC_EID, "enphase_envoy", f"{ENVOY_SERIAL}_battery_level")
    reg.add(
        "number.enpower_same_serial_reserve", "enphase_envoy",
        f"{ENVOY_SERIAL}_reserve_soc",
    )
    install_registry(reg)
    _, bat, v, _ = _verifier(hass)
    bat._entities["reserve_soc_number"] = "number.configured_fallback"
    assert v._local_entity_for(SURFACE) == "number.configured_fallback"


def test_reserve_witness_anchor_not_envoy_falls_back(hass, install_registry):
    """SOC anchor from another platform (Wigton / cloud SOC) whose unique_id
    happens to look Envoy-shaped → today's behaviour (the number)."""
    install_registry(_house_registry(anchor_platform="enphase_ev"))
    _, _, v, _ = _verifier(hass)
    assert v._local_entity_for(SURFACE) == NUMBER_EID


def test_reserve_witness_anchor_not_soc_unique_id_falls_back(hass, install_registry):
    """Anchor is an Envoy entity but not the SOC sensor (unique_id
    `<serial>_battery_power`, same length suffix) → no serial derivation,
    fall back."""
    reg = _Registry()
    reg.add(SOC_EID, "enphase_envoy", f"{ENVOY_SERIAL}_battery_power")
    reg.add(SENSOR_EID, "enphase_envoy", f"{ENVOY_SERIAL}_reserve_soc")
    install_registry(reg)
    _, _, v, _ = _verifier(hass)
    assert v._local_entity_for(SURFACE) == NUMBER_EID


def test_reserve_witness_anchor_unset_falls_back(hass, install_registry):
    install_registry(_house_registry())
    _, bat, v, _ = _verifier(hass)
    del bat._entities["battery_soc"]
    assert v._local_entity_for(SURFACE) == NUMBER_EID


def test_reserve_witness_registry_raises_falls_back(hass, install_registry):
    reg = install_registry(_house_registry())
    reg.raise_on_get = True
    _, _, v, _ = _verifier(hass)
    assert v._local_entity_for(SURFACE) == NUMBER_EID


def test_cfg_and_storage_mode_witness_unchanged(hass, install_registry):
    install_registry(_house_registry())
    _, _, v, _ = _verifier(hass)
    assert v._local_entity_for(CFG_SURFACE) == CFG_EID
    assert v._local_entity_for(SM_SURFACE) == SM_EID


# ==================================================================
# D2 — pending watchdog, both directions
# ==================================================================
def _ledger(bat, commanded, at):
    bat._last_reserve_level = commanded
    bat._last_reserve_level_desired = commanded
    bat._last_reserve_level_at = at


@pytest.mark.asyncio
async def test_reserve_witness_unavailable_sensor_abstains_not_fallback(
    hass, install_registry,
):
    """Sensor resolvable but `unavailable`; frozen number reads 10.
    commanded 10 → abstain (a fallback-on-state build CONVERGES on 10 and
    records oracle 10). commanded 30 aged past attempt 1 → abstain, no row
    (a fallback-on-state build fires attempt 1 with oracle 10)."""
    install_registry(_house_registry())
    _set(hass, SENSOR_EID, "unavailable", unit=None)
    _set(hass, NUMBER_EID, 10)
    coord, bat, v, emitted = _verifier(hass)

    _ledger(bat, 10, ewv.dt_util.utcnow() - timedelta(seconds=3700))
    await v._pending_watchdog_reserve(bat)
    assert SURFACE not in v._pending_last_oracle
    assert v._local_reserve_witness_state(bat) == (None, None)

    _ledger(bat, 30, ewv.dt_util.utcnow() - timedelta(seconds=3700))
    await v._pending_watchdog_reserve(bat)
    assert emitted == []
    assert bat.redispatches == []
    assert coord.nm_calls == []
    assert SURFACE not in v._pending_last_oracle


@pytest.mark.asyncio
async def test_watchdog_no_alert_when_envoy_sensor_matches_command(
    hass, install_registry,
):
    """Direction 1: commanded 80, sensor 80 (unit %), number 10, age 3700 s
    → converged: zero rows, zero NM, no stand-down, no witness divergence.
    F2: the sensor's `%` unit must pass `_compare` (no UNIT_MISMATCH)."""
    install_registry(_house_registry())
    _set(hass, SENSOR_EID, 80, unit="%")
    _set(hass, NUMBER_EID, 10)
    coord, bat, v, emitted = _verifier(hass)
    _ledger(bat, 80, ewv.dt_util.utcnow() - timedelta(seconds=3700))

    status, matched = v._compare(SURFACE, 80, 80.0, "%")
    assert (status, matched) == (ewv.STATUS_OK, True)

    await v._pending_watchdog_reserve(bat)
    await v._witness_compare(SURFACE, 80)
    assert emitted == []
    assert coord.nm_calls == []
    assert bat.redispatches == []
    assert v._pending_standdown_at.get(SURFACE) is None
    assert v._pending_last_oracle[SURFACE] == 80.0


@pytest.mark.asyncio
async def test_watchdog_one_point_miss_within_deadband_tolerance_is_converged(
    hass, install_registry,
):
    """Policy pin (operator: keep ±2): commanded 10, sensor 9 → converged."""
    install_registry(_house_registry())
    _set(hass, SENSOR_EID, 9)
    _set(hass, NUMBER_EID, 10)
    coord, bat, v, emitted = _verifier(hass)
    _ledger(bat, 10, ewv.dt_util.utcnow() - timedelta(seconds=3700))
    await v._pending_watchdog_reserve(bat)
    assert emitted == []
    assert v._pending_last_oracle[SURFACE] == 9.0


async def _drive_ladder(v, bat):
    real = ewv.dt_util.utcnow
    t0 = real()
    _ledger(bat, 10, t0 - timedelta(seconds=60))

    def _clock(off):
        ewv.dt_util.utcnow = lambda: t0 + timedelta(seconds=off)
        bat._desired_stamped_at = t0 + timedelta(seconds=off)
    try:
        for age in (
            CONF_PENDING_ATTEMPT_1_AGE_S,
            CONF_PENDING_ATTEMPT_2_AGE_S,
            CONF_PENDING_ATTEMPT_3_AGE_S,
        ):
            _clock(age)
            await v._pending_watchdog_reserve(bat)
    finally:
        ewv.dt_util.utcnow = real


@pytest.mark.asyncio
async def test_watchdog_alerts_when_sensor_diverges_and_frozen_number_equals_command(
    hass, install_registry,
):
    """Direction 2 (10-12/13): commanded 10, battery reserve 14, frozen
    number 10 → attempts 1/2/3 fire; attempt 3 CRITICAL with oracle 14.0;
    stand-down armed. Old code: silent (number 10 == commanded)."""
    install_registry(_house_registry())
    _set(hass, SENSOR_EID, 14)
    _set(hass, NUMBER_EID, 10)
    coord, bat, v, emitted = _verifier(hass)
    await _drive_ladder(v, bat)
    rows = [e for t, e in emitted if t == "pending_write_stuck"]
    assert [r["attempt"] for r in rows] == [1, 2, 3]
    assert rows[2]["severity_class"] == "CRITICAL"
    assert rows[2]["oracle_seen"] == 14.0
    assert len(bat.redispatches) == 3
    assert v._pending_standdown_at.get(SURFACE) is not None


@pytest.mark.asyncio
async def test_pending_stuck_row_carries_hw_witness_entity(hass, install_registry):
    install_registry(_house_registry())
    _set(hass, SENSOR_EID, 14)
    _set(hass, NUMBER_EID, 10)
    _, bat, v, emitted = _verifier(hass)
    await _drive_ladder(v, bat)
    rows = [e for t, e in emitted if t == "pending_write_stuck"]
    assert rows and all(
        r["hw_witness_entity"] == "sensor.envoy_482543015950_reserve_battery_level"
        for r in rows
    )


@pytest.mark.asyncio
async def test_standdown_not_armed_on_matching_sensor(hass, install_registry):
    """Same ladder drive as direction 2 but the sensor matches commanded:
    no stand-down → same-value dispatch is NOT skipped (C5)."""
    install_registry(_house_registry())
    _set(hass, SENSOR_EID, 10)
    _set(hass, NUMBER_EID, 10)
    _, bat, v, emitted = _verifier(hass)
    await _drive_ladder(v, bat)
    assert emitted == []
    assert v._pending_standdown_at.get(SURFACE) is None
    assert v.is_standdown_active_for_value(SURFACE, 10) is False


@pytest.mark.asyncio
async def test_non_envoy_soc_keeps_todays_number_witness(hass, install_registry):
    """INV-W2: non-Envoy SOC anchor → the number is the witness, so a
    commanded 10 with the number at 10 converges exactly as before."""
    install_registry(_house_registry(anchor_platform="span_panel"))
    _set(hass, SENSOR_EID, 14)
    _set(hass, NUMBER_EID, 10)
    _, bat, v, emitted = _verifier(hass)
    await _drive_ladder(v, bat)
    assert emitted == []
    assert v._pending_last_oracle[SURFACE] == 10.0
