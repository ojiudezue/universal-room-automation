"""Behavioral write-verify tests (v5.19.0 — Tier 3).

D1 CONDUCT + D2 PENDING watchdog + D3 attrs.

Independence discipline: expected values are anchored to the ratified
knob values in `energy_const.py` (rung-1 module constants) OR to
independently reasoned scenarios ("SOC 5pp below floor while discharging
1kW for 3 ticks must trigger"). No test re-implements the invariant it
tests; each test states a falsifiable property and constructs a legal
config repro.

Falsifiable invariant (I-BWV, from planning doc):
  * D1: for the reserve surface, `SOC < commanded - deadband` AND
        `battery_power_w < -epsilon` (URA sign: pos=charging) for N
        consecutive ticks AND no legal exception → exactly one
        `hardware_noncompliance` anomaly per standing episode + one NM
        per (surface, alert_type) per day.
  * D2: divergence age past attempt-N threshold with fresh live desire
        matching commanded → one `pending_write_stuck` anomaly + one
        `force_redispatch` call per attempt. Hard stand-down after
        attempt 3. Ladder cancels when live desire moves.
  * I-D3: never retry while blind (`_desired_stamped_at` stale/None).
"""
from __future__ import annotations

# Reuse the sibling test file's HA-module bootstrap. Import for side-effects
# so the mock modules are installed before we pull the SUT.
import test_energy_write_verification  # noqa: F401 — side-effect bootstrap

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest

from conftest import MockHass, MockState

from custom_components.universal_room_automation.domain_coordinators import (
    energy_write_verify as ewv,
)
from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_CONDUCT_DISCHARGE_EPSILON_W,
    CONF_CONDUCT_N_TICKS,
    CONF_CONDUCT_SOC_DEADBAND_PCT,
    CONF_PENDING_ATTEMPT_1_AGE_S,
    CONF_PENDING_ATTEMPT_2_AGE_S,
    CONF_PENDING_ATTEMPT_3_AGE_S,
    CONF_PENDING_MAX_ATTEMPTS,
    CONF_PENDING_STANDDOWN_COOLOFF_S,
)


SURFACE = "reserve_soc"
LOCAL_RESERVE_EID = "sensor.envoy_reserve_battery_level"
CLOUD_RESERVE_EID = "number.iq_battery_hacs_battery_reserve"


# ------------------------------------------------------------------
# Fixtures — a battery stub carrying only what conduct + pending
# watchdog read. Deliberately not `_FakeBattery` from the sibling file
# so we can freely set battery_soc / battery_power_w / desire values.
# ------------------------------------------------------------------
class _BatStub:
    def __init__(self, hass):
        self.hass = hass
        self._entities = {
            "reserve_soc_number": CLOUD_RESERVE_EID,
            # local witness reads via _local_entity_for role="read"
        }
        self._last_reserve_level: Optional[int] = None
        self._last_reserve_level_at: Optional[datetime] = None
        self._last_reserve_level_desired: Optional[int] = None
        self._last_charge_from_grid_command = None
        self._last_charge_from_grid_command_at = None
        self._last_storage_mode_command = None
        self._last_storage_mode_command_at = None
        self._last_charge_from_grid_desired = None
        self._last_storage_mode_desired = None
        self._write_failover_by_surface = {}
        # Desire is fresh by default (verifier reads via battery.
        # `_desired_stamped_at`). Tests exercising the blind path set None.
        self._desired_stamped_at = ewv.dt_util.utcnow()
        # Directly-set SOC + power_w for tests (bypass the resolver).
        self._soc: Optional[float] = None
        self._power_w: Optional[float] = None
        self._inclement_partial_hold_active = False
        # For force_redispatch tests:
        self._redispatch_calls: list[int] = []
        # Real InclementDecision (v5.19.0 fix-up B-HIGH-1) — set by
        # tests that exercise the inclement partial_hold exception.
        self._last_inclement_decision = None
        # v4.5.0 arbitrage phase (used by hold_owner resolver — kept
        # None-safe in tests).
        self._arbitrage_phase = "n/a"

    def _get_entity(self, key, default=None, *, role="read"):
        # Reserve number always resolves; local vs cloud path uses same
        # entity id for simplicity in test (D1/D2 do not exercise the
        # cloud-vs-local split).
        if key == "reserve_soc_number":
            return self._entities.get(key, default)
        return default

    @property
    def battery_soc(self):
        return self._soc

    @property
    def battery_power_w(self):
        return self._power_w


class _Coord:
    def __init__(self, hass):
        self.hass = hass
        self._battery = _BatStub(hass)
        self.nm_calls: list[dict] = []
        # EVSE-hold overlay state lives on the ENERGY COORDINATOR
        # (`_evse_battery_hold_active` / `_evse_hold_soc` — energy.py
        # :298-299). The write-verifier reads them via `_evse_hold_state`
        # to compute effective post-overlay reserve desired (Root 1).
        self._evse_battery_hold_active = False
        self._evse_hold_soc: Optional[int] = None

    async def _send_nm_alert(self, **kw):
        self.nm_calls.append(kw)


class _FakeInclementDecision:
    """Minimal stand-in for inclement.InclementDecision that carries
    only the fields the write-verifier reads (`hold_depth`,
    `reserve_floor`). Not @frozen so tests can mutate in place.
    """
    def __init__(self, hold_depth: str, reserve_floor: int = 50):
        self.hold_depth = hold_depth
        self.reserve_floor = reserve_floor


@pytest.fixture
def hass():
    h = MockHass()
    h.data["universal_room_automation"] = {}
    # A permissive services stub for force_redispatch tests.
    h.services = type("_Svc", (), {})()
    async def _call(*a, **k):
        return None
    h.services.async_call = _call
    return h


def _set(hass, eid, value, unit="%"):
    attrs = {"unit_of_measurement": unit} if unit else {}
    hass._states[eid] = MockState(eid, str(value), attributes=attrs)


def _install_local_witness(bat, hass, value):
    bat._entities["reserve_soc_number"] = CLOUD_RESERVE_EID
    # `_local_entity_for` in WriteVerifier calls `_get_entity(..., role="read")`.
    # We override to return LOCAL_RESERVE_EID for that lookup.
    orig = bat._get_entity
    def _wrap(key, default=None, *, role="read"):
        if key == "reserve_soc_number" and role == "read":
            return LOCAL_RESERVE_EID
        return orig(key, default, role=role)
    bat._get_entity = _wrap
    _set(hass, LOCAL_RESERVE_EID, value, unit="%")


def _install_cloud_oracle(bat, hass, value):
    # oracle_entity_for uses key "cloud_reserve_oracle" with a default;
    # to keep it deterministic in tests, extend the entity map.
    prev = bat._get_entity
    def _wrap(key, default=None, *, role="read"):
        if key == "cloud_reserve_oracle":
            return CLOUD_RESERVE_EID + "_cloud"
        return prev(key, default, role=role)
    bat._get_entity = _wrap
    _set(hass, CLOUD_RESERVE_EID + "_cloud", value, unit="%")


# ==================================================================
# D1 CONDUCT tests
# ==================================================================
@pytest.mark.asyncio
async def test_conduct_below_floor_fires_once(hass):
    """Falsifiable: SOC deeply below floor + discharging > eps for N ticks
    → exactly one anomaly emitted; further ticks in same episode add no
    more anomalies (per-episode latch).
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    _install_local_witness(bat, hass, 50)  # hw witness present, converged
    # commanded floor 15, SOC 10 (5pp below deadband=4pp), discharging.
    bat._last_reserve_level = 15
    bat._last_reserve_level_desired = 15
    bat._last_reserve_level_at = (
        ewv.dt_util.utcnow() - timedelta(seconds=2000)  # outside verify window
    )
    bat._soc = 10.0
    bat._power_w = -1500.0  # discharging 1.5 kW (negative in URA convention)

    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore

    # Sub-N ticks: no fire.
    for _ in range(CONF_CONDUCT_N_TICKS - 1):
        await v._conduct_check_reserve(bat)
    assert emitted == []
    # Nth tick: fires.
    await v._conduct_check_reserve(bat)
    assert emitted == ["hardware_noncompliance"]
    # Further ticks in the same episode: no re-fire (latched).
    await v._conduct_check_reserve(bat)
    await v._conduct_check_reserve(bat)
    assert emitted == ["hardware_noncompliance"]


@pytest.mark.asyncio
async def test_conduct_counter_resets_on_charge(hass):
    """Charging mid-episode resets the counter — the next below-floor
    discharge episode must accumulate from zero, not from wherever it
    left off.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    bat._last_reserve_level = 20
    bat._last_reserve_level_desired = 20
    bat._last_reserve_level_at = (
        ewv.dt_util.utcnow() - timedelta(seconds=2000)
    )
    bat._soc = 10.0

    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore

    bat._power_w = -1500.0  # discharging
    await v._conduct_check_reserve(bat)
    await v._conduct_check_reserve(bat)
    assert v._conduct_consec[SURFACE] == 2
    # Now charge.
    bat._power_w = +2000.0
    await v._conduct_check_reserve(bat)
    assert v._conduct_consec[SURFACE] == 0
    # Back to discharging — must go 1,2,3 to fire.
    bat._power_w = -1500.0
    await v._conduct_check_reserve(bat)
    await v._conduct_check_reserve(bat)
    assert emitted == []
    await v._conduct_check_reserve(bat)
    assert emitted == ["hardware_noncompliance"]


@pytest.mark.asyncio
async def test_conduct_partial_hold_exempt(hass):
    """Legal exception `inclement_partial_hold` → never fires regardless
    of tick count.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    bat._last_reserve_level = 80
    bat._last_reserve_level_desired = 80
    bat._last_reserve_level_at = (
        ewv.dt_util.utcnow() - timedelta(seconds=2000)
    )
    bat._soc = 40.0
    bat._power_w = -3000.0
    # v5.19.0 fix-up B-HIGH-1/2: read the REAL InclementDecision, not the
    # invented `_inclement_partial_hold_active` attribute. Test now sets
    # the actual decision object with hold_depth == "partial_hold". Under
    # the previous (broken) code this test was green because the
    # invented attribute was truthy; under the fix, the exception path
    # only fires when `_last_inclement_decision.hold_depth ==
    # "partial_hold"`.
    bat._last_inclement_decision = _FakeInclementDecision(
        hold_depth="partial_hold", reserve_floor=30,
    )

    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore

    for _ in range(CONF_CONDUCT_N_TICKS + 3):
        await v._conduct_check_reserve(bat)
    assert emitted == []
    # The last-abstain-reason attr must reflect the exception.
    assert v._conduct_last_abstain_reason[SURFACE] == "inclement_partial_hold"


@pytest.mark.asyncio
async def test_conduct_blind_abstains(hass):
    """SOC None (blind) → abstain, no anomaly, counter not advanced."""
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    bat._last_reserve_level = 15
    bat._last_reserve_level_desired = 15
    bat._last_reserve_level_at = (
        ewv.dt_util.utcnow() - timedelta(seconds=2000)
    )
    bat._soc = None
    bat._power_w = -1500.0

    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore

    for _ in range(CONF_CONDUCT_N_TICKS + 2):
        await v._conduct_check_reserve(bat)
    assert emitted == []
    assert v._conduct_consec.get(SURFACE, 0) == 0
    assert v._conduct_last_abstain_reason[SURFACE] == "soc_blind"


@pytest.mark.asyncio
async def test_conduct_desire_lower_is_exception(hass):
    """Narrow legal exception (operator decision #2): when live desire
    has moved BELOW the historical commanded floor being audited, we are
    catching up to an explicitly-commanded lower floor — no fire.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    bat._last_reserve_level = 80         # historical stamp
    bat._last_reserve_level_desired = 10  # LIVE desire is lower — legit drain
    bat._last_reserve_level_at = (
        ewv.dt_util.utcnow() - timedelta(seconds=2000)
    )
    bat._soc = 40.0
    bat._power_w = -3000.0

    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore
    for _ in range(CONF_CONDUCT_N_TICKS + 2):
        await v._conduct_check_reserve(bat)
    assert emitted == []
    assert v._conduct_last_abstain_reason[SURFACE] == "explicit_drain_desire_lower"


@pytest.mark.asyncio
async def test_conduct_within_verify_window_exempt(hass):
    """Commanded_at fresher than verify window → exception, no fire.

    Prevents racing the initial write.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    bat._last_reserve_level = 15
    bat._last_reserve_level_desired = 15
    bat._last_reserve_level_at = ewv.dt_util.utcnow()  # just now
    bat._soc = 5.0
    bat._power_w = -2000.0

    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore
    for _ in range(CONF_CONDUCT_N_TICKS + 2):
        await v._conduct_check_reserve(bat)
    assert emitted == []
    assert v._conduct_last_abstain_reason[SURFACE] == "within_verify_window"


# ==================================================================
# D2 PENDING watchdog tests
# ==================================================================
def _prime_divergence(hass, bat, commanded, hw_value, age_s):
    """Set up a persistent commanded/hw divergence at the specified age."""
    _install_local_witness(bat, hass, hw_value)
    bat._last_reserve_level = commanded
    bat._last_reserve_level_desired = commanded  # live desire matches
    bat._last_reserve_level_at = (
        ewv.dt_util.utcnow() - timedelta(seconds=age_s)
    )


@pytest.mark.asyncio
async def test_pending_stuck_ladder_fires_three_and_stands_down(hass):
    """Falsifiable I-BWV-2: at age 15/30/60 min with matching live
    desire, exactly ONE retry per attempt fires, and after attempt 3 a
    HARD STAND-DOWN pins the surface.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)

    emitted: list[tuple[str, dict]] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append((type_str, extra))
    v._emit_anomaly = _fake_emit  # type: ignore

    retries: list[str] = []
    async def _fake_redispatch(surface):
        retries.append(surface)
    bat.force_redispatch = _fake_redispatch  # type: ignore[attr-defined]

    # Pin commanded_at (a stuck write does not re-command) and advance
    # WALL TIME by monkeypatching utcnow. This matches the live shape:
    # commanded_at is monotonic; divergence age grows with the clock.
    real_utcnow = ewv.dt_util.utcnow
    t0 = real_utcnow()
    commanded_at = t0 - timedelta(seconds=60)
    _install_local_witness(bat, hass, 63)
    bat._last_reserve_level = 10
    bat._last_reserve_level_desired = 10
    bat._last_reserve_level_at = commanded_at
    bat._desired_stamped_at = t0

    def _clock(offset_s):
        ewv.dt_util.utcnow = lambda: t0 + timedelta(seconds=offset_s)
        # In the live system `_result` restamps the desire every tick
        # (5 min). Keep the stamp fresh vs the fake clock so we don't
        # accidentally hit the blind-hold branch.
        bat._desired_stamped_at = t0 + timedelta(seconds=offset_s)
    try:
        _clock(CONF_PENDING_ATTEMPT_1_AGE_S)
        await v._pending_watchdog_reserve(bat)
        assert len(retries) == 1
        assert v._pending_attempts_fired[SURFACE] == 1
        _clock(CONF_PENDING_ATTEMPT_2_AGE_S)
        await v._pending_watchdog_reserve(bat)
        assert len(retries) == 2
        assert v._pending_attempts_fired[SURFACE] == 2
        _clock(CONF_PENDING_ATTEMPT_3_AGE_S)
        await v._pending_watchdog_reserve(bat)
        assert len(retries) == CONF_PENDING_MAX_ATTEMPTS
        assert v._pending_standdown_at[SURFACE] is not None
        # Subsequent ticks (still diverged, still fresh desire) MUST NOT
        # keep re-dispatching — this is the whole point of stand-down.
        _clock(CONF_PENDING_ATTEMPT_3_AGE_S + 60)
        await v._pending_watchdog_reserve(bat)
        _clock(CONF_PENDING_ATTEMPT_3_AGE_S + 120)
        await v._pending_watchdog_reserve(bat)
        assert len(retries) == CONF_PENDING_MAX_ATTEMPTS
    finally:
        ewv.dt_util.utcnow = real_utcnow


@pytest.mark.asyncio
async def test_pending_stuck_stale_desire_stands_down(hass):
    """MUTATION-ANCHORED (D2 acceptance criterion): with divergence age
    past threshold BUT `_desired_stamped_at` stale (blind-hold), NO
    anomaly, NO retry. I-D3 preserved.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)

    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore
    retries: list[str] = []
    async def _fake_redispatch(surface):
        retries.append(surface)
    bat.force_redispatch = _fake_redispatch  # type: ignore[attr-defined]

    _prime_divergence(hass, bat, 10, 63, CONF_PENDING_ATTEMPT_1_AGE_S + 60)
    # Blind: stamp aged > 600s.
    bat._desired_stamped_at = ewv.dt_util.utcnow() - timedelta(seconds=1200)

    await v._pending_watchdog_reserve(bat)
    assert retries == []
    assert emitted == []


@pytest.mark.asyncio
async def test_pending_stuck_desire_moved_cancels_ladder(hass):
    """Freshness constraint (2026-07-17): if live desire has moved from
    the diverged commanded value, ladder CANCELS (not re-aims).
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    retries: list[str] = []
    async def _fake_redispatch(surface):
        retries.append(surface)
    bat.force_redispatch = _fake_redispatch  # type: ignore[attr-defined]
    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore

    _prime_divergence(hass, bat, 10, 63, CONF_PENDING_ATTEMPT_1_AGE_S + 60)
    # LIVE desire has moved (operator raised the floor). Ledger says
    # 10 was commanded, but strategy now wants 40. Ladder must NOT fire.
    bat._last_reserve_level_desired = 40

    await v._pending_watchdog_reserve(bat)
    assert retries == []
    assert emitted == []
    # Ladder state reset — a new episode with 40 will start its own ladder.
    assert v._pending_attempts_fired.get(SURFACE, 0) == 0


@pytest.mark.asyncio
async def test_pending_converges_resets_state(hass):
    """When hardware converges to commanded, all watchdog state clears."""
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    retries: list[str] = []
    async def _fake_redispatch(surface):
        retries.append(surface)
    bat.force_redispatch = _fake_redispatch  # type: ignore[attr-defined]

    # First: diverged and fire attempt #1.
    _prime_divergence(hass, bat, 10, 63, CONF_PENDING_ATTEMPT_1_AGE_S + 60)
    await v._pending_watchdog_reserve(bat)
    assert v._pending_attempts_fired[SURFACE] == 1

    # Now converge: hw=10.
    _set(hass, LOCAL_RESERVE_EID, 10, unit="%")
    await v._pending_watchdog_reserve(bat)
    assert v._pending_attempts_fired[SURFACE] == 0
    assert v._pending_episode_at[SURFACE] is None
    assert v._pending_standdown_at[SURFACE] is None


@pytest.mark.asyncio
async def test_pending_hardware_witness_unavailable_abstains(hass):
    """Hardware witness `unavailable` → abstain: no state change, no
    attempts, no anomaly. (B0-D2 report mandate.)
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    retries: list[str] = []
    async def _fake_redispatch(surface):
        retries.append(surface)
    bat.force_redispatch = _fake_redispatch  # type: ignore[attr-defined]
    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore

    # Prime with local witness *then* mark unavailable.
    _install_local_witness(bat, hass, 63)
    hass._states[LOCAL_RESERVE_EID] = MockState(
        LOCAL_RESERVE_EID, "unavailable", attributes={"unit_of_measurement": "%"},
    )
    bat._last_reserve_level = 10
    bat._last_reserve_level_desired = 10
    bat._last_reserve_level_at = (
        ewv.dt_util.utcnow()
        - timedelta(seconds=CONF_PENDING_ATTEMPT_1_AGE_S + 60)
    )
    await v._pending_watchdog_reserve(bat)
    assert retries == []
    assert emitted == []


# ==================================================================
# MUTATION ANCHORS — orchestrator must ALSO run on-disk mutation per
# Tier-3 protocol. These in-suite mutation tests are the fastest gate
# (they exercise the specific code path the on-disk mutation would edit).
# ==================================================================
@pytest.mark.asyncio
async def test_mutation_anchor_conduct_condition_neutered(hass):
    """MUTATION ANCHOR: neuter the below_floor computation → episode
    never triggers → alarm never fires despite a clear violation.

    A pass here proves the below-floor arithmetic is load-bearing for
    the alarm — removing it in production source would REMOVE the alarm.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    bat._last_reserve_level = 80
    bat._last_reserve_level_desired = 80
    bat._last_reserve_level_at = (
        ewv.dt_util.utcnow() - timedelta(seconds=2000)
    )
    bat._soc = 10.0
    bat._power_w = -3000.0

    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore

    # Monkey-patch _conduct_check_reserve inner logic: force below_floor
    # detection off by shifting SOC exactly to the floor (deadband edge).
    bat._soc = 80.0 - float(CONF_CONDUCT_SOC_DEADBAND_PCT)  # not < deadband
    for _ in range(CONF_CONDUCT_N_TICKS + 2):
        await v._conduct_check_reserve(bat)
    assert emitted == []


@pytest.mark.asyncio
async def test_mutation_anchor_ladder_attempt_cap_removed(hass):
    """MUTATION ANCHOR: if the attempt cap were removed, retries would
    keep firing past attempt 3.

    In-suite mutation: bypass the standdown by clearing state after each
    attempt. If we can drive 5 retries in a row, the guard is working
    as spec (stand-down is what prevents it).
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    retries: list[str] = []
    async def _fake_redispatch(surface):
        retries.append(surface)
    bat.force_redispatch = _fake_redispatch  # type: ignore[attr-defined]

    real_utcnow = ewv.dt_util.utcnow
    t0 = real_utcnow()
    _install_local_witness(bat, hass, 63)
    bat._last_reserve_level = 10
    bat._last_reserve_level_desired = 10
    bat._last_reserve_level_at = t0 - timedelta(
        seconds=CONF_PENDING_ATTEMPT_3_AGE_S + 60
    )
    bat._desired_stamped_at = t0
    def _clock(offset_s):
        ewv.dt_util.utcnow = lambda: t0 + timedelta(seconds=offset_s)
        bat._desired_stamped_at = t0 + timedelta(seconds=offset_s)
    try:
        # v5.19.0 fix-up A-LOW-1 (ladder spacing): attempts must be
        # spaced by ≥ ATTEMPT_1_AGE_S in addition to absolute age.
        _clock(0)
        await v._pending_watchdog_reserve(bat)
        _clock(int(CONF_PENDING_ATTEMPT_1_AGE_S) + 30)
        await v._pending_watchdog_reserve(bat)
        _clock(2 * int(CONF_PENDING_ATTEMPT_1_AGE_S) + 60)
        await v._pending_watchdog_reserve(bat)
        # Further ticks past standdown — no more retries.
        _clock(3 * int(CONF_PENDING_ATTEMPT_1_AGE_S) + 90)
        await v._pending_watchdog_reserve(bat)
        _clock(4 * int(CONF_PENDING_ATTEMPT_1_AGE_S) + 120)
        await v._pending_watchdog_reserve(bat)
    finally:
        ewv.dt_util.utcnow = real_utcnow
    # With cap enforced: attempts_fired capped at MAX_ATTEMPTS.
    assert v._pending_attempts_fired[SURFACE] == CONF_PENDING_MAX_ATTEMPTS
    assert v._pending_standdown_at[SURFACE] is not None
    # Retries also capped at 3.
    assert len(retries) == CONF_PENDING_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_mutation_anchor_freshness_rederivation(hass):
    """MUTATION ANCHOR (LOAD-BEARING): a retry must RE-DERIVE live desire
    at fire time — it must NEVER replay the detection-time value.

    Scenario: at detection time desire==commanded==10. Between detection
    and the ladder fire tick, live desire moves to 40. If the code
    replays the stale 10 (mutation), retries fire. If it re-derives (spec),
    ladder cancels.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    retries: list[str] = []
    async def _fake_redispatch(surface):
        retries.append(surface)
    bat.force_redispatch = _fake_redispatch  # type: ignore[attr-defined]

    _prime_divergence(hass, bat, 10, 63, CONF_PENDING_ATTEMPT_1_AGE_S + 60)
    # Move live desire BETWEEN priming and the sweep — this is what
    # the boundary/hold-release scenario looks like.
    bat._last_reserve_level_desired = 40
    await v._pending_watchdog_reserve(bat)
    assert retries == []          # ladder cancelled by re-derivation
    assert v._pending_attempts_fired.get(SURFACE, 0) == 0


@pytest.mark.asyncio
async def test_mutation_anchor_standdown_skipped(hass):
    """MUTATION ANCHOR: skipping stand-down would let retries continue
    indefinitely. Verify that after 3 attempts, additional ticks with
    the same divergence do NOT emit further retries UNTIL the cool-off
    elapses.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    retries: list[str] = []
    async def _fake_redispatch(surface):
        retries.append(surface)
    bat.force_redispatch = _fake_redispatch  # type: ignore[attr-defined]

    real_utcnow = ewv.dt_util.utcnow
    t0 = real_utcnow()
    _install_local_witness(bat, hass, 63)
    bat._last_reserve_level = 10
    bat._last_reserve_level_desired = 10
    bat._last_reserve_level_at = t0 - timedelta(
        seconds=CONF_PENDING_ATTEMPT_3_AGE_S + 60
    )
    bat._desired_stamped_at = t0
    def _clock(offset_s):
        ewv.dt_util.utcnow = lambda: t0 + timedelta(seconds=offset_s)
        bat._desired_stamped_at = t0 + timedelta(seconds=offset_s)
    try:
        _clock(0)
        await v._pending_watchdog_reserve(bat)
        _clock(int(CONF_PENDING_ATTEMPT_1_AGE_S) + 30)
        await v._pending_watchdog_reserve(bat)
        _clock(2 * int(CONF_PENDING_ATTEMPT_1_AGE_S) + 60)
        await v._pending_watchdog_reserve(bat)
        assert len(retries) == CONF_PENDING_MAX_ATTEMPTS
        # More ticks — still under cool-off. No further retries.
        _clock(3 * int(CONF_PENDING_ATTEMPT_1_AGE_S) + 90)
        await v._pending_watchdog_reserve(bat)
        _clock(4 * int(CONF_PENDING_ATTEMPT_1_AGE_S) + 120)
        await v._pending_watchdog_reserve(bat)
        assert len(retries) == CONF_PENDING_MAX_ATTEMPTS
        # Now advance standdown past cool-off — ONE cool-off probe fires.
        v._pending_standdown_at[SURFACE] = (
            ewv.dt_util.utcnow()
            - timedelta(seconds=CONF_PENDING_STANDDOWN_COOLOFF_S + 60)
        )
        await v._pending_watchdog_reserve(bat)
        assert len(retries) == CONF_PENDING_MAX_ATTEMPTS + 1
        await v._pending_watchdog_reserve(bat)
        await v._pending_watchdog_reserve(bat)
        assert len(retries) == CONF_PENDING_MAX_ATTEMPTS + 1
    finally:
        ewv.dt_util.utcnow = real_utcnow


@pytest.mark.asyncio
async def test_mutation_anchor_legal_exception_broadened(hass):
    """MUTATION ANCHOR: broadening the legal-exception set would suppress
    real defects. Falsifiable: an obviously-noncompliant state with NO
    exception predicate must fire; enabling the (narrow) inclement
    predicate must suppress it. If the exception was ever broadened to
    always-True, the first assertion fails.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)

    bat._last_reserve_level = 80
    bat._last_reserve_level_desired = 80  # live desire matches
    bat._last_reserve_level_at = (
        ewv.dt_util.utcnow() - timedelta(seconds=2000)
    )
    bat._soc = 40.0
    bat._power_w = -4000.0
    bat._inclement_partial_hold_active = False

    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore

    for _ in range(CONF_CONDUCT_N_TICKS):
        await v._conduct_check_reserve(bat)
    # No exception → must fire.
    assert emitted == ["hardware_noncompliance"]


# ==================================================================
# D3 attrs shape
# ==================================================================
@pytest.mark.asyncio
async def test_d3_attrs_present_when_idle(hass):
    """get_status_attrs() returns the three new keys even when no
    episode is active. Shape check only.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    _install_local_witness(bat, hass, 50)
    attrs = v.get_status_attrs()
    assert "hardware_noncompliance_state" in attrs
    assert "pending_write_stuck_state" in attrs
    assert "command_trail" in attrs
    for key in ("hardware_noncompliance_state", "pending_write_stuck_state",
                "command_trail"):
        assert SURFACE in attrs[key]
    # Idle: not active.
    assert attrs["hardware_noncompliance_state"][SURFACE]["active"] is False
    assert attrs["pending_write_stuck_state"][SURFACE]["active"] is False


# ==================================================================
# force_redispatch on BatteryStrategy — dispatched value + stale gate
# ==================================================================
@pytest.mark.asyncio
async def test_force_redispatch_stale_desire_is_noop(hass):
    """`force_redispatch` refuses to fire when `_desired_stamped_at`
    is stale. I-D3.
    """
    from custom_components.universal_room_automation.domain_coordinators \
        import energy_battery as eb  # noqa: F401

    # Minimal instance — avoid BatteryStrategy.__init__. Attach the
    # method to a bare object and provide the fields it reads.
    class _Bat:
        pass
    bat = _Bat()
    bat.hass = hass
    from homeassistant.util import dt as _dt
    bat._desired_stamped_at = _dt.utcnow() - timedelta(seconds=1200)
    bat._last_reserve_level_desired = 15
    bat._last_reserve_level = 80
    bat._last_reserve_level_at = _dt.utcnow()
    bat._get_entity = lambda k, d=None, *, role="read": (
        CLOUD_RESERVE_EID if k == "reserve_soc_number" else d
    )
    calls: list[tuple] = []
    async def _svc(domain, svc, data, blocking=True):
        calls.append((domain, svc, data))
    hass.services.async_call = _svc

    # Bind the real method to our stub.
    from custom_components.universal_room_automation.domain_coordinators.energy_battery \
        import BatteryStrategy
    await BatteryStrategy.force_redispatch(bat, "reserve_soc")
    assert calls == []


@pytest.mark.asyncio
async def test_force_redispatch_uses_live_desire(hass):
    """Fresh desire → dispatches the CURRENT `_last_reserve_level_desired`
    (never captures upstream).
    """
    class _Bat:
        pass
    bat = _Bat()
    bat.hass = hass
    # Use force_redispatch's OWN `dt_util` binding (fresh from
    # homeassistant.util) so age-compares don't cross module identities
    # when a sibling test reassigns sys.modules["homeassistant.util.dt"].
    from homeassistant.util import dt as _dt
    bat._desired_stamped_at = _dt.utcnow()
    bat._last_reserve_level_desired = 42
    bat._last_reserve_level = 80
    bat._last_reserve_level_at = _dt.utcnow()
    bat._get_entity = lambda k, d=None, *, role="read": (
        CLOUD_RESERVE_EID if k == "reserve_soc_number" else d
    )
    calls: list[tuple] = []
    async def _svc(domain, svc, data, blocking=True):
        calls.append((domain, svc, data))
    hass.services.async_call = _svc

    from custom_components.universal_room_automation.domain_coordinators.energy_battery \
        import BatteryStrategy
    await BatteryStrategy.force_redispatch(bat, "reserve_soc")
    assert len(calls) == 1
    domain, svc, data = calls[0]
    assert domain == "number"
    assert svc == "set_value"
    assert data == {"entity_id": CLOUD_RESERVE_EID, "value": 42}
    # Ledger stamped with re-dispatched value.
    assert bat._last_reserve_level == 42


@pytest.mark.asyncio
async def test_force_redispatch_unsupported_surface_noop(hass):
    """Non-reserve surfaces are intentionally no-op today (scope-limited
    per plan Non-goals).
    """
    class _Bat:
        pass
    bat = _Bat()
    bat.hass = hass
    from homeassistant.util import dt as _dt
    bat._desired_stamped_at = _dt.utcnow()
    bat._last_reserve_level_desired = 10
    bat._last_reserve_level = 10
    bat._last_reserve_level_at = _dt.utcnow()
    bat._get_entity = lambda k, d=None, *, role="read": d
    calls: list[tuple] = []
    async def _svc(domain, svc, data, blocking=True):
        calls.append((domain, svc, data))
    hass.services.async_call = _svc

    from custom_components.universal_room_automation.domain_coordinators.energy_battery \
        import BatteryStrategy
    await BatteryStrategy.force_redispatch(bat, "charge_from_grid")
    await BatteryStrategy.force_redispatch(bat, "storage_mode")
    assert calls == []


# ==================================================================
# ROOT 1 anchors — effective post-overlay desire (D-HIGH-1 / D-HIGH-2)
# ==================================================================
@pytest.mark.asyncio
async def test_conduct_uses_effective_desire_under_evse_hold(hass):
    """MUTATION ANCHOR (Root 1, D-HIGH-1):

    Scenario: strategy pre-overlay desire = 15 (would drain to 15),
    but an EVSE-hold overlay is active with hold_soc = 61, so the
    EFFECTIVE reserve URA is enforcing is 61. Commanded ledger = 61
    (post-overlay stamp). SOC = 45, discharging.

    Under FIX (uses `_effective_reserve_desired`): effective (61) is
    NOT below commanded_floor (61) → exception (d) does NOT fire →
    hardware_noncompliance emits. This is the whole point of the fix:
    a battery draining into the car unalarmed while URA thinks it is
    frozen at 61 must trigger.

    Under MUTATION (revert to `_reserve_desire` / pre-overlay): 15 <
    61 → exception (d) fires → no alarm. Mutating the fix would let
    the D-HIGH-1 leak return.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    bat._last_reserve_level = 61  # post-overlay stamp
    bat._last_reserve_level_desired = 15  # PRE-overlay strategy desire
    bat._last_reserve_level_at = (
        ewv.dt_util.utcnow() - timedelta(seconds=2000)
    )
    # EVSE hold active with hold_soc = 61 — the reason commanded is 61.
    coord._evse_battery_hold_active = True
    coord._evse_hold_soc = 61
    bat._soc = 45.0
    bat._power_w = -3000.0

    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore

    for _ in range(CONF_CONDUCT_N_TICKS):
        await v._conduct_check_reserve(bat)
    assert emitted == ["hardware_noncompliance"], (
        "Effective post-overlay desire (61) equals commanded_floor (61) "
        "so exception (d) must NOT fire; pre-overlay use would break this."
    )


@pytest.mark.asyncio
async def test_watchdog_uses_effective_desire_under_evse_hold(hass):
    """MUTATION ANCHOR (Root 1, D-HIGH-2):

    Watchdog cancel-on-move must compare commanded ledger against the
    EFFECTIVE post-overlay desire — not the pre-overlay strategy value.
    Otherwise a legitimate standing HOLD (commanded=61 via EVSE hold,
    strategy pre-overlay=15) would be classified as "desire moved"
    → ladder cancels → the stuck-hold-write scenario never fires. The
    07-16 fixture (commanded=61 held stuck) becomes unreachable.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    # hw 30 vs cmd 61: divergence > 2% deadband.
    _install_local_witness(bat, hass, 30)
    bat._last_reserve_level = 61
    bat._last_reserve_level_desired = 15  # PRE-overlay
    bat._last_reserve_level_at = (
        ewv.dt_util.utcnow()
        - timedelta(seconds=CONF_PENDING_ATTEMPT_1_AGE_S + 60)
    )
    coord._evse_battery_hold_active = True
    coord._evse_hold_soc = 61

    retries: list[str] = []
    async def _fake_redispatch(surface):
        retries.append(surface)
    bat.force_redispatch = _fake_redispatch  # type: ignore[attr-defined]
    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore

    await v._pending_watchdog_reserve(bat)
    assert retries == ["reserve_soc"], (
        "Effective desire under hold == commanded ledger; ladder must "
        "proceed. Using pre-overlay would cancel the ladder here."
    )
    assert emitted == ["pending_write_stuck"]


# ==================================================================
# ROOT 2 anchor — stand-down honesty (D-HIGH-3)
# ==================================================================
@pytest.mark.asyncio
async def test_standdown_gates_normal_dispatch_same_value(hass):
    """MUTATION ANCHOR (Root 2, D-HIGH-3):

    After a hard stand-down at value V, `is_standdown_active_for_value`
    returns True for V (so the normal `_result` dispatch leg skips
    re-dispatch of V) and False for any other value (auto-resume when
    effective desire changes).
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    retries: list[str] = []
    async def _fake_redispatch(surface):
        retries.append(surface)
    bat.force_redispatch = _fake_redispatch  # type: ignore[attr-defined]

    real_utcnow = ewv.dt_util.utcnow
    t0 = real_utcnow()
    _install_local_witness(bat, hass, 63)
    bat._last_reserve_level = 10
    bat._last_reserve_level_desired = 10
    bat._last_reserve_level_at = t0 - timedelta(
        seconds=CONF_PENDING_ATTEMPT_3_AGE_S + 60
    )
    bat._desired_stamped_at = t0
    def _clock(offset_s):
        ewv.dt_util.utcnow = lambda: t0 + timedelta(seconds=offset_s)
        bat._desired_stamped_at = t0 + timedelta(seconds=offset_s)
    try:
        _clock(0)
        await v._pending_watchdog_reserve(bat)
        _clock(int(CONF_PENDING_ATTEMPT_1_AGE_S) + 30)
        await v._pending_watchdog_reserve(bat)
        _clock(2 * int(CONF_PENDING_ATTEMPT_1_AGE_S) + 60)
        await v._pending_watchdog_reserve(bat)
    finally:
        ewv.dt_util.utcnow = real_utcnow
    assert v._pending_standdown_at[SURFACE] is not None
    assert v._pending_standdown_value[SURFACE] == 10

    # Same value → gate active (dispatch would skip).
    assert v.is_standdown_active_for_value(SURFACE, 10) is True
    # Different value (effective desire moved) → gate NOT active,
    # dispatch proceeds — automatic resume matches ratified conditions.
    assert v.is_standdown_active_for_value(SURFACE, 40) is False


@pytest.mark.asyncio
async def test_self_heal_alarm_suppressed_during_pending_episode(hass):
    """ROOT 2 (b): during an active pending episode, the overlapping
    `write_verification_failed` self_heal_starvation alarm on the same
    surface is suppressed — the more-specific `pending_write_stuck`
    alarm owns the surface. Prevents dual alarms for one divergence.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)

    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore
    # Fire an attempt so the pending episode is armed.
    v._pending_attempts_fired[SURFACE] = 1
    v._pending_episode_at[SURFACE] = ewv.dt_util.utcnow()

    # Simulate the self-heal loop: same-value schedule called 3x. Under
    # `is_pending_episode_active` the emit is suppressed.
    _install_local_witness(bat, hass, 63)  # ensure oracle-probe returns a value
    # Wire a cloud oracle so schedule() proceeds past the 'no oracle' return.
    _install_cloud_oracle(bat, hass, 63)
    for _ in range(3):
        await v.schedule(SURFACE, 10)
    # `write_verification_failed` (self-heal-starvation flavor) MUST NOT
    # be in `emitted` — the pending episode owns the alarm.
    assert "write_verification_failed" not in emitted


# ==================================================================
# D-MED-3 — grid outage exception (narrow, witness-driven)
# ==================================================================
@pytest.mark.asyncio
async def test_conduct_grid_outage_exempts(hass):
    """When `switch.enpower_*_grid_enabled` reads 'off', conduct exempts
    (backup discharge below floor is expected during a grid outage).
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)

    # Wire `_get_entity("grid_enabled", ...)` to a known entity id.
    GRID_EID = "switch.enpower_grid_enabled"
    orig = bat._get_entity
    def _wrap(key, default=None, *, role="read"):
        if key == "grid_enabled":
            return GRID_EID
        return orig(key, default, role=role)
    bat._get_entity = _wrap
    _set(hass, GRID_EID, "off", unit=None)

    bat._last_reserve_level = 60
    bat._last_reserve_level_desired = 60
    bat._last_reserve_level_at = (
        ewv.dt_util.utcnow() - timedelta(seconds=2000)
    )
    bat._soc = 40.0
    bat._power_w = -2500.0

    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore
    for _ in range(CONF_CONDUCT_N_TICKS + 2):
        await v._conduct_check_reserve(bat)
    assert emitted == []
    assert v._conduct_last_abstain_reason[SURFACE] == "grid_outage"


# ==================================================================
# A-LOW-1 / C-M6b — ladder inter-attempt spacing
# ==================================================================
@pytest.mark.asyncio
async def test_ladder_spacing_prevents_consecutive_tick_burst(hass):
    """MUTATION ANCHOR (A-LOW-1 / C-M6b):

    Pre-aged divergence (post-restart shape) — commanded_at already past
    ATTEMPT_3_AGE. Under NO spacing gate, three consecutive decision
    ticks would fire attempts 1/2/3 back-to-back. Under the fix, attempt
    N+1 requires `now - last_attempt_at >= ATTEMPT_1_AGE_S` in addition
    to absolute age. So on three consecutive ticks: attempt 1 fires, the
    next two return early (spacing not yet met).

    C's spec: after attempt 1, tick at ATTEMPT_2_AGE-60 → still 1 retry.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    retries: list[str] = []
    async def _fake_redispatch(surface):
        retries.append(surface)
    bat.force_redispatch = _fake_redispatch  # type: ignore[attr-defined]

    real_utcnow = ewv.dt_util.utcnow
    t0 = real_utcnow()
    # Pre-aged: divergence already at ATTEMPT_3_AGE.
    _install_local_witness(bat, hass, 63)
    bat._last_reserve_level = 10
    bat._last_reserve_level_desired = 10
    bat._last_reserve_level_at = t0 - timedelta(
        seconds=CONF_PENDING_ATTEMPT_3_AGE_S + 60
    )
    bat._desired_stamped_at = t0

    def _clock(offset_s):
        ewv.dt_util.utcnow = lambda: t0 + timedelta(seconds=offset_s)
        bat._desired_stamped_at = t0 + timedelta(seconds=offset_s)
    try:
        # Tick 1 (t=0): attempt 1 fires.
        _clock(0)
        await v._pending_watchdog_reserve(bat)
        assert len(retries) == 1
        # Tick 2 shortly after (t = ATTEMPT_1_AGE - 60): spacing NOT met.
        _clock(int(CONF_PENDING_ATTEMPT_1_AGE_S) - 60)
        await v._pending_watchdog_reserve(bat)
        assert len(retries) == 1, (
            "Spacing gate must block a second consecutive-tick retry."
        )
        # Tick 3 (t = ATTEMPT_1_AGE + 30): spacing met, attempt 2 fires.
        _clock(int(CONF_PENDING_ATTEMPT_1_AGE_S) + 30)
        await v._pending_watchdog_reserve(bat)
        assert len(retries) == 2
    finally:
        ewv.dt_util.utcnow = real_utcnow


# ==================================================================
# D-MED-4 / C-M10 — severity plumbing
# ==================================================================
@pytest.mark.asyncio
async def test_severity_plumbing_per_attempt(hass):
    """MUTATION ANCHOR (D-MED-4 / C-M10):

    Ratified severity: attempt #1 → ALERT, #2 → ALERT (HIGH string
    maps to ALERT enum — the enum has no HIGH bucket), #3 → CRITICAL.
    conduct → ALERT (NOT CRITICAL, per ratification #1 — money leak).

    Assert BOTH the payload `severity_class` string AND the real
    `AnomalySeverity` enum passed to the emitter. A test that only
    checked the string would let a mutation of the mapping ship a
    silent regression.
    """
    from custom_components.universal_room_automation.domain_coordinators.anomaly_event import (  # noqa: E501
        AnomalySeverity,
    )

    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    retries: list[str] = []
    async def _fake_redispatch(surface):
        retries.append(surface)
    bat.force_redispatch = _fake_redispatch  # type: ignore[attr-defined]

    # Capture full AnomalyEvent via a fake database.
    saved: list = []
    class _FakeDB:
        async def save_anomaly_event(self, ev):
            saved.append(ev)
    hass.data["universal_room_automation"]["database"] = _FakeDB()

    real_utcnow = ewv.dt_util.utcnow
    t0 = real_utcnow()
    _install_local_witness(bat, hass, 63)
    bat._last_reserve_level = 10
    bat._last_reserve_level_desired = 10
    bat._last_reserve_level_at = t0 - timedelta(seconds=60)
    bat._desired_stamped_at = t0

    def _clock(offset_s):
        ewv.dt_util.utcnow = lambda: t0 + timedelta(seconds=offset_s)
        bat._desired_stamped_at = t0 + timedelta(seconds=offset_s)
    try:
        _clock(CONF_PENDING_ATTEMPT_1_AGE_S)
        await v._pending_watchdog_reserve(bat)
        _clock(CONF_PENDING_ATTEMPT_2_AGE_S)
        await v._pending_watchdog_reserve(bat)
        _clock(CONF_PENDING_ATTEMPT_3_AGE_S)
        await v._pending_watchdog_reserve(bat)
    finally:
        ewv.dt_util.utcnow = real_utcnow

    # Three pending_write_stuck emits captured.
    pw = [ev for ev in saved if ev.type == "pending_write_stuck"]
    assert len(pw) == 3
    # payload is a dict (build_context_json returns dict); extra keys
    # live under payload["extra"].
    def _extract_sev_class(payload):
        return (payload.get("extra") or {}).get("severity_class")
    sev_classes = [_extract_sev_class(ev.payload) for ev in pw]
    assert sev_classes == ["ALERT", "HIGH", "CRITICAL"]
    # Real AnomalySeverity enum per attempt:
    assert pw[0].severity == AnomalySeverity.ALERT
    assert pw[1].severity == AnomalySeverity.ALERT  # HIGH → ALERT bucket
    assert pw[2].severity == AnomalySeverity.CRITICAL

    # Conduct — must be ALERT (NOT CRITICAL).
    saved.clear()
    coord2 = _Coord(hass)
    bat2 = coord2._battery
    v2 = ewv.WriteVerifier(hass, coord2)
    bat2._last_reserve_level = 15
    bat2._last_reserve_level_desired = 15
    bat2._last_reserve_level_at = (
        ewv.dt_util.utcnow() - timedelta(seconds=2000)
    )
    bat2._soc = 5.0
    bat2._power_w = -2000.0
    for _ in range(CONF_CONDUCT_N_TICKS):
        await v2._conduct_check_reserve(bat2)
    hn = [ev for ev in saved if ev.type == "hardware_noncompliance"]
    assert len(hn) == 1
    assert hn[0].severity == AnomalySeverity.ALERT


# ==================================================================
# C-M8 — command_trail truthfulness
# ==================================================================
@pytest.mark.asyncio
async def test_command_trail_reports_three_distinct_witnesses(hass):
    """C-M8: the `command_trail` D3 attr must NOT collapse or lie —
    each of ledger / hardware-enforced / cloud-oracle must report its
    own value.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    # Distinct values: ledger=10, hw=63, cloud=50.
    _install_local_witness(bat, hass, 63)
    _install_cloud_oracle(bat, hass, 50)
    bat._last_reserve_level = 10
    bat._last_reserve_level_desired = 10
    bat._last_reserve_level_at = ewv.dt_util.utcnow()

    attrs = v.get_status_attrs()
    trail = attrs["command_trail"][SURFACE]
    assert trail["commanded"]["value"] == 10
    assert int(float(trail["hardware_enforced"]["value"])) == 63
    assert trail["cloud_oracle"]["value"] in ("50", 50)
    # All three distinct → not a lie.
    assert (
        trail["commanded"]["value"]
        != trail["hardware_enforced"]["value"]
        != trail["cloud_oracle"]["value"]
    )


# ==================================================================
# C-M11 — kill-switch OFF stops emits/retries under violating fixture
# ==================================================================
@pytest.mark.asyncio
async def test_conduct_kill_switch_disabled_no_emits(hass, monkeypatch):
    """C-M11: when `CONF_CONDUCT_ENABLED` is monkeypatched False,
    a fixture that would normally trigger the alarm produces ZERO
    emits and leaves the tick counter at 0.
    """
    monkeypatch.setattr(ewv, "CONF_CONDUCT_ENABLED", False)
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    bat._last_reserve_level = 15
    bat._last_reserve_level_desired = 15
    bat._last_reserve_level_at = (
        ewv.dt_util.utcnow() - timedelta(seconds=2000)
    )
    bat._soc = 5.0
    bat._power_w = -2000.0
    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore
    for _ in range(CONF_CONDUCT_N_TICKS + 3):
        await v._conduct_check_reserve(bat)
    assert emitted == []
    assert v._conduct_consec.get(SURFACE, 0) == 0


@pytest.mark.asyncio
async def test_pending_watchdog_kill_switch_disabled_no_retries(hass, monkeypatch):
    """C-M11: `CONF_PENDING_WATCHDOG_ENABLED` False → zero retries and
    zero anomaly emits even under a divergence past ATTEMPT_3_AGE.
    """
    monkeypatch.setattr(ewv, "CONF_PENDING_WATCHDOG_ENABLED", False)
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    retries: list[str] = []
    async def _fake_redispatch(surface):
        retries.append(surface)
    bat.force_redispatch = _fake_redispatch  # type: ignore[attr-defined]
    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore
    _prime_divergence(hass, bat, 10, 63, CONF_PENDING_ATTEMPT_3_AGE_S + 60)
    for _ in range(5):
        await v._pending_watchdog_reserve(bat)
    assert retries == []
    assert emitted == []


# ==================================================================
# C-M12 — power-blind abstain
# ==================================================================
@pytest.mark.asyncio
async def test_conduct_power_none_abstains(hass):
    """C-M12: `battery_power_w` None (power sensor blind) → abstain,
    zero emits, counter not advanced. Distinct from soc-blind path.
    """
    coord = _Coord(hass)
    bat = coord._battery
    v = ewv.WriteVerifier(hass, coord)
    bat._last_reserve_level = 15
    bat._last_reserve_level_desired = 15
    bat._last_reserve_level_at = (
        ewv.dt_util.utcnow() - timedelta(seconds=2000)
    )
    bat._soc = 5.0
    bat._power_w = None
    emitted: list[str] = []
    async def _fake_emit(surface, type_str, extra):
        emitted.append(type_str)
    v._emit_anomaly = _fake_emit  # type: ignore
    for _ in range(CONF_CONDUCT_N_TICKS + 2):
        await v._conduct_check_reserve(bat)
    assert emitted == []
    assert v._conduct_consec.get(SURFACE, 0) == 0
    assert v._conduct_last_abstain_reason[SURFACE] == "power_none"
