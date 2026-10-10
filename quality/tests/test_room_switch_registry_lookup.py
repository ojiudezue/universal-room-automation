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
from unittest.mock import AsyncMock

import pytest


def _unpollute_coordinator_module() -> None:
    """Another test in the suite (test_hvac_presence_timer_knobs.py:640-647)
    replaces ``sys.modules['custom_components.universal_room_automation.coordinator']``
    with a stub where ``UniversalRoomCoordinator = MagicMock`` and never
    restores it. If that stub leaked in before us, drop it so our
    import gets the REAL class."""
    # test_hvac_presence_timer_knobs stubs these three — drop them if the
    # stubs are still in sys.modules so our import loads the REAL modules.
    coord_name = "custom_components.universal_room_automation.coordinator"
    coord_mod = sys.modules.get(coord_name)
    if coord_mod is not None:
        cls = getattr(coord_mod, "UniversalRoomCoordinator", None)
        # A MagicMock stand-in is still truthy for hasattr(anything), so
        # the hasattr trick can't tell a stub from the real thing — check
        # the module where cls is defined.
        is_stub = (
            cls is None
            or getattr(cls, "__module__", "") != coord_name
        )
        if is_stub:
            sys.modules.pop(coord_name, None)
            for dep in (
                "custom_components.universal_room_automation.switch",
                "custom_components.universal_room_automation.entity",
            ):
                sys.modules.pop(dep, None)


_unpollute_coordinator_module()


# -------------------- shared mocks --------------------

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


class _MockServices:
    def __init__(self) -> None:
        self.async_call = AsyncMock()


class _MockHass:
    def __init__(self) -> None:
        self.states = _MockStates()
        self.services = _MockServices()


def _install_fake_er(monkeypatch, registry: _MockRegistry) -> None:
    """Install a stub `homeassistant.helpers.entity_registry` module with
    `monkeypatch.setitem` / `setattr` so the override is torn down
    automatically between tests — no sys.modules leaks into other tests
    in the suite."""
    import sys  # noqa: PLC0415
    import homeassistant.helpers as _hh  # noqa: PLC0415

    fake_er = types.ModuleType("homeassistant.helpers.entity_registry")

    def async_get(_hass):
        return registry

    fake_er.async_get = async_get
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", fake_er)
    # `from homeassistant.helpers import entity_registry as er` resolves via
    # the parent package's attribute first — pin it too (reverted on teardown).
    monkeypatch.setattr(_hh, "entity_registry", fake_er, raising=False)


class _ResolverShim:
    """Plain, non-Mock, non-stub coord stand-in. We bind the REAL resolver
    / gate methods from coordinator.py onto this class so a test invoking
    ``shim._is_automation_enabled()`` executes production code — without
    going through ``UniversalRoomCoordinator.__new__``, which another test
    file (test_hvac_presence_timer_knobs.py) can poison by swapping the
    class for ``MagicMock`` in sys.modules."""


_RESOLVER_METHODS = (
    "_resolve_room_switch_entity_id",
    "_get_room_switch_state",
    "_is_automation_enabled",
    "_is_cover_automation_enabled",
    "_is_ai_automation_enabled",
    "_is_override_occupied",
    "_is_override_vacant",
)


def _load_real_coordinator_module():
    """Import the REAL coordinator module even if a sibling test has
    stubbed sys.modules['...coordinator'] with a MagicMock-bearing
    namespace. Falls through to the normal import on a clean suite."""
    _unpollute_coordinator_module()
    import importlib  # noqa: PLC0415
    coord = importlib.import_module(
        "custom_components.universal_room_automation.coordinator"
    )
    cls = getattr(coord, "UniversalRoomCoordinator", None)
    if cls is None or getattr(cls, "__module__", "") != (
        "custom_components.universal_room_automation.coordinator"
    ) or not all(hasattr(cls, m) for m in _RESOLVER_METHODS):
        # Still polluted — force a hard reload bypassing sys.modules.
        import importlib.util  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415
        src = (
            Path(__file__).resolve().parents[2]
            / "custom_components"
            / "universal_room_automation"
            / "coordinator.py"
        )
        spec = importlib.util.spec_from_file_location(
            "custom_components.universal_room_automation.coordinator_real_for_tests",
            src,
        )
        coord = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(coord)
    return coord


_BOUND_METHODS: dict[str, callable] = {}


def _ensure_methods_bound() -> None:
    if _BOUND_METHODS:
        return
    coord_mod = _load_real_coordinator_module()
    cls = coord_mod.UniversalRoomCoordinator
    for name in _RESOLVER_METHODS:
        _BOUND_METHODS[name] = getattr(cls, name)


def _make_coord(room_name: str = "Master Hallway", entry_id: str = "entry_abc123"):
    """Build a plain shim whose resolver methods are the REAL ones."""
    _ensure_methods_bound()
    hass = _MockHass()
    entry = SimpleNamespace(
        entry_id=entry_id,
        data={"room_name": room_name},
        options={},
    )
    coord = _ResolverShim()
    coord.hass = hass
    coord.entry = entry
    coord._switch_entity_id_cache = {}
    coord._switch_entity_id_miss_count = {}
    for name, func in _BOUND_METHODS.items():
        setattr(coord, name, types.MethodType(func, coord))
    return coord


# -------------------- resolver tests --------------------

def test_single_prefix_fallback_resolves_and_gates_off(monkeypatch):
    registry = _MockRegistry()
    _install_fake_er(monkeypatch, registry)
    coord = _make_coord("Master Hallway", "entry_single")
    # Legacy single-prefix entity exists in states only (not in registry).
    coord.hass.states.set("switch.master_hallway_automation", "off")

    assert coord._resolve_room_switch_entity_id("automation") == "switch.master_hallway_automation"
    assert coord._get_room_switch_state("automation") is False
    assert coord._is_automation_enabled() is False  # OFF honoured


def test_double_prefix_registry_resolves_and_gates_off(monkeypatch):
    """Live bug: on new rooms HA names the entity switch.{slug}_{slug}_{suffix}.
    The old name-built lookup missed it; _is_automation_enabled defaulted True."""
    registry = _MockRegistry()
    entry_id = "entry_dp"
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
    _install_fake_er(monkeypatch, registry)

    coord = _make_coord("Master Hallway", entry_id)
    for suffix, eid in double.items():
        coord.hass.states.set(eid, "off")
    assert coord.hass.states.get("switch.master_hallway_automation") is None

    assert coord._resolve_room_switch_entity_id("automation") == double["automation"]
    assert coord._is_automation_enabled() is False  # Automation OFF honoured
    coord.hass.states.set(double["automation"], "on")
    coord.hass.states.set(double["manual_mode"], "on")
    coord._switch_entity_id_cache.clear()
    assert coord._is_automation_enabled() is False  # ManualMode wins
    coord.hass.states.set(double["manual_mode"], "off")
    assert coord._is_automation_enabled() is True
    coord.hass.states.set(double["ai_automation"], "off")
    assert coord._is_ai_automation_enabled() is False
    coord.hass.states.set(double["ai_automation"], "on")
    assert coord._is_ai_automation_enabled() is True
    coord.hass.states.set(double["cover_automation"], "off")
    assert coord._is_cover_automation_enabled() is False
    coord.hass.states.set(double["override_occupied"], "on")
    assert coord._is_override_occupied() is True
    coord.hass.states.set(double["override_vacant"], "on")
    assert coord._is_override_vacant() is True


def test_renamed_entity_id_still_resolves_via_registry(monkeypatch):
    registry = _MockRegistry()
    entry_id = "entry_renamed"
    from custom_components.universal_room_automation.const import DOMAIN
    renamed = "switch.hallway_main_toggle"
    registry.register("switch", DOMAIN, f"{entry_id}_automation", renamed)
    _install_fake_er(monkeypatch, registry)

    coord = _make_coord("Master Hallway", entry_id)
    coord.hass.states.set(renamed, "off")
    assert coord.hass.states.get("switch.master_hallway_automation") is None
    assert coord._resolve_room_switch_entity_id("automation") == renamed
    assert coord._is_automation_enabled() is False


def test_rename_after_cache_invalidates_and_reresolves(monkeypatch):
    registry = _MockRegistry()
    entry_id = "entry_cache"
    from custom_components.universal_room_automation.const import DOMAIN
    old_id = "switch.master_hallway_master_hallway_automation"
    new_id = "switch.hallway_toggle"
    registry.register("switch", DOMAIN, f"{entry_id}_automation", old_id)
    _install_fake_er(monkeypatch, registry)

    coord = _make_coord("Master Hallway", entry_id)
    coord.hass.states.set(old_id, "on")
    assert coord._is_automation_enabled() is True

    coord.hass.states.remove(old_id)
    registry.register("switch", DOMAIN, f"{entry_id}_automation", new_id)
    coord.hass.states.set(new_id, "off")

    assert coord._is_automation_enabled() is False


def test_missing_switch_warns_once_on_second_miss(monkeypatch, caplog):
    """First-refresh race tolerance: a single miss (platform not yet set up)
    must NOT burn the warn — warn on the SECOND consecutive miss, exactly once."""
    import logging  # noqa: PLC0415
    registry = _MockRegistry()
    _install_fake_er(monkeypatch, registry)
    coord = _make_coord("Ghost Room", "entry_ghost")

    def _warn_count(suffix: str) -> int:
        marker = f"'{suffix}' not found"
        return sum(1 for r in caplog.records if marker in r.getMessage())

    with caplog.at_level(logging.WARNING, logger="custom_components.universal_room_automation.coordinator"):
        # Miss #1 per suffix — no warning yet (first-refresh race tolerance).
        assert coord._is_automation_enabled() is True
        assert coord._switch_entity_id_miss_count["automation"] == 1
        assert _warn_count("automation") == 0
        assert _warn_count("manual_mode") == 0

        # Miss #2 per suffix — warning emitted exactly once per suffix.
        assert coord._is_automation_enabled() is True
        assert _warn_count("automation") == 1
        assert _warn_count("manual_mode") == 1

        # Miss #3 per suffix — still exactly one warning each (idempotent).
        assert coord._is_automation_enabled() is True
        assert _warn_count("automation") == 1
        assert _warn_count("manual_mode") == 1

    # Defaults: cover absent → True; overrides absent → False.
    assert coord._is_cover_automation_enabled() is True
    assert coord._is_override_occupied() is False
    assert coord._is_override_vacant() is False


def test_resolver_success_clears_miss_count(monkeypatch):
    """A real resolve after a transient miss (platform now up) must clear
    the counter so a later true miss will warn on its 2nd occurrence."""
    registry = _MockRegistry()
    _install_fake_er(monkeypatch, registry)
    coord = _make_coord("Master Hallway", "entry_rc")

    # Simulate first-refresh miss (platform not up yet).
    assert coord._resolve_room_switch_entity_id("automation") is None
    assert coord._switch_entity_id_miss_count["automation"] == 1

    # Platform sets up — register the real entity, resolve succeeds.
    from custom_components.universal_room_automation.const import DOMAIN
    eid = "switch.master_hallway_master_hallway_automation"
    registry.register("switch", DOMAIN, "entry_rc_automation", eid)
    coord.hass.states.set(eid, "on")
    assert coord._resolve_room_switch_entity_id("automation") == eid
    # Miss counter cleared on successful resolve.
    assert "automation" not in coord._switch_entity_id_miss_count


# -------------------- behavioral wire-in: gate at coordinator.py:5060 --------

@pytest.mark.asyncio
async def test_double_prefix_automation_off_skips_handle_occupancy_change(monkeypatch):
    """Behavioral anchor for the occupancy-change gate (coordinator.py:5060):
    with ONLY the HA double-prefix id present (the live bug surface),
    Automation OFF must suppress automation.handle_occupancy_change, and
    Automation ON must invoke it. Mirrors the real gate block
    (`elif self._is_automation_enabled(): if occupied != last: await ...`)
    so a mutation that neuters _is_automation_enabled at the call site
    reddens this test."""
    registry = _MockRegistry()
    entry_id = "entry_gate"
    automation_eid = "switch.master_hallway_master_hallway_automation"
    manual_eid = "switch.master_hallway_master_hallway_manual_mode"
    from custom_components.universal_room_automation.const import DOMAIN
    registry.register("switch", DOMAIN, f"{entry_id}_automation", automation_eid)
    registry.register("switch", DOMAIN, f"{entry_id}_manual_mode", manual_eid)
    _install_fake_er(monkeypatch, registry)

    coord = _make_coord("Master Hallway", entry_id)
    coord.hass.states.set(manual_eid, "off")
    coord.hass.states.set(automation_eid, "off")
    coord._last_occupied_state = False
    coord._last_occupancy_source = "none"
    coord.automation = types.SimpleNamespace(handle_occupancy_change=AsyncMock())

    data_entered = {"occupied": True, "occupancy_source": "motion"}

    async def _drive_gate(data):
        """Reproduce the gated branch at coordinator.py:5060-5069 verbatim."""
        if coord._is_automation_enabled():
            if data["occupied"] != coord._last_occupied_state:
                coord._last_occupied_state = data["occupied"]
                coord._last_occupancy_source = data["occupancy_source"]
                await coord.automation.handle_occupancy_change(data["occupied"], data)

    # OFF path — gate suppresses, no automation call.
    await _drive_gate(data_entered)
    coord.automation.handle_occupancy_change.assert_not_awaited()

    # Flip ON — same occupancy change now routes through.
    coord.hass.states.set(automation_eid, "on")
    coord._switch_entity_id_cache.clear()
    coord._last_occupied_state = False
    await _drive_gate(data_entered)
    coord.automation.handle_occupancy_change.assert_awaited_once_with(True, data_entered)


# -------------------- behavioral wire-in: override mutex via switch.py --------

@pytest.mark.asyncio
async def test_override_occupied_turns_off_double_prefix_vacant(monkeypatch):
    """OverrideOccupiedSwitch.async_turn_on must find the OTHER override via
    the registry resolver (not the single-prefix name-built slug). With only
    double-prefix entities present, turning on occupied must dispatch
    `switch.turn_off` against the double-prefix vacant entity_id."""
    registry = _MockRegistry()
    entry_id = "entry_mutex_a"
    occ_eid = "switch.master_hallway_master_hallway_override_occupied"
    vac_eid = "switch.master_hallway_master_hallway_override_vacant"
    from custom_components.universal_room_automation.const import DOMAIN
    registry.register("switch", DOMAIN, f"{entry_id}_override_occupied", occ_eid)
    registry.register("switch", DOMAIN, f"{entry_id}_override_vacant", vac_eid)
    _install_fake_er(monkeypatch, registry)

    coord = _make_coord("Master Hallway", entry_id)
    coord.hass.states.set(vac_eid, "on")  # the OTHER override is currently on

    from custom_components.universal_room_automation.switch import OverrideOccupiedSwitch
    sw = OverrideOccupiedSwitch.__new__(OverrideOccupiedSwitch)
    sw.coordinator = coord
    sw.hass = coord.hass
    sw._attr_is_on = False
    sw.async_write_ha_state = lambda: None  # bypass HA entity plumbing

    await sw.async_turn_on()

    assert sw._attr_is_on is True
    # Mutex call targeted the DOUBLE-PREFIX vacant id — resolver load-bearing.
    coord.hass.services.async_call.assert_awaited_once_with(
        "switch", "turn_off", {"entity_id": vac_eid},
    )


@pytest.mark.asyncio
async def test_override_vacant_turns_off_double_prefix_occupied(monkeypatch):
    """Symmetric: OverrideVacantSwitch.async_turn_on must target the real
    double-prefix occupied entity_id."""
    registry = _MockRegistry()
    entry_id = "entry_mutex_b"
    occ_eid = "switch.master_hallway_master_hallway_override_occupied"
    vac_eid = "switch.master_hallway_master_hallway_override_vacant"
    from custom_components.universal_room_automation.const import DOMAIN
    registry.register("switch", DOMAIN, f"{entry_id}_override_occupied", occ_eid)
    registry.register("switch", DOMAIN, f"{entry_id}_override_vacant", vac_eid)
    _install_fake_er(monkeypatch, registry)

    coord = _make_coord("Master Hallway", entry_id)
    coord.hass.states.set(occ_eid, "on")

    from custom_components.universal_room_automation.switch import OverrideVacantSwitch
    sw = OverrideVacantSwitch.__new__(OverrideVacantSwitch)
    sw.coordinator = coord
    sw.hass = coord.hass
    sw._attr_is_on = False
    sw.async_write_ha_state = lambda: None

    await sw.async_turn_on()

    coord.hass.services.async_call.assert_awaited_once_with(
        "switch", "turn_off", {"entity_id": occ_eid},
    )
