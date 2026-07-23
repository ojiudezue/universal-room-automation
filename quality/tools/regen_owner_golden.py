"""Regenerate the owner-registry golden capture.

Phase 1 of the owner-set registry refactor (see
`docs/planning/PLANNING_owner_set_registry_refactor.md`).

Purpose
-------
Drive the CURRENT (pre-refactor) `EVChargerController` and
`SmartPlugController` through a stratified tuple space and capture, per
tuple, the five byte-identical output surfaces the invariant in §0
guarantees:

    (a) emitted action list from `determine_actions(...)`
    (b) post-tick owner-set memberships (all owner sets, both tiers)
    (c) `_save_evse_state` KV payload (JSON-normalized, key-sorted) —
        replicated in-harness (mirrors the exact key set + JSON shape
        the coordinator would write via the DB; no DB required)
    (d) `get_status()` owner slice — `pause_reason_human` +
        `energy_status` per EVSE / plug
    (e) dispatch-ownership bookkeeping — `_dispatch_owners` map +
        `_pause_dispatch_ts` liveness (bool present/absent, timestamp
        NOT emitted — the harness pins monotonic anchor)

Determinism discipline (planning-doc hygiene section)
-----------------------------------------------------
* Wall-clock is pinned via monkeypatch on `homeassistant.util.dt.now`
  and `homeassistant.util.dt.utcnow` in the harness for the duration of
  the sweep. All timestamps derived from these calls are constant.
* `time.monotonic()` is pinned to a fixed value.
* All emitted JSON is `sort_keys=True`, and every set is materialized
  as a sorted list before serialization.
* No RNG is consulted; the tuple space is fully enumerated.

Reduction from the plan's §4a ~64k tuple space (documented, honest)
--------------------------------------------------------------------
The plan speculated ~64k tuples via 40 reachable owner classes × 2 tiers
× 5 TOU × 7 SOC × 23 events. Two reductions were made for phase 1, both
recorded in the header of the generated capture so reviewers see them:

1. **Event space collapsed from 23 to a small tick-family set.** The 23
   listed events are not equally reachable via `determine_actions`
   alone — many (blind_window_enter, dp_transition, load_shed_activate,
   fill_priority_engage, ...) are external mutations from sibling
   coordinators that write to the owner sets directly. For phase 1 we
   encode those as **seeded initial state**: the owner-class dimension
   already covers "device is currently in `_paused_by_dp`" etc., which
   is exactly the state those events produce. The tick-family we DO
   drive through `determine_actions` is:
     {tick_no_grid, tick_grid_on, tick_force_charge_active}
   Plus a stateless `save_snapshot` capture and a `prune_removed_evse`
   capture. This covers surfaces (a)-(e) for every seeded state, and
   captures the shape produced by every external-event owner
   membership as its own seed row. Phase 2's migration surfaces
   (persist/restore/prune/peer-holds/classifier) are ALL covered.

2. **Owner-class enumeration is stratified to 24 classes per tier**,
   not a full ~40 combinatorial reach. The 24 include: empty, each
   single owner, common two-owner peers (drain+TOU, blind+TOU,
   fill+TOU, arb-redirect+TOU, arb-breaker+TOU, dp+TOU, blind+drain,
   blind+liveness_ride, grid_cap+drain, load_shed+TOU, force_charge
   active, proactive_offpeak intent + TOU, excess_solar +
   proactive_offpeak, drain+cooldown_active, blind_epoch_pre_engaged).
   Plug tier gets 10 (empty, each single owner, TOU+drain, TOU+fill,
   TOU+load_shed, TOU+proactive, proactive+drain).

Actual generated tuple size: printed in the header and returned by
`generate()`. Empirically ~7-10k tuples.
"""
from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

# Allow running as `python quality/tools/regen_owner_golden.py` — mirrors
# the sys.path layering the pytest suite uses (via PYTHONPATH=quality).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "quality" / "tests"))

# The energy modules require the bootstrap HA stubs used by the real
# test suite. Import + invoke before touching energy_pool.
from _energy_bootstrap import bootstrap_energy_imports  # noqa: E402
bootstrap_energy_imports()

# ---------------------------------------------------------------------------
# Pinned time anchors (determinism)
# ---------------------------------------------------------------------------
PINNED_UTC = datetime(2026, 7, 23, 12, 0, 0, tzinfo=timezone.utc)
PINNED_MONO = 1_000_000.0
GOLDEN_SCHEMA_VERSION = 2

# v2 extension (phase 1b, 2026-07-23) — merged EV+plug get_status coverage.
# Closes anomaly #3 from the phase-1 report: `EVChargerController.get_status`
# merges plug-tier `paused_by_energy` / `paused_by_battery_drain` /
# `paused_by_fill_priority` lists into its own returns when the caller
# passes `plug_status=SmartPlugController.get_status()` (energy_pool.py
# :2456-2470). This shared-keyspace surface is what dashboards + the
# EV charging-status sensor read; phase 2's registry must preserve it
# byte-identically. v2 adds a merged-status sweep in addition to the
# v1 standalone captures — v1 rows are re-emitted unchanged.
MERGED_TOU_PERIODS = ("off_peak", "mid_peak", "peak")


def _pin_time(monkeypatch_ctx) -> None:
    """Freeze dt_util.now/utcnow + time.monotonic for capture determinism."""
    from homeassistant.util import dt as dt_util

    monkeypatch_ctx.setattr(dt_util, "now", lambda: PINNED_UTC)
    monkeypatch_ctx.setattr(dt_util, "utcnow", lambda: PINNED_UTC)
    # energy_pool imports `time as _time` at module top and calls
    # `_time.monotonic()`.
    import custom_components.universal_room_automation.domain_coordinators.energy_pool as _ep

    monkeypatch_ctx.setattr(_ep._time, "monotonic", lambda: PINNED_MONO)


# ---------------------------------------------------------------------------
# Minimal fake hass — returns caller-injected switch states
# ---------------------------------------------------------------------------
class _FakeState:
    def __init__(self, state: str, attributes: dict[str, Any] | None = None) -> None:
        self.state = state
        self.attributes = attributes or {}


class _FakeHass:
    def __init__(self, states: dict[str, _FakeState]) -> None:
        self._states = states
        self.states = SimpleNamespace(get=self._states.get)
        self.data = {}
        self.config_entries = MagicMock()


# ---------------------------------------------------------------------------
# Minimal fake coord for the blind-window guard predicate
# ---------------------------------------------------------------------------
class _FakeCoord:
    """Duck-types the two guard predicates the pool consults.

    Guard-inactive default: `blind_hold_active=False` disables the
    engagement path; when a fixture seeds `_paused_by_blind_window`
    membership we still exercise the classifier/save/peer surfaces
    but leave the debounce/entry engagement path inert.
    """

    def __init__(
        self,
        blind_hold_active: bool = False,
        reserve_write_verifiable: bool = True,
    ) -> None:
        self._blind = blind_hold_active
        self._verif = reserve_write_verifiable

    def blind_hold_active_snapshot(self) -> bool:
        return self._blind

    @property
    def blind_hold_active(self) -> bool:
        return self._blind

    def reserve_write_verifiable(self) -> bool:
        return self._verif


# ---------------------------------------------------------------------------
# Owner-class enumeration (stratified per §4a reduction)
# ---------------------------------------------------------------------------
EVSE_IDS = ("garage_a", "garage_b")
PLUG_IDS = ("switch.plug_alpha", "switch.plug_beta")
TOU_PERIODS = ("off_peak", "mid_peak", "peak", "super_peak", "unknown")
SOC_BUCKETS = (0, 15, 40, 55, 75, 90, 100)


def _evse_owner_classes() -> list[dict[str, Any]]:
    """Stratified reachable owner combinations for the EV pool tier.

    Each entry is a dict of {owner_set_name: [evse_ids]} plus optional
    side-map / scalar seeds. Two EVSEs allow "one held, one not" mixes.
    """
    classes: list[dict[str, Any]] = []
    a, b = EVSE_IDS

    def C(name: str, **kw: Any) -> dict[str, Any]:
        base = {"__name__": name}
        base.update(kw)
        return base

    classes.append(C("empty"))
    classes.append(C("tou_only_a", _paused_by_us=[a]))
    classes.append(C("tou_both", _paused_by_us=[a, b]))
    classes.append(C("drain_only_a", _paused_by_battery_drain=[a]))
    classes.append(C(
        "drain_plus_tou",
        _paused_by_battery_drain=[a],
        _paused_by_us=[b],
    ))
    classes.append(C("grid_cap_a", _paused_by_grid_cap=[a]))
    classes.append(C(
        "grid_cap_plus_drain",
        _paused_by_grid_cap=[a],
        _paused_by_battery_drain=[b],
    ))
    classes.append(C("fill_priority_a", _paused_by_fill_priority=[a]))
    classes.append(C(
        "fill_plus_tou",
        _paused_by_fill_priority=[a],
        _paused_by_us=[b],
    ))
    classes.append(C(
        "arbitrage_redirect_a",
        _paused_by_arbitrage=[a],
        _arbitrage_pause_reason={a: "redirect"},
    ))
    classes.append(C(
        "arbitrage_breaker_a",
        _paused_by_arbitrage=[a],
        _arbitrage_pause_reason={a: "breaker"},
    ))
    classes.append(C(
        "arbitrage_breaker_plus_tou",
        _paused_by_arbitrage=[a],
        _arbitrage_pause_reason={a: "breaker"},
        _paused_by_us=[b],
    ))
    classes.append(C("dp_only_a", _paused_by_dp=[a]))
    classes.append(C(
        "dp_plus_tou",
        _paused_by_dp=[a],
        _paused_by_us=[b],
    ))
    classes.append(C("load_shed_a", _paused_by_load_shed=[a],
                     _load_shed_was_on_at_shed={a: True}))
    classes.append(C(
        "load_shed_plus_tou",
        _paused_by_load_shed=[a],
        _load_shed_was_on_at_shed={a: True},
        _paused_by_us=[b],
    ))
    classes.append(C(
        "excess_solar_a",
        _excess_solar_active=[a],
    ))
    classes.append(C(
        "excess_solar_plus_proactive",
        _excess_solar_active=[a],
        _proactive_offpeak_holds=[a],
    ))
    classes.append(C("proactive_offpeak_a", _proactive_offpeak_holds=[a]))
    classes.append(C(
        "blind_window_a",
        _paused_by_blind_window=[a],
        _blind_window_epoch_started_at=PINNED_UTC,
    ))
    classes.append(C(
        "blind_window_plus_liveness_ride",
        _paused_by_blind_window=[a],
        _blind_window_liveness_ride=[a],
        _blind_window_epoch_started_at=PINNED_UTC,
    ))
    classes.append(C(
        "blind_window_pre_engaged",
        _paused_by_blind_window=[a],
        _blind_window_pre_engaged=True,
        _blind_window_epoch_started_at=PINNED_UTC,
    ))
    classes.append(C(
        "drain_cooldown_active_a",
        _battery_drain_cooldown={a: PINNED_MONO + 300.0},
    ))
    classes.append(C(
        "force_charge_active",
        _force_charge_until=PINNED_UTC.replace(
            hour=13,
        ),  # +1h from PINNED — active
    ))
    return classes


def _plug_owner_classes() -> list[dict[str, Any]]:
    a, b = PLUG_IDS

    def C(name: str, **kw: Any) -> dict[str, Any]:
        base = {"__name__": name}
        base.update(kw)
        return base

    return [
        C("empty"),
        C("tou_only", _paused_by_us=[a]),
        C("drain_only", _paused_by_battery_drain=[a]),
        C("fill_only", _paused_by_fill_priority=[a]),
        C("load_shed_only", _paused_by_load_shed=[a],
          _load_shed_was_on_at_shed={a: True}),
        C("proactive_only", _proactive_offpeak_holds=[a]),
        C("tou_plus_drain",
          _paused_by_us=[a], _paused_by_battery_drain=[b]),
        C("tou_plus_fill",
          _paused_by_us=[a], _paused_by_fill_priority=[b]),
        C("tou_plus_load_shed",
          _paused_by_us=[a], _paused_by_load_shed=[b],
          _load_shed_was_on_at_shed={b: True}),
        C("proactive_plus_drain",
          _proactive_offpeak_holds=[a], _paused_by_battery_drain=[b]),
    ]


# Tick-family events. Each is (event_id, tou, grid_charge_on, is_on_seeds).
# `is_on_seeds` maps device_id -> HA switch state to inject before the tick.
TICK_EVENTS = ("tick_no_grid", "tick_grid_on")


# ---------------------------------------------------------------------------
# Controller construction (with owner-state injection)
# ---------------------------------------------------------------------------
def _build_evse_config() -> dict[str, dict[str, str]]:
    return {
        eid: {
            "switch": f"switch.{eid}",
            "power": f"sensor.{eid}_power",
            "energy_today": f"sensor.{eid}_energy_today",
            "energy_month": f"sensor.{eid}_energy_month",
            "span_breaker": f"switch.{eid}_breaker",
        }
        for eid in EVSE_IDS
    }


def _make_ev_controller(hass: Any, class_seed: dict[str, Any]):
    from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
        EVChargerController,
    )

    ctrl = EVChargerController(hass, evse_config=_build_evse_config())
    # Attach fake coord so `determine_actions` blind-window guard has a
    # peer to consult; guard is inactive by default.
    ctrl.attach_coord(_FakeCoord(blind_hold_active=False))

    for k, v in class_seed.items():
        if k == "__name__":
            continue
        cur = getattr(ctrl, k, None)
        if isinstance(cur, set):
            cur.clear()
            cur.update(v)
        elif isinstance(cur, dict):
            cur.clear()
            cur.update(v)
        else:
            setattr(ctrl, k, v)
    return ctrl


def _make_plug_controller(hass: Any, class_seed: dict[str, Any]):
    from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
        SmartPlugController,
    )

    ctrl = SmartPlugController(hass, plug_entities=list(PLUG_IDS))
    for k, v in class_seed.items():
        if k == "__name__":
            continue
        cur = getattr(ctrl, k, None)
        if isinstance(cur, set):
            cur.clear()
            cur.update(v)
        elif isinstance(cur, dict):
            cur.clear()
            cur.update(v)
        else:
            setattr(ctrl, k, v)
    return ctrl


# ---------------------------------------------------------------------------
# Save-KV payload replication (mirrors _save_evse_state exactly)
# ---------------------------------------------------------------------------
def _emit_save_kv(ev_ctrl: Any) -> dict[str, Any]:
    """Replicate the KV payload `_save_evse_state` writes.

    Mirrors `energy.py:_save_evse_state` (lines ~1811-1949) key-for-key.
    Any drift here vs the production writer would fail the oracle when
    phase 2 migrates that writer — this is exactly the surface the
    registry must reproduce byte-identically. The KV emission is
    NORMALIZED via `sort_keys` at serialization time.
    """
    from homeassistant.util import dt as dt_util

    payload: dict[str, Any] = {}
    per_evse: dict[str, dict[str, bool]] = {}
    for evse_id in ev_ctrl._evse:
        per_evse[evse_id] = {
            "paused_by_energy": evse_id in ev_ctrl._paused_by_us,
            "excess_solar_active": evse_id in ev_ctrl._excess_solar_active,
        }
    payload["per_evse"] = per_evse
    payload["evse_grid_cap_paused"] = sorted(ev_ctrl._paused_by_grid_cap)
    payload["evse_battery_drain_paused"] = sorted(ev_ctrl._paused_by_battery_drain)
    payload["evse_fill_priority_paused"] = sorted(ev_ctrl._paused_by_fill_priority)
    payload["evse_arbitrage_paused"] = sorted(ev_ctrl._paused_by_arbitrage)
    payload["evse_dp_paused"] = sorted(ev_ctrl._paused_by_dp)
    payload["evse_proactive_offpeak_holds"] = sorted(ev_ctrl._proactive_offpeak_holds)
    payload["evse_blind_window_paused"] = sorted(ev_ctrl._paused_by_blind_window)
    payload["evse_blind_window_liveness_ride"] = sorted(ev_ctrl._blind_window_liveness_ride)

    epoch = ev_ctrl._blind_window_epoch_started_at
    if epoch is not None:
        if epoch.tzinfo is None:
            epoch = epoch.replace(tzinfo=dt_util.UTC)
        payload["evse_blind_window_epoch_started_at"] = epoch.isoformat()
    else:
        payload["evse_blind_window_epoch_started_at"] = ""

    fc_until = ev_ctrl._force_charge_until
    if fc_until is not None:
        if fc_until.tzinfo is None:
            fc_until = fc_until.replace(tzinfo=dt_util.UTC)
        payload["ev_force_charge_until"] = fc_until.isoformat()
    else:
        payload["ev_force_charge_until"] = ""

    return payload


# ---------------------------------------------------------------------------
# Owner-membership + dispatch snapshot serialization
# ---------------------------------------------------------------------------
_EV_OWNER_ATTRS = (
    "_paused_by_us",
    "_excess_solar_active",
    "_paused_by_grid_cap",
    "_paused_by_battery_drain",
    "_paused_by_dp",
    "_paused_by_arbitrage",
    "_paused_by_load_shed",
    "_paused_by_fill_priority",
    "_proactive_offpeak_holds",
    "_paused_by_blind_window",
    "_blind_window_liveness_ride",
)
_PLUG_OWNER_ATTRS = (
    "_paused_by_us",
    "_paused_by_battery_drain",
    "_paused_by_fill_priority",
    "_paused_by_load_shed",
    "_proactive_offpeak_holds",
)


def _snapshot_owners(ctrl: Any, attrs: tuple[str, ...]) -> dict[str, list[str]]:
    return {a: sorted(getattr(ctrl, a)) for a in attrs}


def _snapshot_dispatch(ctrl: Any) -> dict[str, Any]:
    return {
        "dispatch_owners": {
            k: sorted(v) for k, v in sorted(ctrl._dispatch_owners.items())
        },
        # Only presence/absence — the timestamp itself is pinned monotonic.
        "pause_dispatch_ts_ids": sorted(ctrl._pause_dispatch_ts.keys()),
        "observed_off_since_pause": {
            k: bool(v)
            for k, v in sorted(ctrl._observed_off_since_pause.items())
        },
    }


# ---------------------------------------------------------------------------
# Get-status owner slice (dashboards contract)
# ---------------------------------------------------------------------------
def _ev_status_slice(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "pause_reason_human": status.get("pause_reason_human", {}),
        "energy_status": {
            k: v.get("energy_status")
            for k, v in status.items()
            if isinstance(v, dict) and "energy_status" in v
        },
        "paused_by_energy": sorted(status.get("paused_by_energy", [])),
        "paused_by_grid_cap": sorted(status.get("paused_by_grid_cap", [])),
        "paused_by_battery_drain": sorted(status.get("paused_by_battery_drain", [])),
        "paused_by_arbitrage": sorted(status.get("paused_by_arbitrage", [])),
        "paused_by_arbitrage_reasons": status.get("paused_by_arbitrage_reasons", {}),
        "paused_by_fill_priority": sorted(status.get("paused_by_fill_priority", [])),
        "excess_solar_evses": sorted(status.get("excess_solar_evses", [])),
        "proactive_offpeak_holds": sorted(status.get("proactive_offpeak_holds", [])),
    }


def _plug_status_slice(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "pause_reason_human": status.get("pause_reason_human", {}),
        "energy_status_per_plug": {
            k: v.get("energy_status")
            for k, v in status.get("plug_entries", {}).items()
        },
        "paused_by_energy": sorted(status.get("paused_by_energy", [])),
        "paused_by_battery_drain": sorted(status.get("paused_by_battery_drain", [])),
        "paused_by_fill_priority": sorted(status.get("paused_by_fill_priority", [])),
    }


# ---------------------------------------------------------------------------
# Per-tuple driver
# ---------------------------------------------------------------------------
def _run_ev_tuple(
    class_seed: dict[str, Any],
    tou: str,
    soc: int,
    event: str,
    monkeypatch_ctx,
) -> dict[str, Any]:
    is_on_switch = "on" if event == "tick_grid_on" else "off"
    fake_states = {
        f"switch.{eid}": _FakeState(is_on_switch) for eid in EVSE_IDS
    }
    hass = _FakeHass(fake_states)
    ctrl = _make_ev_controller(hass, class_seed)
    _pin_time(monkeypatch_ctx)

    grid_charge_on = (event == "tick_grid_on")
    actions = ctrl.determine_actions(
        tou_period=tou,
        grid_charge_on=grid_charge_on,
        coord=None,
    )
    post_owners = _snapshot_owners(ctrl, _EV_OWNER_ATTRS)
    save_kv = _emit_save_kv(ctrl)
    status = ctrl.get_status(fill_priority_target_soc=soc)
    status_slice = _ev_status_slice(status)
    dispatch = _snapshot_dispatch(ctrl)

    return {
        "tier": "evse",
        "class": class_seed["__name__"],
        "tou": tou,
        "soc": soc,
        "event": event,
        "actions": actions,
        "post_owners": post_owners,
        "save_kv": save_kv,
        "status_slice": status_slice,
        "dispatch": dispatch,
    }


def _run_plug_tuple(
    class_seed: dict[str, Any],
    tou: str,
    soc: int,
    event: str,
    monkeypatch_ctx,
) -> dict[str, Any]:
    is_on_switch = "on" if event == "tick_grid_on" else "off"
    fake_states = {pid: _FakeState(is_on_switch) for pid in PLUG_IDS}
    hass = _FakeHass(fake_states)
    ctrl = _make_plug_controller(hass, class_seed)
    _pin_time(monkeypatch_ctx)

    grid_charge_on = (event == "tick_grid_on")
    actions = ctrl.determine_actions(
        tou_period=tou,
        force_charge_active=False,
        grid_charge_on=grid_charge_on,
    )
    post_owners = _snapshot_owners(ctrl, _PLUG_OWNER_ATTRS)
    status = ctrl.get_status(fill_priority_target_soc=soc)
    status_slice = _plug_status_slice(status)
    dispatch = _snapshot_dispatch(ctrl)

    return {
        "tier": "plug",
        "class": class_seed["__name__"],
        "tou": tou,
        "soc": soc,
        "event": event,
        "actions": actions,
        "post_owners": post_owners,
        # Plug tier bundled into EV KV via the shared save path; the
        # migration surface for the plug KV is identical shape (empty
        # dict here — plug persistence rides EV KV in the coordinator).
        "save_kv": {},
        "status_slice": status_slice,
        "dispatch": dispatch,
    }


# ---------------------------------------------------------------------------
# Prune sweep — a separate stateless capture, one row per class
# ---------------------------------------------------------------------------
def _run_ev_prune(class_seed: dict[str, Any], monkeypatch_ctx) -> dict[str, Any]:
    fake_states = {f"switch.{eid}": _FakeState("off") for eid in EVSE_IDS}
    hass = _FakeHass(fake_states)
    ctrl = _make_ev_controller(hass, class_seed)
    _pin_time(monkeypatch_ctx)
    # Drop garage_b from the config, then prune. This exercises every
    # owner set / dict listed in `_prune_removed_evses` including the
    # documented `_paused_by_load_shed` absence quirk (which the plan's
    # operator rulings say to PRESERVE byte-identically).
    ctrl._evse = {"garage_a": ctrl._evse["garage_a"]}
    ctrl._prune_removed_evses()
    return {
        "tier": "evse",
        "class": class_seed["__name__"],
        "event": "prune_removed_evse:garage_b",
        "post_owners": _snapshot_owners(ctrl, _EV_OWNER_ATTRS),
        # Load-shed quirk surface: NOT pruned by the current code even
        # when membership references the removed EVSE. The golden
        # captures the quirk here so a future accidental "fix" during
        # phase 2 fails the oracle.
        "load_shed_after_prune": sorted(ctrl._paused_by_load_shed),
    }


def _run_plug_prune(class_seed: dict[str, Any], monkeypatch_ctx) -> dict[str, Any]:
    fake_states = {pid: _FakeState("off") for pid in PLUG_IDS}
    hass = _FakeHass(fake_states)
    ctrl = _make_plug_controller(hass, class_seed)
    _pin_time(monkeypatch_ctx)
    ctrl._plugs = [PLUG_IDS[0]]
    ctrl.prune_removed_plugs()
    return {
        "tier": "plug",
        "class": class_seed["__name__"],
        "event": "prune_removed_plug:beta",
        "post_owners": _snapshot_owners(ctrl, _PLUG_OWNER_ATTRS),
    }


# ---------------------------------------------------------------------------
# Peer-holds sweep — one row per (class, evse_id)
# ---------------------------------------------------------------------------
def _run_merged_status(
    ev_class_seed: dict[str, Any],
    plug_class_seed: dict[str, Any],
    tou: str,
    monkeypatch_ctx,
) -> dict[str, Any]:
    """v2 (phase 1b): capture EV.get_status(plug_status=plug.get_status()).

    Exercises the plug-status merge at energy_pool.py:2456 where plug-tier
    paused_by_energy / battery_drain / fill_priority ride into the EV's
    surfaced totals, plus per-plug entries land in the top-level status
    dict and pause_reason_human keyspace becomes shared across tiers.
    """
    fake_states = {f"switch.{eid}": _FakeState("off") for eid in EVSE_IDS}
    fake_states.update({pid: _FakeState("off") for pid in PLUG_IDS})
    hass = _FakeHass(fake_states)
    ev = _make_ev_controller(hass, ev_class_seed)
    plug = _make_plug_controller(hass, plug_class_seed)
    _pin_time(monkeypatch_ctx)

    plug_status = plug.get_status(fill_priority_target_soc=55)
    ev_status = ev.get_status(
        fill_priority_target_soc=55, plug_status=plug_status,
    )
    # Merged slice: focus on the fields the merge actually touches
    # (2456-2470) + the shared pause_reason_human dict + per-plug
    # entries landed at the top level of status.
    merged_slice = {
        "paused_by_energy": sorted(ev_status.get("paused_by_energy", [])),
        "paused_by_battery_drain": sorted(
            ev_status.get("paused_by_battery_drain", []),
        ),
        "paused_by_fill_priority": sorted(
            ev_status.get("paused_by_fill_priority", []),
        ),
        "pause_reason_human": ev_status.get("pause_reason_human", {}),
        "plug_ids_in_status": sorted(
            k for k in ev_status if k in set(PLUG_IDS)
        ),
        "plug_energy_status_per_id": {
            k: ev_status[k].get("energy_status")
            for k in ev_status
            if k in set(PLUG_IDS) and isinstance(ev_status[k], dict)
        },
        "evse_config_keys": sorted(ev_status.get("evse_config", {}).keys()),
        "pause_dispatch_state_keys": sorted(
            ev_status.get("pause_dispatch_state", {}).keys(),
        ),
    }
    return {
        "tier": "merged",
        "ev_class": ev_class_seed["__name__"],
        "plug_class": plug_class_seed["__name__"],
        "tou": tou,
        "event": "merged_get_status",
        "merged_slice": merged_slice,
    }


def _run_ev_peer_holds(class_seed: dict[str, Any], monkeypatch_ctx) -> dict[str, Any]:
    fake_states = {f"switch.{eid}": _FakeState("off") for eid in EVSE_IDS}
    hass = _FakeHass(fake_states)
    ctrl = _make_ev_controller(hass, class_seed)
    _pin_time(monkeypatch_ctx)
    return {
        "tier": "evse",
        "class": class_seed["__name__"],
        "event": "stronger_peer_holds",
        "peer_holds": {eid: ctrl._stronger_peer_holds(eid) for eid in EVSE_IDS},
    }


# ---------------------------------------------------------------------------
# Public generate() entrypoint
# ---------------------------------------------------------------------------
def _monkeypatch_ctx():
    """Homebrew context manager mimicking pytest.MonkeyPatch outside pytest."""
    import contextlib

    class _MP:
        def __init__(self) -> None:
            self._undo: list[tuple[Any, str, Any]] = []

        def setattr(self, target: Any, name: str, value: Any) -> None:
            prev = getattr(target, name)
            self._undo.append((target, name, prev))
            setattr(target, name, value)

        def undo(self) -> None:
            while self._undo:
                target, name, prev = self._undo.pop()
                setattr(target, name, prev)

    @contextlib.contextmanager
    def _ctx():
        mp = _MP()
        try:
            yield mp
        finally:
            mp.undo()

    return _ctx()


def generate(output_path: Path) -> dict[str, Any]:
    """Generate and gzip-write the golden capture. Returns metadata."""
    ev_classes = _evse_owner_classes()
    plug_classes = _plug_owner_classes()

    rows: list[dict[str, Any]] = []
    with _monkeypatch_ctx() as mp:
        for cls in ev_classes:
            for tou in TOU_PERIODS:
                for soc in SOC_BUCKETS:
                    for event in TICK_EVENTS:
                        rows.append(_run_ev_tuple(cls, tou, soc, event, mp))
            rows.append(_run_ev_prune(cls, mp))
            rows.append(_run_ev_peer_holds(cls, mp))

        for cls in plug_classes:
            for tou in TOU_PERIODS:
                for soc in SOC_BUCKETS:
                    for event in TICK_EVENTS:
                        rows.append(_run_plug_tuple(cls, tou, soc, event, mp))
            rows.append(_run_plug_prune(cls, mp))

        # v2 (phase 1b): merged EV+plug get_status sweep — closes
        # anomaly #3 (plug_status merge coverage).
        for ev_cls in ev_classes:
            for plug_cls in plug_classes:
                for tou in MERGED_TOU_PERIODS:
                    rows.append(_run_merged_status(ev_cls, plug_cls, tou, mp))

    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent.parent.parent,
        ).decode().strip()
    except Exception:
        commit = "unknown"

    header = {
        "schema_version": GOLDEN_SCHEMA_VERSION,
        "source_commit": commit,
        "pinned_utc": PINNED_UTC.isoformat(),
        "pinned_monotonic": PINNED_MONO,
        "ev_owner_classes": len(ev_classes),
        "plug_owner_classes": len(plug_classes),
        "tou_periods": list(TOU_PERIODS),
        "soc_buckets": list(SOC_BUCKETS),
        "tick_events": list(TICK_EVENTS),
        "row_count": len(rows),
        "v2_extension_notes": {
            "phase": "1b",
            "coverage_gap_closed": (
                "anomaly #3 from phase-1 report — plug_status merge path "
                "at energy_pool.py:2456 not previously exercised"
            ),
            "merged_row_count": len(ev_classes) * len(plug_classes) * len(MERGED_TOU_PERIODS),
            "merged_tou_periods": list(MERGED_TOU_PERIODS),
        },
        "reductions_from_plan_s4a": {
            "tick_family_events_captured": list(TICK_EVENTS),
            "external_mutation_events_seeded_via_owner_class": True,
            "ev_owner_class_count_stratified": len(ev_classes),
            "plug_owner_class_count_stratified": len(plug_classes),
            "note": (
                "Phase 1 stratifies event space by seeding external-mutation "
                "owner states directly into the tuple's initial owner class, "
                "then drives one tick-family event through determine_actions. "
                "Surfaces D3-D6 (persist/restore, prune, peer-holds, "
                "classifier) are fully covered."
            ),
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output_path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"__header__": header}, sort_keys=True) + "\n")
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")

    return header


def _default_output() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "tests" / "golden" / "owner_registry_v1.jsonl.gz"
    )


if __name__ == "__main__":
    out = _default_output()
    if len(sys.argv) > 1:
        out = Path(sys.argv[1])
    t0 = _time.perf_counter()
    meta = generate(out)
    dt = _time.perf_counter() - t0
    print(f"Wrote {out} ({meta['row_count']} rows, {dt:.2f}s)")
    print(json.dumps(meta, indent=2, sort_keys=True))
