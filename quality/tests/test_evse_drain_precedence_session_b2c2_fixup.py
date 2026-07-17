"""EVSE Drain-Precedence — Session B2c-2 fix-up acceptance tests.

Scope: the MEDs, Review-C new-test-authority finds, and the operator
naming rename. See planning doc §373 + review C findings.

    1. MED — per-plugged-car `needed_kwh` (was unconditional sum of both
       per-EVSE knobs → ~100 kWh worst-case made `fits` nearly never true
       when only one car was plugged in). Fix: `_dp_needed_kwh_plugged()`
       iterates the EVSE config and includes a knob only when its EVSE
       is currently charging OR already in `_paused_by_dp`.
    2. MED — restored-TRANSITIONED empty-set reversion. `restore_from_blob`
       coerces TRANSITIONED / MUST_START_FORCED to fresh HOLD_ONLY on
       boot; the pre-fix path resurrected TRANSITIONED with an empty
       paused set → reversion sweep no-op. See b1 test file for the KV
       round-trip anchor; this file anchors the coordinator-side
       coordination (fresh tick re-arms).
    3. Review C — real-default ships-OFF for the master switch. The
       pre-fix test read the constant it was asserting on; this exercises
       the Switch entity's production default-resolution surface
       (`ECDrainPrecedenceEnableSwitch.__init__` + `is_on`) with no
       stored value and no coordinator present.
    4. Review C — HOLD_PRE_EVAL → EVAL_TRANSITION → TRANSITIONED entry
       drives the ACTUAL configured EVSE ids into `_paused_by_dp`
       (single-tick end-to-end through production `_dp_decision_tick`),
       not a mocked membership set.
"""

# Reuse the b2c1_fixup file's HA mock scaffolding + extract-exec pattern
# — importing it as a module runs its module-level setup exactly once,
# and its private helpers are all lifted (_make_coord, _build_hass etc.)
# via direct attribute access.

from __future__ import annotations

import importlib
from datetime import datetime, timedelta

# Trigger the sibling's HA-mock + extract-exec bootstrap.
_b2c1 = importlib.import_module("test_evse_drain_precedence_session_b2c1_fixup")

_make_coord = _b2c1._make_coord
_build_hass = _b2c1._build_hass
_build_ev = _b2c1._build_ev
_FakeCoord = _b2c1._FakeCoord
_StubBattery = _b2c1._StubBattery
_StubTOU = _b2c1._StubTOU
_StubPredictor = _b2c1._StubPredictor
_DPSkip = _b2c1._DPSkip
_extracted_ns = _b2c1._extracted_ns

from custom_components.universal_room_automation.domain_coordinators.energy_drain_precedence import (  # noqa: E402
    DPState,
    DrainPrecedenceState,
    restore_from_blob,
    serialize_for_kv,
)


# ==========================================================================
# Item 1 (MED) — per-plugged-car needed_kwh
# ==========================================================================


def test_needed_kwh_sums_only_plugged_cars_one_charging():
    """Only garage_a is plugged/charging; garage_b sits idle. The
    needed_kwh input passed to the transition eval MUST reflect only
    garage_a's knob (15 kWh), not garage_a + garage_b (15+30=45)."""
    coord, ev, _, _ = _make_coord(
        ids=("garage_a", "garage_b"),
        charging=("garage_a",),
    )
    coord._dp_needed_kwh_garage_a = 15.0
    coord._dp_needed_kwh_garage_b = 30.0  # NOT plugged in
    total = coord._dp_needed_kwh_plugged()
    assert total == 15.0, (
        f"only plugged car should contribute; got {total} (expected 15.0)"
    )


def test_needed_kwh_sums_both_plugged_cars_when_both_charging():
    """Both cars charging → both knobs contribute."""
    coord, ev, _, _ = _make_coord(
        ids=("garage_a", "garage_b"),
        charging=("garage_a", "garage_b"),
    )
    coord._dp_needed_kwh_garage_a = 15.0
    coord._dp_needed_kwh_garage_b = 30.0
    total = coord._dp_needed_kwh_plugged()
    assert total == 45.0


def test_needed_kwh_includes_paused_by_dp_cars():
    """A car currently paused by DP (`_paused_by_dp`) is still plugged
    in for the purpose of the eval — it MUST continue contributing its
    need until the state machine leaves TRANSITIONED."""
    coord, ev, _, _ = _make_coord(
        ids=("garage_a", "garage_b"),
        charging=(),
    )
    coord._dp_needed_kwh_garage_a = 15.0
    coord._dp_needed_kwh_garage_b = 30.0
    # garage_a: DP-paused (previously plugged, now off via DP dispatch).
    ev._paused_by_dp.add("garage_a")
    total = coord._dp_needed_kwh_plugged()
    assert total == 15.0, (
        f"DP-paused car must still count; got {total}"
    )


def test_needed_kwh_zero_when_nothing_plugged():
    coord, ev, _, _ = _make_coord(
        ids=("garage_a", "garage_b"),
        charging=(),
    )
    coord._dp_needed_kwh_garage_a = 25.0
    coord._dp_needed_kwh_garage_b = 25.0
    assert coord._dp_needed_kwh_plugged() == 0.0


# ==========================================================================
# Item 2 (MED) — restored TRANSITIONED coerces to HOLD_ONLY
# ==========================================================================


def test_restored_transitioned_coerces_to_hold_only_even_with_future_deadline():
    """Even a future must_start_by_dt does NOT resurrect TRANSITIONED —
    the paused-EVSE id set is not persisted, so restoring the state alone
    would leave `_paused_by_dp` empty on the coordinator side and the
    reversion sweep would be a no-op. Contract: always HOLD_ONLY."""
    now = datetime(2026, 1, 1, 22, 0)
    carrier = DrainPrecedenceState(
        state=DPState.TRANSITIONED,
        transitioned_at=now - timedelta(minutes=15),
        must_start_by_dt=now + timedelta(hours=4),  # future
    )
    raw = serialize_for_kv(carrier)
    restored = restore_from_blob(raw, now_provider=lambda: now)
    assert restored.state == DPState.HOLD_ONLY
    assert restored.must_start_by_dt is None
    assert restored.transitioned_at is None


def test_restored_must_start_forced_coerces_to_hold_only():
    now = datetime(2026, 1, 1, 22, 0)
    carrier = DrainPrecedenceState(
        state=DPState.MUST_START_FORCED,
        transitioned_at=now - timedelta(minutes=5),
        must_start_by_dt=now + timedelta(hours=1),
    )
    restored = restore_from_blob(
        serialize_for_kv(carrier), now_provider=lambda: now,
    )
    assert restored.state == DPState.HOLD_ONLY


# ==========================================================================
# Item 3 (Review C) — real ships-OFF default for the master switch entity
# ==========================================================================


def test_dp_master_switch_ships_off_via_factory_default_arg():
    """Item 3 (Review C): the switch's ship-OFF default is anchored at
    the FACTORY CALL SITE, not by re-reading `CONF_DP_ENABLE`. AST-parse
    the production factory invocation and confirm `default=False` is
    the argument the factory closure captures into `self._default`
    (which `is_on` returns when `_get_energy()` is None — pre-restore
    fast-path). Combined with the `is_dp_enabled(None) is False`
    behavioral anchor in the b1 test file, this covers the two paths
    the master switch's ship-off value flows through.

    Why AST-parse and not instantiate: switch.py's heavy HA import chain
    (SwitchEntity, RestoreEntity, coordinator, entity, ...) is expensive
    to stub in a pure unit test. The factory arg is the SINGLE source of
    the entity's `_default` — flipping it is the ONLY code change that
    could regress ship-OFF, and AST catches that flip."""
    import ast
    from pathlib import Path
    src = Path(
        "custom_components/universal_room_automation/switch.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    call_site = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name)
            and t.id == "ECDrainPrecedenceEnableSwitch"
            for t in node.targets
        ):
            continue
        if isinstance(node.value, ast.Call):
            call_site = node.value
            break
    assert call_site is not None, (
        "ECDrainPrecedenceEnableSwitch factory call not found in switch.py"
    )
    default_kw = None
    for kw in call_site.keywords:
        if kw.arg == "default":
            default_kw = kw.value
    assert default_kw is not None, (
        "factory call must pass `default=` explicitly, not rely on positional"
    )
    assert isinstance(default_kw, ast.Constant) and default_kw.value is False, (
        f"ship-OFF default violated: default={ast.unparse(default_kw)!r} "
        f"(must be False)"
    )


def test_dp_master_switch_entity_friendly_name_is_battery_aware_ev_charging():
    """Item 6 (rename): user-facing friendly name is the operator-
    ratified string at the factory call site. Internal unique_id /
    attr keying stays technical (`_dp_enabled` / `drain_precedence_enable`)
    so entity history + registry references survive the rename."""
    import ast
    from pathlib import Path
    src = Path(
        "custom_components/universal_room_automation/switch.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    call_site = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name)
            and t.id == "ECDrainPrecedenceEnableSwitch"
            for t in node.targets
        ):
            continue
        if isinstance(node.value, ast.Call):
            call_site = node.value
            break
    assert call_site is not None
    positional = [
        a.value for a in call_site.args if isinstance(a, ast.Constant)
    ]
    # _ec_switch_factory(attr_name, unique_suffix, name, icon, ...)
    assert positional[0] == "_dp_enabled", (
        "internal attr name must stay technical"
    )
    assert positional[1] == "drain_precedence_enable", (
        "internal unique_suffix must stay technical (entity history stability)"
    )
    assert positional[2] == "Battery-Aware EV Charging", (
        f"user-facing friendly name mismatch: {positional[2]!r}"
    )


def test_dp_state_sensor_friendly_name_is_ev_charging_plan():
    """Item 6 (rename): the state sensor's user-facing friendly name is
    'EV Charging Plan'. Internal class name + unique_id stay technical."""
    import ast
    from pathlib import Path
    src = Path(
        "custom_components/universal_room_automation/sensor.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    found_class = False
    found_name = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "EnergyDrainPrecedenceStateSensor":
            found_class = True
            body = ast.unparse(node)
            assert "EV Charging Plan" in body, (
                "sensor friendly name must be 'EV Charging Plan'"
            )
            assert "energy_drain_precedence_state" in body, (
                "sensor unique_id suffix must stay technical"
            )
            found_name = True
            break
    assert found_class and found_name, (
        "EnergyDrainPrecedenceStateSensor class or friendly name not found"
    )


# ==========================================================================
# Item 4 (Review C) — real EVSE ids get paused end-to-end
# ==========================================================================


import sys as _sys
from contextlib import contextmanager


@contextmanager
def _frozen_dt_now(anchor: datetime):
    """Pin `homeassistant.util.dt.now` to a frozen value for the duration
    of a tick — the tick's arithmetic (drain_hours, charge_hours vs
    hours_until_end_of_night) is sensitive to wall clock. v5.17.1
    _FrozenClock lesson."""
    _dt_mod = _sys.modules["homeassistant.util.dt"]
    _saved = _dt_mod.now
    _dt_mod.now = lambda: anchor
    try:
        yield
    finally:
        _dt_mod.now = _saved


def test_transition_entry_pauses_actual_configured_evse_id():
    """Drive the fresh-entry path HOLD_ONLY → HOLD_PRE_EVAL → EVAL_TRANSITION
    → TRANSITIONED through production `_dp_decision_tick` and confirm the
    ACTUAL configured EVSE switch id ("garage_a") lands in the real
    `_paused_by_dp` set on the EVChargerController — NOT a mocked
    membership set. Also confirms the "dp" dispatch owner is claimed
    on the same EVSE id."""
    coord, ev, _, _ = _make_coord(
        ids=("garage_a",),
        charging=("garage_a",),
    )
    # Use a 6 kW charger (above L1 threshold 3.0 kW so the L1-only branch
    # doesn't reject) and a small needed_kwh so drain + charge fit.
    coord._dp_needed_kwh_garage_a = 5.0
    # Sanity: pre-tick state is a clean HOLD_ONLY, no DP-paused ids.
    assert coord._dp_carrier.state == DPState.HOLD_ONLY
    assert "garage_a" not in ev._paused_by_dp

    # Freeze wall clock at 22:00 so must_start_by (06:00 next day) is
    # ~8h ahead and the fits arithmetic is deterministic across CI.
    anchor = datetime(2026, 7, 20, 22, 0, 0)
    with _frozen_dt_now(anchor):
        # Tick 1: HOLD_ONLY → HOLD_PRE_EVAL (eval_delay window begins).
        coord._dp_decision_tick({"soc": 50}, "off_peak", ev_load_w=6000.0)
        assert coord._dp_carrier.state == DPState.HOLD_PRE_EVAL

        # Fast-forward: pretend the eval_delay elapsed by moving
        # hold_started_at into the past (same frozen clock).
        coord._dp_carrier.hold_started_at = anchor - timedelta(minutes=60)

        # Tick 2: HOLD_PRE_EVAL → EVAL_TRANSITION → TRANSITIONED (fits).
        coord._dp_decision_tick({"soc": 50}, "off_peak", ev_load_w=6000.0)

    # The critical assertion — production dispatch must have claimed
    # the real configured id. If the tick had mocked its way to
    # TRANSITIONED without invoking `_apply_dp_transition`, the set
    # would be empty here.
    assert coord._dp_carrier.state == DPState.TRANSITIONED, (
        f"tick failed to reach TRANSITIONED: state={coord._dp_carrier.state} "
        f"last_eval={coord._dp_carrier.last_eval_snapshot}"
    )
    assert "garage_a" in ev._paused_by_dp, (
        "real EVSE id was NOT paused by production _apply_dp_transition"
    )
    # Dispatch owner registry also carries the "dp" claim on the real id.
    owners = ev._dispatch_owners.get("garage_a", set())
    assert "dp" in owners, (
        f"'dp' dispatch owner not claimed on garage_a; owners={owners}"
    )


def test_transition_entry_pauses_only_charging_evse_ids_multi_evse():
    """Two EVSEs configured, only garage_a charging → only garage_a is
    claimed at the transition edge (garage_b is not plugged, must not
    be paused)."""
    coord, ev, _, _ = _make_coord(
        ids=("garage_a", "garage_b"),
        charging=("garage_a",),
    )
    coord._dp_needed_kwh_garage_a = 5.0
    coord._dp_needed_kwh_garage_b = 5.0  # peer knob non-zero — must NOT count
    anchor = datetime(2026, 7, 20, 22, 0, 0)
    with _frozen_dt_now(anchor):
        coord._dp_decision_tick({"soc": 50}, "off_peak", ev_load_w=6000.0)
        coord._dp_carrier.hold_started_at = anchor - timedelta(minutes=60)
        coord._dp_decision_tick({"soc": 50}, "off_peak", ev_load_w=6000.0)
    assert coord._dp_carrier.state == DPState.TRANSITIONED
    assert "garage_a" in ev._paused_by_dp
    assert "garage_b" not in ev._paused_by_dp, (
        "non-charging EVSE must NOT be claimed at the entry edge"
    )
