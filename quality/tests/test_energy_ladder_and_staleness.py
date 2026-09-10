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

    def test_helper_fresh_primary_returns_value(self):
        """C-LOW-2 fix-up: retitled — this is a HELPER-level sanity check
        (_read_fresh_float returns the value for a fresh stamp), NOT proof
        that the envelope SITE consumes the freshness gate. The site
        wire-in is exercised by
        test_frozen_primary_does_not_suppress_envelope_engagement."""
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

    def test_helper_frozen_primary_rejected_by_fresh_read(self):
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

    def test_helper_killswitch_max_age_zero_disables_gate(self):
        """C-LOW-1 fix-up: retitled to make clear this is the HELPER-level
        kill-switch parity, NOT proof that any specific D2 site respects
        the kill-switch. Sites are exercised in the wire-in-anchor tests
        (test_frozen_primary_does_not_suppress_envelope_engagement /
        test_frozen_primary_reports_envoy_unavailable)."""
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


# ──────────────────────────────────────────────────────────────────────────
# A-HIGH-1 fix-up — very_poor drain bucket participates in the validator
# ──────────────────────────────────────────────────────────────────────────

class TestLadderVeryPoorBucket:
    """OFFPEAK-DRAIN-VERYPOOR-SLIDER-1 is the 5th quality bucket. Its
    default (30) equals `poor` (30) — a coincidental equality (Bug Class
    #63). Drive it OFF the default to prove the validator branch is
    actually exercised."""

    def _base_with_vp(self, vp):
        return dict(
            reserve_soc=10,
            drain_targets={
                "excellent": 10, "good": 15, "moderate": 20,
                "poor": 30, "very_poor": vp,
            },
            arbitrage_trigger=None,
            peak_buffer_target=80,
            fill_priority_soc=30,
            excess_solar_soc=80,
            ev_battery_drain_soc=20,
            inclement_partial_hold_reserve_floor=30,
        )

    def test_very_poor_at_or_above_poor_accepted(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            validate_threshold_ladder,
        )
        assert validate_threshold_ladder(**self._base_with_vp(30)) is None
        assert validate_threshold_ladder(**self._base_with_vp(50)) is None

    def test_very_poor_below_poor_rejected_monotonic(self):
        """Discriminating config: very_poor=25 < poor=30. Neutering the
        very_poor branch of the monotonic check → this test FAILS."""
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            validate_threshold_ladder,
        )
        result = validate_threshold_ladder(**self._base_with_vp(25))
        assert result is not None
        assert result[0] == "drain_ladder_not_monotonic"
        assert "very_poor" in result[1]

    def test_very_poor_below_reserve_rejected(self):
        """very_poor=5 < reserve=10; drain ladder valid except very_poor."""
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            validate_threshold_ladder,
        )
        kw = self._base_with_vp(5)
        kw["drain_targets"] = {
            "excellent": 10, "good": 15, "moderate": 20,
            "poor": 30, "very_poor": 5,
        }
        result = validate_threshold_ladder(**kw)
        assert result is not None
        assert result[0] == "drain_very_poor_below_reserve"

    def test_peak_buffer_check_uses_top_drain_including_very_poor(self):
        """peak_buffer=45 above poor(30) but below very_poor(50) → reject."""
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            validate_threshold_ladder,
        )
        kw = self._base_with_vp(50)
        kw["peak_buffer_target"] = 45
        result = validate_threshold_ladder(**kw)
        assert result is not None
        assert result[0] == "peak_buffer_target_at_or_below_drain_poor"


# ──────────────────────────────────────────────────────────────────────────
# C-HIGH-1 fix-up — runtime wire-in anchors for _check_threshold_ladder
# ──────────────────────────────────────────────────────────────────────────

class TestCheckThresholdLadderRuntimeWireIn:
    """Guards against the recurring failure: validator unit-tested but
    the runtime call site drops kwargs, or the setter never re-invokes
    the check. Anchors drive the REAL EnergyCoordinator methods."""

    def _make_ec(self, *, fill_priority=90, excess_solar=80,
                 ev_drain=20, reserve=10, inclement_floor=30):
        import types
        from custom_components.universal_room_automation.domain_coordinators.energy import (
            EnergyCoordinator,
        )
        battery = types.SimpleNamespace(
            reserve_soc=reserve,
            _drain_targets={
                "excellent": max(reserve, 10), "good": 15,
                "moderate": 20, "poor": 30, "very_poor": 30,
            },
            _peak_buffer_target=80,
            _inclement_config=lambda: {
                "partial_hold_reserve_floor": inclement_floor,
            },
        )

        class _Hass:
            def __init__(_self):
                _self.data = {}

                class _S:
                    def get(__self, _k):
                        return None
                _self.states = _S()

            def async_create_task(_self, coro):
                try:
                    coro.close()
                except Exception:
                    pass
                task = types.SimpleNamespace()
                task.add_done_callback = lambda _cb: None
                return task

        ec = EnergyCoordinator.__new__(EnergyCoordinator)
        ec.hass = _Hass()
        ec._battery = battery
        ec._fill_priority_soc = fill_priority
        ec._excess_solar_soc = excess_solar
        ec._ev_battery_drain_soc = ev_drain
        ec._ladder_anomaly_last = {}
        # Provide DOMAIN db so emit path stamps the code.
        ec.hass.data = {"universal_room_automation": {"database": types.SimpleNamespace(
            save_anomaly_event=lambda evt: None,
        )}}
        return ec

    def test_runtime_call_passes_fill_priority_and_excess_solar(self):
        """WIRE-IN — dropping fill_priority_soc/excess_solar_soc kwargs
        from the runtime call → this test FAILS (code not stamped)."""
        ec = self._make_ec(
            fill_priority=90, excess_solar=80,
            ev_drain=30, reserve=10, inclement_floor=30,
        )
        ec._check_threshold_ladder()
        assert "fill_priority_above_excess_solar" in ec._ladder_anomaly_last

    def test_runtime_call_passes_ev_drain(self):
        """WIRE-IN — ev_battery_drain_soc kwarg dropped → FAILS."""
        ec = self._make_ec(
            fill_priority=30, excess_solar=80,
            ev_drain=5, reserve=15, inclement_floor=30,
        )
        ec._battery._drain_targets = {
            "excellent": 15, "good": 20, "moderate": 25,
            "poor": 30, "very_poor": 30,
        }
        ec._check_threshold_ladder()
        assert "ev_drain_below_reserve" in ec._ladder_anomaly_last

    def test_runtime_call_passes_inclement_floor(self):
        """WIRE-IN — inclement_partial_hold_reserve_floor kwarg dropped
        OR _inclement_config lookup removed → FAILS."""
        ec = self._make_ec(
            fill_priority=30, excess_solar=80,
            ev_drain=30, reserve=15, inclement_floor=5,
        )
        ec._battery._drain_targets = {
            "excellent": 15, "good": 20, "moderate": 25,
            "poor": 30, "very_poor": 30,
        }
        ec._check_threshold_ladder()
        assert "inclement_partial_hold_below_reserve" in ec._ladder_anomaly_last

    def test_set_ev_battery_drain_soc_recheck_wired(self):
        """WIRE-IN — setter must invoke _check_threshold_ladder. Neuter
        the `self._check_threshold_ladder()` line in set_ev_battery_drain_soc
        → this test FAILS."""
        ec = self._make_ec(
            fill_priority=30, excess_solar=80,
            ev_drain=30, reserve=15, inclement_floor=30,
        )
        ec._battery._drain_targets = {
            "excellent": 15, "good": 20, "moderate": 25,
            "poor": 30, "very_poor": 30,
        }
        ec._ladder_anomaly_last = {}
        ec.set_ev_battery_drain_soc(5)
        assert "ev_drain_below_reserve" in ec._ladder_anomaly_last

    def test_set_fill_priority_soc_recheck_wired(self):
        """WIRE-IN — set_fill_priority_soc setter re-check anchor."""
        ec = self._make_ec(
            fill_priority=30, excess_solar=80,
            ev_drain=30, reserve=15, inclement_floor=30,
        )
        ec._battery._drain_targets = {
            "excellent": 15, "good": 20, "moderate": 25,
            "poor": 30, "very_poor": 30,
        }
        ec._ladder_anomaly_last = {}
        ec.set_fill_priority_soc(90)
        assert "fill_priority_above_excess_solar" in ec._ladder_anomaly_last

    def test_set_excess_solar_soc_recheck_wired(self):
        """WIRE-IN — set_excess_solar_soc setter re-check anchor."""
        ec = self._make_ec(
            fill_priority=50, excess_solar=80,
            ev_drain=30, reserve=15, inclement_floor=30,
        )
        ec._battery._drain_targets = {
            "excellent": 15, "good": 20, "moderate": 25,
            "poor": 30, "very_poor": 30,
        }
        ec._ladder_anomaly_last = {}
        ec.set_excess_solar_soc(40)
        assert "fill_priority_above_excess_solar" in ec._ladder_anomaly_last


# ──────────────────────────────────────────────────────────────────────────
# C-HIGH-2 fix-up — config-flow save-time gate wire-in anchor
# ──────────────────────────────────────────────────────────────────────────

class TestConfigFlowLadderSaveTimeGate:
    """Neutering the `if _ladder_result is not None:` block at
    config_flow.py:4005 → these tests FAIL (save proceeds instead of
    returning a form with errors)."""

    def _run(self, coro):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_inverted_fill_priority_returns_form_with_error(self):
        """WIRE-IN — submit fill_priority(90) > excess_solar(80) via the
        REAL options-flow step. Form + field-scoped + base error."""
        import importlib
        _baec = importlib.import_module("test_baec_config_flow_round_trip")
        _cbcf = importlib.import_module("test_cycle_b_config_flow")
        _make_options_flow = _cbcf._make_options_flow
        _ha_mocks_injected = _baec._ha_mocks_injected
        user_input = {
            "energy_fill_priority_soc": 90,
            "energy_excess_solar_soc": 80,
        }
        flow = _make_options_flow(options={})
        # _FakeHass lacks .data; error-path falls through to show-form which
        # reads self.hass.data.get(DOMAIN, ...) for weather-entity defaults.
        flow.hass.data = {}
        with _ha_mocks_injected():
            result = self._run(
                flow.async_step_coordinator_energy(user_input=user_input),
            )
        assert result["type"] == "form", (
            f"expected form (validation blocked save); got {result}"
        )
        errors = result.get("errors") or {}
        assert errors.get("energy_fill_priority_soc") ==             "fill_priority_above_excess_solar", errors
        assert errors.get("base") == "fill_priority_above_excess_solar", errors

    def test_inclement_below_reserve_routes_to_base(self):
        """B2 fix-up — inclement error routes to `base` only (nested key
        cannot render inline). Adding the inclement field back to the
        `_field_map` → this test FAILS."""
        import importlib
        _baec = importlib.import_module("test_baec_config_flow_round_trip")
        _cbcf = importlib.import_module("test_cycle_b_config_flow")
        _make_options_flow = _cbcf._make_options_flow
        _ha_mocks_injected = _baec._ha_mocks_injected
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            CONF_ENERGY_RESERVE_SOC,
            CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR,
        )
        user_input = {
            CONF_ENERGY_RESERVE_SOC: 40,
            CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR: 10,
            "energy_offpeak_drain_excellent": 40,
            "energy_offpeak_drain_good": 45,
            "energy_offpeak_drain_moderate": 50,
            "energy_offpeak_drain_poor": 55,
            "energy_offpeak_drain_very_poor": 60,
            "energy_peak_buffer_target": 80,
            "energy_fill_priority_soc": 50,
            "energy_excess_solar_soc": 60,
            "energy_ev_battery_drain_soc": 50,
        }
        flow = _make_options_flow(options={})
        # _FakeHass lacks .data; error-path falls through to show-form which
        # reads self.hass.data.get(DOMAIN, ...) for weather-entity defaults.
        flow.hass.data = {}
        with _ha_mocks_injected():
            result = self._run(
                flow.async_step_coordinator_energy(user_input=user_input),
            )
        assert result["type"] == "form", result
        errors = result.get("errors") or {}
        assert errors.get("base") == "inclement_partial_hold_below_reserve"
        assert CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR not in errors, errors
