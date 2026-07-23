"""Arbitrage reason-map invariant sweep — Tier-1 follow-up cycle.

Registry danger-spot #4: `_arbitrage_pause_reason.keys()` must remain a
subset of `_paused_by_arbitrage`. Every legitimate write pairs them (add
side ~L2286; release side ~L2331 pops+discards together). A future
mismatched discard of the set would leave an orphaned reason key behind
— this sweep polices the invariant defensively in
`_enforce_arbitrage_reason_invariant`, called from
`_prune_removed_evses`.

Mutation anchors
----------------
Disabling the sweep (body of `_enforce_arbitrage_reason_invariant` -> `pass`)
must flip `test_orphan_reason_key_cleaned_by_prune` RED.

Legitimate reason keys (i.e. present in `_paused_by_arbitrage`) must
survive the sweep — asserted by `test_legitimate_reason_key_survives`.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    energy_pool as _epool,
)


class _FakeState:
    def __init__(self, state: str) -> None:
        self.state = state
        self.attributes: dict = {}


class _FakeHass:
    def __init__(self, entities: dict[str, str] | None = None) -> None:
        self._entities = entities or {}
        self.states = MagicMock()
        self.states.get = lambda eid: (
            _FakeState(self._entities[eid])
            if eid in self._entities else None
        )


def _make_evpool(evse_ids: list[str]) -> _epool.EVChargerController:
    hass = _FakeHass({eid: "off" for eid in evse_ids})
    pool = _epool.EVChargerController.__new__(_epool.EVChargerController)
    pool.hass = hass
    pool._evse = {eid: {"switch": eid} for eid in evse_ids}
    pool._paused_by_us = set()
    pool._paused_by_grid_cap = set()
    pool._paused_by_fill_priority = set()
    pool._paused_by_battery_drain = set()
    pool._paused_by_arbitrage = set()
    pool._paused_by_load_shed = set()
    pool._paused_by_dp = set()
    pool._paused_by_blind_window = set()
    pool._blind_window_liveness_ride = set()
    pool._excess_solar_active = set()
    pool._proactive_offpeak_holds = set()
    pool._arbitrage_pause_reason = {}
    pool._load_shed_was_on_at_shed = {}
    pool._battery_drain_cooldown = {}
    pool._pause_dispatch_ts = {}
    pool._observed_off_since_pause = {}
    pool._dispatch_owners = {}
    pool._power_sensor_unavail_count = {}
    pool._power_sensor_unavail_since = {}
    pool._power_sensor_alerted = set()
    pool._force_charge_until = None
    return pool


def test_orphan_reason_key_cleaned_by_prune() -> None:
    """A reason key with NO matching `_paused_by_arbitrage` membership
    is dropped by the invariant sweep during prune."""
    pool = _make_evpool(["garage_a", "garage_b"])
    # Simulate a mismatched-discard bug: reason set but the set already
    # discarded (real code today does pop+discard together, but a
    # future patch could break that pairing).
    pool._arbitrage_pause_reason["garage_a"] = "breaker"
    # Not adding to _paused_by_arbitrage — this is the orphan.

    pool._prune_removed_evses()

    assert "garage_a" not in pool._arbitrage_pause_reason, (
        "orphan reason key survived the invariant sweep"
    )


def test_legitimate_reason_key_survives() -> None:
    """A reason key whose evse_id IS in `_paused_by_arbitrage` and IS
    in the config must NOT be swept."""
    pool = _make_evpool(["garage_a", "garage_b"])
    pool._paused_by_arbitrage.add("garage_a")
    pool._arbitrage_pause_reason["garage_a"] = "redirect"

    pool._prune_removed_evses()

    assert pool._arbitrage_pause_reason.get("garage_a") == "redirect"
    assert "garage_a" in pool._paused_by_arbitrage


def test_helper_is_idempotent() -> None:
    """Calling the sweep repeatedly on a clean state is a no-op."""
    pool = _make_evpool(["garage_a"])
    pool._paused_by_arbitrage.add("garage_a")
    pool._arbitrage_pause_reason["garage_a"] = "breaker"

    pool._enforce_arbitrage_reason_invariant()
    pool._enforce_arbitrage_reason_invariant()

    assert pool._arbitrage_pause_reason == {"garage_a": "breaker"}
    assert pool._paused_by_arbitrage == {"garage_a"}


def test_prune_of_removed_evse_also_clears_reason_key() -> None:
    """When the config drops an EVSE, both `_paused_by_arbitrage`
    membership AND the paired reason key are cleaned (the dict-prune
    pass drops the reason; the set-prune pass drops the membership).
    Belt-and-braces sweep leaves the pair consistent."""
    pool = _make_evpool(["garage_a", "garage_b"])
    pool._paused_by_arbitrage.update({"garage_a", "garage_b"})
    pool._arbitrage_pause_reason.update(
        {"garage_a": "breaker", "garage_b": "redirect"},
    )
    # Drop garage_b from config.
    pool._evse = {"garage_a": pool._evse["garage_a"]}

    pool._prune_removed_evses()

    assert "garage_b" not in pool._paused_by_arbitrage
    assert "garage_b" not in pool._arbitrage_pause_reason
    # garage_a untouched.
    assert pool._paused_by_arbitrage == {"garage_a"}
    assert pool._arbitrage_pause_reason == {"garage_a": "breaker"}
