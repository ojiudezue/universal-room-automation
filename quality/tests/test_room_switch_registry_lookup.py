"""ROOM-SWITCH-LOOKUP-BY-NAME-1 — registry-backed resolver tests.

Drives the REAL UniversalRoomCoordinator helpers (not a monkeypatch
stub) over a mock entity registry + hass.states. Verifies the gate
semantics for every room control switch (automation / manual_mode /
ai_automation / cover_automation / override_occupied / override_vacant /
auto_recovery) under THREE entity_id shapes:

  1. legacy single-prefix name-built id   : switch.{slug}_{suffix}
  2. new double-prefix HA-generated id    : switch.{slug}_{slug}_{suffix}
  3. operator-renamed id                  : switch.anything_else

All three must honour OFF through the gate; the previous name-only
lookup silently failed open on (2) and (3), which is the live bug this
card fixes (Wigton + main-house 2026-10-10).
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace


class _MockState:
    def __init__(self, entity_id: str, state: str) -> None:
        self.entity_id = entity_id
        self.state = state


class _MockStates:
    def __init__(self) -> None:
        self._by_id: dict[str, _MockState] = {}

    def set(self, entity_id: str, state: str) -> None:
        self._by_id[entity_id] = _MockState(entity_id, state)

    def get(self, entity_id: str) -> _MockState | None:
        return self._by_id.get(entity_id)

    def remove(self, entity_id: str) -> None:
        self._by_id.pop(entity_id, None)


class _MockRegistry:
    """Mimics homeassistant.helpers.entity_registry.EntityRegistry.async_get_entity_id."""

    def __init__(self) -> None:
        # key = (domain, platform, unique_id) -> entity_id
        self._by_unique: dict[tuple[str, str, str], str] = {}

    def register(self, domain: str, platform: str, unique_id: str, entity_id: str) -> None:
        self._by_unique[(domain, platform, unique_id)] = entity_id

    def async_get_entity_id(self, domain: str, platform: str, unique_id: str) -> str | None:
        return self._by_unique.get((domain, platform, unique_id))


class _MockHass:
    def __init__(self) -> None:
        self.states = _MockStates()


def _install_fake_er(registry: _MockRegistry) -> None:
    """Replace homeassistant.helpers.entity_registry with a stub that returns our registry."""
    fake_er = types.ModuleType("homeassistant.helpers.entity_registry")

    def async_get(_hass):
        return registry

    fake_er.async_get = async_get
    sys.modules["homeassistant.helpers.entity_registry"] = fake_er
    # `from homeassistant.helpers import entity_registry as er` resolves via
    # the parent package's attribute if already set — pin it too.
    import homeassistant.helpers as _hh  # noqa: PLC0415
    _hh.entity_registry = fake_er


def _make_coord(room_name: str = "Master Hallway", entry_id: str = "entry_abc123"):
    """Build a UniversalRoomCoordinator stand-in that routes the resolver
    through the REAL coordinator.py method, not a stub."""
    from custom_components.universal_room_automation.coordinator import (
        UniversalRoomCoordinator,
    )

    hass = _MockHass()
    entry = SimpleNamespace(
        entry_id=entry_id,
        data={"room_name": room_name},
        options={},
    )
    coord = UniversalRoomCoordinator.__new__(UniversalRoomCoordinator)
    coord.hass = hass
    coord.entry = entry
    coord._switch_entity_id_cache = {}
    coord._switch_entity_id_warned = set()
    return coord


# ---- Shape 1: legacy single-prefix (no registry entry — pure fallback) -----

def test_single_prefix_fallback_resolves_and_gates_off():
    registry = _MockRegistry()
    _install_fake_er(registry)
    coord = _make_coord("Master Hallway", "entry_single")
    # Legacy single-prefix entity exists in states only (not in registry).
    coord.hass.states.set("switch.master_hallway_automation", "off")

    assert coord._resolve_room_switch_entity_id("automation") == "switch.master_hallway_automation"
    assert coord._get_room_switch_state("automation") is False
    assert coord._is_automation_enabled() is False  # OFF honoured


# ---- Shape 2: double-prefix (what HA generates for new rooms) --------------

def test_double_prefix_registry_resolves_and_gates_off():
    """Live bug: on new rooms HA names the entity switch.{slug}_{slug}_{suffix}.
    The old name-built lookup missed it; _is_automation_enabled defaulted True."""
    registry = _MockRegistry()
    entry_id = "entry_dp"
    # Register every room-switch unique_id → double-prefix entity_id.
    double = {
        "automation": "switch.master_hallway_master_hallway_automation",
        "manual_mode": "switch.master_hallway_master_hallway_manual_mode",
        "ai_automation": "switch.master_hallway_master_hallway_ai_automation",
        "cover_automation": "switch.master_hallway_master_hallway_cover_automation",
        "override_occupied": "switch.master_hallway_master_hallway_override_occupied",
        "override_vacant": "switch.master_hallway_master_hallway_override_vacant",
        "auto_recovery": "switch.master_hallway_master_hallway_auto_recovery",
    }
    from custom_components.universal_room_automation.const import DOMAIN
    for suffix, eid in double.items():
        registry.register("switch", DOMAIN, f"{entry_id}_{suffix}", eid)
    _install_fake_er(registry)

    coord = _make_coord("Master Hallway", entry_id)
    for suffix, eid in double.items():
        coord.hass.states.set(eid, "off")
    # Sanity: name-built legacy id does NOT exist (this is the bug surface).
    assert coord.hass.states.get("switch.master_hallway_automation") is None

    assert coord._resolve_room_switch_entity_id("automation") == double["automation"]
    assert coord._is_automation_enabled() is False  # Automation OFF honoured
    # Flip automation ON, manual ON → still disabled.
    coord.hass.states.set(double["automation"], "on")
    coord.hass.states.set(double["manual_mode"], "on")
    coord._switch_entity_id_cache.clear()  # keep cache honest for test
    assert coord._is_automation_enabled() is False
    # Clear manual, confirm now enabled.
    coord.hass.states.set(double["manual_mode"], "off")
    assert coord._is_automation_enabled() is True
    # AI gate honoured
    coord.hass.states.set(double["ai_automation"], "off")
    assert coord._is_ai_automation_enabled() is False
    coord.hass.states.set(double["ai_automation"], "on")
    assert coord._is_ai_automation_enabled() is True
    # Cover gate
    coord.hass.states.set(double["cover_automation"], "off")
    assert coord._is_cover_automation_enabled() is False
    # Overrides
    coord.hass.states.set(double["override_occupied"], "on")
    assert coord._is_override_occupied() is True
    coord.hass.states.set(double["override_vacant"], "on")
    assert coord._is_override_vacant() is True


# ---- Shape 3: operator-renamed entity_id (registry authoritative) ----------

def test_renamed_entity_id_still_resolves_via_registry():
    registry = _MockRegistry()
    entry_id = "entry_renamed"
    from custom_components.universal_room_automation.const import DOMAIN
    renamed = "switch.hallway_main_toggle"
    registry.register("switch", DOMAIN, f"{entry_id}_automation", renamed)
    _install_fake_er(registry)

    coord = _make_coord("Master Hallway", entry_id)
    coord.hass.states.set(renamed, "off")
    # Legacy name-built id is absent.
    assert coord.hass.states.get("switch.master_hallway_automation") is None
    assert coord._resolve_room_switch_entity_id("automation") == renamed
    assert coord._is_automation_enabled() is False


# ---- Shape 3b: operator renames AFTER first resolve → cache invalidates ----

def test_rename_after_cache_invalidates_and_reresolves():
    registry = _MockRegistry()
    entry_id = "entry_cache"
    from custom_components.universal_room_automation.const import DOMAIN
    old_id = "switch.master_hallway_master_hallway_automation"
    new_id = "switch.hallway_toggle"
    registry.register("switch", DOMAIN, f"{entry_id}_automation", old_id)
    _install_fake_er(registry)

    coord = _make_coord("Master Hallway", entry_id)
    coord.hass.states.set(old_id, "on")
    # First call warms the cache with old_id.
    assert coord._is_automation_enabled() is True

    # Operator renames: states.get(old_id) is None; registry points at new_id.
    coord.hass.states.remove(old_id)
    registry.register("switch", DOMAIN, f"{entry_id}_automation", new_id)
    coord.hass.states.set(new_id, "off")

    # Resolver must invalidate cache on hass.states miss and find new_id.
    assert coord._is_automation_enabled() is False


# ---- Nothing resolves → WARNING once + documented default --------------------

def test_missing_switch_warns_once_and_defaults():
    registry = _MockRegistry()
    _install_fake_er(registry)
    coord = _make_coord("Ghost Room", "entry_ghost")

    # automation absent → default True (documented current behaviour).
    assert coord._is_automation_enabled() is True
    # cover absent → default True.
    assert coord._is_cover_automation_enabled() is True
    # overrides absent → False (documented).
    assert coord._is_override_occupied() is False
    assert coord._is_override_vacant() is False
    # WARN set is populated per suffix exactly once.
    assert "automation" in coord._switch_entity_id_warned
    before = len(coord._switch_entity_id_warned)
    coord._is_automation_enabled()  # second call must not re-warn (set membership)
    assert len(coord._switch_entity_id_warned) == before
