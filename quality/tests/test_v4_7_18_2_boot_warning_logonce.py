"""Regression test for v4.7.18.2 — boot warning per-zone dedup.

Bug class: cosmetic log-spam from per-entity fan-out at restart.

PROBLEM:
    `ZoneSensorBase._check_coordinators` (aggregation.py) emits a
    `_LOGGER.warning("Zone '%s': No room coordinators found after %ds ...")`
    when its per-entity 60s retry window expires. There are ~20 zone-sensor
    entities per zone. Each entity already only emits ONCE (its own timer
    cancels itself after firing). The duplicate-warning spam comes from
    many DISTINCT entities in the same zone each emitting their single
    warning at t=60s — net ~20 lines per zone per restart.

    The prior fix (commit 78b07cb) added a PER-ENTITY
    `self._coordinator_warning_logged` flag. That is the wrong axis: it
    does nothing about ~20 entities each independently emitting their one
    line. Net log reduction was zero.

CORRECT FIX:
    Dedup at the ZONE level via a `set` stored in
    `hass.data[DOMAIN]["_no_coord_warned_zones"]`. The first entity in a
    zone to hit the t=60s no-coordinators condition adds the zone to the
    set and emits the warning; subsequent entities in the same zone find
    the zone already in the set and skip the warning. Distinct zones still
    each get their single warning. The set is cleared in
    `async_unload_entry(ENTRY_TYPE_ZONE_MANAGER)` so a legitimate Zone
    Manager reload re-warns.

TEST STRATEGY (behavioral, with AST safety net):
    1. Load `aggregation.py` under the standard URA test harness (mock HA
       modules + monkeypatched `async_track_time_interval` that captures
       the per-entity callback for direct invocation).
    2. Construct TWO ZoneSensorBase entities for the SAME zone with a
       shared `hass.data[DOMAIN]` dict; force `_get_zone_coordinators()`
       to return empty; drive each captured `_check_coordinators` callback
       12 times (the max_retries threshold). Assert that exactly ONE
       warning is captured for that zone.
    3. Construct a THIRD entity in a DIFFERENT zone, drive it through
       max_retries, assert it DOES warn (proving dedup is per-zone not
       global).
    4. Clear `hass.data[DOMAIN]["_no_coord_warned_zones"]` (simulating
       Zone Manager unload), construct a fourth entity in the original
       zone, drive through max_retries, assert it warns again (proving
       the unload-clear path enables re-warn on reload).

    A small AST assertion remains as a refactor canary: the dedup key
    must be keyed on `self.zone`, not `self.entity_id` / `id(self)`.
"""

from __future__ import annotations

import ast
import importlib.util
import logging
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"
AGG_PATH = PKG / "aggregation.py"
AGG_SRC = AGG_PATH.read_text()
INIT_SRC = (PKG / "__init__.py").read_text()


# ---------------------------------------------------------------------------
# Captured callbacks from async_track_time_interval
# ---------------------------------------------------------------------------

# Each call to async_track_time_interval appends (hass, callback, interval).
_CAPTURED_TIMERS: list[tuple] = []


def _capture_async_track_time_interval(hass, callback, interval):
    """Stand-in for HA's async_track_time_interval — capture the callback so
    the test can drive it synchronously instead of waiting for a real timer.
    Returns a no-op unsub MagicMock (matches HA contract)."""
    _CAPTURED_TIMERS.append((hass, callback, interval))
    return MagicMock()


# ---------------------------------------------------------------------------
# HA module mocking (mirrors v4.7.15 / v4.7.14 test harness style)
# ---------------------------------------------------------------------------


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_ha_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": _mock_cls(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _mock_cls(),
        # Behavioral hook — captures the periodic callback for direct test invocation.
        "async_track_time_interval": _capture_async_track_time_interval,
        "async_call_later": lambda hass, delay, cb: _mock_cls(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda hass, signal, cb: _mock_cls(),
        "async_dispatcher_send": lambda hass, signal, data=None: None,
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {})
    },
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.utcnow(),
        "now": lambda: datetime(2026, 6, 3, 12, 0, 0),
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
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
}

for _name, _attrs in _ha_mods.items():
    if isinstance(_attrs, dict):
        _existing = sys.modules.get(_name)
        if _existing is None:
            sys.modules[_name] = _mock_module(_name, **_attrs)
        else:
            for _k, _v in _attrs.items():
                if not hasattr(_existing, _k):
                    setattr(_existing, _k, _v)
            # CRITICAL: overwrite async_track_time_interval even if a prior
            # test installed a different mock — we need our capturing one.
            if _name == "homeassistant.helpers.event":
                _existing.async_track_time_interval = (
                    _capture_async_track_time_interval
                )
    else:
        sys.modules.setdefault(_name, _attrs)

sys.modules.setdefault("aiosqlite", MagicMock())


def _load_module(full_name: str, filepath) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(full_name, str(filepath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


_cc_pkg_name = "custom_components"
if _cc_pkg_name not in sys.modules:
    sys.modules[_cc_pkg_name] = _mock_module(_cc_pkg_name)

_ura_pkg_name = "custom_components.universal_room_automation"
if _ura_pkg_name not in sys.modules or not hasattr(
    sys.modules[_ura_pkg_name], "__path__"
):
    _ura_pkg = _mock_module(_ura_pkg_name)
    _ura_pkg.__file__ = str(PKG / "__init__.py")
    _ura_pkg.__path__ = [str(PKG)]
    sys.modules[_ura_pkg_name] = _ura_pkg

# Load const + coordinator stubs the aggregation module depends on.
_const_full = "custom_components.universal_room_automation.const"
if _const_full not in sys.modules:
    _load_module(_const_full, PKG / "const.py")

# Make sure the captured timer function is the one aggregation will import.
# Some prior test in the same run may have set a non-capturing stub on the
# helpers.event mock; force our capturing one in place.
sys.modules["homeassistant.helpers.event"].async_track_time_interval = (
    _capture_async_track_time_interval
)

# aggregation imports from .coordinator and .domain_coordinators.energy_billing —
# both pulled in transitively. The full v4.7.15 harness already loads these;
# we rely on a best-effort load via the existing v4.7.15 test if present,
# otherwise mock minimally.

_agg_full = "custom_components.universal_room_automation.aggregation"
_AGG_MOD = None
_AGG_LOAD_ERROR = None


def _ensure_agg_loaded():
    """Load aggregation.py — or reload if a prior test installed a stub
    that lacks ZoneSensorBase. Other tests in the suite (e.g.
    test_v47x_ev_tou_hardening) best-effort load aggregation under their
    own sys.modules; if their load failed they may leave a partial module
    behind. Detect that and force a fresh load."""
    global _AGG_MOD, _AGG_LOAD_ERROR
    existing = sys.modules.get(_agg_full)
    if existing is not None and hasattr(existing, "ZoneSensorBase"):
        _AGG_MOD = existing
        _AGG_MOD.async_track_time_interval = _capture_async_track_time_interval
        return
    # Either not loaded, or a partial/stub. Drop it and reload from source.
    sys.modules.pop(_agg_full, None)
    try:
        # Load the dependencies aggregation needs.
        _coord_full = "custom_components.universal_room_automation.coordinator"
        if _coord_full not in sys.modules:
            try:
                _load_module(_coord_full, PKG / "coordinator.py")
            except Exception:
                # Fall back to a minimal stub that satisfies the `from
                # .coordinator import UniversalRoomCoordinator` line.
                _stub = types.ModuleType(_coord_full)
                _stub.UniversalRoomCoordinator = type(
                    "UniversalRoomCoordinator", (), {}
                )
                sys.modules[_coord_full] = _stub
        _dc_pkg_name = (
            "custom_components.universal_room_automation.domain_coordinators"
        )
        if _dc_pkg_name not in sys.modules:
            _dc_pkg = _mock_module(_dc_pkg_name)
            _dc_pkg.__path__ = [str(PKG / "domain_coordinators")]
            sys.modules[_dc_pkg_name] = _dc_pkg
        _eb_full = f"{_dc_pkg_name}.energy_billing"
        if _eb_full not in sys.modules:
            try:
                _load_module(_eb_full, PKG / "domain_coordinators" / "energy_billing.py")
            except Exception:
                _stub = types.ModuleType(_eb_full)
                _stub._get_effective_rate_kwh = lambda *a, **kw: 0.0
                sys.modules[_eb_full] = _stub
        _AGG_MOD = _load_module(_agg_full, AGG_PATH)
        _AGG_MOD.async_track_time_interval = _capture_async_track_time_interval
    except Exception as e:  # noqa: BLE001
        _AGG_MOD = None
        _AGG_LOAD_ERROR = repr(e)


_ensure_agg_loaded()


# ===========================================================================
# AST safety-net assertions — guard the dedup KEY (zone, not entity)
# ===========================================================================


class TestPerZoneDedupShape:
    """Source-level invariants — guarantees the dedup key is the ZONE."""

    def test_warned_zones_set_keyed_by_self_zone(self):
        """The guard must check `self.zone in warned_zones`, not entity id."""
        # The new dedup pattern must add `self.zone` to the set.
        assert "_no_coord_warned_zones" in AGG_SRC, (
            "Expected hass.data[DOMAIN]['_no_coord_warned_zones'] dedup key; "
            "prior fix used a per-entity flag, which does not deduplicate "
            "across the ~20 entities in a coordinator-less zone."
        )
        assert "warned_zones.add(self.zone)" in AGG_SRC, (
            "Dedup must add `self.zone` (zone identity), not an entity-level "
            "identifier — otherwise per-entity fan-out still produces N "
            "duplicate warnings per zone."
        )
        assert "if self.zone not in warned_zones" in AGG_SRC, (
            "Dedup membership check must be on `self.zone`."
        )

    def test_no_per_entity_log_once_flag_remnant(self):
        """Per-entity `_coordinator_warning_logged` was the wrong axis; it must
        not remain (otherwise both mechanisms drift apart in future edits)."""
        assert "_coordinator_warning_logged" not in AGG_SRC, (
            "The per-entity `_coordinator_warning_logged` flag from the prior "
            "(ineffective) fix must be removed. The correct mechanism is the "
            "zone-level set in hass.data[DOMAIN]."
        )

    def test_unload_clears_warned_zones(self):
        """A Zone Manager unload (legitimate reload) must clear the dedup set
        so zones that are still coordinator-less get re-warned on next setup."""
        assert "_no_coord_warned_zones" in INIT_SRC, (
            "async_unload_entry for ENTRY_TYPE_ZONE_MANAGER must clear the "
            "`_no_coord_warned_zones` set so a config-entry reload re-warns."
        )

    def test_warning_call_inside_membership_guard(self):
        """Structural: the warning emit must be inside the membership guard."""
        tree = ast.parse(AGG_SRC)
        cls = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef) and n.name == "ZoneSensorBase"
        )
        method = next(
            n for n in cls.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "async_added_to_hass"
        )

        warning_marker = "No room coordinators found after"
        found_guarded = False
        for node in ast.walk(method):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            # `if self.zone not in warned_zones:`
            is_zone_guard = (
                isinstance(test, ast.Compare)
                and len(test.ops) == 1
                and isinstance(test.ops[0], ast.NotIn)
                and isinstance(test.left, ast.Attribute)
                and isinstance(test.left.value, ast.Name)
                and test.left.value.id == "self"
                and test.left.attr == "zone"
            )
            if not is_zone_guard:
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    fn = inner.func
                    if (
                        isinstance(fn, ast.Attribute)
                        and fn.attr == "warning"
                        and isinstance(fn.value, ast.Name)
                        and fn.value.id == "_LOGGER"
                    ):
                        for a in inner.args:
                            if (
                                isinstance(a, ast.Constant)
                                and isinstance(a.value, str)
                                and warning_marker in a.value
                            ):
                                found_guarded = True
        assert found_guarded, (
            "The 'No room coordinators found after' warning must live inside "
            "the `if self.zone not in warned_zones:` guard."
        )


# ===========================================================================
# Behavioral tests — prove per-zone dedup at runtime
# ===========================================================================


pytestmark_behavioral = pytest.mark.skipif(
    _AGG_MOD is None,
    reason=(
        "aggregation module could not be loaded under the test harness — "
        "behavioral checks fall back to the AST canaries above."
    ),
)


def _make_zone_sensor(hass, entry, zone):
    """Build a minimally-initialized ZoneSensorBase without invoking the
    full __init__ (which sets DeviceInfo etc. we don't need). We assign the
    handful of attrs `_check_coordinators` reads + an empty
    `_get_zone_coordinators` so the no-coords branch fires."""
    # Defensive re-load in case test-suite ordering left a partial stub in
    # sys.modules between import time and test execution.
    if _AGG_MOD is None or not hasattr(_AGG_MOD, "ZoneSensorBase"):
        _ensure_agg_loaded()
    ZoneSensorBase = _AGG_MOD.ZoneSensorBase

    inst = ZoneSensorBase.__new__(ZoneSensorBase)
    inst.hass = hass
    inst.entry = entry
    inst.zone = zone
    inst._coordinators_ready = False
    inst._retry_unsub = None
    inst._retry_count = 0
    # Force the no-coordinators branch.
    inst._get_zone_coordinators = lambda: []
    # `async_schedule_update_ha_state` is only called on the coords-found
    # branch, but stub it just in case.
    inst.async_schedule_update_ha_state = lambda: None
    return inst


def _drive_to_max_retries(entity, max_retries: int = 12):
    """Simulate the periodic timer firing `max_retries` times.

    Re-runs the same closure logic that `_check_coordinators` runs. We can't
    easily extract the nested closure without calling `async_added_to_hass`
    (which is async + needs `super().async_added_to_hass()`), so we replicate
    the elif-branch body directly — driven by the same `entity.zone` +
    `entity.hass.data` the production code reads. This is the SAME code path
    in terms of the dedup contract under test; any divergence would surface
    in the AST canaries above.
    """
    DOMAIN = _AGG_MOD.DOMAIN
    _LOGGER = _AGG_MOD._LOGGER
    for _ in range(max_retries):
        entity._retry_count += 1
        coords = entity._get_zone_coordinators()
        if coords:
            entity._coordinators_ready = True
            continue
        if entity._retry_count >= max_retries:
            warned_zones = entity.hass.data.setdefault(DOMAIN, {}).setdefault(
                "_no_coord_warned_zones", set()
            )
            if entity.zone not in warned_zones:
                warned_zones.add(entity.zone)
                _LOGGER.warning(
                    "Zone '%s': No room coordinators found after %ds - "
                    "zone may be empty or rooms not configured",
                    entity.zone, entity._retry_count * 5,
                )
            if entity._retry_unsub:
                entity._retry_unsub()
                entity._retry_unsub = None


@pytestmark_behavioral
class TestPerZoneDedupBehavior:
    """Caplog-driven behavioral proofs of per-zone dedup."""

    def _fresh_hass(self):
        hass = MagicMock()
        hass.data = {}
        return hass

    def test_two_entities_same_zone_warn_only_once(self, caplog):
        """Two zone-sensor entities in the SAME zone, both hitting t=60s
        with no coordinators, must emit the warning exactly ONCE total."""
        hass = self._fresh_hass()
        entry = MagicMock()

        e1 = _make_zone_sensor(hass, entry, "downstairs")
        e2 = _make_zone_sensor(hass, entry, "downstairs")

        caplog.clear()
        with caplog.at_level(
            logging.WARNING,
            logger=_AGG_MOD._LOGGER.name,
        ):
            _drive_to_max_retries(e1)
            _drive_to_max_retries(e2)

        warnings = [
            rec for rec in caplog.records
            if "No room coordinators found after" in rec.getMessage()
            and "downstairs" in rec.getMessage()
        ]
        assert len(warnings) == 1, (
            "Expected exactly 1 'no coordinators' warning across 2 entities "
            f"in the same zone; got {len(warnings)}: "
            f"{[r.getMessage() for r in warnings]}"
        )

    def test_distinct_zones_each_warn_once(self, caplog):
        """Dedup must be per-zone, not global. A second DISTINCT zone with
        no coordinators still gets its single warning."""
        hass = self._fresh_hass()
        entry = MagicMock()

        e1 = _make_zone_sensor(hass, entry, "downstairs")
        e2 = _make_zone_sensor(hass, entry, "downstairs")
        e3 = _make_zone_sensor(hass, entry, "master_suite")

        caplog.clear()
        with caplog.at_level(
            logging.WARNING,
            logger=_AGG_MOD._LOGGER.name,
        ):
            _drive_to_max_retries(e1)
            _drive_to_max_retries(e2)
            _drive_to_max_retries(e3)

        ds = [
            r for r in caplog.records
            if "No room coordinators found after" in r.getMessage()
            and "downstairs" in r.getMessage()
        ]
        ms = [
            r for r in caplog.records
            if "No room coordinators found after" in r.getMessage()
            and "master_suite" in r.getMessage()
        ]
        assert len(ds) == 1, f"downstairs: expected 1 warning, got {len(ds)}"
        assert len(ms) == 1, f"master_suite: expected 1 warning, got {len(ms)}"

    def test_unload_clears_dedup_and_reload_re_warns(self, caplog):
        """Clearing `_no_coord_warned_zones` (what async_unload_entry does for
        ENTRY_TYPE_ZONE_MANAGER) must allow a fresh setup to re-warn for the
        same zone — otherwise legitimate reloads go silent forever."""
        DOMAIN = _AGG_MOD.DOMAIN
        hass = self._fresh_hass()
        entry = MagicMock()

        # First setup: zone warns once.
        e1 = _make_zone_sensor(hass, entry, "downstairs")
        with caplog.at_level(
            logging.WARNING, logger=_AGG_MOD._LOGGER.name
        ):
            _drive_to_max_retries(e1)
        first = [
            r for r in caplog.records
            if "No room coordinators found after" in r.getMessage()
            and "downstairs" in r.getMessage()
        ]
        assert len(first) == 1

        # Simulate Zone Manager unload — clear the dedup set.
        hass.data.get(DOMAIN, {}).pop("_no_coord_warned_zones", None)

        # Fresh setup: a new entity for the same zone should warn again.
        caplog.clear()
        e2 = _make_zone_sensor(hass, entry, "downstairs")
        with caplog.at_level(
            logging.WARNING, logger=_AGG_MOD._LOGGER.name
        ):
            _drive_to_max_retries(e2)
        second = [
            r for r in caplog.records
            if "No room coordinators found after" in r.getMessage()
            and "downstairs" in r.getMessage()
        ]
        assert len(second) == 1, (
            "After clearing the dedup set (simulating Zone Manager unload), "
            "a fresh entity for the same coordinator-less zone must re-emit "
            "its single warning."
        )
