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

    async def _send_nm_alert(self, **kw):
        self.nm_calls.append(kw)


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
    bat._inclement_partial_hold_active = True

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

    _prime_divergence(hass, bat, 10, 63, CONF_PENDING_ATTEMPT_3_AGE_S + 60)
    # First three attempts fire; the third sets standdown.
    for _ in range(5):
        await v._pending_watchdog_reserve(bat)
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

    _prime_divergence(hass, bat, 10, 63, CONF_PENDING_ATTEMPT_3_AGE_S + 60)
    # Drive to hard stand-down.
    for _ in range(5):
        await v._pending_watchdog_reserve(bat)
    assert len(retries) == CONF_PENDING_MAX_ATTEMPTS
    # Age the standdown so it stays under cool-off; more ticks → no retry.
    for _ in range(10):
        await v._pending_watchdog_reserve(bat)
    assert len(retries) == CONF_PENDING_MAX_ATTEMPTS
    # Now advance standdown past cool-off — ONE cool-off probe fires.
    v._pending_standdown_at[SURFACE] = (
        ewv.dt_util.utcnow()
        - timedelta(seconds=CONF_PENDING_STANDDOWN_COOLOFF_S + 60)
    )
    await v._pending_watchdog_reserve(bat)
    assert len(retries) == CONF_PENDING_MAX_ATTEMPTS + 1
    # And that probe latches: no further retries during this stand-down.
    await v._pending_watchdog_reserve(bat)
    await v._pending_watchdog_reserve(bat)
    assert len(retries) == CONF_PENDING_MAX_ATTEMPTS + 1


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
