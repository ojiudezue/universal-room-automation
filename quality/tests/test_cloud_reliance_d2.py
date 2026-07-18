"""Tests for v5.20.0 D2 cloud-reliance hardening.

Covers the READ-side telemetry observability + divergence detection added
to `BatteryStrategy` (energy_battery.py). Reuses the test-harness bootstrap
from `test_energy_battery.py` (import order matters — the module builds
the mock `custom_components.universal_room_automation` package tree).

D2 owns the SOC read-side witness; write-verify (v5.19.0) owns the write
side. These tests DO NOT touch write-verify surfaces.

Fix-up review coverage (A/B/C/D):
- C#1 NM backref latch (live, once/day, re-fires next day)
- C#2 bidirectional divergence (primary=87 / cloud=60)
- C#3 age truthfulness (cloud age vs lkg age asserted distinctly)
- C#4 wrong-leg discrimination (cloud oracle stale vs local write fresh)
- C#5 `get_status` wiring (soc_resolution attr present w/ tier + divergence)
- A cloud-age-gate abstain (delta 27 pp but cloud age 700s → no fire)
- Split-timer regression (D-HIGH-1): clear-branch seeding a shared timer
  must NOT let an outage-recovery transient instant-fire.
- Tier-consistency: divergence only evaluates when `_soc_source_last ==
  "envoy"` (must not fire from the cloud-fallback tier).
"""

# Bootstrap the same mock HA / package tree the sibling test uses.
import test_energy_battery  # noqa: F401  (side-effect: builds sys.modules)

from datetime import datetime, timedelta

import pytest

from conftest import MockHass, MockState  # noqa: E402
from custom_components.universal_room_automation.domain_coordinators import (
    energy_const,  # noqa: E402
)
from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
    BatteryStrategy,  # noqa: E402
)


CLOUD_SOC_ENTITY = energy_const.DEFAULT_CLOUD_BATTERY_SOC_FALLBACK_ENTITY
CLOUD_RESERVE_ENTITY = energy_const.DEFAULT_CLOUD_RESERVE_ORACLE_ENTITY
CLOUD_CFG_ENTITY = energy_const.DEFAULT_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY
CLOUD_STORAGE_MODE_ENTITY = energy_const.DEFAULT_CLOUD_STORAGE_MODE_ORACLE_ENTITY

PRIMARY_SOC_ENTITY = "sensor.test_envoy_battery"


class _FakeCoord:
    """Minimal fake EnergyCoordinator that counts NM invocations.

    Mirrors the real `_send_nm_alert(title, message, severity, hazard_type,
    location)` signature so D2's per-day latch path exercises the same
    call shape as production.
    """

    def __init__(self):
        self.calls: list[dict] = []

    async def _send_nm_alert(  # noqa: N802 — matches production name
        self, title="", message="", severity="warning",
        hazard_type="", location="",
    ):
        self.calls.append({
            "title": title, "message": message, "severity": severity,
            "hazard_type": hazard_type, "location": location,
        })


def _make_strategy(with_coord: bool = True) -> BatteryStrategy:
    """Return a minimally-configured BatteryStrategy wired for D2 tests.

    When `with_coord=True` (default), installs a `_FakeCoord` on the
    real backref field production uses (`_coord`). This proves the
    D-CRIT-1 fix: production installs `self._battery._coord = self` at
    energy.py:270; the test path installs its fake at the SAME attr so
    NM invocations are actually observable.
    """
    hass = MockHass()
    hass.set_state(CLOUD_RESERVE_ENTITY, "20")
    hass.set_state(CLOUD_CFG_ENTITY, "off")
    hass.set_state(CLOUD_STORAGE_MODE_ENTITY, "Self-Consumption")
    strat = BatteryStrategy(
        hass,
        reserve_soc=20,
        arbitrage_enabled=False,
        entity_config={
            "battery_soc": PRIMARY_SOC_ENTITY,
            "battery_soc_cloud": CLOUD_SOC_ENTITY,
            "cloud_reserve_oracle": CLOUD_RESERVE_ENTITY,
            "cloud_charge_from_grid_oracle": CLOUD_CFG_ENTITY,
            "cloud_storage_mode_oracle": CLOUD_STORAGE_MODE_ENTITY,
        },
    )
    if with_coord:
        strat._coord = _FakeCoord()
    return strat


def _set_state_at(hass: MockHass, entity_id: str, state: str,
                  age_s: float = 0.0, unit: str = "%") -> None:
    """Set a state whose `last_updated` is age_s in the past.

    Uses whatever `dt_util.utcnow` is CURRENTLY bound to at call-time so
    the arithmetic stays in the same tz-domain as the production code
    path reads it (sibling test modules occasionally monkeypatch it).
    """
    from homeassistant.util import dt as dt_util
    when = dt_util.utcnow() - timedelta(seconds=age_s)
    mstate = MockState(
        entity_id, state, attributes={"unit_of_measurement": unit},
        last_changed=when,
    )
    mstate.last_updated = when
    hass._states[entity_id] = mstate


def _prime_envoy_tier(strat: BatteryStrategy) -> None:
    """Force `_soc_source_last = 'envoy'` (tier-consistency gate)."""
    strat._soc_source_last = "envoy"


# ---------------------------------------------------------------------------
# D2.2 — tier observability
# ---------------------------------------------------------------------------

def test_soc_resolution_populated_primary_envoy_tier():
    """Primary Envoy present → tier=primary_envoy, cloud snapshot recorded."""
    strat = _make_strategy()
    _set_state_at(strat.hass, PRIMARY_SOC_ENTITY, "62.0")
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "61.0")
    _ = strat.battery_soc
    strat._evaluate_soc_resolution(strat.battery_soc)
    attrs = strat._soc_resolution_attrs()
    assert attrs["tier"] == "primary_envoy"
    assert attrs["primary_envoy_soc"] == pytest.approx(62.0)
    assert attrs["cloud_soc"] == pytest.approx(61.0)
    assert attrs["tier_disagreement_pp"] == pytest.approx(1.0)


def test_soc_resolution_tier_disagreement_pp_computed_over_all_tiers():
    """With primary=60, LKG=58 (stale), cloud=87 → disagreement is 87-60 = 27."""
    strat = _make_strategy()
    _set_state_at(strat.hass, PRIMARY_SOC_ENTITY, "60.0")
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "87.0")
    _set_state_at(strat.hass, PRIMARY_SOC_ENTITY, "58.0")
    _ = strat.battery_soc
    _set_state_at(strat.hass, PRIMARY_SOC_ENTITY, "60.0")
    _ = strat.battery_soc
    strat._evaluate_soc_resolution(strat.battery_soc)
    attrs = strat._soc_resolution_attrs()
    assert attrs["primary_envoy_soc"] == pytest.approx(60.0)
    assert attrs["cloud_soc"] == pytest.approx(87.0)
    assert attrs["tier_disagreement_pp"] == pytest.approx(27.0)


# ---------------------------------------------------------------------------
# C#3 — age truthfulness: cloud age vs lkg age asserted distinctly
# ---------------------------------------------------------------------------

def test_soc_resolution_cloud_age_vs_lkg_age_distinct():
    """Cloud state age ~120s while LKG stamped ~3600s ago.

    Mutation anchor: swap cloud_age and lkg_age in `_soc_resolution_attrs`
    → this test fails (each is checked in its OWN range).
    """
    from homeassistant.util import dt as dt_util
    strat = _make_strategy()
    # Drive resolver so LKG stamps.
    _set_state_at(strat.hass, PRIMARY_SOC_ENTITY, "60.0")
    _ = strat.battery_soc
    # Cloud state age ~120s.
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "61.0", age_s=120)
    # Age LKG by 3600s AFTER driving resolver (mutate stored ts directly).
    # Do NOT drive resolver again — that would restamp LKG.
    strat._soc_lkg_at = dt_util.utcnow() - timedelta(seconds=3600)
    # Pass a stored primary_soc directly (avoids resolver restamp).
    strat._evaluate_soc_resolution(60.0)
    attrs = strat._soc_resolution_attrs()
    assert attrs["cloud_soc_age_s"] is not None
    assert 60 <= attrs["cloud_soc_age_s"] <= 200, attrs
    assert attrs["lkg_age_s"] is not None
    assert 3500 <= attrs["lkg_age_s"] <= 3700, attrs


# ---------------------------------------------------------------------------
# D2.1 — SOC divergence detector (with dwell + hysteresis + latch)
# ---------------------------------------------------------------------------

def test_soc_divergence_no_alert_before_dwell():
    """Divergence held < dwell → no active alert.

    Mutation anchor for the dwell branch: remove the dwell gate and the
    second call would flip active True.
    """
    strat = _make_strategy()
    _prime_envoy_tier(strat)
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "87.0", age_s=5)
    strat._evaluate_soc_divergence(60.0)
    assert strat._d2_soc_div_above_first_at is not None
    strat._evaluate_soc_divergence(60.0)
    assert strat._d2_soc_div_active is False


def test_soc_divergence_fires_after_dwell_and_latches():
    """Divergence 27 pp held past 5-min dwell → active + NM latch."""
    from homeassistant.util import dt as dt_util
    strat = _make_strategy()
    _prime_envoy_tier(strat)
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "87.0", age_s=5)
    strat._evaluate_soc_divergence(60.0)
    assert strat._d2_soc_div_above_first_at is not None
    strat._d2_soc_div_above_first_at = dt_util.utcnow() - timedelta(minutes=6)
    strat._evaluate_soc_divergence(60.0)
    assert strat._d2_soc_div_active is True
    assert strat._d2_soc_div_last_delta == pytest.approx(27.0)
    assert strat._d2_soc_div_nm_date == (
        dt_util.utcnow().date().isoformat()
    )


# ---------------------------------------------------------------------------
# C#1 — NM backref path actually invoked; once/day, re-fires next day
# ---------------------------------------------------------------------------

def test_soc_divergence_nm_invoked_via_backref_once_per_day(monkeypatch):
    """Prove the backref path is REAL (fix-up D-CRIT-1).

    Uses a counting `_FakeCoord` installed on `strat._coord` (the same
    attr `EnergyCoordinator.__init__` sets at energy.py:270). Fires
    divergence past dwell; asserts the fake's `_send_nm_alert` was
    scheduled EXACTLY once. Then advances the date via monkeypatch on
    `dt_util.utcnow` and drives a subsequent confirmed tick; asserts a
    SECOND send happens (standing multi-day divergence re-alerts daily
    per fix-up D-MED-1).

    Mutation anchors:
      - Break the backref: replace `getattr(self, "_coord", None)` with
        `getattr(self, "coordinator", None)` in `_fire_d2_nm` → this
        test fails (0 calls).
      - Drop the daily-refire (change `_fire_d2_nm` to fire only when
        latch != today AND ever) → next-day assertion fails.

    Verifies `hass.async_create_task` actually got a coroutine.
    """
    from homeassistant.util import dt as dt_util
    strat = _make_strategy(with_coord=True)
    _prime_envoy_tier(strat)
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "87.0", age_s=5)

    scheduled: list = []

    def _capture_task(coro):
        scheduled.append(coro)
        # Close coroutine to avoid "never awaited" warnings.
        try:
            coro.close()
        except Exception:
            pass
        return None

    # MockHass may not define async_create_task; assign directly.
    strat.hass.async_create_task = _capture_task  # type: ignore[attr-defined]

    strat._evaluate_soc_divergence(60.0)
    strat._d2_soc_div_above_first_at = dt_util.utcnow() - timedelta(minutes=6)
    strat._evaluate_soc_divergence(60.0)
    strat._evaluate_soc_divergence(60.0)  # per-tick fire, latch dedups
    assert len(scheduled) == 1, scheduled
    assert strat._d2_soc_div_active is True
    latched = strat._d2_soc_div_nm_date
    assert latched is not None

    # Simulate next calendar day.
    tomorrow = dt_util.utcnow() + timedelta(days=1)
    import homeassistant.util.dt as _du

    def _now_tomorrow():
        return tomorrow

    monkeypatch.setattr(_du, "utcnow", _now_tomorrow)
    # Refresh cloud SOC state so its age (against tomorrow's clock)
    # stays under the freshness gate. last_updated must be within
    # DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S of `tomorrow`.
    mstate = strat.hass._states[CLOUD_SOC_ENTITY]
    mstate.last_updated = tomorrow - timedelta(seconds=5)
    # Drive again — dwell already met (above_first_at wall-clock from
    # yesterday, elapsed >> dwell).
    strat._evaluate_soc_divergence(60.0)
    assert len(scheduled) == 2, "standing divergence must re-alert next day"
    assert strat._d2_soc_div_nm_date == tomorrow.date().isoformat()


# ---------------------------------------------------------------------------
# C#2 — bidirectional divergence (abs pinned)
# ---------------------------------------------------------------------------

def test_soc_divergence_bidirectional_primary_high_cloud_low():
    """primary=87 / cloud=60 → delta=27 fires (abs pinned).

    Mutation anchor: drop `abs()` in `delta = abs(primary_soc -
    cloud_soc)` → primary > cloud produces delta=27 fine, but if the
    sign convention were flipped this test would fail. Combined with
    the sibling test (primary=60 / cloud=87), any implementation that
    only handles one direction would fail one of the two.
    """
    from homeassistant.util import dt as dt_util
    strat = _make_strategy()
    _prime_envoy_tier(strat)
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "60.0", age_s=5)
    strat._evaluate_soc_divergence(87.0)
    strat._d2_soc_div_above_first_at = dt_util.utcnow() - timedelta(minutes=6)
    strat._evaluate_soc_divergence(87.0)
    assert strat._d2_soc_div_active is True
    assert strat._d2_soc_div_last_delta == pytest.approx(27.0)


def test_soc_divergence_clears_with_hysteresis():
    """Hysteresis band 8 <= delta <= 10: neither fire nor clear.

    Fix-up D-HIGH-1 (split timers): the hysteresis-band branch zeros
    BOTH above and below timers; the outage-recovery instant-clear
    regression is separately covered below.
    """
    from homeassistant.util import dt as dt_util
    strat = _make_strategy()
    _prime_envoy_tier(strat)
    strat._d2_soc_div_active = True
    strat._d2_soc_div_above_first_at = None
    strat._d2_soc_div_below_first_at = None
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "69.0", age_s=5)
    strat._evaluate_soc_divergence(60.0)  # delta=9, hysteresis band
    assert strat._d2_soc_div_above_first_at is None
    assert strat._d2_soc_div_below_first_at is None
    strat._d2_soc_div_below_first_at = dt_util.utcnow() - timedelta(minutes=6)
    strat._evaluate_soc_divergence(60.0)  # still band; must not clear
    assert strat._d2_soc_div_active is True
    # Now drop clearly below hysteresis → clears after dwell.
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "63.0", age_s=5)
    strat._d2_soc_div_above_first_at = None
    strat._d2_soc_div_below_first_at = None
    strat._evaluate_soc_divergence(60.0)
    assert strat._d2_soc_div_below_first_at is not None
    strat._d2_soc_div_below_first_at = dt_util.utcnow() - timedelta(minutes=6)
    strat._evaluate_soc_divergence(60.0)
    assert strat._d2_soc_div_active is False


def test_soc_divergence_abstains_on_stale_or_unavailable():
    """None primary → dwell resets, active PRESERVED (B-MED-2)."""
    strat = _make_strategy()
    _prime_envoy_tier(strat)
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "87.0", age_s=5)
    strat._d2_soc_div_active = True  # simulate a previously-latched alert
    strat._evaluate_soc_divergence(60.0)
    assert strat._d2_soc_div_above_first_at is not None
    strat._evaluate_soc_divergence(None)
    assert strat._d2_soc_div_above_first_at is None
    assert strat._d2_soc_div_last_delta is None
    # Blind != resolved — must NOT clear active.
    assert strat._d2_soc_div_active is True


def test_soc_divergence_disabled_when_threshold_zero(monkeypatch):
    """Kill-switch: threshold=0 → clears active + resets timers (B-LOW-1)."""
    import sys as _sys
    _live_ec = _sys.modules[
        "custom_components.universal_room_automation.domain_coordinators.energy_const"
    ]
    monkeypatch.setattr(_live_ec, "CONF_SOC_DIVERGENCE_THRESHOLD_PP", 0)
    strat = _make_strategy()
    _prime_envoy_tier(strat)
    strat._d2_soc_div_active = True
    strat._d2_soc_div_above_first_at = "sentinel"
    strat._evaluate_soc_divergence(60.0)
    assert strat._d2_soc_div_above_first_at is None
    assert strat._d2_soc_div_active is False


# ---------------------------------------------------------------------------
# A / D-HIGH-2 — cloud age gate
# ---------------------------------------------------------------------------

def test_soc_divergence_abstains_on_stale_cloud_age(monkeypatch):
    """Cloud age 700s > 600s max → abstain even at 27 pp delta.

    Mutation anchor: remove the `cloud_fresh` gate in
    `_evaluate_soc_divergence` → this test fails (would fire after
    dwell).
    """
    from homeassistant.util import dt as dt_util
    strat = _make_strategy()
    _prime_envoy_tier(strat)
    # Cloud SOC is numeric+in-range+correct unit BUT stale.
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "87.0", age_s=700)
    strat._evaluate_soc_divergence(60.0)
    assert strat._d2_soc_div_above_first_at is None, (
        "stale cloud must not arm above dwell"
    )
    assert strat._d2_soc_div_active is False
    # Advance dwell forcibly; still no fire because gate re-abstains.
    strat._d2_soc_div_above_first_at = dt_util.utcnow() - timedelta(minutes=6)
    strat._evaluate_soc_divergence(60.0)
    assert strat._d2_soc_div_active is False


def test_soc_divergence_tier_consistency_no_fire_on_cloud_fallback():
    """Divergence must abstain when this tick's tier != 'envoy'.

    Simulates a resolver output on the cloud_fallback tier (primary
    dead). Even at 27 pp delta the divergence detector must not fire —
    comparing cloud to a cloud-served SOC is not a witness disagreement.
    """
    from homeassistant.util import dt as dt_util
    strat = _make_strategy()
    strat._soc_source_last = "cloud_fallback"
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "87.0", age_s=5)
    strat._evaluate_soc_divergence(60.0)
    strat._d2_soc_div_above_first_at = dt_util.utcnow() - timedelta(minutes=6)
    strat._evaluate_soc_divergence(60.0)
    assert strat._d2_soc_div_active is False


# ---------------------------------------------------------------------------
# D-HIGH-1 — split-timer regression: outage-recovery must NOT instant-fire
# ---------------------------------------------------------------------------

def test_split_timer_outage_recovery_no_instant_fire():
    """Simulate: cloud steady 87, primary=60 for a while (below-band far
    from threshold? no — actually delta=27 is above). Better regime:
    long steady CLEAR (below_first_at seeded), then divergence spikes.

    Regression this catches: the initial build used a SHARED
    `_d2_soc_div_first_at` seeded by whichever branch fired last.
    Sequence:
      1) delta=5 (clear branch) — seeds shared timer.
      2) delta=27 (above branch) — with shared timer already >dwell,
         instant-fires without dwelling.

    With split timers, step 2 must arm `above_first_at` fresh at step 2
    and NOT fire until dwell elapses.
    """
    from homeassistant.util import dt as dt_util
    strat = _make_strategy()
    _prime_envoy_tier(strat)
    # Step 1: below-clear regime.
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "65.0", age_s=5)
    strat._evaluate_soc_divergence(60.0)  # delta=5, below clear_below=8
    # Force below timer past dwell (simulates long healthy period).
    strat._d2_soc_div_below_first_at = dt_util.utcnow() - timedelta(minutes=10)
    # Step 2: transient jump to divergence.
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "87.0", age_s=5)
    strat._evaluate_soc_divergence(60.0)  # delta=27, above threshold=10
    # MUST NOT instant-fire — above_first_at should be JUST armed.
    assert strat._d2_soc_div_active is False, (
        "shared-timer regression: above branch fired without its own dwell"
    )
    assert strat._d2_soc_div_above_first_at is not None
    # Below timer must have been reset when above regime engaged.
    assert strat._d2_soc_div_below_first_at is None


def test_split_timer_convergence_no_instant_clear():
    """Symmetric to the above: outage keeps above_first_at past dwell
    (divergence active), then a transient tick drops into clear-band —
    must NOT instant-clear active.
    """
    from homeassistant.util import dt as dt_util
    strat = _make_strategy()
    _prime_envoy_tier(strat)
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "87.0", age_s=5)
    strat._d2_soc_div_active = True
    strat._d2_soc_div_above_first_at = dt_util.utcnow() - timedelta(minutes=10)
    # Transient tick into clear range.
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "63.0", age_s=5)
    strat._evaluate_soc_divergence(60.0)  # delta=3, clear branch
    # Must NOT instant-clear — below_first_at fresh, active still True.
    assert strat._d2_soc_div_active is True
    assert strat._d2_soc_div_below_first_at is not None
    assert strat._d2_soc_div_above_first_at is None


# ---------------------------------------------------------------------------
# C#4 — wrong-leg discrimination (cloud oracle stale vs local write fresh)
# ---------------------------------------------------------------------------

def test_cloud_settings_lag_reads_cloud_oracle_not_local(monkeypatch):
    """Wrong-leg discrimination.

    Fixture: cloud oracle entities STALE 5000s. Local write entities
    (Enpower) FRESH 10s. `_read_cloud_settings_max_age_s` must observe
    the CLOUD leg. If a future refactor accidentally routes through
    `_get_entity(role="write")` (which returns local when the failover
    flag is False), this test fails.

    Mutation anchor: swap the read path to local entities → age would
    drop to ~10s and the assert fails.
    """
    # Local Enpower analogs — SHOULD NOT be read.
    local_reserve = "number.enpower_local_reserve"
    local_cfg = "switch.enpower_local_charge_from_grid"
    local_storage = "select.enpower_local_storage_mode"
    strat = _make_strategy()
    _set_state_at(strat.hass, local_reserve, "20", age_s=10)
    _set_state_at(strat.hass, local_cfg, "off", age_s=10, unit="")
    _set_state_at(strat.hass, local_storage, "Self-Consumption", age_s=10,
                  unit="")
    # Cloud oracle entities STALE.
    _set_state_at(strat.hass, CLOUD_RESERVE_ENTITY, "20", age_s=5000)
    _set_state_at(strat.hass, CLOUD_CFG_ENTITY, "off", age_s=5000, unit="")
    _set_state_at(strat.hass, CLOUD_STORAGE_MODE_ENTITY,
                  "Self-Consumption", age_s=5000, unit="")
    age = strat._read_cloud_settings_max_age_s()
    assert age is not None
    assert age >= 5000, f"expected cloud-leg age ~5000s, got {age}"


# ---------------------------------------------------------------------------
# D2.3 — cloud settings-lag
# ---------------------------------------------------------------------------

def test_cloud_settings_lag_reports_max_age():
    """`_read_cloud_settings_max_age_s` returns max across the 3 entities."""
    strat = _make_strategy()
    _set_state_at(strat.hass, CLOUD_RESERVE_ENTITY, "20", age_s=100)
    _set_state_at(strat.hass, CLOUD_CFG_ENTITY, "off", age_s=1900)
    _set_state_at(strat.hass, CLOUD_STORAGE_MODE_ENTITY,
                  "Self-Consumption", age_s=300)
    age = strat._read_cloud_settings_max_age_s()
    assert age is not None and age >= 1900


def test_cloud_settings_lag_fires_after_dwell():
    """max_age > 1800 for > 5 min → active alert + NM latched."""
    from homeassistant.util import dt as dt_util
    strat = _make_strategy()
    _set_state_at(strat.hass, CLOUD_RESERVE_ENTITY, "20", age_s=100)
    _set_state_at(strat.hass, CLOUD_CFG_ENTITY, "off", age_s=1900)
    _set_state_at(strat.hass, CLOUD_STORAGE_MODE_ENTITY,
                  "Self-Consumption", age_s=300)
    strat._evaluate_cloud_settings_lag()
    assert strat._d2_cloud_lag_above_first_at is not None
    assert strat._d2_cloud_lag_active is False
    strat._d2_cloud_lag_above_first_at = (
        dt_util.utcnow() - timedelta(minutes=6)
    )
    strat._evaluate_cloud_settings_lag()
    assert strat._d2_cloud_lag_active is True
    assert strat._d2_cloud_lag_nm_date == (
        dt_util.utcnow().date().isoformat()
    )


def test_cloud_settings_lag_healthy_no_alert():
    """max_age well below threshold → no active alert, no dwell."""
    strat = _make_strategy()
    _set_state_at(strat.hass, CLOUD_RESERVE_ENTITY, "20", age_s=60)
    _set_state_at(strat.hass, CLOUD_CFG_ENTITY, "off", age_s=90)
    _set_state_at(strat.hass, CLOUD_STORAGE_MODE_ENTITY,
                  "Self-Consumption", age_s=120)
    strat._evaluate_cloud_settings_lag()
    assert strat._d2_cloud_lag_active is False
    assert strat._d2_cloud_lag_last_age_s is not None
    assert strat._d2_cloud_lag_last_age_s < 200


def test_cloud_settings_lag_killswitch(monkeypatch):
    """CONF_CLOUD_LAG_ALERT_S=0 → attr populated, no dwell, no NM, clears active."""
    import sys as _sys
    _live_ec = _sys.modules[
        "custom_components.universal_room_automation.domain_coordinators.energy_const"
    ]
    monkeypatch.setattr(_live_ec, "CONF_CLOUD_LAG_ALERT_S", 0)
    strat = _make_strategy()
    strat._d2_cloud_lag_active = True  # simulate prior latch
    _set_state_at(strat.hass, CLOUD_RESERVE_ENTITY, "20", age_s=100)
    _set_state_at(strat.hass, CLOUD_CFG_ENTITY, "off", age_s=99999)
    _set_state_at(strat.hass, CLOUD_STORAGE_MODE_ENTITY,
                  "Self-Consumption", age_s=300)
    strat._evaluate_cloud_settings_lag()
    assert strat._d2_cloud_lag_above_first_at is None
    assert strat._d2_cloud_lag_active is False  # kill-switch clears
    assert strat._d2_cloud_lag_last_age_s is not None
    assert strat._d2_cloud_lag_last_age_s >= 99999


# ---------------------------------------------------------------------------
# C#5 — get_status wiring: `soc_resolution` attr present with tier + divergence
# ---------------------------------------------------------------------------

def test_get_status_publishes_soc_resolution_block():
    """`get_status` must call the D2 evaluators and expose `soc_resolution`.

    Mutation anchor: drop the `_evaluate_soc_resolution` call inside
    `get_status` → this test fails (`tier` would be None, and
    `divergence_active` key still present but tier missing).
    """
    strat = _make_strategy()
    _set_state_at(strat.hass, PRIMARY_SOC_ENTITY, "62.0")
    _set_state_at(strat.hass, CLOUD_SOC_ENTITY, "61.0", age_s=30)
    status = strat.get_status()
    assert "soc_resolution" in status, list(status.keys())[:20]
    block = status["soc_resolution"]
    assert set(block.keys()) >= {
        "tier", "divergence_active", "tier_disagreement_pp",
        "cloud_settings_lag_s",
    }
    assert block["tier"] == "primary_envoy"


# ---------------------------------------------------------------------------
# Attribute-surface smoke: `soc_resolution` block shape.
# ---------------------------------------------------------------------------

def test_soc_resolution_attr_block_keys_stable():
    strat = _make_strategy()
    attrs = strat._soc_resolution_attrs()
    expected = {
        "tier", "tier_disagreement_pp",
        "primary_envoy_soc", "lkg_soc", "lkg_age_s",
        "cloud_soc", "cloud_soc_age_s",
        "divergence_pp", "divergence_active",
        "cloud_settings_lag_s", "cloud_settings_lag_active",
    }
    assert set(attrs.keys()) == expected
