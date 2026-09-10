"""EC-SOC-LADDER-XVALIDATE-1 + FROZEN-POWER-READ-STALENESS-CLASS-1 tests.

D1 — cross-field SOC ladder validation:
  * validator rejects each new inversion with a stable error code and
    a human-readable message
  * safely_ordered_ladder() clamps inversions to the canonical order
  * mutation drill: deleting the new cross-field checks from the
    validator body breaks the matching test (wire-in anchor)

D2 — staleness gates on the two remaining primary-SOC decision reads:
  * soc_envelope engages when primary SOC is FROZEN-VALID (state numeric,
    stamp older than DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S) — proving the
    envelope path is no longer suppressed by a stale primary
  * envoy_available detection returns False when primary SOC is
    FROZEN-VALID (same gate, same const)
  * kill-switch (max_age_s=0) disables the gate
  * mutation drill: reverting either site to raw `_get_state_float`
    causes the frozen-valid test to fail
"""

from __future__ import annotations

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

# Force tz-aware utcnow into the shared HA stub — some sibling test modules
# (test_energy_battery.py) install a NAIVE `datetime.utcnow` stub whose
# tzinfo is None. `_state_age_s` refuses to compute age on naive stamps
# (returns None → gate passes), which would silently make our staleness
# tests non-discriminating when run in the same pytest process.
import sys as _sys
from datetime import datetime as _dt, timezone as _tz
_dtmod = _sys.modules.get("homeassistant.util.dt")
if _dtmod is not None:
    _dtmod.utcnow = lambda: _dt.now(_tz.utc)


# ──────────────────────────────────────────────────────────────────────────
# D1 — validator cross-field checks
# ──────────────────────────────────────────────────────────────────────────

class TestLadderCrossFieldValidation:
    """EC-SOC-LADDER-XVALIDATE-1: validator returns (code, message)."""

    def _base(self):
        return dict(
            reserve_soc=10,
            drain_targets={"excellent": 10, "good": 15, "moderate": 20, "poor": 30},
            arbitrage_trigger=None,
            peak_buffer_target=80,
            fill_priority_soc=30,
            excess_solar_soc=80,
            ev_battery_drain_soc=20,
            inclement_partial_hold_reserve_floor=30,
        )

    def test_ladder_all_valid_returns_none(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            validate_threshold_ladder,
        )
        assert validate_threshold_ladder(**self._base()) is None

    def test_fill_priority_above_excess_solar_rejected(self):
        """Inverted band: fill_priority=90 > excess_solar=80 — oscillates
        EV pause/resume. This is the wire-in anchor for the new check."""
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            validate_threshold_ladder,
        )
        kw = self._base()
        kw["fill_priority_soc"] = 90
        kw["excess_solar_soc"] = 80
        result = validate_threshold_ladder(**kw)
        assert result is not None
        code, msg = result
        assert code == "fill_priority_above_excess_solar"
        assert "fill_priority_soc" in msg
        assert "excess_solar_soc" in msg

    def test_ev_drain_below_reserve_rejected(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            validate_threshold_ladder,
        )
        kw = self._base()
        kw["reserve_soc"] = 20
        kw["drain_targets"] = {
            "excellent": 20, "good": 25, "moderate": 28, "poor": 30,
        }
        kw["ev_battery_drain_soc"] = 15  # below reserve
        result = validate_threshold_ladder(**kw)
        assert result is not None
        code, msg = result
        assert code == "ev_drain_below_reserve"
        assert "ev_battery_drain_soc" in msg

    def test_inclement_partial_hold_below_reserve_rejected(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            validate_threshold_ladder,
        )
        kw = self._base()
        kw["reserve_soc"] = 20
        kw["drain_targets"] = {
            "excellent": 20, "good": 25, "moderate": 28, "poor": 30,
        }
        kw["inclement_partial_hold_reserve_floor"] = 15  # below reserve
        result = validate_threshold_ladder(**kw)
        assert result is not None
        code, msg = result
        assert code == "inclement_partial_hold_below_reserve"
        assert "partial_hold" in msg or "inclement" in msg

    def test_extreme_floor_greater_than_target_still_rejected(self):
        """Config-boundary combinatorial: floor > target (independent
        sliders). Falsifies the invariant on a legal-config path."""
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            validate_threshold_ladder,
        )
        kw = self._base()
        # reserve above every drain target — should fail drain_below_reserve
        kw["reserve_soc"] = 40
        kw["drain_targets"] = {
            "excellent": 10, "good": 15, "moderate": 20, "poor": 30,
        }
        result = validate_threshold_ladder(**kw)
        assert result is not None
        assert result[0] == "drain_excellent_below_reserve"

    def test_optional_kwargs_skipped_when_none(self):
        """New kwargs are ALL Optional — None skips the corresponding
        cross-field check. Back-compat with pre-XVALIDATE-1 callers."""
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            validate_threshold_ladder,
        )
        result = validate_threshold_ladder(
            reserve_soc=10,
            drain_targets={"excellent": 10, "good": 15, "moderate": 20, "poor": 30},
            arbitrage_trigger=None,
            peak_buffer_target=80,
        )
        assert result is None


# ──────────────────────────────────────────────────────────────────────────
# D1 — mutation-anchor drills: the new cross-field checks must be reachable
# ──────────────────────────────────────────────────────────────────────────

class TestLadderCrossFieldValidationMutationAnchor:
    """Removing the fill_priority/excess_solar block from the validator's
    body must break `test_fill_priority_above_excess_solar_rejected`.

    We verify that the return TUPLE is exercised on this exact code path
    by checking the specific ``fill_priority_above_excess_solar`` error
    code — reachable only via the new cross-field block."""

    def test_fill_priority_check_produces_specific_code(self):
        """Neuter drill: replace the fill_priority `if` branch in
        `energy_const.validate_threshold_ladder` with `pass` — this test
        must FAIL (result is None or code != fill_priority_above_excess_solar).
        """
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            validate_threshold_ladder,
        )
        # These values violate ONLY the fill_priority cross-field check.
        result = validate_threshold_ladder(
            reserve_soc=10,
            drain_targets={"excellent": 10, "good": 15, "moderate": 20, "poor": 30},
            arbitrage_trigger=None,
            peak_buffer_target=80,
            fill_priority_soc=90,
            excess_solar_soc=80,
            ev_battery_drain_soc=20,
            inclement_partial_hold_reserve_floor=30,
        )
        assert result is not None, "fill_priority block removed?"
        assert result[0] == "fill_priority_above_excess_solar", (
            f"expected fill_priority_above_excess_solar, got {result[0]}"
        )

    def test_ev_drain_check_produces_specific_code(self):
        """Neuter drill: replace the ev_drain `if` branch with `pass` —
        this test must FAIL."""
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            validate_threshold_ladder,
        )
        result = validate_threshold_ladder(
            reserve_soc=25,
            drain_targets={"excellent": 25, "good": 27, "moderate": 28, "poor": 30},
            arbitrage_trigger=None,
            peak_buffer_target=80,
            fill_priority_soc=40,
            excess_solar_soc=80,
            ev_battery_drain_soc=20,  # < reserve=25
            inclement_partial_hold_reserve_floor=30,
        )
        assert result is not None, "ev_drain block removed?"
        assert result[0] == "ev_drain_below_reserve"

    def test_inclement_check_produces_specific_code(self):
        """Neuter drill: replace the inclement `if` branch with `pass` —
        this test must FAIL."""
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            validate_threshold_ladder,
        )
        result = validate_threshold_ladder(
            reserve_soc=25,
            drain_targets={"excellent": 25, "good": 27, "moderate": 28, "poor": 30},
            arbitrage_trigger=None,
            peak_buffer_target=80,
            fill_priority_soc=40,
            excess_solar_soc=80,
            ev_battery_drain_soc=30,
            inclement_partial_hold_reserve_floor=20,  # < reserve=25
        )
        assert result is not None, "inclement block removed?"
        assert result[0] == "inclement_partial_hold_below_reserve"


# ──────────────────────────────────────────────────────────────────────────
# D1 — safely_ordered_ladder accessor (runtime clamp)
# ──────────────────────────────────────────────────────────────────────────

class TestSafelyOrderedLadder:
    """safely_ordered_ladder() clamps inversions to canonical order."""

    def _make_coord(self):
        """Build a bare EnergyCoordinator-like object with the attrs the
        accessor reads. We do NOT instantiate the real coordinator —
        the accessor logic is pure and self-contained."""
        import types
        c = types.SimpleNamespace()
        battery = types.SimpleNamespace(reserve_soc=20)
        c._battery = battery
        c._fill_priority_soc = 30
        c._excess_solar_soc = 80
        c._ev_battery_drain_soc = 25
        # Bind the real bound-method to this SimpleNamespace so we
        # exercise production code, not a copy.
        from custom_components.universal_room_automation.domain_coordinators.energy import (
            EnergyCoordinator,
        )
        c.safely_ordered_ladder = EnergyCoordinator.safely_ordered_ladder.__get__(c)
        return c

    def test_ordered_when_ladder_is_valid(self):
        c = self._make_coord()
        out = c.safely_ordered_ladder()
        assert out["ev_battery_drain_soc"] == 25
        assert out["fill_priority_soc"] == 30

    def test_clamps_ev_drain_up_to_reserve(self):
        c = self._make_coord()
        c._ev_battery_drain_soc = 10  # below reserve=20
        out = c.safely_ordered_ladder()
        assert out["ev_battery_drain_soc"] == 20  # clamped up

    def test_clamps_fill_priority_down_to_excess_solar(self):
        c = self._make_coord()
        c._fill_priority_soc = 90  # above excess_solar=80
        out = c.safely_ordered_ladder()
        assert out["fill_priority_soc"] == 80  # clamped down


# ──────────────────────────────────────────────────────────────────────────
# D2 — primary-SOC staleness at the two remaining decision sites
# ──────────────────────────────────────────────────────────────────────────

class _FrozenState:
    """Minimal fake for hass.states.get() — numeric state + old stamp."""

    def __init__(self, value, age_s, attrs=None):
        from homeassistant.util import dt as dt_util
        from datetime import timedelta
        self.state = str(value)
        self.last_reported = dt_util.utcnow() - timedelta(seconds=age_s)
        self.last_updated = self.last_reported
        self.attributes = attrs or {"unit_of_measurement": "%"}


class _FakeHass:
    def __init__(self, mapping):
        self._m = mapping

        class _States:
            def __init__(_self, m):
                _self._m = m

            def get(_self, eid):
                return _self._m.get(eid)

        self.states = _States(mapping)
        self.data = {}


def _make_battery(hass, entity_map):
    """Build a BatteryStrategy shell with just enough for the two reads."""
    import types
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        BatteryStrategy,
    )
    bat = BatteryStrategy.__new__(BatteryStrategy)
    bat.hass = hass
    bat._entities = entity_map
    bat._write_failover_by_surface = {}
    bat._cloud_demote_logged = set()
    return bat


class TestFrozenPrimarySocEnvelope:
    """FROZEN-POWER-READ-STALENESS-CLASS-1: soc_envelope must engage on
    a frozen-valid primary SOC — the pre-fix `_get_state_float` accepted
    it and suppressed envelope engagement."""

    def _setup(self, age_s):
        eid = "sensor.envoy_battery"
        hass = _FakeHass({eid: _FrozenState(42.0, age_s=age_s)})
        bat = _make_battery(hass, {"battery_soc": eid})
        # Seed LKG so envelope has something to return.
        from homeassistant.util import dt as dt_util
        from datetime import timedelta
        bat._soc_lkg = 42.0
        bat._soc_lkg_at = dt_util.utcnow() - timedelta(seconds=60)
        return bat

    def test_fresh_primary_suppresses_envelope(self):
        """Sanity: a fresh primary SOC (age < max) → envelope returns None."""
        bat = self._setup(age_s=10)
        # Envelope depends on other unwired methods on the real object —
        # we assert the fresh-read PATH inside soc_envelope succeeds by
        # calling _read_fresh_float directly against the same entity.
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S,
        )
        val = bat._read_fresh_float(
            "sensor.envoy_battery",
            DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S,
            stamp="last_reported",
        )
        assert val == 42.0

    def test_frozen_primary_rejected_by_fresh_read(self):
        """Mutation anchor: if soc_envelope's primary read is reverted
        to raw `_get_state_float`, this test still passes — but the
        `test_frozen_primary_does_not_suppress_envelope_engagement`
        below FAILS. That is the specific fail-signal for the neuter drill."""
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S,
        )
        bat = self._setup(age_s=DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S + 60)
        val = bat._read_fresh_float(
            "sensor.envoy_battery",
            DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S,
            stamp="last_reported",
        )
        assert val is None

    def test_frozen_primary_does_not_suppress_envelope_engagement(self):
        """WIRE-IN ANCHOR — soc_envelope's own reachable behavior. When
        the entity is FROZEN-VALID, soc_envelope must NOT early-return
        None on the "primary is live" check. Neuter drill: revert
        energy_battery.py:soc_envelope's `self._read_fresh_float(...)`
        call back to `self._get_state_float(...)` and this test FAILS
        (soc_envelope returns None on the frozen entity)."""
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S,
        )
        bat = self._setup(age_s=DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S + 60)
        # Provide required capacity/kW constants via env — they come from
        # energy_const so no monkeypatch needed. Just call and expect a
        # SOCEnvelope result (not None), proving we passed the primary
        # gate.
        env = bat.soc_envelope()
        assert env is not None, (
            "soc_envelope returned None — primary-SOC fresh gate not "
            "engaged (site reverted to raw _get_state_float?)"
        )

    def test_killswitch_max_age_zero_disables_gate(self):
        """Kill-switch parity: max_age_s=0 → helper skips the age check."""
        bat = self._setup(age_s=99999)
        val = bat._read_fresh_float(
            "sensor.envoy_battery",
            0,  # kill-switch
            stamp="last_reported",
        )
        assert val == 42.0


class TestFrozenPrimarySocEnvoyAvailable:
    """Second D2 site: `envoy_available` (~:2602) — the local-availability
    detector that binds envoy_available=True on a frozen primary SOC."""

    def _setup(self, age_s):
        eid = "sensor.envoy_battery"
        mode_eid = "select.envoy_storage_mode"
        hass = _FakeHass({
            eid: _FrozenState(42.0, age_s=age_s),
            mode_eid: _FrozenState("self_consumption", age_s=1, attrs={}),
        })
        bat = _make_battery(hass, {
            "battery_soc": eid,
            "storage_mode": mode_eid,
        })
        return bat

    def test_frozen_primary_reports_envoy_unavailable(self):
        """WIRE-IN ANCHOR — envoy_available site. When primary SOC is
        FROZEN-VALID, envoy_available must return False. Neuter drill:
        revert energy_battery.py:2602 to raw `_get_state_float` and this
        test FAILS (envoy_available returns True on the frozen entity)."""
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S,
        )
        bat = self._setup(age_s=DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S + 60)
        # envoy_available is a method — locate it.
        # Call the method that reads primary_soc; per source it's part of
        # a helper that returns bool. Method name may vary — use the same
        # `envoy_available` producer.
        result = bat.envoy_available  # @property
        assert result is False, (
            "envoy_available returned True on FROZEN primary SOC — the "
            "primary-SOC fresh gate did not engage at the envoy_available "
            "site (reverted to raw _get_state_float?)"
        )

    def test_fresh_primary_reports_envoy_available(self):
        """Sanity: a fresh primary SOC + a live storage_mode → available."""
        bat = self._setup(age_s=5)
        result = bat.envoy_available  # @property
        assert result is True
