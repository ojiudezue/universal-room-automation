"""EVSE Drain-Precedence — Session B2b-i acceptance tests.

Scope of this file (bounded slice, per session brief):
    - `_paused_by_dp` provenance on EVChargerController (peer of
      `_paused_by_battery_drain` / `_paused_by_arbitrage` /
      `_paused_by_load_shed`).
    - Owner tag "dp" claimed via `_claim_pause_dispatch_owner`.
    - Legacy-carryover guard in `determine_actions` off_peak branch treats
      `_paused_by_dp` as a peer (TOU ensure-on does NOT release it).
    - `pause_reason_human` renders "drain-precedence transition (paused)".
    - `_prune_removed_evses` includes `_paused_by_dp`.
    - `_apply_dp_transition` (new EnergyCoordinator method) pauses the
      target EVSEs into `_paused_by_dp` + stamps `_dp_decision_soc`.
    - `_apply_evse_battery_hold` update-in-place leg composes the reserve
      floor as `max(existing_action_value, hold_reserve, drain_target)` —
      INV-DP3 fit-supremacy (never demote).
    - Interaction trace: force-charge preempts DP (§127 — force-charge is
      the sole authoritative override).

EXECUTED source mutations (Reviewer-C authority per Tier-3):
    (a) INV-DP3: replace the DP-composed max() with raw drain_target →
        `test_composed_reserve_floor_max_of_all_three_contributors` fails.
    (b) Ownership: swap `_paused_by_dp` → `_paused_by_battery_drain` in
        `_apply_dp_transition` → `test_apply_dp_transition_claims_paused_by_dp`
        fails.
    (c) Interaction trace (in-process, no mutation needed): force-charge
        active preempts DP (documented via
        `test_force_charge_preempts_dp_pause_release`).

Actuation for the append leg + must-start-by + decision-cycle wiring is
Session B2b-ii; write-verify extension + remaining traces are Session
B2b-iii.
"""

from __future__ import annotations

import ast as _ast
import asyncio
import importlib
import importlib.util
import os
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Mock homeassistant (setdefault-only — coexists with sibling test files)
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

for _sub in ("energy_const", "energy_tou", "energy_pool"):
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
from conftest import MockHass  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController,
)


# ---------------------------------------------------------------------------
# Exec-extract `_apply_evse_battery_hold` and `_apply_dp_transition` from
# energy.py so we can drive the real production source bytes without
# constructing a full EnergyCoordinator (which requires HA selectors etc).
# Same pattern as test_energy_load_shedding_correctness.py.
# ---------------------------------------------------------------------------


def _extract_named(source: str, names: set[str]) -> str:
    tree = _ast.parse(source)
    src_lines = source.splitlines()
    out: list[str] = []
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.ClassDef) or node.name != "EnergyCoordinator":
            continue
        for child in node.body:
            if isinstance(child, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                if child.name in names:
                    seg = "\n".join(
                        src_lines[child.lineno - 1: child.end_lineno]
                    )
                    dedented = "\n".join(
                        line[4:] if line.startswith("    ") else line
                        for line in seg.splitlines()
                    )
                    out.append(dedented)
    return "\n\n".join(out)


with open(os.path.join(_dc_path, "energy.py"), "r", encoding="utf-8") as _fh:
    _energy_src = _fh.read()

_extracted = _extract_named(
    _energy_src,
    {"_apply_evse_battery_hold", "_apply_dp_transition"},
)

import logging as _logging
_LOGGER = _logging.getLogger("test_dp_b2b_i")

# Extract minimal DEFAULT_RESERVE_SOC_ENTITY reference — the code does
# `from .energy_const import DEFAULT_RESERVE_SOC_ENTITY` inline, so we
# also need to make relative-import work in the exec'd namespace.
_extracted_ns: dict = {
    "_LOGGER": _LOGGER,
    "Any": object,
    "__name__": (
        "custom_components.universal_room_automation.domain_coordinators.energy"
    ),
    "__package__": (
        "custom_components.universal_room_automation.domain_coordinators"
    ),
}
exec(compile(_extracted, "<energy.py-extract>", "exec"), _extracted_ns)


class _StubBattery:
    """Minimal `_battery` stub — only the attrs `_apply_evse_battery_hold`
    reads (reserve entity resolution + ledger stamps)."""

    def __init__(self, reserve_entity: str = "number.reserve_soc"):
        self._reserve_entity = reserve_entity
        self._last_reserve_level = None
        self._last_reserve_level_at = None
        self._last_reserve_level_desired = None

    def _get_entity(self, key, default, role=None):
        return self._reserve_entity


class _FakeCoord:
    """Host for the extracted _apply_evse_battery_hold / _apply_dp_transition."""

    def __init__(self, hass, ev, battery):
        self.hass = hass
        self._ev = ev
        self._battery = battery
        self._evse_hold_soc: int | None = None
        self._dp_decision_soc: int | None = None
        self._write_verifier = None  # boot/tests: verifier=None → gate off


_FakeCoord._apply_evse_battery_hold = _extracted_ns["_apply_evse_battery_hold"]
_FakeCoord._apply_dp_transition = _extracted_ns["_apply_dp_transition"]


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _build_hass() -> MockHass:
    hass = MockHass()
    loop = asyncio.new_event_loop()

    def _run_task(coro):
        loop.run_until_complete(coro)
        return MagicMock()

    hass.async_create_task = _run_task

    async def _svc(*a, **k):
        return None
    hass.services = MagicMock()
    hass.services.async_call = _svc
    return hass


def _build_ev(hass) -> EVChargerController:
    evse_cfg = {
        "garage_a": {
            "switch": "switch.garage_a",
            "power": "sensor.garage_a_power",
            "energy_today": "sensor.garage_a_energy_today",
            "energy_month": "sensor.garage_a_energy_month",
        },
        "garage_b": {
            "switch": "switch.garage_b",
            "power": "sensor.garage_b_power",
            "energy_today": "sensor.garage_b_energy_today",
            "energy_month": "sensor.garage_b_energy_month",
        },
    }
    hass.set_state("switch.garage_a", "on")
    hass.set_state("switch.garage_b", "on")
    hass.set_state("sensor.garage_a_power", "1000",
                   attributes={"unit_of_measurement": "W"})
    hass.set_state("sensor.garage_b_power", "1000",
                   attributes={"unit_of_measurement": "W"})
    return EVChargerController(hass, evse_config=evse_cfg)


def _make_coord():
    hass = _build_hass()
    ev = _build_ev(hass)
    battery = _StubBattery()
    return _FakeCoord(hass, ev, battery), ev, battery


# ==========================================================================
# Provenance + prune
# ==========================================================================


def test_paused_by_dp_set_exists_on_ev_controller_and_is_peer():
    _, ev, _ = _make_coord()
    # Peer of the sibling owner sets — same type, initially empty.
    assert isinstance(ev._paused_by_dp, set)
    assert ev._paused_by_dp == set()
    # Distinct object from siblings (Bug Class #46 — collision-by-set-overload).
    assert ev._paused_by_dp is not ev._paused_by_battery_drain
    assert ev._paused_by_dp is not ev._paused_by_arbitrage
    assert ev._paused_by_dp is not ev._paused_by_load_shed
    assert ev._paused_by_dp is not ev._paused_by_us


def test_prune_removed_evses_prunes_paused_by_dp():
    hass = _build_hass()
    ev = _build_ev(hass)
    ev._paused_by_dp.add("garage_a")
    ev._paused_by_dp.add("orphan_gone")
    ev._prune_removed_evses()
    # Configured EVSE stays; orphan pruned.
    assert "garage_a" in ev._paused_by_dp
    assert "orphan_gone" not in ev._paused_by_dp


# ==========================================================================
# Carry-over guard in determine_actions (~:558)
# ==========================================================================


def test_off_peak_carryover_dp_pause_wins_over_tou_ensure_on():
    """Off-peak `determine_actions` must treat `_paused_by_dp` as a peer
    of the other battery-protection owners — TOU ensure-on must NOT
    release a DP-owned pause. Mutation-anchored via the sibling test
    below (`test_removing_dp_from_carryover_lets_ev_turn_on`)."""
    hass = _build_hass()
    ev = _build_ev(hass)
    # Simulate: DP has claimed garage_a; switch is currently off.
    ev._paused_by_dp.add("garage_a")
    hass.set_state("switch.garage_a", "off")
    hass.set_state("sensor.garage_a_power", "0",
                   attributes={"unit_of_measurement": "W"})
    hass.set_state("switch.garage_b", "off")
    hass.set_state("sensor.garage_b_power", "0",
                   attributes={"unit_of_measurement": "W"})
    actions = ev.determine_actions("off_peak", grid_charge_on=False)
    # garage_a is DP-paused → NO turn_on action emitted.
    a_targets = [a for a in actions if a.get("target") == "switch.garage_a"]
    assert a_targets == [], (
        f"DP-paused garage_a produced actions {a_targets}; expected [] "
        "(carry-over guard should skip TOU ensure-on)."
    )


# ==========================================================================
# pause_reason_human
# ==========================================================================


def test_pause_reason_human_reports_dp_paused_classification():
    hass = _build_hass()
    ev = _build_ev(hass)
    ev._paused_by_dp.add("garage_a")
    hass.set_state("switch.garage_a", "off")
    hass.set_state("sensor.garage_a_power", "0",
                   attributes={"unit_of_measurement": "W"})
    hass.set_state("switch.garage_b", "off")
    hass.set_state("sensor.garage_b_power", "0",
                   attributes={"unit_of_measurement": "W"})
    status = ev.get_status()
    prh = status.get("pause_reason_human", {})
    assert prh.get("garage_a") == "drain-precedence transition (paused)"


# ==========================================================================
# _apply_dp_transition — pause claim + owner tag + decision-SOC stamp
# ==========================================================================


class _Decision:
    """Duck-typed TransitionDecision extension carrying the actuation
    payload B2b-ii will produce."""

    def __init__(self, transition, drain_target_soc, evse_ids_to_pause):
        self.transition = transition
        self.drain_target_soc = drain_target_soc
        self.evse_ids_to_pause = evse_ids_to_pause


def test_apply_dp_transition_claims_paused_by_dp():
    """Ownership mutation anchor: `_apply_dp_transition` must add
    target evse ids to `_paused_by_dp` (not any sibling set), claim
    the "dp" dispatch owner, and stamp `_dp_decision_soc`."""
    coord, ev, _ = _make_coord()
    d = _Decision(
        transition=True,
        drain_target_soc=30,
        evse_ids_to_pause=["garage_a"],
    )
    coord._apply_dp_transition(d)
    # Ownership routes into `_paused_by_dp`, NOT `_paused_by_battery_drain`.
    assert "garage_a" in ev._paused_by_dp
    assert "garage_a" not in ev._paused_by_battery_drain
    assert "garage_a" not in ev._paused_by_arbitrage
    assert "garage_a" not in ev._paused_by_us
    # Dispatch owner "dp" claimed via reference-counted owner map.
    owners = ev._dispatch_owners.get("garage_a", set())
    assert "dp" in owners
    # DP decision SOC stamped for the next _apply_evse_battery_hold tick.
    assert coord._dp_decision_soc == 30


def test_apply_dp_transition_noop_when_transition_false():
    coord, ev, _ = _make_coord()
    d = _Decision(
        transition=False,
        drain_target_soc=30,
        evse_ids_to_pause=["garage_a"],
    )
    coord._apply_dp_transition(d)
    assert "garage_a" not in ev._paused_by_dp
    assert coord._dp_decision_soc is None


# ==========================================================================
# _apply_evse_battery_hold — INV-DP3 composed reserve floor (update-in-place)
# ==========================================================================


def _decision_with_existing_reserve(existing_val: int, reserve_entity: str):
    """Build a `decision` dict shape mirroring what BatteryStrategy emits
    into `_apply_evse_battery_hold`. The pre-existing reserve action
    carries the strategy-composed floor (inclement_partial_hold /
    arbitrage_attain via `decision.reserve_floor` at
    energy_battery.py:4407,4428,4439,4447)."""
    return {
        "reason": "test-strategy",
        "actions": [
            {
                "service": "number.set_value",
                "target": reserve_entity,
                "data": {"value": existing_val},
            }
        ],
        "soc": 60,
    }


def test_composed_reserve_floor_max_of_all_three_contributors():
    """INV-DP3 fit-supremacy mutation anchor: the update-in-place leg
    composes `max(existing_action_value, hold_reserve, drain_target)`.

    Sources:
        - existing_val = strategy-decided reserve_floor (inclement floor
          / arbitrage attain floor via energy_battery.py:4407,4428,4439,4447).
        - hold_reserve = `_evse_hold_soc` captured at hold-start.
        - drain_target = `_dp_decision_soc` stamped by
          `_apply_dp_transition`.
    Test scenario picks values such that dropping ANY contributor from
    the max() would change the emitted value — proving each is
    load-bearing.
    """
    coord, _, battery = _make_coord()
    coord._evse_hold_soc = 25          # hold_reserve
    coord._dp_decision_soc = 40         # drain_target (STRONGEST)
    decision = _decision_with_existing_reserve(20, battery._reserve_entity)
    #                                             ^ existing (inclement/attain floor)
    result = coord._apply_evse_battery_hold(decision)
    reserve_actions = [
        a for a in result["actions"]
        if a.get("target") == battery._reserve_entity
    ]
    assert len(reserve_actions) == 1
    val = reserve_actions[0]["data"]["value"]
    # max(20, 25, 40) = 40; if the mutation drops drain_target the value
    # becomes max(20, 25) = 25 and this assertion fails.
    assert val == 40, (
        f"expected composed floor 40 = max(existing=20, hold=25, drain=40); "
        f"got {val}. If mutation dropped drain_target, expect 25."
    )


def test_composed_reserve_floor_never_demotes_below_existing():
    """When drain_target is BELOW existing (inclement/attain) floor, the
    composed value stays at existing — never demote."""
    coord, _, battery = _make_coord()
    coord._evse_hold_soc = 25
    coord._dp_decision_soc = 15          # drain_target LOWER than existing
    decision = _decision_with_existing_reserve(50, battery._reserve_entity)
    result = coord._apply_evse_battery_hold(decision)
    val = [
        a for a in result["actions"]
        if a.get("target") == battery._reserve_entity
    ][0]["data"]["value"]
    assert val == 50, (
        f"expected floor 50 (existing wins); got {val}. INV-DP3 violated: "
        "drain_target demoted an existing higher floor."
    )


def test_composed_reserve_floor_absent_dp_decision_matches_pre_slice_behavior():
    """When `_dp_decision_soc` is None (no active DP transition), the
    composition is byte-identical to pre-slice `max(existing, hold)`."""
    coord, _, battery = _make_coord()
    coord._evse_hold_soc = 25
    coord._dp_decision_soc = None
    decision = _decision_with_existing_reserve(20, battery._reserve_entity)
    result = coord._apply_evse_battery_hold(decision)
    val = [
        a for a in result["actions"]
        if a.get("target") == battery._reserve_entity
    ][0]["data"]["value"]
    assert val == 25  # max(20, 25) unchanged from pre-slice


# ==========================================================================
# Interaction trace: force-charge preempts DP
# ==========================================================================


def test_force_charge_preempts_dp_pause_release():
    """Plan §127 interaction matrix row 1: force-charge is the single
    authoritative override. When a DP pause is active AND force-charge
    is armed on the EV controller, `determine_actions` in off_peak +
    force-charge-active must not touch the DP set (force-charge doesn't
    live in a set — it's a window on `_force_charge_until`) and the
    peak-branch bypass returns early. Here we verify the peak-period
    bypass: force-charge active + DP-paused EVSE → the peak branch
    `continue`s past pause without perturbing the DP set."""
    hass = _build_hass()
    ev = _build_ev(hass)
    ev._paused_by_dp.add("garage_a")
    # B2c-1 fix-up item 7 (HIGH test-hygiene): use a FROZEN injected clock
    # rather than naive `datetime.utcnow()` — the underlying comparison
    # is `_force_charge_until > dt_util.utcnow()`, so a live naive-utc
    # read is race-prone if the process pauses between assignment and
    # `determine_actions`. Pin `dt_util.utcnow` to a fixed moment and
    # restore in a finally.
    from datetime import timedelta as _td
    import sys as _sys
    _dt_mod = _sys.modules["homeassistant.util.dt"]
    _orig_utcnow = getattr(_dt_mod, "utcnow")
    _pinned = datetime(2026, 7, 17, 2, 0, 0)
    _dt_mod.utcnow = lambda: _pinned
    try:
        ev._force_charge_until = _pinned + _td(hours=1)
        # Peak branch: force-charge active → continues past pause;
        # `_paused_by_dp` is NOT touched (DP owns its set exclusively).
        _ = ev.determine_actions("peak", grid_charge_on=False)
        assert "garage_a" in ev._paused_by_dp, (
            "force-charge branch must NOT strip DP ownership; force-charge is "
            "a window override, not a set owner. If the DP set was cleared here "
            "the release path became racy."
        )
    finally:
        _dt_mod.utcnow = _orig_utcnow


# ==========================================================================
# EXECUTED source mutations (Reviewer-C authority per Tier-3)
# --------------------------------------------------------------------------
# Each mutation edits energy.py / energy_pool.py on disk, runs the target
# test in a subprocess (isolated from the parent's already-imported
# module bytes), asserts it FAILS, and restores. Same isolation pattern
# as test_evse_drain_precedence_session_b2a.py.
# ==========================================================================


_HERE = os.path.dirname(os.path.abspath(__file__))
_ENERGY_SRC = Path(_dc_path) / "energy.py"
_POOL_SRC = Path(_dc_path) / "energy_pool.py"


def _run_named_test_under_mutation(
    src_path: Path, old: str, new: str, target_test: str,
) -> None:
    backup = src_path.read_text()
    assert old in backup, (
        f"mutation anchor NOT FOUND in {src_path.name} — test needs "
        f"updating for source drift.\nanchor snippet:\n{old[:200]}"
    )
    try:
        mutated = backup.replace(old, new, 1)
        assert mutated != backup, "mutation was a no-op"
        src_path.write_text(mutated)
        pyc_dir = src_path.parent / "__pycache__"
        if pyc_dir.exists():
            for p in pyc_dir.glob(f"{src_path.stem}.*"):
                p.unlink()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(_HERE).parent) + os.pathsep + env.get(
            "PYTHONPATH", ""
        )
        proc = subprocess.run(
            [
                sys.executable, "-m", "pytest", "-x", "--no-header",
                f"quality/tests/test_evse_drain_precedence_session_b2b_i.py::{target_test}",
                "-q",
            ],
            cwd=str(Path(_HERE).parent.parent),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert proc.returncode != 0, (
            f"mutation did NOT cause {target_test} to fail; site not "
            f"load-bearing.\nstdout={proc.stdout[-2000:]}\n"
            f"stderr={proc.stderr[-2000:]}"
        )
    finally:
        src_path.write_text(backup)
        pyc_dir = src_path.parent / "__pycache__"
        if pyc_dir.exists():
            for p in pyc_dir.glob(f"{src_path.stem}.*"):
                p.unlink()


def test_mutation_inv_dp3_raw_drain_target_breaks_composition():
    """Mutation (a) — INV-DP3 fit-supremacy: replace the composed
    `max(existing_val, hold_reserve, _dp_soc)` with the raw `_dp_soc`
    when the DP branch fires. Then a scenario where existing > drain
    (test_composed_reserve_floor_never_demotes_below_existing) will
    emit drain_target=15 while the guaranteed floor is 50 → test fails.
    """
    old = (
        "                    if _dp_soc is not None:\n"
        "                        effective = max(\n"
        "                            int(existing_val),\n"
        "                            int(hold_reserve),\n"
        "                            int(_dp_soc),\n"
        "                        )\n"
        "                    else:\n"
        "                        effective = max(int(existing_val), int(hold_reserve))"
    )
    new = (
        "                    if _dp_soc is not None:\n"
        "                        effective = int(_dp_soc)  # MUTATED: raw drain\n"
        "                    else:\n"
        "                        effective = max(int(existing_val), int(hold_reserve))"
    )
    _run_named_test_under_mutation(
        _ENERGY_SRC, old, new,
        "test_composed_reserve_floor_never_demotes_below_existing",
    )


def test_mutation_ownership_dp_swapped_to_battery_drain_breaks_attribution():
    """Mutation (b) — Ownership: swap the `_paused_by_dp.add` in
    `_apply_dp_transition` for `_paused_by_battery_drain.add`. Then
    `test_apply_dp_transition_claims_paused_by_dp` fails because the
    ID lands in the wrong owner set (attribution corruption; would
    cause a battery-drain release path to spuriously clear a DP pause).
    """
    old = 'self._ev._paused_by_dp.add(evse_id)  # noqa: SLF001'
    new = 'self._ev._paused_by_battery_drain.add(evse_id)  # noqa: SLF001'
    _run_named_test_under_mutation(
        _ENERGY_SRC, old, new,
        "test_apply_dp_transition_claims_paused_by_dp",
    )
