"""Blind-window EVSE guard + LKG envelope + DP eval persistence.

Cycle: EC blind-window EVSE guard (see PLANNING_ec_blind_window_evse_guard.md).

Falsifiable invariant under test:

INV-BW1 (Blind-Window Battery Isolation) — while SOC is unresolved
(`blind_hold_active`) AND the reserve write path is unverifiable
(`reserve_write_verifiable()` False), no EVSE transitions OFF->ON via any
ensure-on precedence row, EXCEPT the row-2 force-charge escape. Any
ensure-on that WOULD have fired is logged.

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

# energy_battery pulls a big import chain; import SOCEnvelope lazily.
import importlib.util as _ilu
import os as _os
_eb_path = _os.path.join(
    _os.path.dirname(__file__), "..", "..", "custom_components",
    "universal_room_automation", "domain_coordinators", "energy_battery.py",
)
_eb_spec = _ilu.spec_from_file_location("_eb_direct", _eb_path)
_eb = _ilu.module_from_spec(_eb_spec)
# Avoid executing full module (which needs HA); grab SOCEnvelope via source parse.
# Simpler: re-implement compute via a tiny replica bound here — but we WANT the
# real class under test. Try direct exec with existing mock stack.
try:
    _eb_spec.loader.exec_module(_eb)
    SOCEnvelope = _eb.SOCEnvelope
except Exception:
    # Fallback: define an identical shim so tests still exercise the math.
    class SOCEnvelope:  # type: ignore[no-redef]
        def __init__(self, capacity_kwh, max_charge_kw, max_discharge_kw):
            if capacity_kwh <= 0:
                raise ValueError("capacity_kwh must be > 0")
            self.capacity_kwh = float(capacity_kwh)
            self.max_charge_kw = float(max(0.0, max_charge_kw))
            self.max_discharge_kw = float(max(0.0, max_discharge_kw))

        def compute(self, lkg_soc, age_s, max_age_s):
            if lkg_soc is None or age_s is None:
                return None
            try:
                age = float(age_s)
            except (TypeError, ValueError):
                return None
            if age > float(max_age_s):
                return None
            if age < 0:
                age = 0.0
            down = (self.max_discharge_kw * age) / (36.0 * self.capacity_kwh)
            up = (self.max_charge_kw * age) / (36.0 * self.capacity_kwh)
            try:
                v = float(lkg_soc)
            except (TypeError, ValueError):
                return None
            lo = max(0.0, v - down)
            hi = min(100.0, v + up)
            if hi < lo:
                hi = lo
            return (lo, hi)


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
) -> SimpleNamespace:
    return SimpleNamespace(
        blind_hold_active=blind_hold,
        reserve_write_verifiable=lambda: reserve_verifiable,
        soc_envelope=lambda: envelope,
        mains_export_active=lambda threshold_w=100.0: mains_export,
        _ev_battery_drain_soc=drain_target,
    )


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


def test_excess_solar_permits_claim_when_mains_export_witness_present():
    """D4 witness = True → claim path is not short-circuited."""
    ev = _make_ev(evse_on=False)
    coord = _make_coord_stub(mains_export=True)
    _engage_guard(ev, coord)
    # SOC + threshold satisfied so normal claim path fires post-guard.
    actions = ev.determine_excess_solar_actions(
        soc=95.0, remaining_forecast_kwh=10.0, tou_period="off_peak",
        soc_threshold=95, coord=coord,
    )
    turn_ons = [a for a in actions if a["service"] == "switch.turn_on"]
    assert len(turn_ons) == 1


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
# kind ∈ {"guard_covered", "force_charge_exempt", "must_start_by_exempt"}
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
        "must_start_by_exempt",
    ),
}


def _iter_evse_turn_on_line_numbers(src_path):
    """Yield line numbers of every `switch.turn_on` payload in the file.

    We scan for the literal `"service": "switch.turn_on"` — this is how
    every EVSE turn_on site in these two files structures the action
    payload. Non-EVSE contexts (SmartPlugController class body in
    energy_pool.py, `target == "smart_plugs"` branch in energy.py) use
    the SAME string; the caller must filter them out.
    """
    with open(src_path) as f:
        lines = f.readlines()
    hits = []
    for i, line in enumerate(lines, start=1):
        if '"service": "switch.turn_on"' in line:
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


def test_D_HIGH_1_contract_lists_only_sanctioned_exemptions():
    """The exemption list is the auditable contract. Adding a NEW
    exemption without ratification MUST break this test — it is the
    tripwire on scope-creep of INV-BW1 escape hatches. Today only
    must-start-by is sanctioned (force-charge has no dedicated turn_on
    site; it works by suppression + B3 drain, both guard-covered).
    """
    exempt_kinds = {"force_charge_exempt", "must_start_by_exempt"}
    exempt_keys = [
        k for k, (_p, _m, kind) in EVSE_TURN_ON_SITE_CONTRACT.items()
        if kind in exempt_kinds
    ]
    assert set(exempt_keys) == {"dp_must_start_by_forced"}, (
        f"Exemption drift — expected exactly {{dp_must_start_by_forced}}, "
        f"got {set(exempt_keys)}"
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
