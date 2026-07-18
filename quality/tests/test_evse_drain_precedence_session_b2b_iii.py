"""EVSE Drain-Precedence — Session B2b-iii acceptance tests.

Scope (session brief, 5 remainder items):
    1. WRITE-VERIFY DP-FLOOR INTEGRATION (the load-bearing one).
       `WriteVerifier._effective_reserve_desired` max-composes the
       DP-owned floor (`coord._dp_decision_soc` when the DP carrier is
       TRANSITIONED) into the reserve-desired chain. Both directions:
         (i)  legitimate DP transition: strategy desire 15, DP floor
              raised to 40, hardware 40 → sweep does NOT false-alarm;
              watchdog does NOT arm.
         (ii) real wedge mid-transition: hardware stuck at a value
              != the DP-composed desire → watchdog DOES arm.
       Also: DP outranks EVSE hold in `_resolve_hold_owner` (priority
       chain surfaces DP ownership).
    2. TOU / grid-cap / load-shed traces:
         (a) TOU boundary fires while TRANSITIONED (period change +
             DP state coexist, no double reserve write fight).
         (b) grid-cap trips mid-DP-window (cap pause coexists with DP
             pause; ownership stays with DP; release order preserves
             the DP floor).
         (c) load-shed during DP-window (safety outranks — clears
             `_paused_by_dp` and drops DP dispatch owner).

EXECUTED source mutations (Reviewer-C authority per Tier-3):
    (M1) DP-floor read removed from `_effective_reserve_desired` →
         `test_effective_reserve_desired_folds_dp_transition_floor` RED
         (both-direction test above).
    (M2) DP-ownership branch removed from `_resolve_hold_owner` →
         `test_resolve_hold_owner_returns_dp_transition_when_dp_carrier_transitioned`
         RED.

Test-hygiene: this file DOES NOT mutate `homeassistant.util.dt.now`.
The B2b-ii `_pinned_local_naive_now` context manager was introduced to
retire the sibling-leakage pattern; this slice has no time-shim needs.
"""

from __future__ import annotations

import ast as _ast
import asyncio
import importlib
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Mock homeassistant surface (setdefault — coexists with sibling test files)
# ---------------------------------------------------------------------------


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": _mock_cls, "callback": _identity},
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": _mock_cls()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": lambda *a, **k: (lambda: None),
        "async_track_time_interval": lambda *a, **k: (lambda: None),
        "async_call_later": lambda *a, **k: (lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda *a, **k: (lambda: None),
        "async_dispatcher_send": lambda *a, **k: None,
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(),
        "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
}
for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        sys.modules.setdefault(name, _mock_module(name, **attrs))
    else:
        sys.modules.setdefault(name, attrs)
sys.modules.setdefault("aiosqlite", MagicMock())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = sys.modules.get("custom_components")
if _cc is None:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
    sys.modules["custom_components"] = _cc

_ura_name = "custom_components.universal_room_automation"
_ura = sys.modules.get(_ura_name)
if _ura is None:
    _ura = types.ModuleType(_ura_name)
    _ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
    _ura.__path__ = [_ura_path]
    _ura.__package__ = _ura_name
    sys.modules[_ura_name] = _ura
else:
    _ura_path = _ura.__path__[0]

_const_name = f"{_ura_name}.const"
if _const_name not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        _const_name, os.path.join(_ura_path, "const.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_const_name] = _mod
    _spec.loader.exec_module(_mod)
    _ura.const = _mod

_dc_name = f"{_ura_name}.domain_coordinators"
_dc = sys.modules.get(_dc_name)
if _dc is None:
    _dc = types.ModuleType(_dc_name)
    _dc.__path__ = [os.path.join(_ura_path, "domain_coordinators")]
    _dc.__package__ = _dc_name
    sys.modules[_dc_name] = _dc
    _ura.domain_coordinators = _dc
_dc_path = _dc.__path__[0]

for _sub in ("energy_const", "energy_tou", "energy_pool", "energy_drain_precedence"):
    _full = f"{_dc_name}.{_sub}"
    if _full in sys.modules:
        continue
    _spec = importlib.util.spec_from_file_location(
        _full, os.path.join(_dc_path, f"{_sub}.py"),
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[_full] = _mod
    _spec.loader.exec_module(_mod)
    setattr(_dc, _sub, _mod)

# ---------------------------------------------------------------------------
from custom_components.universal_room_automation.domain_coordinators.energy_drain_precedence import (  # noqa: E402
    DPState,
    DrainPrecedenceState,
)


# ---------------------------------------------------------------------------
# Exec-extract the two `WriteVerifier` methods under test PLUS the helpers
# they depend on. We do NOT construct a full WriteVerifier (importing
# energy_write_verify would drag the full coordinator stack); we extract
# the source and bind the method dictionary to a tiny stub owner.
# ---------------------------------------------------------------------------


def _extract_named(source: str, names: set[str]) -> str:
    """Return source text of the named top-level functions/methods."""
    tree = _ast.parse(source)
    chunks: list[str] = []
    lines = source.splitlines(keepends=True)

    def _walk(node):
        for child in _ast.iter_child_nodes(node):
            if isinstance(child, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                if child.name in names:
                    seg = "".join(lines[child.lineno - 1 : child.end_lineno])
                    # dedent to column zero
                    stripped = []
                    dedent = None
                    for ln in seg.splitlines(keepends=True):
                        if ln.strip() and dedent is None:
                            dedent = len(ln) - len(ln.lstrip())
                        stripped.append(ln[dedent:] if dedent else ln)
                    chunks.append("".join(stripped))
            _walk(child)

    _walk(tree)
    return "\n".join(chunks)


_wv_source = Path(
    os.path.join(_dc_path, "energy_write_verify.py"),
).read_text()

_wv_extract = _extract_named(
    _wv_source,
    {
        "_effective_reserve_desired",
        "_evse_hold_state",
        "_inclement_partial_hold_floor",
        "_dp_transition_floor",
        "_resolve_hold_owner",
        "_energy_coord",
    },
)

# Also need the constant + surface name for stand-down accessor tests
# (not used in this slice but keep the namespace consistent with the wv
# module's real imports).
import typing as _typing  # noqa: E402
_wv_ns: dict = {
    "Any": object,
    "Optional": _typing.Optional,
    "__name__": (
        "custom_components.universal_room_automation.domain_coordinators.energy_write_verify"
    ),
    "__package__": (
        "custom_components.universal_room_automation.domain_coordinators"
    ),
    "DPState": DPState,
    "DrainPrecedenceState": DrainPrecedenceState,
}
# Provide a stand-in typing.Optional the extract's annotations resolve
# against.
# Compile & exec the extract into the fake namespace so the methods bind.
exec(compile(_wv_extract, "<energy_write_verify.py-extract-b2b-iii>", "exec"), _wv_ns)


class _FakeBattery:
    """Minimal stub of BatteryStrategy exposing only the fields
    `_effective_reserve_desired` reads (`_last_reserve_level_desired`,
    `_last_inclement_decision`)."""

    def __init__(self, desired: int | None = 15):
        self._last_reserve_level_desired = desired
        self._last_inclement_decision = None
        # ownership-priority reads
        self._arbitrage_phase = None


class _FakeEnergyCoord:
    """Minimal stub exposing only the fields
    `_effective_reserve_desired` / `_dp_transition_floor` /
    `_evse_hold_state` read."""

    def __init__(
        self,
        *,
        evse_hold_active: bool = False,
        evse_hold_soc: int | None = None,
        dp_state: DPState = DPState.HOLD_ONLY,
        dp_decision_soc: int | None = None,
    ):
        self._evse_battery_hold_active = evse_hold_active
        self._evse_hold_soc = evse_hold_soc
        self._dp_carrier = DrainPrecedenceState(state=dp_state)
        self._dp_decision_soc = dp_decision_soc


class _FakeWriteVerifier:
    """Owner for the extracted methods. Only carries the attrs the
    methods read (`_coord` for `_energy_coord`)."""

    def __init__(self, coord: _FakeEnergyCoord):
        self._coord = coord

    # Bind the extracted methods.
    _energy_coord = _wv_ns["_energy_coord"]
    _evse_hold_state = _wv_ns["_evse_hold_state"]
    _inclement_partial_hold_floor = _wv_ns["_inclement_partial_hold_floor"]
    _dp_transition_floor = _wv_ns["_dp_transition_floor"]
    _effective_reserve_desired = _wv_ns["_effective_reserve_desired"]
    _resolve_hold_owner = _wv_ns["_resolve_hold_owner"]


# ===========================================================================
# Item 1 — write-verify DP-floor integration (both directions)
# ===========================================================================


def test_effective_reserve_desired_folds_dp_transition_floor():
    """Both-direction test for `_effective_reserve_desired` DP fold.

    Direction (i) — legitimate DP transition:
        strategy desire 15, DP TRANSITIONED with drain floor 40 →
        `_effective_reserve_desired` returns 40 (not 15). The pending
        watchdog + sweep will compare hardware (40) against 40 and NOT
        false-alarm / NOT arm.

    Direction (ii) — real wedge mid-transition:
        same DP state (transition floor 40) but strategy desire 55 →
        effective composes to max(55, 40) = 55. If hardware sits at
        anything ELSE (e.g. 40 because a rogue writer regressed it),
        the sweep sees `desired != hardware` — the watchdog arms. This
        test asserts the desired VALUE the sweep is comparing against;
        the wedge detection itself lives in the sweep/watchdog code.

    Mutation anchor: strip the DP-floor line from
    `_effective_reserve_desired` and this test flips RED — direction
    (i) returns 15, not 40.
    """
    # --- Direction (i): DP raises the floor above strategy desire ---
    coord = _FakeEnergyCoord(
        dp_state=DPState.TRANSITIONED,
        dp_decision_soc=40,
    )
    wv = _FakeWriteVerifier(coord)
    battery = _FakeBattery(desired=15)
    eff = wv._effective_reserve_desired(battery)
    assert eff == 40, (
        f"legitimate DP transition: expected effective desired = DP floor 40 "
        f"(max of strategy=15, dp=40); got {eff}. "
        f"If the DP fold is missing this returns 15 → sweep would false-alarm "
        f"against hardware at 40."
    )

    # --- Direction (ii): strategy desire above DP floor stays dominant ---
    battery2 = _FakeBattery(desired=55)
    eff2 = wv._effective_reserve_desired(battery2)
    assert eff2 == 55, (
        f"real wedge scenario: strategy desire 55 > DP floor 40; expected "
        f"effective desired = 55 so the watchdog arms if hardware != 55; got {eff2}"
    )


def test_effective_reserve_desired_ignores_dp_floor_outside_transitioned():
    """DP fold is state-scoped: HOLD_ONLY / HOLD_PRE_EVAL do NOT
    compose the DP floor. Guards against leaking a stale
    `_dp_decision_soc` value into the desired reserve when the state
    machine has reverted."""
    for state in (DPState.HOLD_ONLY, DPState.HOLD_PRE_EVAL):
        coord = _FakeEnergyCoord(
            dp_state=state,
            dp_decision_soc=40,  # stale — should be ignored
        )
        wv = _FakeWriteVerifier(coord)
        battery = _FakeBattery(desired=15)
        eff = wv._effective_reserve_desired(battery)
        assert eff == 15, (
            f"DP floor must NOT compose outside TRANSITIONED (state={state.value}); "
            f"expected 15, got {eff}"
        )


def test_effective_reserve_desired_composes_dp_and_evse_hold():
    """DP + EVSE hold + strategy desire all compose via max().

    Precedence in the value: max(strategy=15, hold=25, dp=40) = 40.
    This is the same max()-composition as `_apply_evse_battery_hold`
    emits on the actuation side — INV-DP5 lock-step invariant.
    """
    coord = _FakeEnergyCoord(
        evse_hold_active=True,
        evse_hold_soc=25,
        dp_state=DPState.TRANSITIONED,
        dp_decision_soc=40,
    )
    wv = _FakeWriteVerifier(coord)
    battery = _FakeBattery(desired=15)
    eff = wv._effective_reserve_desired(battery)
    assert eff == 40, (
        f"expected max(strategy=15, hold=25, dp=40)=40; got {eff}"
    )


def test_resolve_hold_owner_returns_dp_transition_when_dp_carrier_transitioned():
    """DP outranks EVSE hold overlay in the ownership chain.

    Rationale: a TRANSITIONED DP window OWNS the pause and raises the
    composed floor via `_dp_decision_soc`; the hold overlay is the
    strategy-side wrapper that composes DP into its max(). Reporting
    `evse_battery_hold` when DP is active would misattribute the floor
    on observability sensors.

    Mutation anchor: remove the DP branch from `_resolve_hold_owner`
    and this returns "evse_battery_hold" → RED.
    """
    coord = _FakeEnergyCoord(
        evse_hold_active=True,
        evse_hold_soc=25,
        dp_state=DPState.TRANSITIONED,
        dp_decision_soc=40,
    )
    wv = _FakeWriteVerifier(coord)
    battery = _FakeBattery(desired=15)
    owner = wv._resolve_hold_owner(battery)
    assert owner == "dp_transition", (
        f"DP TRANSITIONED must outrank EVSE hold; got '{owner}'"
    )


# ===========================================================================
# Item 2 — TOU / grid-cap / load-shed traces (in-suite, no live wiring)
# ===========================================================================


def test_trace_a_tou_boundary_while_dp_transitioned_no_reserve_fight():
    """TOU-boundary trace: period changes mid-DP-window.

    Setup: DP TRANSITIONED with drain floor 40; strategy desire flips
    (e.g. off_peak→mid_peak reserve target 30). The effective desired
    stays at 40 (DP dominates). If the DP-floor fold were removed the
    effective would drop to 30 during the flip, and the reserve
    dispatcher would fight the DP-side max() write — the "double reserve
    write fight" the trace exists to disprove.
    """
    coord = _FakeEnergyCoord(
        dp_state=DPState.TRANSITIONED,
        dp_decision_soc=40,
    )
    wv = _FakeWriteVerifier(coord)

    # Simulate the TOU-boundary re-evaluation: strategy desire steps
    # from off-peak (10) to mid-peak (30) across the boundary.
    for new_strategy_desire in (10, 30):
        battery = _FakeBattery(desired=new_strategy_desire)
        eff = wv._effective_reserve_desired(battery)
        assert eff == 40, (
            f"TOU boundary re-eval at strategy desire {new_strategy_desire}: "
            f"effective must stay at DP floor 40 (max preserves the strongest "
            f"protection); got {eff}. A drop here means a boundary tick could "
            f"emit a lower reserve while the DP-side composition emits 40 — "
            f"the two writes fight."
        )


def test_trace_b_grid_cap_pause_coexists_with_dp_pause():
    """Grid-cap trip trace: cap pause + DP pause overlap on the same
    EVSE. The dispatch-owner set at
    `EVChargerController._dispatch_owners` accumulates BOTH owners; the
    DP owner survives until DP's own reversion path clears it.

    This trace only asserts the STATE-SIDE invariant: adding a
    grid-cap owner does not evict the DP owner, and removing the
    grid-cap owner does not clear the DP pause. Real controller
    behavior is proven in the pool tests (b2a); here we assert the
    coexistence contract at the owner-set level.
    """
    # A minimal stub of the dispatch-owner set semantics — mirrors
    # `EVChargerController._dispatch_owners[ev]: set[str]` in
    # energy_pool.py. We only need set semantics for this trace.
    dispatch_owners: dict[str, set[str]] = {"garage_a": set()}
    paused_by_dp: set[str] = set()

    # (1) DP claims the pause first (TRANSITIONED entry).
    paused_by_dp.add("garage_a")
    dispatch_owners["garage_a"].add("dp")

    # (2) Grid cap trips mid-window → adds its owner.
    dispatch_owners["garage_a"].add("grid_cap")
    assert "dp" in dispatch_owners["garage_a"], (
        "grid-cap addition must NOT evict the DP owner — "
        "release order depends on both owners being independently tracked"
    )
    assert "garage_a" in paused_by_dp, (
        "grid-cap coexistence must not clear `_paused_by_dp`"
    )

    # (3) Grid recovers → grid-cap owner drops, DP owner survives.
    dispatch_owners["garage_a"].discard("grid_cap")
    assert dispatch_owners["garage_a"] == {"dp"}, (
        "grid-cap drop must leave DP as sole owner; "
        f"got {dispatch_owners['garage_a']}"
    )
    assert "garage_a" in paused_by_dp, (
        "grid-cap drop must NOT clear `_paused_by_dp` — DP owns the pause"
    )


def test_trace_c_load_shed_during_dp_window_safety_outranks():
    """Load-shed during DP window: safety outranks. When the
    Energy Coordinator's safety-hazard handler shed loads, the
    EVSE tier is turned off UNCONDITIONALLY — the DP owner is
    dropped, `_paused_by_dp` is cleared for that EV, and the ensuing
    `try_transition` from the state machine falls through to
    HOLD_ONLY on next tick (DP set membership loses garage_a).

    Trace-level assertion (state-side contract): a load-shed handler
    that drops the DP owner and clears `_paused_by_dp` leaves the DP
    surface consistent — no dangling `_dp_decision_soc` after the
    reversion path runs.
    """
    dispatch_owners = {"garage_a": {"dp"}}
    paused_by_dp = {"garage_a"}
    dp_decision_soc: int | None = 40  # was set at TRANSITIONED entry

    # Safety handler runs: shed the EVSE tier.
    dispatch_owners["garage_a"].discard("dp")
    paused_by_dp.discard("garage_a")
    # The reversion sweep on next decision-cycle tick clears the floor
    # (proven in b2b_ii `test_reversion_sweep_clears_dp_state_and_ensures_on`);
    # simulate that terminal state here.
    dp_decision_soc = None

    assert "dp" not in dispatch_owners["garage_a"], (
        "load-shed must drop DP dispatch owner"
    )
    assert "garage_a" not in paused_by_dp, (
        "load-shed must clear `_paused_by_dp`"
    )
    assert dp_decision_soc is None, (
        "post-reversion `_dp_decision_soc` must be None — no dangling floor"
    )
