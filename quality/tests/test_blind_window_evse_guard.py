"""Blind-window EVSE guard + LKG envelope + DP eval persistence.

Cycle: EC blind-window EVSE guard (see PLANNING_ec_blind_window_evse_guard.md).

Falsifiable invariant under test:

INV-BW1 (Blind-Window Battery Isolation) — while SOC is unresolved
(`blind_hold_active`) AND the reserve write path is unverifiable
(`reserve_write_verifiable()` False), no EVSE transitions OFF->ON via any
ensure-on precedence row EXCEPT via one of the TWO sanctioned liveness
escapes, and both escapes route through
`EnergyCoordinator.blind_window_liveness_release(evse_id, reason,
has_pressure)` which consults the envelope and writes ONE decision_log
row (decision_type='blind_window_liveness_release') per consultation:
  1. MAX-DEFER EXPIRY — the outage has exceeded
     `CONF_BLIND_WINDOW_MAX_DEFER_MIN`; helper called with
     `has_pressure=False`. Envelope proving lower < drain_target HOLDS
     the pause; envelope permitting OR unknown YIELDS to must-start-by.
  2. DP MUST-START-BY FIRE — INV-DP2 car-charge liveness deadline;
     helper called with `has_pressure=True` (INV-DP2 trumps envelope).
Any ensure-on that WOULD have fired is logged. Row-2 force-charge is a
prior-tick suppression (not a turn_on site of its own), so it does not
need the helper — B3's drain plumbing (Batch 2) covers it.

Mutation anchors (documented at each test):
  * `_blind_window_guard_engaged` -> if the debounce short-circuit is removed,
    `test_MUTATION_debounce_gates_flap` fails.
  * `_blind_window_max_defer_exceeded` -> if the max-defer cap is dropped,
    `test_MUTATION_max_defer_yields_to_mustartby` fails.
  * `_blind_window_envelope_permits_ride` -> if the envelope lower-bound
    check is removed, `test_MUTATION_envelope_permits_ride_at_high_soc` fails.
  * `_paused_by_blind_window` -> if the pause set is dropped from
    `_stronger_peer_holds` or the guard site skipped, the guard-vs-force-charge
    precedence test fails.
  * `EnergyCoordinator.reserve_write_verifiable` -> if the WV predicate is
    removed, `test_guard_engages_when_wv_unverifiable_and_blind` fails.
  * `SOCEnvelope.compute` -> mutating the sign of `max_discharge_kw` widening
    breaks `test_envelope_widens_downward_over_time`.
"""
from __future__ import annotations

# Bootstrap HA mocks via sibling test (must run BEFORE energy_pool import).
import test_energy_load_shedding_correctness  # noqa: F401  # sets up sys.modules

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.universal_room_automation.domain_coordinators.energy_const import (
    CONF_BLIND_WINDOW_ENTRY_DEBOUNCE_S,
    CONF_BLIND_WINDOW_MAX_DEFER_MIN,
    CONF_DP_EVAL_LOG_RETENTION_DAYS,
    CONF_ENERGY_MAINS_EXPORT_ENTITY,
)
from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
    EVChargerController,
)

# ---------------------------------------------------------------------------
# Fix-up C-HIGH-1 (Batch 3) — LOUD test-shim guard on SOCEnvelope import.
# ---------------------------------------------------------------------------
# The prior try/except silently fell back to a HAND-ROLLED shim whenever the
# production module failed to import under the test harness. This defeated
# reviewer C's mutation A6 (neuter production `SOCEnvelope.compute`
# discharge-widening) — the shim's identical arithmetic would still make
# the tests pass, so the mutation looked "green" while the production code
# was broken. Per the C-HIGH-1 ruling, the failure must be LOUD:
#   (a) Import via the same `custom_components...` package path the rest of
#       the test file uses (bootstrapped by `test_energy_load_shedding_correctness`).
#   (b) Assert `SOCEnvelope.__module__` is the production module — if the
#       import somehow bound a different class, pytest.fail with the
#       observed __module__ so the drift is instantly visible.
# No fallback shim exists anywhere in this file.
# ---------------------------------------------------------------------------
import os as _os
import pytest as _pytest_boot

try:
    from custom_components.universal_room_automation.domain_coordinators.energy_battery import (
        SOCEnvelope,
    )
except Exception as _e:  # noqa: BLE001
    _pytest_boot.fail(
        f"C-HIGH-1: production SOCEnvelope failed to import under the test "
        f"harness — no shim fallback is allowed. Fix the import path before "
        f"re-running tests. Underlying error: {_e!r}"
    )

_EXPECTED_SOC_ENVELOPE_MODULE = (
    "custom_components.universal_room_automation.domain_coordinators.energy_battery"
)
if getattr(SOCEnvelope, "__module__", None) != _EXPECTED_SOC_ENVELOPE_MODULE:
    _pytest_boot.fail(
        f"C-HIGH-1: SOCEnvelope resolved to a non-production module — "
        f"expected {_EXPECTED_SOC_ENVELOPE_MODULE!r}, got "
        f"{getattr(SOCEnvelope, '__module__', None)!r}. A hand-rolled shim "
        f"is not allowed; mutation A6 would go GREEN. Fix the import path."
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeHass:
    def __init__(self) -> None:
        self._states: dict[str, MagicMock] = {}
        self.data = {}

    def _set(self, entity_id: str, state: str, unit: str | None = None) -> None:
        st = MagicMock()
        st.state = state
        st.attributes = {"unit_of_measurement": unit} if unit else {}
        self._states[entity_id] = st

    class _States:
        def __init__(self, outer: "_FakeHass") -> None:
            self._outer = outer

        def get(self, eid):
            return self._outer._states.get(eid)

    @property
    def states(self):
        return _FakeHass._States(self)


def _make_ev(evse_on: bool = False) -> EVChargerController:
    hass = _FakeHass()
    hass._set("switch.garage_a", "on" if evse_on else "off")
    hass._set(
        "sensor.garage_a_power", "1000" if evse_on else "0", unit="W",
    )
    cfg = {"garage_a": {"switch": "switch.garage_a", "power": "sensor.garage_a_power"}}
    return EVChargerController(hass, evse_config=cfg)


def _make_coord_stub(
    *,
    blind_hold: bool = True,
    reserve_verifiable: bool = False,
    envelope: tuple[float, float] | None = None,
    mains_export: bool | None = None,
    drain_target: int = 40,
    liveness_release_returns: bool = True,
) -> SimpleNamespace:
    """Test stub for EnergyCoordinator public surface consumed by the guard.

    Batch 4 additions:
      * `maybe_log_blind_window_defer(evse_id)` — records the call and
        returns True on the FIRST call per evse_id (matching production
        dedup semantics), False after.
      * `_reset_blind_window_defer_dedup()` — clears the recorded set.
      * `blind_window_liveness_release(evse_id, reason, has_pressure)`
        — returns `liveness_release_returns` (default True) and records
        the call so tests can assert wiring.
    """
    ns = SimpleNamespace(
        blind_hold_active=blind_hold,
        reserve_write_verifiable=lambda: reserve_verifiable,
        soc_envelope=lambda: envelope,
        mains_export_active=lambda threshold_w=100.0: mains_export,
        _ev_battery_drain_soc=drain_target,
    )
    ns._defer_logged = set()
    ns._defer_calls = []
    ns._liveness_calls = []

    def _maybe_log(evse_id):
        ns._defer_calls.append(evse_id)
        if evse_id in ns._defer_logged:
            return False
        ns._defer_logged.add(evse_id)
        return True

    def _reset_dedup():
        ns._defer_logged = set()

    def _liveness(evse_id, reason, has_pressure=False):
        ns._liveness_calls.append((evse_id, reason, has_pressure))
        return liveness_release_returns

    ns.maybe_log_blind_window_defer = _maybe_log
    ns._reset_blind_window_defer_dedup = _reset_dedup
    ns.blind_window_liveness_release = _liveness
    return ns


# ---------------------------------------------------------------------------
# SOCEnvelope (reusable primitive)
# ---------------------------------------------------------------------------


def test_envelope_returns_none_when_lkg_missing():
    env = SOCEnvelope(40.0, 30.72, 30.72)
    assert env.compute(None, 0.0, 21600) is None
    assert env.compute(50.0, None, 21600) is None


def test_envelope_returns_none_when_beyond_max_age():
    env = SOCEnvelope(40.0, 30.72, 30.72)
    assert env.compute(50.0, 99999.0, 21600) is None


def test_envelope_collapses_to_point_at_zero_age():
    env = SOCEnvelope(40.0, 30.72, 30.72)
    lo, hi = env.compute(50.0, 0.0, 21600)
    assert lo == pytest.approx(50.0)
    assert hi == pytest.approx(50.0)


def test_envelope_widens_downward_over_time():
    """Mutation: negating max_discharge_kw in .compute makes lo == hi.

    Physics: 30.72 kW * 3600 s / (36 * 40 kWh) = 76.8 pp (fully unbounded
    at max power for 1h) — capped at [0, 100]. Test uses moderate 1000 s.
    """
    env = SOCEnvelope(40.0, 30.72, 30.72)
    lo, hi = env.compute(50.0, 1000.0, 21600)
    # 30.72 * 1000 / (36 * 40) = 21.333...
    assert lo == pytest.approx(50.0 - 21.333, abs=0.05)
    assert hi == pytest.approx(50.0 + 21.333, abs=0.05)


def test_envelope_bounds_clamp_to_percent_range():
    env = SOCEnvelope(40.0, 30.72, 30.72)
    # 30.72 * 5000 / (36 * 40) = 106.6 → hi clamps to 100, lo clamps to 0.
    lo, hi = env.compute(5.0, 5000.0, 21600)
    assert lo == 0.0
    assert hi == 100.0


def test_envelope_zero_capacity_raises():
    with pytest.raises(ValueError):
        SOCEnvelope(0.0, 30.72, 30.72)


# ---------------------------------------------------------------------------
# Guard predicate
# ---------------------------------------------------------------------------


def test_predicate_false_when_envoy_available():
    ev = _make_ev()
    coord = _make_coord_stub(blind_hold=False, reserve_verifiable=False)
    assert ev._blind_window_entry_predicate(coord) is False


def test_predicate_false_when_reserve_verifiable():
    ev = _make_ev()
    coord = _make_coord_stub(blind_hold=True, reserve_verifiable=True)
    assert ev._blind_window_entry_predicate(coord) is False


def test_predicate_true_when_blind_and_unverifiable():
    ev = _make_ev()
    coord = _make_coord_stub(blind_hold=True, reserve_verifiable=False)
    assert ev._blind_window_entry_predicate(coord) is True


# ---------------------------------------------------------------------------
# Debounce (D3 probe gate: sub-2-min blips must NOT flap)
# ---------------------------------------------------------------------------


def test_MUTATION_debounce_gates_flap(monkeypatch):
    """First raw-predicate tick does NOT engage the guard.

    Mutation anchor: if the debounce check is removed from
    `_blind_window_guard_engaged`, this test fails.
    """
    ev = _make_ev()
    coord = _make_coord_stub()
    # First tick: predicate true but debounce not yet satisfied.
    assert ev._blind_window_guard_engaged(coord) is False
    # Rewind the debounce clock so the elapsed passes.
    ev._blind_window_entry_first_at = (
        time.monotonic() - float(CONF_BLIND_WINDOW_ENTRY_DEBOUNCE_S) - 1
    )
    assert ev._blind_window_guard_engaged(coord) is True


def test_debounce_resets_when_predicate_clears():
    ev = _make_ev()
    coord_blind = _make_coord_stub()
    coord_clear = _make_coord_stub(blind_hold=False)
    ev._blind_window_guard_engaged(coord_blind)
    assert ev._blind_window_entry_first_at is not None
    # Predicate clears → debounce timestamp + epoch cleared.
    ev._blind_window_guard_engaged(coord_clear)
    assert ev._blind_window_entry_first_at is None
    assert ev._blind_window_epoch_started_at is None
    assert ev._blind_window_defers_this_epoch == 0


# ---------------------------------------------------------------------------
# Max-defer bound (D3 probe: ~2-3 outages/day >30min must yield)
# ---------------------------------------------------------------------------


def test_MUTATION_max_defer_yields_to_mustartby(monkeypatch):
    """After max-defer minutes, guard yields (returns True on 'exceeded').

    Mutation: dropping the cap → this test fails.
    """
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    ev = _make_ev()
    ev._blind_window_epoch_started_at = dt_util.utcnow() - timedelta(
        minutes=CONF_BLIND_WINDOW_MAX_DEFER_MIN + 1,
    )
    assert ev._blind_window_max_defer_exceeded() is True


def test_max_defer_not_exceeded_when_within_window():
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    ev = _make_ev()
    ev._blind_window_epoch_started_at = dt_util.utcnow() - timedelta(minutes=1)
    assert ev._blind_window_max_defer_exceeded() is False


# ---------------------------------------------------------------------------
# Envelope-permits-ride (Q1 + Q4)
# ---------------------------------------------------------------------------


def test_MUTATION_envelope_permits_ride_at_high_soc():
    """Envelope lower bound >= threshold → ride OK.

    Mutation: dropping the envelope check makes this always False.
    """
    ev = _make_ev()
    coord = _make_coord_stub(envelope=(70.0, 80.0))  # lower 70 >= threshold 40
    assert ev._blind_window_envelope_permits_ride(coord, 40) is True


def test_envelope_denies_ride_below_threshold():
    ev = _make_ev()
    coord = _make_coord_stub(envelope=(20.0, 30.0))
    assert ev._blind_window_envelope_permits_ride(coord, 40) is False


def test_envelope_none_denies_ride():
    ev = _make_ev()
    coord = _make_coord_stub(envelope=None)
    assert ev._blind_window_envelope_permits_ride(coord, 40) is False


def test_mains_export_active_permits_ride_even_without_envelope():
    """Q1 branch a: D4 mains-export witness proves battery not discharging."""
    ev = _make_ev()
    coord = _make_coord_stub(envelope=None, mains_export=True)
    assert ev._blind_window_envelope_permits_ride(coord, 40) is True


# ---------------------------------------------------------------------------
# INV-BW1: full determine_actions guard site
# ---------------------------------------------------------------------------


def _engage_guard(ev: EVChargerController, coord) -> None:
    """Force guard past the debounce so the row-2.5 gate fires this tick."""
    ev._blind_window_entry_first_at = (
        time.monotonic() - float(CONF_BLIND_WINDOW_ENTRY_DEBOUNCE_S) - 1
    )
    from homeassistant.util import dt as dt_util
    ev._blind_window_epoch_started_at = dt_util.utcnow()


def test_INV_BW1_offpeak_ensure_on_deferred_when_guard_engaged():
    """OFF EVSE + blind + unverifiable → no turn_on, guard claims pause."""
    ev = _make_ev(evse_on=False)
    coord = _make_coord_stub()
    _engage_guard(ev, coord)
    actions = ev.determine_actions("off_peak", coord=coord)
    assert "garage_a" in ev._paused_by_blind_window
    assert not any(a["service"] == "switch.turn_on" for a in actions)


def test_INV_BW1_offpeak_fail_safe_pauses_already_on_evse():
    """ON EVSE + blind + unverifiable + envelope denies → turn_off dispatched."""
    ev = _make_ev(evse_on=True)
    coord = _make_coord_stub(envelope=(20.0, 30.0))  # lower < 40 threshold
    _engage_guard(ev, coord)
    actions = ev.determine_actions("off_peak", coord=coord)
    assert any(a["service"] == "switch.turn_off" for a in actions)
    assert "garage_a" in ev._paused_by_blind_window


def test_INV_BW1_envelope_high_bound_permits_ride():
    """ON EVSE + blind + envelope proves SOC >= threshold → no turn_off."""
    ev = _make_ev(evse_on=True)
    coord = _make_coord_stub(envelope=(70.0, 80.0))  # lower >= 40 threshold
    _engage_guard(ev, coord)
    actions = ev.determine_actions("off_peak", coord=coord)
    # No pause action; guard claim exists (documented "held pending clear").
    assert not any(a["service"] == "switch.turn_off" for a in actions)


def test_force_charge_preempts_guard():
    """Row 2 force-charge escape hatch (INV-BW1 explicit exception).

    Mutation: removing the `not force_charge_active` guard around the
    row-2.5 block re-pauses the EVSE even under force-charge.
    """
    ev = _make_ev(evse_on=False)
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    ev.set_force_charge_override(dt_util.utcnow() + timedelta(minutes=30))
    coord = _make_coord_stub()
    _engage_guard(ev, coord)
    actions = ev.determine_actions("off_peak", coord=coord)
    # Force-charge branch reaches (row 2 escape); pause set NOT populated
    # by blind-window logic on this tick.
    assert "garage_a" not in ev._paused_by_blind_window


def test_guard_carry_over_is_idempotent():
    """Second engaged tick with EVSE already OFF issues no new turn_off."""
    ev = _make_ev(evse_on=True)
    coord = _make_coord_stub(envelope=(20.0, 30.0))
    _engage_guard(ev, coord)
    ev.determine_actions("off_peak", coord=coord)
    # Simulate hardware now off after first pause.
    ev.hass._set("switch.garage_a", "off")
    ev.hass._set("sensor.garage_a_power", "0", unit="W")
    actions2 = ev.determine_actions("off_peak", coord=coord)
    turn_offs = [a for a in actions2 if a["service"] == "switch.turn_off"]
    assert len(turn_offs) == 0


def test_guard_clears_on_envoy_recovery():
    """Recovery: envoy_available flips → debounce state + pause set drained."""
    ev = _make_ev(evse_on=False)
    ev._paused_by_blind_window.add("garage_a")
    coord = _make_coord_stub(blind_hold=False)  # Envoy back
    ev.determine_actions("off_peak", coord=coord)
    assert "garage_a" not in ev._paused_by_blind_window


def test_stronger_peer_holds_includes_blind_window():
    """Peer battery-protection set membership.

    Mutation: removing `_paused_by_blind_window` from `_stronger_peer_holds`
    makes this test fail — and then TOU ensure-on + excess-solar could
    pre-empt the guard.
    """
    ev = _make_ev()
    ev._paused_by_blind_window.add("garage_a")
    assert ev._stronger_peer_holds("garage_a") is True


# ---------------------------------------------------------------------------
# D4: excess-solar path consults mains-export when Envoy blind
# ---------------------------------------------------------------------------


def test_MUTATION_excess_solar_defers_when_blind_and_no_d4_witness():
    """Envoy blind + no mains-export → excess-solar refused, no turn_on.

    Mutation: removing the D4 guard block from
    `determine_excess_solar_actions` lets stale SOC drive the claim.
    """
    ev = _make_ev(evse_on=False)
    coord = _make_coord_stub(mains_export=None)
    _engage_guard(ev, coord)
    actions = ev.determine_excess_solar_actions(
        soc=None, remaining_forecast_kwh=10.0, tou_period="off_peak", coord=coord,
    )
    assert not any(a["service"] == "switch.turn_on" for a in actions)


def test_C_HIGH_2_witness_and_envelope_together_permit_CONTINUE():
    """C-HIGH-2 + D-MED-1 (Batch 3) — CONTINUE-permission semantics.

    Setup: guard engaged, EVSE already ON and already in
    `_excess_solar_active` (a claim was active pre-outage), witness True
    AND envelope permits ride. RULING: the active EVSE may CONTINUE —
    no turn_off, no drain, no `_paused_by_blind_window` claim. New
    claims still refused (return early).

    Mutation A4 (delete the D4 witness block entirely) → this test's
    complement `test_MUTATION_excess_solar_defers_when_blind_and_no_d4_witness`
    passes trivially even after mutation because SOC=None + blind
    already refuses; but THIS test would go RED under A4 (the drop leg
    would turn off the already-ON EVSE), so A4 no longer looks green.
    """
    ev = _make_ev(evse_on=True)
    coord = _make_coord_stub(
        envelope=(70.0, 80.0),  # lower 70 >= threshold 40 ⇒ envelope ok
        mains_export=True,
    )
    _engage_guard(ev, coord)
    ev._excess_solar_active.add("garage_a")
    actions = ev.determine_excess_solar_actions(
        soc=None,  # blind ⇒ SOC unknowable; witness/envelope only
        remaining_forecast_kwh=10.0, tou_period="off_peak", coord=coord,
    )
    # No turn_off — active EVSE continues.
    assert not any(a["service"] == "switch.turn_off" for a in actions), (
        "CONTINUE-permission violated: witness + envelope both ok yet "
        "an already-active excess-solar EVSE was dropped"
    )
    # No turn_on either — new claims refused.
    assert not any(a["service"] == "switch.turn_on" for a in actions)
    # Claim preserved, no blind-window pause claim.
    assert "garage_a" in ev._excess_solar_active
    assert "garage_a" not in ev._paused_by_blind_window


def test_C_HIGH_2_no_witness_forces_DROP_of_active_evse():
    """Under CONTINUE-permission semantics, an already-active excess-
    solar EVSE MUST be dropped (turn_off + claim drain + guard-pause add)
    when the witness is absent. This is the fail-safe leg.
    """
    ev = _make_ev(evse_on=True)
    coord = _make_coord_stub(envelope=(70.0, 80.0), mains_export=None)
    _engage_guard(ev, coord)
    ev._excess_solar_active.add("garage_a")
    actions = ev.determine_excess_solar_actions(
        soc=None, remaining_forecast_kwh=10.0, tou_period="off_peak",
        coord=coord,
    )
    assert any(a["service"] == "switch.turn_off" for a in actions)
    assert "garage_a" not in ev._excess_solar_active
    assert "garage_a" in ev._paused_by_blind_window


def test_C_HIGH_2_envelope_denies_forces_DROP_even_with_witness():
    """Both conditions are required. Witness True but envelope denies
    (SOC bounded below drain threshold) => DROP.
    """
    ev = _make_ev(evse_on=True)
    coord = _make_coord_stub(
        envelope=(20.0, 30.0),  # lower 20 < threshold 40 ⇒ envelope denies
        mains_export=True,
    )
    _engage_guard(ev, coord)
    ev._excess_solar_active.add("garage_a")
    actions = ev.determine_excess_solar_actions(
        soc=None, remaining_forecast_kwh=10.0, tou_period="off_peak",
        coord=coord,
    )
    assert any(a["service"] == "switch.turn_off" for a in actions)
    assert "garage_a" not in ev._excess_solar_active
    assert "garage_a" in ev._paused_by_blind_window


def test_C_HIGH_2_new_claims_refused_even_with_witness_and_envelope():
    """New claims are refused while blind, regardless of witness state.
    An EVSE NOT already in `_excess_solar_active` must not gain the
    claim via the CONTINUE-permission leg — that leg is CONTINUE-only.
    """
    ev = _make_ev(evse_on=False)
    coord = _make_coord_stub(envelope=(70.0, 80.0), mains_export=True)
    _engage_guard(ev, coord)
    # NOT in _excess_solar_active — a would-be new claim.
    assert "garage_a" not in ev._excess_solar_active
    actions = ev.determine_excess_solar_actions(
        soc=None, remaining_forecast_kwh=10.0, tou_period="off_peak",
        coord=coord,
    )
    assert not any(a["service"] == "switch.turn_on" for a in actions)
    assert "garage_a" not in ev._excess_solar_active


# ---------------------------------------------------------------------------
# D2: DP eval decision-log write shape
# ---------------------------------------------------------------------------


def test_retention_constant_is_90_days():
    assert CONF_DP_EVAL_LOG_RETENTION_DAYS == 90


def test_conf_mains_export_key_is_stable():
    """The CONF key must not silently rename — options-flow / reload-suppress
    membership + operator-persisted configs depend on the string.
    """
    assert CONF_ENERGY_MAINS_EXPORT_ENTITY == "energy_mains_export_entity"


# ---------------------------------------------------------------------------
# Reload-suppression trap (per operator rule)
# ---------------------------------------------------------------------------


def test_mains_export_key_in_reload_suppress_set():
    """New CONF key must be in `OPTIONS_RELOAD_SUPPRESS_KEYS` so options
    edits don't trigger a full CM reload. Source-parse (init module can't
    fully import under the test mock stack).
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "__init__.py",
    )
    with open(src_path) as f:
        src = f.read()
    idx = src.find("OPTIONS_RELOAD_SUPPRESS_KEYS: frozenset")
    assert idx != -1, "reload-suppress set not found in __init__.py"
    # Grab the frozenset body — roughly 5000 chars is sufficient.
    body = src[idx : idx + 8000]
    assert "_CONF_ENERGY_MAINS_EXPORT_ENTITY" in body, (
        "new CONF key must appear in OPTIONS_RELOAD_SUPPRESS_KEYS body"
    )


# ---------------------------------------------------------------------------
# Fix-up D-CRIT-2 (Batch 1) — restart mid-outage persistence
# ---------------------------------------------------------------------------
# RULING: (a) persist `_blind_window_epoch_started_at` alongside the pause
# set (also fixes D-LOW-1 max-defer clock reset); (b) on restore of a
# non-empty set, mark the guard pre-engaged (skip debounce); (c) the
# else-branch drains membership ONLY when the raw entry predicate is
# confirmed False (envoy back), not when debounce is merely pending.
#
# These tests exercise the guard AFTER a simulated restart mid-outage:
# the persisted pause set is restored, the pre-engaged flag is set, and
# the very first post-restart tick MUST keep the EVSE paused (no turn_on).


def test_pre_engaged_flag_bypasses_debounce_on_first_tick():
    """Restart-restore case: pre-engaged flag makes the first tick engage
    immediately, no debounce wait. Mutation: removing the pre-engaged
    bypass in `_blind_window_guard_engaged` reverts to the flapping bug.
    """
    ev = _make_ev(evse_on=True)
    coord = _make_coord_stub()  # raw predicate True (blind + unverifiable)
    from homeassistant.util import dt as dt_util
    from datetime import timedelta
    # Simulate a restart-restore: persisted pause set + persisted epoch,
    # NO fresh entry_first_at (would be None post-restart RAM boot).
    ev._paused_by_blind_window.add("garage_a")
    ev.mark_pre_engaged_from_restore(
        dt_util.utcnow() - timedelta(minutes=5),  # outage started 5min ago
    )
    # First post-restart tick — pre-engaged bypass MUST fire True.
    assert ev._blind_window_guard_engaged(coord) is True
    # After consumption, subsequent ticks stay engaged via seeded
    # entry_first_at (debounce still satisfied on next call).
    assert ev._blind_window_pre_engaged is False
    assert ev._blind_window_guard_engaged(coord) is True


def test_pre_engaged_epoch_survives_restore_for_max_defer():
    """D-LOW-1 close: the persisted epoch anchors max-defer to the actual
    outage start-time, not post-restart now(). A 5-hour-old epoch trips
    max-defer even though the restart just happened.
    """
    from homeassistant.util import dt as dt_util
    from datetime import timedelta
    ev = _make_ev()
    ev._paused_by_blind_window.add("garage_a")
    ev.mark_pre_engaged_from_restore(
        dt_util.utcnow() - timedelta(minutes=CONF_BLIND_WINDOW_MAX_DEFER_MIN + 5),
    )
    # Max-defer must be exceeded because the epoch is honestly old.
    assert ev._blind_window_max_defer_exceeded() is True


def test_MUTATION_mid_outage_restart_first_tick_keeps_evse_paused(monkeypatch):
    """B's mandated mid-outage-restart fixture.

    Setup: outage in progress, EVSE is currently ON (never got its
    fail-safe pause pre-crash — or already paused, either way we prove
    the RESTORED pause set means the guard IMMEDIATELY commands OFF /
    stays OFF, no `switch.turn_on`).

    Mutations killed:
      * Removing `mark_pre_engaged_from_restore` wiring => guard reports
        not engaged on first tick, else-branch would drain the set OR
        (post-fix) leaves membership intact but ensure-on could still
        fire in a subsequent tick. Either failure mode makes this test
        fail (no persisted pause, guard cannot claim, ensure-on wins).
      * Reverting the else-branch drain to unconditional discard =>
        first tick with `_blind_window_pre_engaged=True` still engages
        via the bypass, but if a code-path bug leaves the guard in the
        else-branch (e.g. broken pre-engaged path), unconditional drain
        would immediately wipe the restored set. Guarded by the
        assertion below.
    """
    from homeassistant.util import dt as dt_util
    from datetime import timedelta
    ev = _make_ev(evse_on=True)
    coord = _make_coord_stub(envelope=(20.0, 30.0))  # envelope denies ride
    # Simulate the restore handler having run.
    ev._paused_by_blind_window.add("garage_a")
    ev.mark_pre_engaged_from_restore(
        dt_util.utcnow() - timedelta(minutes=10),
    )
    actions = ev.determine_actions("off_peak", coord=coord)
    # No turn_on emitted (guard has authority).
    assert not any(a["service"] == "switch.turn_on" for a in actions)
    # Restored pause set survived the tick.
    assert "garage_a" in ev._paused_by_blind_window
    # Fail-safe pause leg still commands OFF for the currently-ON EVSE.
    assert any(a["service"] == "switch.turn_off" for a in actions)


def test_mid_outage_restart_else_branch_narrowed_drain_holds_membership_during_debounce():
    """Fix-up D-CRIT-2 (c) — else-branch drains only when raw predicate is
    confirmed False. During a debounce-pending tick (raw True, engaged
    False because pre-engaged is off and clock hasn't elapsed), the else
    branch MUST NOT drain the pause set.

    Prior-bug repro: even without the pre-engaged bypass, membership
    survives a debounce-pending tick provided the raw predicate says
    we're still blind.
    """
    ev = _make_ev(evse_on=False)
    coord = _make_coord_stub()  # raw predicate True
    ev._paused_by_blind_window.add("garage_a")
    # Force the debounce clock to be PENDING (freshly stamped now).
    import time as _time
    ev._blind_window_entry_first_at = _time.monotonic()  # 0 elapsed
    # No pre-engaged bypass (default False) — engaged reports False due
    # to debounce, but raw predicate is True.
    assert ev._blind_window_guard_engaged(coord) is False
    # NOTE: the guard-engaged call above set entry_first_at as a side
    # effect if it was None; we set it explicitly, so debounce is still
    # pending. The determine_actions else-branch must NOT drain because
    # the raw predicate is True (this is D-CRIT-2 (c)).
    ev.determine_actions("off_peak", coord=coord)
    assert "garage_a" in ev._paused_by_blind_window


def test_else_branch_drains_only_on_confirmed_envoy_recovery():
    """Fix-up D-CRIT-2 (c) — the drain path fires when the raw predicate
    is False (envoy actually back). Existing carry-over-then-recovery test
    still holds. This is the paired case: identical to
    `test_guard_clears_on_envoy_recovery` but explicitly through the
    else-branch drain gate.
    """
    ev = _make_ev(evse_on=False)
    ev._paused_by_blind_window.add("garage_a")
    coord_recovered = _make_coord_stub(blind_hold=False)  # raw predicate False
    ev.determine_actions("off_peak", coord=coord_recovered)
    assert "garage_a" not in ev._paused_by_blind_window


def test_mark_pre_engaged_from_restore_stores_epoch():
    """Public helper contract: sets both epoch + flag; flag is one-shot
    (consumed by next `_blind_window_guard_engaged` call).
    """
    from homeassistant.util import dt as dt_util
    ev = _make_ev()
    stamp = dt_util.utcnow()
    ev.mark_pre_engaged_from_restore(stamp)
    assert ev._blind_window_epoch_started_at == stamp
    assert ev._blind_window_pre_engaged is True


# ===========================================================================
# Fix-up Batch 2 — D-HIGH-1 nine sites + B3 + B4 + enumeration contract
# ===========================================================================


# ---------------------------------------------------------------------------
# ENUMERATION CONTRACT (D-HIGH-1) — auditable list of every EVSE
# `switch.turn_on` emission site in energy_pool.py + energy.py that could
# resume/release an EVSE. Each site MUST either (a) consult the blind-window
# guard membership set in its own owner-precedence list, OR (b) be on the
# sanctioned-exemption list below.
#
# Sanctioned exemptions (INV-BW1 escape hatches — MUST stay short):
#   * MUST_START_BY — the DP-liveness ceiling. Fix-up D-HIGH-2 (Batch 3)
#     will wrap this in an explicit liveness-release helper that consults
#     the envelope + writes a `blind_window_liveness_release` decision_log
#     row. Until then the exemption exists so the DP invariant is not
#     accidentally violated by this batch.
# Note on force-charge: force-charge does NOT emit a dedicated turn_on;
# it works by SUPPRESSING peak/mid_peak pause and SKIPPING the row-2.5
# guard block. B3 (Batch 2) drains `_paused_by_blind_window` at
# determine_actions off_peak so the peer-guard `continue` cannot deadlock
# an already-guard-claimed EVSE when the operator flips force-charge.
#
# If a NEW turn_on site appears in either file that is NOT in this table,
# `test_D_HIGH_1_enumeration_contract_covers_every_evse_turn_on_site` fails.
# ---------------------------------------------------------------------------

# name -> (relative_file_path, marker_substring, kind)
# kind ∈ {"guard_covered", "guard_covered_via_liveness_helper",
#         "force_charge_exempt", "must_start_by_exempt"}
# The two "exempt" kinds are LEGACY — Batch 4 (D-HIGH-2) closed the last
# bare exemption. Retained in the enum so a regression can re-introduce
# one and immediately fail `test_D_HIGH_1_contract_has_no_bare_exemptions_after_batch_4`.
# marker_substring is used to identify the specific block after slicing near
# the `switch.turn_on` line — it is a distinctive log/comment string in the
# same routine that anchors the site to a semantic name.
EVSE_TURN_ON_SITE_CONTRACT = {
    # ============= energy_pool.py — EVChargerController =============
    "off_peak_ensure_on": (
        "custom_components/universal_room_automation/domain_coordinators/energy_pool.py",
        "EV: proactive off-peak turn-on",
        "guard_covered",
    ),
    "excess_solar_claim": (
        "custom_components/universal_room_automation/domain_coordinators/energy_pool.py",
        "Excess solar: turning on",
        "guard_covered",
    ),
    "grid_cap_resume": (
        "custom_components/universal_room_automation/domain_coordinators/energy_pool.py",
        "EV grid cap: resuming",
        "guard_covered",
    ),
    "battery_drain_resume": (
        "custom_components/universal_room_automation/domain_coordinators/energy_pool.py",
        "EV battery drain: resuming",
        "guard_covered",
    ),
    "fill_priority_resume": (
        "custom_components/universal_room_automation/domain_coordinators/energy_pool.py",
        "EV fill-priority: resuming",
        "guard_covered",
    ),
    "arbitrage_release": (
        "custom_components/universal_room_automation/domain_coordinators/energy_pool.py",
        "EV %s resumed (arbitrage released",
        "guard_covered",
    ),
    "release_all_tou": (
        "custom_components/universal_room_automation/domain_coordinators/energy_pool.py",
        "EV release_all_tou: releasing",
        "guard_covered",
    ),
    "release_all_fill_priority": (
        "custom_components/universal_room_automation/domain_coordinators/energy_pool.py",
        "EV release_all_fill_priority: releasing",
        "guard_covered",
    ),
    "release_all_grid_cap": (
        "custom_components/universal_room_automation/domain_coordinators/energy_pool.py",
        "EV release_all_grid_cap: releasing",
        "guard_covered",
    ),
    # ============= energy.py — EnergyCoordinator =============
    "load_shed_restore": (
        "custom_components/universal_room_automation/domain_coordinators/energy.py",
        "Load shed release EV %s",  # release-side turn_on
        "guard_covered",
    ),
    "dp_reversion_resume": (
        "custom_components/universal_room_automation/domain_coordinators/energy.py",
        "drain-precedence: resumed EVSE",
        "guard_covered",
    ),
    "dp_must_start_by_forced": (
        "custom_components/universal_room_automation/domain_coordinators/energy.py",
        "drain-precedence must-start-by fire: forced EVSE",
        # Fix-up D-HIGH-2 (Batch 4) — no longer an exempt turn_on site.
        # The DP must-start-by path routes through
        # `blind_window_liveness_release(has_pressure=True)` which
        # consults the envelope + writes a decision_log row before the
        # turn_on can fire. Now guard-covered via helper. Batch 6 adds
        # ride-authority latch so the next tick cannot re-capture.
        "guard_covered_via_liveness_helper",
    ),
    # D-MED-1 (Batch 6) — the `dp_reversion_resume` entry above is
    # discovered by the enumerator's NEW positional-idiom scanner in
    # addition to the hand-list. No new contract entry needed for the
    # two DP sites; the pre-existing `dp_reversion_resume` +
    # `dp_must_start_by_forced` entries cover them, and the scanner
    # confirms both are actually reachable in source.
}


def _iter_evse_turn_on_line_numbers(src_path):
    """Yield line numbers of every `switch.turn_on` payload in the file.

    D-MED-1 (Batch 6) — scans BOTH idioms:
      (a) The dict-payload shape used by `EVChargerController` actions:
          ``"service": "switch.turn_on"`` on a payload line.
      (b) The positional `hass.services.async_call` shape used by DP
          release paths in `EnergyCoordinator`: ``async_call("switch",
          "turn_on"`` — with the two literal args on the same line.
    Scope: this scanner is anchored to TWO source files only —
    `energy_pool.py` (EVChargerController class body) and `energy.py`
    (`_execute_shed_action` EV branch + DP release paths). Non-EVSE
    contexts (SmartPlugController class body in energy_pool.py,
    `target == "smart_plugs"` / `target == "hvac"` branches in
    energy.py) use the SAME strings; the caller must filter them out.
    An EVSE `switch.turn_on` site added to any OTHER file will not be
    scanned by this contract — that is a deliberate scope limitation
    the enumeration test docstring makes explicit.
    """
    with open(src_path) as f:
        lines = f.readlines()
    hits = []
    for i, line in enumerate(lines, start=1):
        if '"service": "switch.turn_on"' in line:
            hits.append(i)
        elif '"switch", "turn_on"' in line:
            # Positional shape: `hass.services.async_call("switch",
            # "turn_on", ...)`. The two literal args land on one line
            # in the DP release sites; anchor the pair to distinguish
            # from unrelated `"switch"` mentions.
            hits.append(i)
    return hits, lines


def _find_smart_plug_class_range(lines):
    """Return (start, end) line numbers of the SmartPlugController class
    in energy_pool.py so we can EXCLUDE its `switch.turn_on` sites (out
    of EVSE scope). Also returns the end line of EVChargerController.
    """
    smart_plug_start = None
    ev_charger_end = None
    for i, line in enumerate(lines, start=1):
        if line.startswith("class SmartPlugController"):
            smart_plug_start = i
            ev_charger_end = i - 1
            break
    return smart_plug_start, ev_charger_end


def _find_non_evse_target_ranges(lines):
    """Return line ranges in energy.py that host non-EVSE `switch.turn_on`
    payloads inside `_execute_shed_action` — the `target == "smart_plugs"`
    and `target == "hvac"` branches. Their turn_on payloads are out of
    EVSE scope and must be excluded from the enumeration.
    """
    ranges = []
    smart_plug_start = None
    hvac_start = None
    end_marker = None
    for i, line in enumerate(lines, start=1):
        if 'elif target == "smart_plugs"' in line:
            smart_plug_start = i
        elif 'elif target == "hvac"' in line:
            hvac_start = i
            if smart_plug_start is not None:
                ranges.append((smart_plug_start, i - 1))
        elif hvac_start is not None and end_marker is None:
            # End of _execute_shed_action: next dedented def or new
            # top-level `elif target == ...` — approximate by hunting the
            # next `def ` at method indentation.
            stripped = line.rstrip("\n")
            if stripped.startswith("    def ") or (
                stripped and not stripped.startswith(" ") and not stripped.startswith("\t")
            ):
                end_marker = i - 1
                ranges.append((hvac_start, end_marker))
                break
    if hvac_start is not None and end_marker is None:
        ranges.append((hvac_start, len(lines)))
    return ranges


def _nearest_prior_marker(lines, hit_line, contract):
    """Return the contract key whose marker appears in the ~30 lines
    surrounding the hit, or None if unmatched.
    """
    window_start = max(0, hit_line - 25)
    window_end = min(len(lines), hit_line + 25)
    window = "".join(lines[window_start:window_end])
    for key, (_path, marker, _kind) in contract.items():
        if marker in window:
            return key
    return None


def test_D_HIGH_1_enumeration_contract_covers_every_evse_turn_on_site():
    """D-HIGH-1 auditable enumeration test.

    Source-parses every `switch.turn_on` emission site in the two files
    that host EVSE control paths (energy_pool.py::EVChargerController and
    energy.py::EnergyCoordinator). Every hit must be classifiable as
    either (a) covered by the blind-window guard's peer-owner set (i.e.
    the routine consults `_paused_by_blind_window` OR routes through
    `_stronger_peer_holds` which already includes it), OR (b) a
    sanctioned exemption (force-charge / must-start-by).

    Mutations killed:
      * Adding a new EVSE turn_on site without also adding it to the
        contract table above => this test fails on the next commit.
      * Removing the `_paused_by_blind_window` inline check at any
        "guard_covered" site => the paired per-site behavioral test in
        this module (or the guard-integration tests already shipped)
        fails; this enumeration is the AUDIT LEDGER, the behavioral
        tests are the load-bearing proofs.
    """
    repo_root = _os.path.join(_os.path.dirname(__file__), "..", "..")
    # Group hits by file (they share the contract table).
    files_seen = set()
    for _key, (rel, _marker, _kind) in EVSE_TURN_ON_SITE_CONTRACT.items():
        files_seen.add(rel)

    unmatched = []
    for rel in sorted(files_seen):
        src = _os.path.join(repo_root, rel)
        hits, lines = _iter_evse_turn_on_line_numbers(src)
        # For energy_pool.py, exclude SmartPlugController + downstream
        # (its plug turn_on sites are NOT EVSE control paths).
        if rel.endswith("energy_pool.py"):
            smart_start, _ev_end = _find_smart_plug_class_range(lines)
            if smart_start is not None:
                hits = [h for h in hits if h < smart_start]
        # For energy.py, exclude `target == "smart_plugs"` and
        # `target == "hvac"` branches inside `_execute_shed_action`.
        if rel.endswith("energy.py"):
            excluded = _find_non_evse_target_ranges(lines)
            def _in_excluded(h):
                for lo, hi in excluded:
                    if lo <= h <= hi:
                        return True
                return False
            hits = [h for h in hits if not _in_excluded(h)]
        for h in hits:
            key = _nearest_prior_marker(lines, h, EVSE_TURN_ON_SITE_CONTRACT)
            if key is None:
                unmatched.append((rel, h))
    assert not unmatched, (
        f"Unclassified EVSE `switch.turn_on` site(s) — add to "
        f"EVSE_TURN_ON_SITE_CONTRACT or remove: {unmatched}"
    )


def test_D_HIGH_1_contract_has_no_bare_exemptions_after_batch_4():
    """Batch 4 (D-HIGH-2) closed the last bare INV-BW1 exemption. All
    live turn_on sites are now either directly guard-covered (peer-
    defer includes `_paused_by_blind_window`) or covered-via-liveness-
    helper (must-start-by routes through
    `blind_window_liveness_release`). Any NEW bare exemption MUST
    break this test — the two sanctioned escapes (max-defer expiry,
    must-start-by fire) both flow through the helper, which is not a
    bare exemption.
    """
    bare_exempt_kinds = {"force_charge_exempt", "must_start_by_exempt"}
    bare_keys = [
        k for k, (_p, _m, kind) in EVSE_TURN_ON_SITE_CONTRACT.items()
        if kind in bare_exempt_kinds
    ]
    assert bare_keys == [], (
        f"Bare-exemption drift — all live turn_on sites should be "
        f"guard_covered or guard_covered_via_liveness_helper, but "
        f"found bare exempts: {bare_keys}"
    )


def test_D_HIGH_2_liveness_helper_covers_dp_must_start_by_site():
    """Positive assertion: the DP must-start-by fire is now classified
    as `guard_covered_via_liveness_helper` — the enumeration contract's
    proof that D-HIGH-2 wired the site through the helper.
    """
    assert EVSE_TURN_ON_SITE_CONTRACT["dp_must_start_by_forced"][2] == (
        "guard_covered_via_liveness_helper"
    )


# ---------------------------------------------------------------------------
# Per-site behavioral tests (D-HIGH-1 load-bearing proofs)
# ---------------------------------------------------------------------------


def test_grid_cap_resume_defers_to_blind_window_owner():
    """Site 1: grid-cap resume drops its own claim + does NOT turn on
    when `_paused_by_blind_window` still holds the EVSE.

    Mutation: removing the inline `_paused_by_blind_window` check at the
    grid-cap resume site fires a spurious turn_on and this test fails.
    """
    ev = _make_ev(evse_on=False)
    ev._paused_by_grid_cap.add("garage_a")
    ev._paused_by_blind_window.add("garage_a")
    # Grid at 0 kW (well below cap) — resume conditions met.
    actions = ev.determine_grid_cap_actions(
        net_power_kw=0.0, grid_cap_kw=10.0, hysteresis_kw=1.0,
    )
    # No turn_on emitted.
    assert not any(a["service"] == "switch.turn_on" for a in actions)
    # Grid-cap owner released (its claim dropped when other owner holds),
    # blind-window claim preserved for the next tick's own decision.
    assert "garage_a" not in ev._paused_by_grid_cap
    assert "garage_a" in ev._paused_by_blind_window


def test_release_all_tou_defers_to_blind_window_owner():
    """Site 5: release_all_tou drops the TOU membership but does NOT
    turn on while blind-window still owns the device.
    """
    ev = _make_ev(evse_on=False)
    ev._paused_by_us.add("garage_a")
    ev._paused_by_blind_window.add("garage_a")
    actions = ev.release_all_tou()
    assert not any(a["service"] == "switch.turn_on" for a in actions)
    assert "garage_a" not in ev._paused_by_us
    assert "garage_a" in ev._paused_by_blind_window


def test_release_all_fill_priority_defers_to_blind_window_owner():
    ev = _make_ev(evse_on=False)
    ev._paused_by_fill_priority.add("garage_a")
    ev._paused_by_blind_window.add("garage_a")
    actions = ev.release_all_fill_priority()
    assert not any(a["service"] == "switch.turn_on" for a in actions)
    assert "garage_a" not in ev._paused_by_fill_priority
    assert "garage_a" in ev._paused_by_blind_window


def test_release_all_grid_cap_defers_to_blind_window_owner():
    ev = _make_ev(evse_on=False)
    ev._paused_by_grid_cap.add("garage_a")
    ev._paused_by_blind_window.add("garage_a")
    actions = ev.release_all_grid_cap()
    assert not any(a["service"] == "switch.turn_on" for a in actions)
    assert "garage_a" not in ev._paused_by_grid_cap
    assert "garage_a" in ev._paused_by_blind_window


# ---------------------------------------------------------------------------
# B3 — force-charge preempts blind-window guard (INV-BW1 escape)
# ---------------------------------------------------------------------------


def test_B3_force_charge_drains_blind_window_before_2a_check():
    """Force-charge is the sole INV-BW1 escape. If the EVSE was paused by
    the guard on a prior tick (membership survives ticks), force-charge
    MUST drain it BEFORE the 2a peer-guard check — otherwise
    `_stronger_peer_holds` (which now includes blind-window) causes the
    2a `continue` and force-charge cannot preempt.

    Mutation: removing the B3 drain snippet at determine_actions off_peak
    (`if force_charge_active and evse_id in self._paused_by_blind_window`)
    makes this test fail — force-charge remains deadlocked behind the
    guard's pause claim.
    """
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    ev = _make_ev(evse_on=False)
    # Pre-existing guard claim from a prior tick.
    ev._paused_by_blind_window.add("garage_a")
    # Operator hits the force-charge button.
    ev.set_force_charge_override(dt_util.utcnow() + timedelta(minutes=30))
    # Coord passed (guard block skipped when force_charge_active).
    coord = _make_coord_stub()
    actions = ev.determine_actions("off_peak", coord=coord)
    # The B3 drain runs => membership dropped.
    assert "garage_a" not in ev._paused_by_blind_window
    # Force-charge preempt is complete: an ensure-on can now fire in the
    # normal downstream path. We assert the primary effect (drain); the
    # ensure-on dispatch is guarded by other precedence rules and is
    # covered by existing force-charge tests.


# ---------------------------------------------------------------------------
# B4 — guard-not-engaged drain at top of determine_excess_solar_actions
# ---------------------------------------------------------------------------


def test_B4_daytime_recovery_drains_stale_blind_window_membership():
    """B4 (Batch 2): symmetric to determine_actions off_peak else-branch
    narrowing. When the raw entry predicate flips False (envoy back,
    reserve write verifiable), stale `_paused_by_blind_window` membership
    that survived from an overnight outage MUST be drained at the top of
    `determine_excess_solar_actions` so a daytime claim can proceed.

    Mutation: removing the B4 drain snippet (`if not
    self._blind_window_entry_predicate(coord): drain`) makes this test
    fail — the stale membership blocks `_stronger_peer_holds` and the
    normal claim path never fires.
    """
    ev = _make_ev(evse_on=False)
    # Overnight outage left an orphan claim.
    ev._paused_by_blind_window.add("garage_a")
    # Daytime — envoy back, reserve verifiable (raw predicate False).
    coord = _make_coord_stub(blind_hold=False, reserve_verifiable=True)
    actions = ev.determine_excess_solar_actions(
        soc=95.0, remaining_forecast_kwh=10.0,
        tou_period="off_peak", soc_threshold=95, coord=coord,
    )
    # Membership drained by B4.
    assert "garage_a" not in ev._paused_by_blind_window
    # And the claim path proceeded (turn_on emitted).
    assert any(a["service"] == "switch.turn_on" for a in actions)


def test_B4_debounce_pending_does_NOT_drain_membership():
    """B4 counterpart: when raw predicate is TRUE (blind + unverifiable)
    but debounce is still counting, we must NOT drain — that would be the
    D-CRIT-2 flap sibling. The drain gate must be raw-false only.
    """
    ev = _make_ev(evse_on=False)
    ev._paused_by_blind_window.add("garage_a")
    coord = _make_coord_stub()  # raw True
    ev.determine_excess_solar_actions(
        soc=95.0, remaining_forecast_kwh=10.0,
        tou_period="off_peak", soc_threshold=95, coord=coord,
    )
    # Raw predicate is True → membership preserved.
    assert "garage_a" in ev._paused_by_blind_window


def test_load_shed_restore_site_consults_blind_window():
    """Site 8 (load-shed restore, energy.py::_execute_shed_action ev branch).

    Source-anchored behavioral proof: the load-shed release deferral list
    MUST include `_paused_by_blind_window`. Fully instantiating an
    `EnergyCoordinator` for a runtime test would require the entire EC
    dependency graph; the anchor here is on the code shape at the exact
    site, paired with the enumeration contract test above (which alone
    catches added sites but does not prove the peer set is threaded).

    Mutation: removing the `_paused_by_blind_window` line from the
    load-shed EV-release deferral block => this test fails.
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy.py",
    )
    with open(src_path) as f:
        src = f.read()
    idx = src.find("Load shed release EV")
    assert idx != -1, "Load-shed EV release site not found"
    # Grab the preceding ~2000 chars — the deferral if-block sits above.
    window = src[max(0, idx - 2000): idx]
    assert "_paused_by_blind_window" in window, (
        "Load-shed EV release deferral does not consult "
        "_paused_by_blind_window — D-HIGH-1 site 8 regression"
    )


def test_dp_reversion_site_consults_blind_window():
    """Site 9 (DP reversion, energy.py::_apply_dp_reversion).

    Same shape as load-shed proof: source-anchored on the peer-defer list.
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy.py",
    )
    with open(src_path) as f:
        src = f.read()
    idx = src.find("drain-precedence release: %s — peer owner still holds")
    assert idx != -1, "DP reversion peer-defer site not found"
    window = src[max(0, idx - 2000): idx]
    assert "_paused_by_blind_window" in window, (
        "DP reversion peer-defer does not consult _paused_by_blind_window"
    )


# ---------------------------------------------------------------------------
# Fix-up A-MED-1 (Batch 3) — unit normalization on mains_export_active
# ---------------------------------------------------------------------------
# The threshold contract is W-only. Direct unit tests on the coordinator
# method are heavy (require an EnergyCoordinator instance); mirror the
# existing source-anchored proof pattern the batch has been using +
# stand up a MINIMAL shim that exercises the normalization logic against
# a fake state. The shim reproduces the code path bit-for-bit; any drift
# would cause the source-anchored assertion below to fail.


class _MainsExportShim:
    """Mirrors `EnergyCoordinator.mains_export_active` normalization logic
    against a fake state dict so we can exercise unit branches without
    instantiating the full coordinator (which requires the full EC
    dependency graph). Guarded by
    `test_A_MED_1_shim_matches_production_normalization_source` — if the
    production method diverges from this shim's shape, that test fails
    and the mutation window opens.
    """

    def __init__(self, state_value, unit):
        self._state_value = state_value
        self._unit = unit

    def get(self, _eid):
        class _S:
            state = self._state_value  # noqa: N815
            attributes = {"unit_of_measurement": self._unit}
        # Bind the outer values (not the class body) — return an instance.
        s = _S()
        s.state = self._state_value
        s.attributes = {"unit_of_measurement": self._unit}
        return s


def _shim_mains_export_active(state_value, unit, threshold_w=100.0):
    """Bit-for-bit replica of `EnergyCoordinator.mains_export_active`'s
    normalization + threshold logic. Anchored to source by the
    `test_A_MED_1_shim_matches_production_normalization_source` test.
    """
    st = _MainsExportShim(state_value, unit).get("_")
    if st is None or st.state in ("unknown", "unavailable"):
        return None
    try:
        v = float(st.state)
    except (ValueError, TypeError, AttributeError):
        return None
    uom = st.attributes.get("unit_of_measurement", "")
    uom_norm = (uom or "").strip()
    if uom_norm in ("kW", "kw"):
        v *= 1000.0
    elif uom_norm not in ("W", "w", "", None):
        return None
    return v > float(threshold_w)


def test_A_MED_1_watts_identity_above_threshold_returns_true():
    """Raw W above threshold: no conversion, positive-export detected."""
    assert _shim_mains_export_active("500", "W") is True


def test_A_MED_1_watts_identity_below_threshold_returns_false():
    assert _shim_mains_export_active("50", "W") is False


def test_A_MED_1_kw_conversion_above_threshold_returns_true():
    """kW should multiply by 1000 before comparing to W-only threshold.
    0.5 kW = 500 W > 100 W ⇒ True. Mutation: dropping the *1000 makes
    0.5 < 100 ⇒ False, this test fails.
    """
    assert _shim_mains_export_active("0.5", "kW") is True


def test_A_MED_1_kw_conversion_below_threshold_returns_false():
    """0.05 kW = 50 W < 100 W ⇒ False. Without the conversion, 0.05
    would be compared directly to 100 and also return False — but the
    kW-above test above catches the mutation. This test guards
    correctness in the near-zero band.
    """
    assert _shim_mains_export_active("0.05", "kW") is False


def test_A_MED_1_kw_lowercase_also_normalized():
    """Case-insensitive check on 'kw' unit string."""
    assert _shim_mains_export_active("0.5", "kw") is True


def test_A_MED_1_unknown_unit_refused_as_None():
    """Unknown unit (e.g. 'MW', 'kWh') must return None — fail-safe.
    Silent admission of a wiring bug is exactly Bug Class #30's failure
    mode. Refusing None here means the guard sees `exp is not True` and
    engages the fail-safe DROP leg.
    """
    assert _shim_mains_export_active("500", "MW") is None
    assert _shim_mains_export_active("500", "kWh") is None


def test_A_MED_1_empty_or_none_unit_treated_as_watts():
    """Historic Emporia sensors sometimes lack a unit attribute — for
    a POWER sensor, empty/None is treated as W (identity path)."""
    assert _shim_mains_export_active("500", "") is True
    assert _shim_mains_export_active("500", None) is True


def test_A_MED_1_unavailable_state_returns_None():
    assert _shim_mains_export_active("unavailable", "W") is None
    assert _shim_mains_export_active("unknown", "kW") is None


def test_A_MED_1_shim_matches_production_normalization_source():
    """Guard the shim above against production drift. The shim is a
    bit-for-bit replica of `EnergyCoordinator.mains_export_active`; if
    the production method's normalization block changes, either update
    the shim to match OR the whole A-MED-1 test surface is invalid.
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy.py",
    )
    with open(src_path) as f:
        src = f.read()
    idx = src.find("def mains_export_active(")
    assert idx != -1, "mains_export_active method vanished"
    body = src[idx: idx + 4000]
    # Load-bearing tokens the shim relies on. Any drift here should
    # trigger a shim update or a re-review of A-MED-1's contract.
    for token in (
        'uom = st.attributes.get("unit_of_measurement", "")',
        'uom_norm = (uom or "").strip()',
        'if uom_norm in ("kW", "kw"):',
        "v *= 1000.0",
        'elif uom_norm not in ("W", "w", "", None):',
    ):
        assert token in body, (
            f"A-MED-1: production normalization drifted — shim no "
            f"longer matches source. Missing token: {token!r}"
        )


# ===========================================================================
# Fix-up Batch 4 — D-HIGH-2 liveness helper + B5 defer rows + A-HIGH-1 prune
# ===========================================================================


# ---------------------------------------------------------------------------
# D-HIGH-2 — max-defer path routes through liveness helper
# ---------------------------------------------------------------------------


def test_D_HIGH_2_max_defer_calls_liveness_helper_no_silent_release():
    """When max-defer expires, the guard MUST call
    `blind_window_liveness_release(evse, 'max_defer_exceeded',
    has_pressure=False)` before yielding. Direct release without the
    helper = silent ensure-on = D-HIGH-2 regression.

    Mutation: revert the max-defer branch to unconditional discard =>
    the recorded helper-call list would be empty and this test fails.
    """
    from homeassistant.util import dt as dt_util
    from datetime import timedelta
    ev = _make_ev(evse_on=False)
    coord = _make_coord_stub(liveness_release_returns=True)
    _engage_guard(ev, coord)
    # Force max-defer exceeded.
    ev._blind_window_epoch_started_at = dt_util.utcnow() - timedelta(
        minutes=CONF_BLIND_WINDOW_MAX_DEFER_MIN + 5,
    )
    ev._paused_by_blind_window.add("garage_a")
    ev.determine_actions("off_peak", coord=coord)
    # Helper called exactly with the expected shape.
    assert ("garage_a", "max_defer_exceeded", False) in coord._liveness_calls
    # Release permitted -> membership drained.
    assert "garage_a" not in ev._paused_by_blind_window


def test_D_HIGH_2_max_defer_helper_refusal_holds_pause():
    """If the helper refuses release (envelope proves lower < drain
    AND no pressure), the guard MUST keep `_paused_by_blind_window`
    membership. Silent fall-through to plain ensure-on is exactly the
    bug D-HIGH-2 closed.
    """
    from homeassistant.util import dt as dt_util
    from datetime import timedelta
    ev = _make_ev(evse_on=False)
    # Stub's liveness_release_returns=False mimics envelope-refusal.
    coord = _make_coord_stub(liveness_release_returns=False)
    _engage_guard(ev, coord)
    ev._blind_window_epoch_started_at = dt_util.utcnow() - timedelta(
        minutes=CONF_BLIND_WINDOW_MAX_DEFER_MIN + 5,
    )
    ev._paused_by_blind_window.add("garage_a")
    actions = ev.determine_actions("off_peak", coord=coord)
    assert ("garage_a", "max_defer_exceeded", False) in coord._liveness_calls
    # No turn_on emitted.
    assert not any(a["service"] == "switch.turn_on" for a in actions)
    # Membership survives — waiting on must-start-by.
    assert "garage_a" in ev._paused_by_blind_window


def test_D_HIGH_2_liveness_helper_semantics_pressure_overrides_envelope():
    """Source-anchored proof: the production helper decision-branches on
    `has_pressure` BEFORE the envelope check. With `has_pressure=True`,
    the release ALWAYS fires + row is written with reason including
    'must_start_by_pressure' (INV-DP2 trumps envelope).
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy.py",
    )
    with open(src_path) as f:
        src = f.read()
    idx = src.find("def blind_window_liveness_release(")
    assert idx != -1, "liveness helper missing"
    body = src[idx: idx + 4000]
    assert "if has_pressure:" in body
    assert "release = True" in body
    # Envelope-refusal branch requires envelope_low_below_drain AND no
    # pressure — verify the AND-shape didn't drift.
    assert "envelope_low_below_drain = (" in body
    assert "decision_type=\"blind_window_liveness_release\"" in src


def test_D_HIGH_2_dp_must_start_by_site_routes_through_helper():
    """Source-anchored proof that `_apply_dp_must_start_release` now
    routes through the liveness helper BEFORE the turn_on can fire.
    Batch 2 marked this the sole exempt site; Batch 4 closes the
    exemption by routing it through the helper.
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy.py",
    )
    with open(src_path) as f:
        src = f.read()
    idx = src.find("def _apply_dp_must_start_release(")
    assert idx != -1, "must-start-by helper missing"
    body = src[idx: idx + 6000]
    # Helper call precedes the turn_on dispatch.
    call_idx = body.find("blind_window_liveness_release(")
    turn_on_idx = body.find('"switch", "turn_on"')
    assert call_idx != -1, "must-start-by site does NOT call liveness helper"
    assert turn_on_idx != -1, "must-start-by turn_on dispatch missing"
    assert call_idx < turn_on_idx, (
        "liveness helper must be called BEFORE the turn_on dispatch — "
        "regression opens the silent ensure-on bug"
    )
    assert 'reason="dp_must_start_by"' in body
    assert "has_pressure=True" in body


# ---------------------------------------------------------------------------
# B5 — INV-BW1 defer decision_log rows (dedup per (evse, epoch))
# ---------------------------------------------------------------------------


def test_B5_defer_log_fires_once_per_evse_per_epoch():
    """Multiple guard ticks in the SAME epoch => ONE defer row per EVSE
    (not one per tick). Mutation: dropping the dedup gate makes the
    counter and row cardinality grow with tick count.
    """
    ev = _make_ev(evse_on=False)
    coord = _make_coord_stub()
    _engage_guard(ev, coord)
    # Two ticks in the same epoch.
    ev.determine_actions("off_peak", coord=coord)
    ev.determine_actions("off_peak", coord=coord)
    # `garage_a` recorded exactly ONCE in coord._defer_logged.
    assert list(coord._defer_calls).count("garage_a") >= 1
    # Dedup: only the FIRST call returned True; only ONE increment.
    assert ev._blind_window_defers_this_epoch == 1


def test_B5_defer_counter_resets_on_epoch_clear():
    """Epoch clears (raw predicate False) drop dedup + counter.
    Mutation: the reset call missing => a subsequent outage's first
    defer would NOT re-log (dedup carryover)."""
    ev = _make_ev(evse_on=False)
    coord = _make_coord_stub()
    _engage_guard(ev, coord)
    ev.determine_actions("off_peak", coord=coord)
    assert ev._blind_window_defers_this_epoch == 1
    assert "garage_a" in coord._defer_logged
    # Envoy recovers — the guard's clear path fires.
    coord_recovered = _make_coord_stub(blind_hold=False)
    # Copy the state fields (defer log dedup lives on coord — clearing
    # it requires the recovered coord's _reset method to be called).
    # In production the SAME coord instance is passed; here we simulate
    # by pointing at the recovered coord for guard state, but call the
    # recovered coord's reset explicitly (production would do this via
    # the recovered coord's `_reset_blind_window_defer_dedup`).
    ev._energy_coord = coord  # ensure the reset path finds a coord
    ev._blind_window_guard_engaged(coord)  # triggers reset via raw-true
    # Force raw-false clear on the ORIGINAL coord.
    coord.blind_hold_active = False
    ev._blind_window_guard_engaged(coord)
    assert coord._defer_logged == set(), (
        "epoch clear must reset dedup set on the coord"
    )
    assert ev._blind_window_defers_this_epoch == 0


def test_B5_defer_log_source_anchored_row_shape():
    """Source-anchored contract on the defer row: coordinator_id='energy',
    decision_type='blind_window_defer', context includes evse_id +
    epoch + envelope snapshot + reserve_verifiable + blind_hold_active.
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy.py",
    )
    with open(src_path) as f:
        src = f.read()
    idx = src.find("async def _log_blind_window_defer(")
    assert idx != -1
    body = src[idx: idx + 2500]
    for token in (
        'decision_type="blind_window_defer"',
        'coordinator_id="energy"',
        '"evse_id": evse_id',
        '"epoch": epoch_key',
        '"reserve_verifiable"',
        '"blind_hold_active"',
        '"envelope_lower"',
        '"envelope_upper"',
    ):
        assert token in body, (
            f"B5 row-shape drift — missing token: {token!r}"
        )


# ---------------------------------------------------------------------------
# A-HIGH-1 — cleanup_decision_log DAO
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_A_HIGH_1_cleanup_decision_log_prunes_old_rows_of_named_type():
    """Direct SQL replica of the DAO. Standing up the full Database
    class under the test harness requires the entire HA / integration
    boot chain, so we exercise the EXACT SQL the production DAO issues
    against a raw aiosqlite connection. The paired
    `test_A_HIGH_1_cleanup_decision_log_source_anchored_sql` guards
    that the replica stays in sync with production.
    """
    import aiosqlite
    import os as _os2
    from datetime import datetime, timedelta

    db_path = _os2.path.join(
        _os2.path.dirname(__file__), "..", "..",
        f"scratchpad_ec_batch4_prune_{_os2.getpid()}.sqlite",
    )
    db_path = _os2.path.normpath(db_path)
    if _os2.path.exists(db_path):
        _os2.unlink(db_path)

    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                CREATE TABLE decision_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    coordinator_id TEXT NOT NULL,
                    decision_type TEXT NOT NULL,
                    context_json TEXT,
                    action_json TEXT
                )
            """)
            now = datetime.utcnow()
            old = (now - timedelta(days=120)).isoformat()
            fresh = (now - timedelta(days=5)).isoformat()
            for ts, dtype in [
                (old, "dp_eval"), (fresh, "dp_eval"),
                (old, "other_kind"), (fresh, "other_kind"),
            ]:
                await db.execute(
                    """INSERT INTO decision_log
                       (timestamp, coordinator_id, decision_type,
                        context_json, action_json)
                       VALUES (?, ?, ?, ?, ?)""",
                    (ts, "energy", dtype, "{}", "{}"),
                )
            await db.commit()

            # Direct execution of the DAO's SQL.
            cutoff = (now - timedelta(days=90)).isoformat()
            cursor = await db.execute(
                """DELETE FROM decision_log
                WHERE rowid IN (
                    SELECT rowid FROM decision_log
                    WHERE decision_type = ?
                      AND timestamp < ?
                    LIMIT ?
                )""",
                ("dp_eval", cutoff, 1000),
            )
            await db.commit()
            deleted = cursor.rowcount
            assert deleted == 1, f"expected 1 old dp_eval pruned, got {deleted}"

            cur = await db.execute(
                "SELECT decision_type, timestamp FROM decision_log "
                "ORDER BY timestamp"
            )
            rows = await cur.fetchall()
            types_left = [(r[0], r[1] == old) for r in rows]
            assert ("dp_eval", False) in types_left, (
                "fresh dp_eval must survive"
            )
            assert ("dp_eval", True) not in types_left, (
                "old dp_eval must be gone"
            )
            assert ("other_kind", False) in types_left, (
                "other_kind fresh untouched"
            )
            assert ("other_kind", True) in types_left, (
                "other_kind old untouched"
            )
    finally:
        if _os2.path.exists(db_path):
            _os2.unlink(db_path)


def test_A_HIGH_1_cleanup_decision_log_source_anchored_sql():
    """Source-anchored contract on the DAO's SQL — guards that the
    behavioral replica in the async test above stays in sync with
    production.
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "database.py",
    )
    with open(src_path) as f:
        src = f.read()
    idx = src.find("async def cleanup_decision_log(")
    assert idx != -1, "cleanup_decision_log DAO missing"
    body = src[idx: idx + 2500]
    for token in (
        "DELETE FROM decision_log",
        "WHERE rowid IN (",
        "SELECT rowid FROM decision_log",
        "WHERE decision_type = ?",
        "AND timestamp < ?",
        "LIMIT ?",
        "await asyncio.sleep(0.1)",  # batching contract
    ):
        assert token in body, (
            f"A-HIGH-1: DAO SQL drifted from replica — missing token: {token!r}"
        )


def test_A_HIGH_1_cleanup_decision_log_wired_into_nightly_cadence():
    """Source-anchored: both nightly-cadence registration sites must
    include entries for dp_eval, blind_window_defer, blind_window_
    liveness_release, otherwise rows grow unbounded.
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "__init__.py",
    )
    with open(src_path) as f:
        src = f.read()
    # BOTH registration blocks (primary + deferred-startup mirror).
    for token in (
        '"cleanup_decision_log", {"decision_type": "dp_eval"',
        '"cleanup_decision_log", {"decision_type": "blind_window_defer"',
        '"cleanup_decision_log", {"decision_type": "blind_window_liveness_release"',
    ):
        # Must appear twice: primary + deferred-startup mirror.
        assert src.count(token) == 2, (
            f"A-HIGH-1: nightly-cadence registration missing/asymmetric "
            f"for {token!r} (found {src.count(token)}, expected 2)"
        )


# ===========================================================================
# Fix-up Batch 5 (FINAL) — MEDIUMs + LOWs + docs anchoring
# ===========================================================================


# ---------------------------------------------------------------------------
# C-MED-1 — D2 dp_eval row-shape test (kills reviewer mutation B5-log)
# ---------------------------------------------------------------------------


def test_C_MED_1_dp_eval_row_shape_source_anchored():
    """The dp_eval row shape is the forensic ledger's contract. Source-
    anchored on the exact context/action keys so a mutation that
    neuters `_log_dp_eval_decision` (empty context, wrong decision_type,
    missing keys) fails this test.
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy.py",
    )
    with open(src_path) as f:
        src = f.read()
    idx = src.find("async def _log_dp_eval_decision(")
    assert idx != -1, "_log_dp_eval_decision missing"
    body = src[idx: idx + 4500]
    # Row must land on decision_log with decision_type='dp_eval'.
    assert 'decision_type="dp_eval"' in body
    assert 'coordinator_id="energy"' in body
    # Context keys required for forensic replay of the 2026-07-20 shape:
    for key in (
        '"state"',
        '"prior_state"',
        '"reason"',
        '"charger_rate_kw"',
        '"soc"',
        '"is_blind_hold"',
        '"reserve_verifiable"',
        '"drain_target_soc"',
        '"tou_period"',
        '"force_charge_active"',
        '"soc_envelope_lower"',
        '"soc_envelope_upper"',
        '"ev_load_w"',
        '"now_iso"',
    ):
        assert key in body, (
            f"C-MED-1: dp_eval context missing key {key!r} — forensic "
            f"replay shape regressed"
        )
    # Action shape.
    assert '"transitioned"' in body
    assert '"next_state"' in body


def test_C_MED_1_dp_eval_call_site_uses_async_create_task():
    """The dp_eval log dispatch must not block the decision-cycle path.
    Batch 5 B6-low anchors the task handle for teardown-cancel; the
    schedule call itself must remain non-blocking.
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy.py",
    )
    with open(src_path) as f:
        src = f.read()
    idx = src.find("_dp_eval_task = self.hass.async_create_task(")
    assert idx != -1, (
        "dp_eval schedule call must retain async_create_task + task "
        "handle assignment (B6-low)"
    )


# ---------------------------------------------------------------------------
# C-MED-2 — LKG persist/restore round-trip (kills mutation B6-LKG)
# ---------------------------------------------------------------------------


def _ensure_dt_parse_available():
    """The sibling `test_energy_load_shedding_correctness` bootstrap
    does NOT provide `parse_datetime` / `UTC` on the mocked
    `homeassistant.util.dt`. `restore_lkg_snapshot` needs both; patch
    them in on-the-fly so this test's round-trip actually exercises
    the production code path (rather than falling into the broad
    `except` which would silently no-op).
    """
    from datetime import datetime, timezone
    import homeassistant.util.dt as _dt
    if not hasattr(_dt, "parse_datetime"):
        _dt.parse_datetime = lambda s: (
            datetime.fromisoformat(s) if isinstance(s, str) and s else None
        )
    if not hasattr(_dt, "UTC"):
        _dt.UTC = timezone.utc


def test_C_MED_2_lkg_snapshot_round_trip_preserves_value_and_timestamp():
    """Round-trip contract:
      * `get_lkg_snapshot()` returns None when unset (first-boot safety).
      * After manual set, returns {"value": float, "at_iso": ISO}.
      * `restore_lkg_snapshot(payload)` rehydrates value + timestamp.
      * Empty/None payload does NOT clobber existing RAM state.

    Mutation B6-LKG: neuter `restore_lkg_snapshot` (e.g. drop the
    `self._soc_lkg = v` line) => the round-trip assertion below fails.
    """
    _ensure_dt_parse_available()
    from datetime import datetime, timezone
    # BatteryStrategy has a heavy ctor; probe via a __new__ instance to
    # exercise ONLY the LKG methods (they are pure and only read
    # instance attrs `_soc_lkg` + `_soc_lkg_at`).
    import importlib
    _mod = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators.energy_battery"
    )
    BatteryStrategy = _mod.BatteryStrategy
    b = BatteryStrategy.__new__(BatteryStrategy)
    b._soc_lkg = None
    b._soc_lkg_at = None
    # First-boot: no LKG => None.
    assert b.get_lkg_snapshot() is None
    # Set + snapshot.
    stamp = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
    b._soc_lkg = 47.5
    b._soc_lkg_at = stamp
    snap = b.get_lkg_snapshot()
    assert snap is not None
    assert snap["value"] == 47.5
    assert snap["at_iso"].startswith("2026-07-22T12:00:00")

    # Restore into a fresh instance.
    b2 = BatteryStrategy.__new__(BatteryStrategy)
    b2._soc_lkg = None
    b2._soc_lkg_at = None
    b2.restore_lkg_snapshot(snap)
    assert b2._soc_lkg == 47.5
    assert b2._soc_lkg_at is not None
    # Timestamp round-trips (tz-aware preservation contract).
    assert b2._soc_lkg_at.isoformat().startswith("2026-07-22T12:00:00")


def test_C_MED_2_lkg_restore_none_or_empty_does_not_clobber():
    """Contract on the RESTORE side — a None / empty payload is a no-op,
    not a wipe. Prevents a first-boot deserialize-empty-KV from
    destroying a same-boot fresh LKG read.
    """
    from datetime import datetime, timezone
    import importlib
    _mod = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators.energy_battery"
    )
    BatteryStrategy = _mod.BatteryStrategy
    b = BatteryStrategy.__new__(BatteryStrategy)
    b._soc_lkg = 55.0
    b._soc_lkg_at = datetime(2026, 7, 22, tzinfo=timezone.utc)
    b.restore_lkg_snapshot(None)
    assert b._soc_lkg == 55.0
    b.restore_lkg_snapshot({})
    assert b._soc_lkg == 55.0


def test_C_MED_2_lkg_restore_garbage_payload_is_safe_noop():
    """Corrupt payload (non-numeric value, unparseable timestamp) must
    NOT crash and must leave RAM state untouched.
    """
    from datetime import datetime, timezone
    import importlib
    _mod = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators.energy_battery"
    )
    BatteryStrategy = _mod.BatteryStrategy
    b = BatteryStrategy.__new__(BatteryStrategy)
    b._soc_lkg = 60.0
    original_at = datetime(2026, 7, 21, tzinfo=timezone.utc)
    b._soc_lkg_at = original_at
    b.restore_lkg_snapshot({"value": "not_a_number", "at_iso": "garbage"})
    assert b._soc_lkg == 60.0
    assert b._soc_lkg_at == original_at


def test_C_MED_2_lkg_get_snapshot_returns_none_when_only_partial_ram_state():
    """If _soc_lkg is set but _soc_lkg_at is None (or vice versa) the
    snapshot must be None — an incomplete pair can't be trusted on
    restore to age correctly.
    """
    import importlib
    _mod = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators.energy_battery"
    )
    BatteryStrategy = _mod.BatteryStrategy
    b = BatteryStrategy.__new__(BatteryStrategy)
    b._soc_lkg = 40.0
    b._soc_lkg_at = None
    assert b.get_lkg_snapshot() is None
    b._soc_lkg = None
    from datetime import datetime, timezone
    b._soc_lkg_at = datetime(2026, 7, 22, tzinfo=timezone.utc)
    assert b.get_lkg_snapshot() is None


def test_C_MED_2_soc_envelope_returns_none_when_lkg_past_max_age():
    """Past-max-age contract on the envelope side: a stale LKG produces
    None from `soc_envelope()` (via the SOCEnvelope max-age gate). The
    guard's fail-safe pause leg then cannot ride, which is the
    correct-safe behavior.
    """
    from datetime import datetime, timezone, timedelta
    from custom_components.universal_room_automation.domain_coordinators.energy_const import (
        DEFAULT_SOC_LKG_ENVELOPE_MAX_AGE_S,
    )
    import importlib
    _mod = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators.energy_battery"
    )
    BatteryStrategy = _mod.BatteryStrategy
    b = BatteryStrategy.__new__(BatteryStrategy)
    # Stub the private helpers the property invokes.
    b._get_entity = lambda k, d=None, **kw: None
    b._get_state_float = lambda eid: None  # primary SOC unavailable
    b._soc_lkg = 50.0
    b._soc_lkg_at = (
        datetime.now(tz=timezone.utc)
        - timedelta(seconds=int(DEFAULT_SOC_LKG_ENVELOPE_MAX_AGE_S) + 60)
    )
    assert b.soc_envelope() is None


# ---------------------------------------------------------------------------
# B7 — DP-tick snapshot threaded into the guard path
# ---------------------------------------------------------------------------


def test_B7_guard_prefers_snapshot_when_available():
    """When the coord exposes `blind_hold_active_snapshot`, the guard
    predicate reads THAT (single per-tick truth), not the property.
    """
    from types import SimpleNamespace
    coord = SimpleNamespace(
        # Property says NOT blind, snapshot says BLIND. Guard MUST honor
        # the snapshot (DP tick's authoritative value for this tick).
        blind_hold_active=False,
        blind_hold_active_snapshot=lambda: True,
        reserve_write_verifiable=lambda: False,
    )
    ev = _make_ev()
    assert ev._blind_window_entry_predicate(coord) is True


def test_B7_guard_falls_back_to_property_without_snapshot():
    """Legacy stubs (no snapshot method) still work — the getattr
    fallback keeps existing test fixtures + non-tick call sites honest.
    """
    from types import SimpleNamespace
    coord = SimpleNamespace(
        blind_hold_active=True,
        reserve_write_verifiable=lambda: False,
    )
    ev = _make_ev()
    assert ev._blind_window_entry_predicate(coord) is True


def test_B7_snapshot_method_returns_fresh_or_property():
    """Source-anchored: the snapshot method must consult the recorded
    snapshot within a staleness window, else fall back to the property.
    Mutation: replace the snapshot check with `return
    self.blind_hold_active` unconditionally => this test fails.
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy.py",
    )
    with open(src_path) as f:
        src = f.read()
    idx = src.find("def blind_hold_active_snapshot(")
    assert idx != -1
    body = src[idx: idx + 1500]
    assert "_blind_hold_snapshot" in body
    assert "max_age_s" in body
    assert "return bool(self.blind_hold_active)" in body


# ---------------------------------------------------------------------------
# D-LOW-2 — riding EVSEs must NOT be added to _paused_by_blind_window
# ---------------------------------------------------------------------------


def test_D_LOW_2_riding_evse_is_not_claimed_as_paused():
    """Ownership honesty: an ON EVSE with envelope permitting ride is
    NOT paused by the guard, so it MUST NOT appear in
    `_paused_by_blind_window`. Persistence (`_save_evse_state`) would
    otherwise restore a bogus pause.
    """
    ev = _make_ev(evse_on=True)
    coord = _make_coord_stub(envelope=(70.0, 80.0))  # lower 70 >= 40 => ride
    _engage_guard(ev, coord)
    ev.determine_actions("off_peak", coord=coord)
    assert "garage_a" not in ev._paused_by_blind_window
    # Defer counter also does NOT increment (not deferred, riding).
    assert ev._blind_window_defers_this_epoch == 0


def test_D_LOW_2_ride_ok_drops_stale_membership_from_prior_pause():
    """Envelope was tight last tick (real pause claimed) → envelope
    permits this tick (ride). The stale claim must drop so ownership
    matches reality.
    """
    ev = _make_ev(evse_on=True)
    ev._paused_by_blind_window.add("garage_a")  # stale from prior tick
    coord = _make_coord_stub(envelope=(70.0, 80.0))
    _engage_guard(ev, coord)
    ev.determine_actions("off_peak", coord=coord)
    assert "garage_a" not in ev._paused_by_blind_window


def test_D_LOW_2_real_pause_still_claims_membership():
    """Regression guard: an ON EVSE with envelope DENYING ride still
    gets claimed (real pause). And an OFF EVSE (defer-ensure-on) also
    claims (so `_stronger_peer_holds` blocks other paths from turning
    it on).
    """
    # ON + envelope denies => real pause + claim.
    ev = _make_ev(evse_on=True)
    coord_deny = _make_coord_stub(envelope=(20.0, 30.0))
    _engage_guard(ev, coord_deny)
    ev.determine_actions("off_peak", coord=coord_deny)
    assert "garage_a" in ev._paused_by_blind_window

    # OFF + envelope denies (or None) => defer + claim.
    ev2 = _make_ev(evse_on=False)
    coord_none = _make_coord_stub(envelope=None)
    _engage_guard(ev2, coord_none)
    ev2.determine_actions("off_peak", coord=coord_none)
    assert "garage_a" in ev2._paused_by_blind_window


# ---------------------------------------------------------------------------
# D-LOW-3 — blind_hold_active fail-CLOSED on exception
# ---------------------------------------------------------------------------


def test_D_LOW_3_blind_hold_active_source_anchored_fail_closed():
    """Source-anchored: the exception branch on `envoy_available` MUST
    default `env_ok = False` (fail-closed), NOT True. Prior code was
    fail-open which silently disabled the guard under a transient
    read exception. WARNING logging must be present.
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy.py",
    )
    with open(src_path) as f:
        src = f.read()
    idx = src.find("def blind_hold_active(")
    assert idx != -1
    body = src[idx: idx + 3000]
    # Fail-closed direction.
    assert "env_ok = False" in body
    assert "assuming " in body  # WARNING message present
    assert "_LOGGER.warning" in body


# ---------------------------------------------------------------------------
# B6-low — teardown cancels the dp_eval task handle
# ---------------------------------------------------------------------------


def test_B6_low_teardown_cancels_pending_dp_eval_task_source_anchored():
    """Source-anchored: teardown must consult `_dp_eval_last_task` and
    cancel if pending. Removing the cancel snippet opens Bug Class #38.
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy.py",
    )
    with open(src_path) as f:
        src = f.read()
    # Teardown block includes the dp_eval cancel snippet.
    idx = src.find("async def async_teardown(")
    assert idx != -1
    body = src[idx:]
    # Locate the tail of teardown (up to the class-end or next def).
    end_idx = body.find("\n    async def ", 100)
    end_idx = end_idx if end_idx != -1 else 8000
    body = body[:end_idx]
    assert "_dp_eval_last_task" in body
    assert "_dp_task.cancel()" in body


# ---------------------------------------------------------------------------
# EC manual anchor — row 2.5 documents the FINAL semantics
# ---------------------------------------------------------------------------


def test_EC_manual_row_2_5_documents_final_semantics():
    """Guardrail: the operator-facing manual entry for row 2.5 must
    reference the final semantics so a doc drift is caught at test time.
    """
    manual = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "docs", "Coordinator",
        "ENERGY_COORDINATOR_MANUAL.md",
    )
    with open(manual) as f:
        src = f.read()
    for token in (
        "CONF_BLIND_WINDOW_ENTRY_DEBOUNCE_S",
        "CONF_BLIND_WINDOW_MAX_DEFER_MIN",
        "blind_window_liveness_release",
        "CONTINUE-permission",
        "D-LOW-2",
        "blind_window_defer",
    ):
        assert token in src, (
            f"EC manual §2.4b row 2.5 stale — missing token: {token!r}"
        )


# ===========================================================================
# Fix-up Batch 6 — D re-pass findings (liveness ride authority)
# ===========================================================================


# ---------------------------------------------------------------------------
# D-HIGH-3 — Sequence test: must-start release grants per-epoch ride
# authority; the pause leg does NOT re-capture on the very next tick.
# ---------------------------------------------------------------------------


def test_D_HIGH_3_must_start_release_grants_ride_and_next_tick_stays_on():
    """The D-HIGH-3 sequence:
      t=0  guard engaged, EVSE paused in `_paused_by_blind_window`.
      t=1  DP must-start-by fire calls `grant_liveness_ride_authority(evse)`
           — membership drops from `_paused_by_blind_window` AND ride
           latch gains membership.
      t=2  Next tick's pause leg sees the EVSE ON. Envelope may deny
           ride, but the ride-latch overrides: `will_pause = False`.
           No turn_off; no re-capture. Car stays ON.
      t=3  Next tick after that — SAME OUTCOME while epoch is open.
      t=4  Envoy recovers → epoch clears → ride latch cleared.

    Mutations killed:
      * Removing `_paused_by_blind_window.discard(evse_id)` from
        `grant_liveness_ride_authority` => membership survives + next
        tick's peer-set check re-holds it; this test's turn_off
        assertion fails.
      * Removing the `_blind_window_liveness_ride` short-circuit in the
        pause leg's `will_pause` computation => the next tick's pause
        leg re-captures the just-released EVSE.
    """
    ev = _make_ev(evse_on=False)
    coord = _make_coord_stub(envelope=(20.0, 30.0))  # envelope denies ride
    _engage_guard(ev, coord)

    # t=0 — guard engaged; EVSE has been paused earlier (simulate the
    # membership state that `determine_actions` would produce).
    ev._paused_by_blind_window.add("garage_a")

    # t=1 — DP must-start-by fire simulates: the helper (mocked True)
    # then `grant_liveness_ride_authority`. Mirror the production
    # sequencing (energy.py `_apply_dp_must_start_release`).
    ev.grant_liveness_ride_authority("garage_a")
    assert "garage_a" not in ev._paused_by_blind_window, (
        "D-HIGH-3: pressure release must discard blind-window claim"
    )
    assert "garage_a" in ev._blind_window_liveness_ride, (
        "D-HIGH-3: ride authority latch must gain membership"
    )
    # Simulate the turn_on that DP dispatched (production would fire
    # via hass.services). Rewire the EVSE state to ON for the next tick.
    ev.hass._set("switch.garage_a", "on")
    ev.hass._set("sensor.garage_a_power", "1000", unit="W")

    # t=2 — next tick's pause leg MUST NOT re-capture.
    actions_t2 = ev.determine_actions("off_peak", coord=coord)
    assert not any(a["service"] == "switch.turn_off" for a in actions_t2), (
        "D-HIGH-3: next tick re-captured a just-released EVSE"
    )
    assert "garage_a" not in ev._paused_by_blind_window, (
        "D-HIGH-3: pause leg re-added membership despite ride authority"
    )
    assert "garage_a" in ev._blind_window_liveness_ride, (
        "D-HIGH-3: ride authority MUST persist through the epoch"
    )

    # t=3 — tick after that — SAME outcome (idempotent within epoch).
    actions_t3 = ev.determine_actions("off_peak", coord=coord)
    assert not any(a["service"] == "switch.turn_off" for a in actions_t3)
    assert "garage_a" in ev._blind_window_liveness_ride

    # t=4 — envoy recovers → epoch close → latch cleared.
    coord_recovered = _make_coord_stub(blind_hold=False)
    ev.determine_actions("off_peak", coord=coord_recovered)
    assert "garage_a" not in ev._blind_window_liveness_ride, (
        "D-HIGH-3: ride latch must clear on epoch close"
    )


def test_D_HIGH_3_ride_authority_survives_persist_restore():
    """A mid-epoch restart must not strand the car. The latch is written
    to KV (`evse_blind_window_liveness_ride`) alongside the pause set
    persistence; restore rehydrates it. Verified via a source-anchored
    proof (round-trip through the whole EC teardown is out of scope for
    this unit test; the anchor guards the persistence contract).
    """
    # Phase-2 owner-registry refactor: the KV key literal + attr name
    # now live on the `blind_window_liveness_ride` OwnerDeclaration in
    # `energy_pool_owners.py`, and `energy.py` iterates
    # `EV_REGISTRY.iter_persisted_lists()` for both save and restore.
    # The persistence contract this test guards is preserved — the
    # anchor migrates to the declaration site.
    _cc_dir = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators",
    )
    with open(_os.path.join(_cc_dir, "energy.py")) as f:
        energy_src = f.read()
    with open(_os.path.join(_cc_dir, "energy_pool_owners.py")) as f:
        owners_src = f.read()
    # KV key literal + attr name still bound together in one declaration.
    assert '"evse_blind_window_liveness_ride"' in owners_src
    assert "_blind_window_liveness_ride" in owners_src
    # Save + restore paths iterate the registry — both KV directions
    # covered by one enumeration site.
    assert "iter_persisted_lists" in energy_src, (
        "D-HIGH-3: registry-driven save/restore enumeration missing"
    )
    # RAM attr still consumed by the pause-leg pause/release logic in
    # energy_pool.py — that source-anchor lives in the sibling test
    # `test_D_HIGH_3_will_pause_gate_respects_ride_authority_source_anchored`.


def test_D_HIGH_3_grant_helper_drops_pause_membership():
    """Mutation: `grant_liveness_ride_authority` without the
    `_paused_by_blind_window.discard(evse_id)` line lets the just-
    released EVSE stay in the peer-defer set, and the next tick's
    `_stronger_peer_holds` blocks ensure-on.
    """
    ev = _make_ev()
    ev._paused_by_blind_window.add("garage_a")
    ev.grant_liveness_ride_authority("garage_a")
    assert "garage_a" not in ev._paused_by_blind_window
    assert "garage_a" in ev._blind_window_liveness_ride


def test_D_HIGH_3_will_pause_gate_respects_ride_authority_source_anchored():
    """Source-anchored: the `will_pause = False` short-circuit MUST
    appear immediately after the ride-authority membership check in
    the pause leg. Reviewer C-style mutation of the check pattern
    would surface here.
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy_pool.py",
    )
    with open(src_path) as f:
        src = f.read()
    idx = src.find("if evse_id in self._blind_window_liveness_ride:")
    assert idx != -1, "D-HIGH-3 will_pause short-circuit missing"
    tail = src[idx: idx + 200]
    assert "will_pause = False" in tail


# ---------------------------------------------------------------------------
# D-MED-1 — enumerator finds BOTH idioms (dict-payload + positional)
# ---------------------------------------------------------------------------


def test_D_MED_1_enumerator_finds_positional_dp_release_sites():
    """The positional idiom `hass.services.async_call("switch",
    "turn_on", ...)` is used by the DP reversion + must-start-by
    release sites. The enumerator must find them by scanning that
    idiom's on-line literal token, not just the dict-payload shape.
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy.py",
    )
    hits, lines = _iter_evse_turn_on_line_numbers(src_path)
    # Filter to lines that use the POSITIONAL idiom.
    positional_hits = [h for h in hits if '"switch", "turn_on"' in lines[h - 1]]
    assert len(positional_hits) >= 2, (
        f"D-MED-1: enumerator must find the two DP positional sites; "
        f"found {len(positional_hits)}"
    )


def test_D_MED_1_scope_limitation_documented_in_iterator_docstring():
    """Guardrail: the enumerator's docstring must state the two-file
    scope limitation so a future contributor knows an EVSE turn_on in
    a THIRD file will not be caught by this contract.
    """
    import inspect
    src = inspect.getsource(_iter_evse_turn_on_line_numbers)
    assert "TWO source files" in src
    assert "scope limitation" in src


# ---------------------------------------------------------------------------
# D-MED-2 — cap<=0 short-circuits (guard defer/pause disabled)
# ---------------------------------------------------------------------------


def test_D_MED_2_cap_zero_short_circuits_liveness_helper():
    """When `CONF_BLIND_WINDOW_MAX_DEFER_MIN <= 0`, the max-defer
    branch MUST NOT consult the liveness helper — the guard's
    defer/pause is disabled by that kill-switch. `_max_defer_exceeded`
    returns True unconditionally when cap<=0, so the elif branch is
    reached every tick under the kill-switch; the helper must be
    bypassed OR the helper's rows would flood the decision_log.
    """
    import importlib
    _epc = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators.energy_const"
    )
    _ep = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators.energy_pool"
    )
    # Save + patch the cap to 0.
    original_cap = _epc.CONF_BLIND_WINDOW_MAX_DEFER_MIN
    try:
        _epc.CONF_BLIND_WINDOW_MAX_DEFER_MIN = 0
        ev = _make_ev(evse_on=False)
        coord = _make_coord_stub()
        _engage_guard(ev, coord)
        ev._paused_by_blind_window.add("garage_a")
        # The helper is on the coord stub with a call recorder.
        pre_calls = len(coord._liveness_calls)
        ev.determine_actions("off_peak", coord=coord)
        post_calls = len(coord._liveness_calls)
        assert post_calls == pre_calls, (
            f"D-MED-2: cap<=0 short-circuit failed — liveness helper was "
            f"called ({post_calls - pre_calls} new calls under kill-switch)"
        )
        # And the pause membership is dropped (kill-switch => guard no-op).
        assert "garage_a" not in ev._paused_by_blind_window
    finally:
        _epc.CONF_BLIND_WINDOW_MAX_DEFER_MIN = original_cap


# ---------------------------------------------------------------------------
# D-LOW-3 (Batch 6) — epoch dedup on liveness-release rows
# ---------------------------------------------------------------------------


def test_D_LOW_3_liveness_release_row_dedups_within_epoch_source_anchored():
    """Source-anchored: the liveness helper writes ONE row per
    (evse_id, epoch, branch) via `_blind_window_liveness_release_logged`
    dedup set. Repeat consultations within the epoch (either branch)
    are suppressed. The dedup set is cleared on epoch close via
    `_reset_blind_window_defer_dedup`.
    """
    src_path = _os.path.join(
        _os.path.dirname(__file__), "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy.py",
    )
    with open(src_path) as f:
        src = f.read()
    idx = src.find("def blind_window_liveness_release(")
    assert idx != -1
    body = src[idx: idx + 5500]
    for token in (
        "_blind_window_liveness_release_logged",
        "dedup_key = (evse_id, epoch_key, branch)",
        '"release" if release else "refuse"',
        "if dedup_key in seen:",
        "seen.add(dedup_key)",
    ):
        assert token in body, (
            f"D-LOW-3: liveness-release dedup shape missing: {token!r}"
        )
    # Reset path clears BOTH dedup sets on epoch close.
    reset_idx = src.find("_reset_blind_window_defer_dedup(self)")
    assert reset_idx != -1
    reset_body = src[reset_idx: reset_idx + 800]
    assert "_blind_window_liveness_release_logged = set()" in reset_body


# ===========================================================================
# Fix-up Micro-batch 7 — D-F1: DROP leg honors ride latch
# ===========================================================================


def test_D_F1_excess_solar_DROP_leg_skips_ride_latch_members():
    """Restart-epoch-loss re-capture repro:
      * KV restore rehydrates `_blind_window_liveness_ride` with
        `garage_a` (a mid-outage restart, latch persisted from a prior
        DP must-start-by grant).
      * The excess-solar DROP leg fires (guard engaged fresh-epoch,
        witness absent, envelope denies): `garage_a` is in
        `_excess_solar_active`.
      * Pre-fix: the DROP leg turn_off'd + re-added to
        `_paused_by_blind_window`, stranding the car.
      * Post-fix: the loop's one-line ride-latch guard skips granted
        EVSEs entirely — no turn_off, no re-add.

    Mutation: removing the `if evse_id in self._blind_window_liveness_ride:
    continue` guard in the DROP loop makes this test fail (turn_off
    appears in actions AND the EVSE lands in _paused_by_blind_window).
    """
    ev = _make_ev(evse_on=True)
    coord = _make_coord_stub(envelope=None, mains_export=None)
    _engage_guard(ev, coord)
    # Post-restart shape: granted authority carried in via KV restore.
    ev._blind_window_liveness_ride.add("garage_a")
    ev._excess_solar_active.add("garage_a")
    actions = ev.determine_excess_solar_actions(
        soc=None, remaining_forecast_kwh=10.0, tou_period="off_peak",
        coord=coord,
    )
    assert not any(a["service"] == "switch.turn_off" for a in actions), (
        "D-F1: DROP leg turn_off'd a ride-authority-granted EVSE"
    )
    assert "garage_a" not in ev._paused_by_blind_window, (
        "D-F1: DROP leg re-added a granted EVSE to the pause set"
    )
    # Excess-solar claim preserved (skipped, not drained).
    assert "garage_a" in ev._excess_solar_active
    # Ride latch still armed.
    assert "garage_a" in ev._blind_window_liveness_ride
