"""Sticky-DP yield to excess-solar — acceptance tests.

Cycle: docs/planning/PLANNING_dp_sticky_yields_to_excess_solar.md

Invariants under test:
    INV-YIELD-1 (permissive): HOLD_ONLY + `_paused_by_dp` membership +
        excess conditions ⇒ claimable, always. Atomic ownership handoff.
    INV-YIELD-2 (restrictive, LOAD-BEARING): TRANSITIONED /
        MUST_START_FORCED / HOLD_PRE_EVAL / EVAL_TRANSITION ⇒ NEVER
        released by excess-solar, any config.

Mutation anchors (subprocess-isolated, b2c3 pattern):
    M1 — remove the HOLD_ONLY condition (make yield fire unconditionally
         under any DP state) ⇒ INV-YIELD-2 negative test goes RED.
    M2 — remove the yield entirely (restore flat `_paused_by_dp` skip)
         ⇒ garage-A fixture (INV-YIELD-1 positive) goes RED.
    M3 — break the owner handoff (drop `_paused_by_dp` membership
         without releasing the "dp" owner) ⇒ ownerless-gap test goes RED.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# HA module mocks (setdefault-only — coexists with sibling test files)
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
        "async_track_point_in_time": lambda *a, **k: (lambda: None),
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


from conftest import MockHass  # noqa: E402

from custom_components.universal_room_automation.domain_coordinators.energy_pool import (  # noqa: E402
    EVChargerController,
)
from custom_components.universal_room_automation.domain_coordinators.energy_drain_precedence import (  # noqa: E402
    DPState,
)


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


def _build_ev(hass, second: bool = False) -> EVChargerController:
    evse_cfg = {
        "garage_a": {
            "switch": "switch.garage_a",
            "power": "sensor.garage_a_power",
            "energy_today": "sensor.garage_a_energy_today",
            "energy_month": "sensor.garage_a_energy_month",
        },
    }
    if second:
        evse_cfg["garage_b"] = {
            "switch": "switch.garage_b",
            "power": "sensor.garage_b_power",
            "energy_today": "sensor.garage_b_energy_today",
            "energy_month": "sensor.garage_b_energy_month",
        }
        hass.set_state("switch.garage_b", "off")
        hass.set_state(
            "sensor.garage_b_power", "0",
            attributes={"unit_of_measurement": "W"},
        )
    hass.set_state("switch.garage_a", "off")
    hass.set_state(
        "sensor.garage_a_power", "0",
        attributes={"unit_of_measurement": "W"},
    )
    return EVChargerController(hass, evse_config=evse_cfg)


def _stage_dp_sticky(ev, evse_id: str = "garage_a") -> None:
    """Put an EVSE in the deferred-DP-orphan shape: `_paused_by_dp`
    membership + "dp" dispatch owner, as `_apply_dp_reversion` sticky
    branch leaves it."""
    ev._paused_by_dp.add(evse_id)
    ev._claim_pause_dispatch_owner(evse_id, "dp")


# ==========================================================================
# INV-YIELD-1 positive
# ==========================================================================


def test_INV_YIELD_1_hold_only_orphan_is_claimed_by_excess_solar():
    """HOLD_ONLY orphan + excess conditions ⇒ claimed. Atomic handoff:
    dropped from `_paused_by_dp`, "dp" owner released, added to
    `_excess_solar_active`, switch.turn_on appended."""
    hass = _build_hass()
    ev = _build_ev(hass)
    _stage_dp_sticky(ev, "garage_a")
    actions = ev.determine_excess_solar_actions(
        soc=99.0, remaining_forecast_kwh=10.0, tou_period="mid_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.HOLD_ONLY.value,
    )
    # Atomic ownership handoff
    assert "garage_a" not in ev._paused_by_dp, "dp membership must drop"
    assert "garage_a" in ev._excess_solar_active, "excess claim must add"
    owners = ev._dispatch_owners.get("garage_a", set())
    assert "dp" not in owners, "dp dispatch owner must be released"
    # Dispatch present
    turn_on = [
        a for a in actions
        if a.get("service") == "switch.turn_on"
        and a.get("target") == "switch.garage_a"
    ]
    assert len(turn_on) == 1, f"expected 1 turn_on for garage_a, got {actions}"


def test_INV_YIELD_1_hold_only_orphan_at_off_peak_still_yields():
    """The yield fires whenever conditions hold — off_peak is NOT a
    prerequisite (config-boundary: TOU period edge). Rules out an
    accidental "only mid_peak" implementation."""
    hass = _build_hass()
    ev = _build_ev(hass)
    _stage_dp_sticky(ev, "garage_a")
    actions = ev.determine_excess_solar_actions(
        soc=95.0, remaining_forecast_kwh=5.0, tou_period="off_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.HOLD_ONLY.value,
    )
    assert "garage_a" in ev._excess_solar_active
    assert any(a.get("target") == "switch.garage_a" for a in actions)


# ==========================================================================
# INV-YIELD-2 negative — parametrized across active states + config extremes
# ==========================================================================


def _assert_not_yielded(ev, evse_id: str, actions) -> None:
    assert evse_id in ev._paused_by_dp, (
        f"INV-YIELD-2 breach: {evse_id} lost DP membership"
    )
    assert evse_id not in ev._excess_solar_active
    owners = ev._dispatch_owners.get(evse_id, set())
    assert "dp" in owners, "INV-YIELD-2 breach: dp dispatch owner dropped"
    for a in actions:
        assert a.get("target") != f"switch.{evse_id}"


def test_INV_YIELD_2_transitioned_never_yields():
    hass = _build_hass()
    ev = _build_ev(hass)
    _stage_dp_sticky(ev, "garage_a")
    actions = ev.determine_excess_solar_actions(
        soc=100.0, remaining_forecast_kwh=50.0, tou_period="mid_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.TRANSITIONED.value,
    )
    _assert_not_yielded(ev, "garage_a", actions)


def test_INV_YIELD_2_must_start_forced_never_yields():
    hass = _build_hass()
    ev = _build_ev(hass)
    _stage_dp_sticky(ev, "garage_a")
    actions = ev.determine_excess_solar_actions(
        soc=100.0, remaining_forecast_kwh=50.0, tou_period="off_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.MUST_START_FORCED.value,
    )
    _assert_not_yielded(ev, "garage_a", actions)


def test_INV_YIELD_2_transitioned_at_excess_soc_edge_still_no_yield():
    """Config-boundary: soc = threshold (inclusive), remaining = threshold
    (inclusive) — excess conditions technically met, TRANSITIONED still
    protects."""
    hass = _build_hass()
    ev = _build_ev(hass)
    _stage_dp_sticky(ev, "garage_a")
    actions = ev.determine_excess_solar_actions(
        soc=95.0, remaining_forecast_kwh=5.0, tou_period="mid_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.TRANSITIONED.value,
    )
    _assert_not_yielded(ev, "garage_a", actions)


def test_INV_YIELD_2_transitioned_at_forecast_edge_still_no_yield():
    """Config-boundary: forecast just BELOW threshold — but the guard
    only cares about DP state (conditions_met false ⇒ no claim path
    reached at all, but membership stays)."""
    hass = _build_hass()
    ev = _build_ev(hass)
    _stage_dp_sticky(ev, "garage_a")
    actions = ev.determine_excess_solar_actions(
        soc=94.0, remaining_forecast_kwh=4.9, tou_period="mid_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.TRANSITIONED.value,
    )
    _assert_not_yielded(ev, "garage_a", actions)


def test_INV_YIELD_2_default_none_state_never_yields():
    """Defensive: when caller cannot supply DP state (dp_carrier_state=None,
    the default), the yield must NOT fire. Backward compatibility with
    the pre-cycle test in b2b-ii item 5."""
    hass = _build_hass()
    ev = _build_ev(hass)
    _stage_dp_sticky(ev, "garage_a")
    actions = ev.determine_excess_solar_actions(
        soc=99.0, remaining_forecast_kwh=10.0, tou_period="off_peak",
        soc_threshold=95, kwh_threshold=5.0,
    )
    _assert_not_yielded(ev, "garage_a", actions)


# ==========================================================================
# Peer safety owners strictly outrank yield
# ==========================================================================


def test_stronger_peer_owners_outrank_hold_only_yield():
    """HOLD_ONLY yield conditions true BUT EVSE also in a stronger peer
    set (grid_cap / drain / fill_priority / arbitrage / load_shed) ⇒
    strictly-stronger skip fires FIRST; no yield, no membership mutation
    on `_paused_by_dp`."""
    for stronger in (
        "_paused_by_grid_cap",
        "_paused_by_battery_drain",
        "_paused_by_fill_priority",
        "_paused_by_arbitrage",
        "_paused_by_load_shed",
    ):
        hass = _build_hass()
        ev = _build_ev(hass)
        _stage_dp_sticky(ev, "garage_a")
        getattr(ev, stronger).add("garage_a")
        actions = ev.determine_excess_solar_actions(
            soc=99.0, remaining_forecast_kwh=10.0, tou_period="mid_peak",
            soc_threshold=95, kwh_threshold=5.0,
            dp_carrier_state=DPState.HOLD_ONLY.value,
        )
        assert "garage_a" in ev._paused_by_dp, stronger
        assert "garage_a" not in ev._excess_solar_active, stronger
        assert not any(
            a.get("target") == "switch.garage_a" for a in actions
        ), stronger


# ==========================================================================
# Garage-A day fixture (motivating 2026-07-20 shape)
# ==========================================================================


def test_garage_a_day_fixture_sticky_all_day_battery_full_forecast_healthy():
    """Replay of the planning-doc fixture (garage-A day 2026-07-20):
    garage A sticky in `_paused_by_dp` all day post-transition, battery
    at 100, forecast healthy, TOU=mid_peak → yield fires, car charges."""
    hass = _build_hass()
    ev = _build_ev(hass, second=True)
    _stage_dp_sticky(ev, "garage_a")
    # Garage B not in DP set — the "diverges only by plug-in timing"
    # peer from the motivating fixture. Both cars end up claimed.
    actions = ev.determine_excess_solar_actions(
        soc=100.0, remaining_forecast_kwh=20.0, tou_period="mid_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.HOLD_ONLY.value,
    )
    assert "garage_a" in ev._excess_solar_active
    assert "garage_b" in ev._excess_solar_active
    turn_on_targets = {
        a["target"] for a in actions if a.get("service") == "switch.turn_on"
    }
    assert "switch.garage_a" in turn_on_targets
    assert "switch.garage_b" in turn_on_targets
    # pause_reason_human derivation is set-membership driven
    # (`energy_pool.py::_classify_evse`, closed over ev's sets in
    # `evse_pause_reason_status`): after yield garage_a is in
    # `_excess_solar_active` and NOT in `_paused_by_dp`, so the
    # classifier will return the `excess_solar` branch. Membership
    # asserts above prove that condition.
    assert "garage_a" in ev._excess_solar_active
    assert "garage_a" not in ev._paused_by_dp


# ==========================================================================
# No-yield-when-excess-conditions-absent (plain sticky defer preserved)
# ==========================================================================


def test_plain_sticky_defer_preserved_when_excess_conditions_absent():
    """SOC below threshold ⇒ conditions_met false ⇒ no claim path
    reached; garage_a stays in `_paused_by_dp` awaiting the next
    off_peak reversion. HOLD_ONLY does not force a yield without
    conditions."""
    hass = _build_hass()
    ev = _build_ev(hass)
    _stage_dp_sticky(ev, "garage_a")
    actions = ev.determine_excess_solar_actions(
        soc=80.0, remaining_forecast_kwh=10.0, tou_period="mid_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.HOLD_ONLY.value,
    )
    assert "garage_a" in ev._paused_by_dp
    assert "garage_a" not in ev._excess_solar_active
    assert not any(a.get("target") == "switch.garage_a" for a in actions)


# ==========================================================================
# Restart-after-yield (no DP resurrection from persisted blob)
# ==========================================================================


def test_restart_after_yield_no_dp_resurrection_from_persisted_blob():
    """Mid-yield, the KV blob for `_paused_by_dp` MUST reflect the
    dropped membership (garage_a moved out). Simulate the persist +
    restore round-trip: yield mutates the set → the set the persistence
    layer writes must NOT contain garage_a → post-restart the HOLD_ONLY
    orphan retry driver at energy.py sees an empty set and does not
    re-add it."""
    hass = _build_hass()
    ev = _build_ev(hass)
    _stage_dp_sticky(ev, "garage_a")
    ev.determine_excess_solar_actions(
        soc=99.0, remaining_forecast_kwh=10.0, tou_period="mid_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.HOLD_ONLY.value,
    )
    # Persist-time snapshot: what the KV write would see.
    persisted_dp_set = list(ev._paused_by_dp)
    persisted_excess = list(ev._excess_solar_active)
    assert "garage_a" not in persisted_dp_set, (
        "restart safety: KV must not persist garage_a as DP-paused"
    )
    assert "garage_a" in persisted_excess, (
        "restart safety: KV must persist garage_a as excess-solar-active"
    )

    # Simulate a fresh boot: build a new controller, restore the
    # persisted membership shape.
    hass2 = _build_hass()
    ev2 = _build_ev(hass2)
    for eid in persisted_dp_set:
        ev2._paused_by_dp.add(eid)
    for eid in persisted_excess:
        ev2._excess_solar_active.add(eid)
    # Post-restart excess-solar tick (conditions still hold, HOLD_ONLY
    # because the DP transition already completed pre-yield).
    hass2.set_state("switch.garage_a", "on")
    actions2 = ev2.determine_excess_solar_actions(
        soc=99.0, remaining_forecast_kwh=10.0, tou_period="mid_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.HOLD_ONLY.value,
    )
    # garage_a is still claimed, still NOT in _paused_by_dp.
    assert "garage_a" in ev2._excess_solar_active
    assert "garage_a" not in ev2._paused_by_dp
    # No duplicate turn_on (already on).
    turn_ons = [
        a for a in actions2
        if a.get("service") == "switch.turn_on"
        and a.get("target") == "switch.garage_a"
    ]
    assert turn_ons == []


def test_restart_after_yield_conditions_gone_cleanly_releases():
    """Mid-yield restart WITH excess conditions no longer holding ⇒
    existing off-conditions branch turns off + discards from
    `_excess_solar_active`. DP does NOT re-claim (HOLD_ONLY)."""
    hass = _build_hass()
    ev = _build_ev(hass)
    ev._excess_solar_active.add("garage_a")
    hass.set_state("switch.garage_a", "on")
    actions = ev.determine_excess_solar_actions(
        soc=80.0, remaining_forecast_kwh=1.0, tou_period="mid_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.HOLD_ONLY.value,
    )
    assert "garage_a" not in ev._excess_solar_active
    assert "garage_a" not in ev._paused_by_dp
    assert any(
        a.get("service") == "switch.turn_off"
        and a.get("target") == "switch.garage_a"
        for a in actions
    )


# ==========================================================================
# Ownerless-gap regression guard
# ==========================================================================


def test_atomic_handoff_no_ownerless_gap():
    """The four-step handoff (discard _paused_by_dp, release "dp"
    dispatch owner, add _excess_solar_active, append turn_on) happens
    synchronously. At function exit, garage_a has EITHER "dp" ownership
    (before yield) OR excess_solar_active membership (after yield) —
    never neither. This anchors mutation M3."""
    hass = _build_hass()
    ev = _build_ev(hass)
    _stage_dp_sticky(ev, "garage_a")
    ev.determine_excess_solar_actions(
        soc=99.0, remaining_forecast_kwh=10.0, tou_period="mid_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.HOLD_ONLY.value,
    )
    owners = ev._dispatch_owners.get("garage_a", set())
    in_dp = "garage_a" in ev._paused_by_dp
    in_excess = "garage_a" in ev._excess_solar_active
    # Exactly one of (dp owner) or (excess claim) — never zero.
    has_owner_or_claim = ("dp" in owners) or in_excess or in_dp
    assert has_owner_or_claim, (
        "ownerless gap: garage_a is neither DP-owned nor excess-claimed"
    )
    # Post-yield specifically: excess-claim exists and "dp" owner gone.
    assert in_excess
    assert "dp" not in owners


# ==========================================================================
# Mutation anchors (subprocess-isolated — real production source edits)
# ==========================================================================


_HERE = os.path.dirname(os.path.abspath(__file__))
_POOL_SRC = Path(_dc_path) / "energy_pool.py"


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _clear_pycache():
    for root, dirs, _ in os.walk(_dc_path):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)


def _run_test_in_subprocess(test_name: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.abspath(os.path.join(_HERE, ".."))
    return subprocess.run(
        [
            sys.executable, "-m", "pytest",
            f"{os.path.abspath(__file__)}::{test_name}",
            "-x", "--tb=short", "-q",
        ],
        env=env,
        capture_output=True, text=True,
        cwd=os.path.abspath(os.path.join(_HERE, "..", "..")),
    )


def _mutate_and_expect_red(swap_from: str, swap_to: str, test_name: str):
    src_path = _POOL_SRC
    original = src_path.read_text(encoding="utf-8")
    assert swap_from in original, f"anchor missing: {swap_from!r}"
    mutated = original.replace(swap_from, swap_to, 1)
    assert mutated != original, "mutation was a no-op"
    src_path.write_text(mutated, encoding="utf-8")
    _md5_after = _md5(src_path)
    try:
        _clear_pycache()
        result = _run_test_in_subprocess(test_name)
        assert result.returncode != 0, (
            f"expected {test_name} to FAIL under mutation; got returncode="
            f"{result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    finally:
        src_path.write_text(original, encoding="utf-8")
        _clear_pycache()
        assert _md5(src_path) != _md5_after
        assert src_path.read_text(encoding="utf-8") == original


def test_MUTATION_M1_remove_hold_only_condition_makes_INV_YIELD_2_red():
    """M1: relax the HOLD_ONLY condition (make yield fire under any DP
    state). The TRANSITIONED negative test MUST go RED — the guard is
    the load-bearing INV-YIELD-2 protection."""
    _mutate_and_expect_red(
        swap_from=(
            '_dp_yield_ok = (\n'
            '                    evse_id in self._paused_by_dp\n'
            '                    and dp_carrier_state == "hold_only"\n'
            '                )'
        ),
        swap_to=(
            '_dp_yield_ok = (\n'
            '                    evse_id in self._paused_by_dp\n'
            '                )'
        ),
        test_name="test_INV_YIELD_2_transitioned_never_yields",
    )


def test_MUTATION_M2_remove_yield_entirely_makes_garage_a_fixture_red():
    """M2: restore the flat `_paused_by_dp` skip (kill the yield). The
    garage-A day fixture MUST go RED — garage_a stays skipped and no
    turn_on fires for it."""
    _mutate_and_expect_red(
        swap_from=(
            '_dp_yield_ok = (\n'
            '                    evse_id in self._paused_by_dp\n'
            '                    and dp_carrier_state == "hold_only"\n'
            '                )\n'
            '                if evse_id in self._paused_by_dp and not _dp_yield_ok:'
        ),
        swap_to=(
            '_dp_yield_ok = False\n'
            '                if evse_id in self._paused_by_dp:'
        ),
        test_name="test_garage_a_day_fixture_sticky_all_day_battery_full_forecast_healthy",
    )


# ==========================================================================
# Fix-up: A-HIGH-1 orphan reserve-floor collapse + timer cancel
# ==========================================================================


def _bind_holder(hass, ev):
    """Bind post-yield/reconcile helpers from the REAL EnergyCoordinator
    source to a SimpleNamespace holder (pattern mirrors
    `_bind_persistence_methods` in test_ev_offpeak_proactive.py). Lets
    us drive the tested block against the actual production method
    without constructing the full coordinator."""
    from custom_components.universal_room_automation.domain_coordinators import (
        energy as _energy_mod,
    )
    holder = types.SimpleNamespace(
        hass=hass,
        _ev=ev,
        _dp_decision_soc=None,
        _dp_must_start_unsub=None,
        _dp_carrier=types.SimpleNamespace(
            state=types.SimpleNamespace(value="hold_only"),
        ),
    )

    async def _save_stub():
        return None
    holder._save_evse_state = _save_stub
    holder._post_excess_solar_bookkeeping = (
        _energy_mod.EnergyCoordinator._post_excess_solar_bookkeeping.__get__(
            holder, type(holder),
        )
    )
    holder._cancel_dp_must_start_by_timer = (
        _energy_mod.EnergyCoordinator._cancel_dp_must_start_by_timer.__get__(
            holder, type(holder),
        )
    )
    holder._reconcile_dp_excess_on_restore = (
        _energy_mod.EnergyCoordinator._reconcile_dp_excess_on_restore.__get__(
            holder, type(holder),
        )
    )
    return holder


def test_AHIGH1_yield_last_dp_member_clears_decision_soc_and_cancels_timer():
    """A-HIGH-1: when the yield DRAINS `_paused_by_dp` (last member
    claimed by excess-solar), the composed DP floor
    `_dp_decision_soc` MUST be cleared and any armed must-start-by
    timer MUST be cancelled. Otherwise the reserve floor pins into
    evening peak (money loss)."""
    hass = _build_hass()
    ev = _build_ev(hass)
    _stage_dp_sticky(ev, "garage_a")
    holder = _bind_holder(hass, ev)
    holder._dp_decision_soc = 40  # simulated stamped drain target
    _timer_cancelled = {"n": 0}

    def _unsub():
        _timer_cancelled["n"] += 1
    holder._dp_must_start_unsub = _unsub

    pre_dp_set = set(ev._paused_by_dp)
    ev.determine_excess_solar_actions(
        soc=99.0, remaining_forecast_kwh=10.0, tou_period="mid_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.HOLD_ONLY.value,
    )
    holder._post_excess_solar_bookkeeping(pre_dp_set)

    assert holder._dp_decision_soc is None, (
        "A-HIGH-1: orphan reserve floor left stamped"
    )
    assert _timer_cancelled["n"] == 1, (
        "A-HIGH-1: must-start-by timer not cancelled"
    )
    assert holder._dp_must_start_unsub is None


def test_AHIGH1_yield_non_empty_dp_set_leaves_decision_soc_intact():
    """Sibling assertion: if the yield claims ONE of two DP members
    (set still non-empty post-yield), the composed floor MUST stay
    stamped — INV-DP3 max()-composition still needs it for the
    remaining sticky member."""
    hass = _build_hass()
    ev = _build_ev(hass, second=True)
    _stage_dp_sticky(ev, "garage_a")
    _stage_dp_sticky(ev, "garage_b")
    holder = _bind_holder(hass, ev)
    holder._dp_decision_soc = 40

    pre_dp_set = set(ev._paused_by_dp)
    ev.determine_excess_solar_actions(
        soc=99.0, remaining_forecast_kwh=10.0, tou_period="mid_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.HOLD_ONLY.value,
    )
    holder._post_excess_solar_bookkeeping(pre_dp_set)

    # Both garages yielded — set is now empty → collapse fires.
    # (verified in AHIGH1 above). Here we assert the NEGATIVE control:
    # if we manually re-add one back BEFORE bookkeeping, the collapse
    # must NOT fire.
    hass2 = _build_hass()
    ev2 = _build_ev(hass2, second=True)
    _stage_dp_sticky(ev2, "garage_a")
    _stage_dp_sticky(ev2, "garage_b")
    holder2 = _bind_holder(hass2, ev2)
    holder2._dp_decision_soc = 40
    pre2 = set(ev2._paused_by_dp)
    # Yield only garage_a by pinning garage_b behind a stronger owner.
    ev2._paused_by_grid_cap.add("garage_b")
    ev2.determine_excess_solar_actions(
        soc=99.0, remaining_forecast_kwh=10.0, tou_period="mid_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.HOLD_ONLY.value,
    )
    holder2._post_excess_solar_bookkeeping(pre2)
    assert "garage_b" in ev2._paused_by_dp
    assert holder2._dp_decision_soc == 40, (
        "reserve floor collapsed while sticky member remained"
    )


# ==========================================================================
# Fix-up: B-M1 restore-reconcile for torn mid-yield restart shapes
# ==========================================================================


def test_BM1_restore_reconcile_dponly_orphan_hold_only_commands_turn_off():
    """B-M1 shape (2): DP-only orphan + HOLD_ONLY + physically ON ⇒
    reconciler commands switch OFF to honor DP-pause intent (torn
    restart resurrected DP membership but excess claim didn't survive
    the flush; peak arrives and only `_excess_solar_active` members
    get turned off → car sails through peak without this fix)."""
    hass = _build_hass()
    ev = _build_ev(hass)
    # Simulate the resurrected DP membership without excess claim.
    ev._paused_by_dp.add("garage_a")
    ev._claim_pause_dispatch_owner("garage_a", "dp")
    hass.set_state("switch.garage_a", "on")
    holder = _bind_holder(hass, ev)  # dp_carrier.state.value = hold_only
    _turn_off_calls = {"n": 0}

    async def _svc(domain, service, data, blocking=False):
        if service == "turn_off" and data.get("entity_id") == "switch.garage_a":
            _turn_off_calls["n"] += 1
    hass.services.async_call = _svc

    holder._reconcile_dp_excess_on_restore()
    assert _turn_off_calls["n"] == 1, (
        "B-M1: DP-only HOLD_ONLY orphan not commanded off"
    )


def test_BM1_restore_reconcile_double_membership_excess_wins():
    """B-M1 shape (1): torn double-membership (id in both
    `_paused_by_dp` AND `_excess_solar_active`) ⇒ excess wins, DP
    membership + owner dropped."""
    hass = _build_hass()
    ev = _build_ev(hass)
    ev._paused_by_dp.add("garage_a")
    ev._claim_pause_dispatch_owner("garage_a", "dp")
    ev._excess_solar_active.add("garage_a")
    hass.set_state("switch.garage_a", "on")
    holder = _bind_holder(hass, ev)

    holder._reconcile_dp_excess_on_restore()
    assert "garage_a" not in ev._paused_by_dp
    assert "garage_a" in ev._excess_solar_active
    owners = ev._dispatch_owners.get("garage_a", set())
    assert "dp" not in owners


def test_BM1_restore_reconcile_transitioned_dp_left_alone():
    """B-M1 restraint: TRANSITIONED post-restore is NOT the reconciler's
    territory — the sticky retry driver + must-start-by timer handle
    that. Reconciler only acts under HOLD_ONLY."""
    hass = _build_hass()
    ev = _build_ev(hass)
    ev._paused_by_dp.add("garage_a")
    ev._claim_pause_dispatch_owner("garage_a", "dp")
    hass.set_state("switch.garage_a", "on")
    holder = _bind_holder(hass, ev)
    holder._dp_carrier.state.value = "transitioned"
    _turn_off_calls = {"n": 0}

    async def _svc(domain, service, data, blocking=False):
        if service == "turn_off":
            _turn_off_calls["n"] += 1
    hass.services.async_call = _svc

    holder._reconcile_dp_excess_on_restore()
    assert _turn_off_calls["n"] == 0
    assert "garage_a" in ev._paused_by_dp


# ==========================================================================
# Fix-up: C-b5 already-on yield branch + C-b7 persistence authority
# ==========================================================================


def test_Cb5_already_on_yield_branch_claims_from_dp_without_new_turn_on():
    """C-b5: sticky DP + HOLD_ONLY + switch ALREADY ON ⇒ ownership
    handed to excess (added to `_excess_solar_active`, dropped from
    `_paused_by_dp`, "dp" owner released), NO turn_on dispatched."""
    hass = _build_hass()
    ev = _build_ev(hass)
    _stage_dp_sticky(ev, "garage_a")
    hass.set_state("switch.garage_a", "on")  # already ON pre-tick
    actions = ev.determine_excess_solar_actions(
        soc=99.0, remaining_forecast_kwh=10.0, tou_period="mid_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.HOLD_ONLY.value,
    )
    assert "garage_a" in ev._excess_solar_active
    assert "garage_a" not in ev._paused_by_dp
    assert "dp" not in ev._dispatch_owners.get("garage_a", set())
    turn_ons = [
        a for a in actions
        if a.get("service") == "switch.turn_on"
        and a.get("target") == "switch.garage_a"
    ]
    assert turn_ons == [], (
        f"C-b5: unexpected turn_on for already-on switch: {actions}"
    )


def test_Cb7_yielding_tick_schedules_save_evse_state():
    """C-b7: post-yield bookkeeping MUST schedule `_save_evse_state`
    when the DP set was mutated. Persist authority — a yield that
    isn't flushed cannot survive a restart."""
    hass = _build_hass()
    ev = _build_ev(hass)
    _stage_dp_sticky(ev, "garage_a")
    holder = _bind_holder(hass, ev)
    _save_calls = {"n": 0}

    async def _save_stub():
        _save_calls["n"] += 1
    holder._save_evse_state = _save_stub

    pre = set(ev._paused_by_dp)
    ev.determine_excess_solar_actions(
        soc=99.0, remaining_forecast_kwh=10.0, tou_period="mid_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.HOLD_ONLY.value,
    )
    holder._post_excess_solar_bookkeeping(pre)
    assert _save_calls["n"] == 1


def test_Cb7_non_yielding_tick_does_not_schedule_save():
    """C-b7: non-yielding tick (DP set unchanged) MUST NOT schedule a
    save — avoid write-queue amplification from every excess-solar
    tick."""
    hass = _build_hass()
    ev = _build_ev(hass)
    # No DP membership at all — nothing to yield, set unchanged.
    holder = _bind_holder(hass, ev)
    _save_calls = {"n": 0}

    async def _save_stub():
        _save_calls["n"] += 1
    holder._save_evse_state = _save_stub

    pre = set(ev._paused_by_dp)
    ev.determine_excess_solar_actions(
        soc=99.0, remaining_forecast_kwh=10.0, tou_period="mid_peak",
        soc_threshold=95, kwh_threshold=5.0,
        dp_carrier_state=DPState.HOLD_ONLY.value,
    )
    holder._post_excess_solar_bookkeeping(pre)
    assert _save_calls["n"] == 0


# ==========================================================================
# Fix-up: C-b8 shared strong-peer helper mutation authority
# ==========================================================================


def test_Cb8_stronger_peer_helper_covers_five_owners():
    """C-b8: `_stronger_peer_holds` returns True for any of the five
    peer sets (drain, fill_priority, grid_cap, arbitrage, load_shed),
    False otherwise. DP is INTENTIONALLY excluded."""
    hass = _build_hass()
    ev = _build_ev(hass)
    assert ev._stronger_peer_holds("garage_a") is False
    ev._paused_by_dp.add("garage_a")
    assert ev._stronger_peer_holds("garage_a") is False, (
        "DP must be excluded from the shared helper (yield-conditional)"
    )
    for peer in (
        "_paused_by_battery_drain",
        "_paused_by_fill_priority",
        "_paused_by_grid_cap",
        "_paused_by_arbitrage",
        "_paused_by_load_shed",
    ):
        hass2 = _build_hass()
        ev2 = _build_ev(hass2)
        getattr(ev2, peer).add("garage_a")
        assert ev2._stronger_peer_holds("garage_a") is True, peer


def test_MUTATION_M4_remove_orphan_floor_clear_makes_AHIGH1_red():
    """M4 (A-HIGH-1 anchor): drop the `_dp_decision_soc = None` clear
    from the post-yield bookkeeping ⇒ the AHIGH1 test goes RED."""
    _POOL_SRC_ENERGY = Path(_dc_path) / "energy.py"
    original = _POOL_SRC_ENERGY.read_text(encoding="utf-8")
    swap_from = (
        "if not self._ev._paused_by_dp:  # noqa: SLF001\n"
        "                self._dp_decision_soc = None\n"
        "                self._cancel_dp_must_start_by_timer()"
    )
    swap_to = (
        "if not self._ev._paused_by_dp:  # noqa: SLF001\n"
        "                pass"
    )
    assert swap_from in original, "M4 anchor missing"
    mutated = original.replace(swap_from, swap_to, 1)
    _POOL_SRC_ENERGY.write_text(mutated, encoding="utf-8")
    try:
        _clear_pycache()
        result = _run_test_in_subprocess(
            "test_AHIGH1_yield_last_dp_member_clears_decision_soc_and_cancels_timer"
        )
        assert result.returncode != 0, (
            f"expected test to fail under M4 mutation; got "
            f"returncode={result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    finally:
        _POOL_SRC_ENERGY.write_text(original, encoding="utf-8")
        _clear_pycache()


def test_MUTATION_M3_break_owner_handoff_makes_ownerless_gap_test_red():
    """M3: drop `_paused_by_dp` membership WITHOUT releasing the "dp"
    dispatch owner. The ownerless-gap test asserts "dp" is gone
    post-yield — under the mutation the "dp" owner survives → RED."""
    _mutate_and_expect_red(
        swap_from=(
            'if _yielded_from_dp:\n'
            '                    self._paused_by_dp.discard(evse_id)\n'
            '                    self._release_pause_dispatch_owner(evse_id, "dp")'
        ),
        swap_to=(
            'if _yielded_from_dp:\n'
            '                    self._paused_by_dp.discard(evse_id)'
        ),
        test_name="test_atomic_handoff_no_ownerless_gap",
    )
