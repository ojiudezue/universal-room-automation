"""Shared helpers for the phase-3 owner-registry persistence oracle
and adjacent behavioral tests.

Provides:
- `FakeKVDB` — captures `save_energy_state` / `save_evse_state` writes,
  serves `restore_energy_state_with_age` / `restore_evse_state` reads
  from the captured map. Mirrors the DB DAOs consumed by
  `EnergyCoordinator._save_registry_owner_lists` /
  `_restore_registry_owner_lists`.
- `make_fake_energy_coord()` — a minimal instance carrying only the
  attributes the two helpers need: a real `EVChargerController` as
  `_ev`, `hass` stub, and the extracted method references. The
  production helpers are bound to it via `types.MethodType`.
"""
from __future__ import annotations

import types
from typing import Any
from unittest.mock import MagicMock

from _energy_bootstrap import bootstrap_energy_imports
bootstrap_energy_imports()

from custom_components.universal_room_automation.domain_coordinators import (
    energy as _energy_mod, energy_pool as _energy_pool_mod,
)


class FakeKVDB:
    """DB-DAO stand-in with in-memory KV maps for both write directions."""

    def __init__(self) -> None:
        # `save_energy_state(key, value)` writes here.
        self.energy_state: dict[str, str] = {}
        # `save_evse_state(evse_id, paused_by_energy, excess_solar_active)`
        # writes here. `restore_evse_state` reads back.
        self.evse_state: dict[str, dict[str, Any]] = {}
        # Diagnostics: ordered list of writes for order-sensitive checks
        self.write_log: list[tuple[str, str]] = []

    async def save_energy_state(self, key: str, value: str) -> None:
        self.energy_state[key] = value
        self.write_log.append(("energy_state", key))

    async def save_evse_state(
        self, evse_id: str, paused_by_energy: bool,
        excess_solar_active: bool,
    ) -> None:
        self.evse_state[evse_id] = {
            "paused_by_energy": bool(paused_by_energy),
            "excess_solar_active": bool(excess_solar_active),
        }

    async def restore_energy_state_with_age(
        self, key: str, max_age_hours: float,
    ) -> str | None:
        return self.energy_state.get(key)

    async def restore_evse_state(
        self, max_age_hours: float,
    ) -> dict[str, dict[str, Any]]:
        return dict(self.evse_state)


DEFAULT_EVSE_CONFIG = {
    "garage_a": {
        "switch": "switch.garage_a",
        "power": "sensor.garage_a_power",
        "energy_today": "sensor.garage_a_energy_today",
        "energy_month": "sensor.garage_a_energy_month",
        "span_breaker": "switch.garage_a_breaker",
    },
    "garage_b": {
        "switch": "switch.garage_b",
        "power": "sensor.garage_b_power",
        "energy_today": "sensor.garage_b_energy_today",
        "energy_month": "sensor.garage_b_energy_month",
        "span_breaker": "switch.garage_b_breaker",
    },
}


def make_fake_energy_coord(
    evse_config: dict | None = None,
):
    """Return a minimal object exposing `_ev` + the two registry helpers.

    We bind the production methods directly via `types.MethodType` so
    the tests exercise the exact functions `_save_evse_state` /
    `_restore_evse_state` delegate to — not a re-implementation.
    """
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get = lambda _e: None
    ev = _energy_pool_mod.EVChargerController(
        hass, evse_config=evse_config or DEFAULT_EVSE_CONFIG,
    )
    coord = types.SimpleNamespace()
    coord.hass = hass
    coord._ev = ev
    coord._save_registry_owner_lists = types.MethodType(
        _energy_mod.EnergyCoordinator._save_registry_owner_lists, coord,
    )
    coord._restore_registry_owner_lists = types.MethodType(
        _energy_mod.EnergyCoordinator._restore_registry_owner_lists, coord,
    )
    return coord
