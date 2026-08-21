"""AC14 + AC14b — BEHAVIOURAL drive of ``_apply_house_state_presets``.

Companion to ``test_hvac_excursion_lease_gate_placement.py`` (structural).
Per operator: a source-text line-ordering assertion is Bug Class #62 and
does not qualify as the anchor. This file exercises the REAL production
method end-to-end.

Fixture: HVACCoordinator instance built via ``__new__`` (skips heavy
__init__) with the minimum attributes ``_apply_house_state_presets``
reads on the vacancy-bypass path. Preset writes are captured by
patching ``emit_set_preset_mode`` on the module.

AC14 (positive control + gate honoured): without a lease, a home->away
tick writes the preset. WITH a lease, the same tick writes nothing.

AC14b (the mandatory one): the tick must specifically traverse the
vacancy-bypass arm at ``hvac.py:1906-1909`` (`if zi and
(zone_vacant_past_grace or zone.runtime_exceeded) and effective_preset
== "away"`) — that arm skips ``should_change_preset`` entirely. A gate
placed BEFORE ``should_change_preset`` would leave this arm unreachable
and would let a vacancy sweep write ``away`` through a live excursion.
The AC14b test proves the vacancy arm is honoured by the gate.

Harness pattern adapted from
``test_hvac_vacancy_sweep_manual_on_guard.py``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# HA module mocking (same shape as sibling test)
# ---------------------------------------------------------------------------

def _mock_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_ha_mods: dict = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
        "CALLBACK_TYPE": object,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": _mock_module(
        "homeassistant.const",
        SERVICE_TURN_ON="turn_on",
        SERVICE_TURN_OFF="turn_off",
        STATE_ON="on",
        STATE_OFF="off",
        STATE_UNAVAILABLE="unavailable",
        STATE_UNKNOWN="unknown",
    ),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict, "EntityCategory": _mock_cls(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _mock_cls(),
        "async_track_time_interval": lambda hass, cb, interval: _mock_cls(),
        "async_call_later": lambda hass, delay, cb: _mock_cls(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda hass, signal, cb: _mock_cls(),
        "async_dispatcher_send": lambda hass, signal, data=None: None,
    },
    "homeassistant.helpers.storage": {"Store": _mock_cls},
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {"is_up": lambda hass: True},
    "homeassistant.util": {},
    "homeassistant.components": {},
    "homeassistant.components.recorder": {"get_instance": _mock_cls()},
    "homeassistant.components.recorder.history": {
        "get_significant_states": _mock_cls(),
    },
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(), "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
}


_dt_now_fn = lambda: datetime.now(timezone.utc)  # noqa: E731


def _parse_dt(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


_dt_mock = _mock_module(
    "homeassistant.util.dt",
    utcnow=lambda: _dt_now_fn(),
    now=lambda: _dt_now_fn(),
    as_local=lambda dt: dt,
    parse_datetime=_parse_dt,
)

_MISSING = object()

for _name, _attrs in _ha_mods.items():
    if isinstance(_attrs, dict):
        _existing = sys.modules.get(_name)
        if _existing is None:
            sys.modules[_name] = _mock_module(_name, **_attrs)
        else:
            for _k, _v in _attrs.items():
                setattr(_existing, _k, _v)
    else:
        sys.modules.setdefault(_name, _attrs)

_HA_DT_ORIG = sys.modules.get("homeassistant.util.dt", _MISSING)
sys.modules["homeassistant.util.dt"] = _dt_mock
sys.modules.setdefault("aiosqlite", MagicMock())


_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
_ura_root = os.path.join(
    _project_root, "custom_components", "universal_room_automation",
)


def _load_module(full_name: str, filepath: str) -> types.ModuleType:
    existing = sys.modules.get(full_name)
    if (
        existing is not None
        and isinstance(existing, types.ModuleType)
        and isinstance(getattr(existing, "__file__", None), str)
        and os.path.isfile(existing.__file__)
    ):
        return existing
    spec = importlib.util.spec_from_file_location(full_name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


if "custom_components" not in sys.modules:
    _cc_pkg = _mock_module("custom_components")
    _cc_pkg.__path__ = [os.path.join(_project_root, "custom_components")]
    sys.modules["custom_components"] = _cc_pkg
else:
    _existing_cc = sys.modules["custom_components"]
    if not getattr(_existing_cc, "__path__", None):
        _existing_cc.__path__ = [os.path.join(_project_root, "custom_components")]
if "custom_components.universal_room_automation" not in sys.modules:
    _ura_pkg = _mock_module("custom_components.universal_room_automation")
    _ura_pkg.__file__ = os.path.join(_ura_root, "__init__.py")
    _ura_pkg.__path__ = [_ura_root]
    sys.modules["custom_components.universal_room_automation"] = _ura_pkg
else:
    _existing_ura = sys.modules["custom_components.universal_room_automation"]
    if not getattr(_existing_ura, "__path__", None):
        _existing_ura.__path__ = [_ura_root]
    if not getattr(_existing_ura, "__file__", None):
        _existing_ura.__file__ = os.path.join(_ura_root, "__init__.py")


_SNAPSHOT_KEYS = [
    "custom_components.universal_room_automation.const",
    "custom_components.universal_room_automation.fan_veto",
    "custom_components.universal_room_automation.domain_coordinators.house_state",
    "custom_components.universal_room_automation.domain_coordinators.signals",
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "custom_components.universal_room_automation.domain_coordinators.base",
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "custom_components.universal_room_automation.domain_coordinators.hvac_fans",
    "custom_components.universal_room_automation.domain_coordinators.hvac_covers",
    "custom_components.universal_room_automation.domain_coordinators.hvac_egress",
    "custom_components.universal_room_automation.domain_coordinators.hvac_preset",
    "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
    "custom_components.universal_room_automation.domain_coordinators.hvac_predict",
    "custom_components.universal_room_automation.domain_coordinators.hvac_excursion",
    "custom_components.universal_room_automation.domain_coordinators.hvac",
]
_MODULE_SNAPSHOT: dict = {k: sys.modules.get(k, _MISSING) for k in _SNAPSHOT_KEYS}

_load_module(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_root, "const.py"),
)
if "custom_components.universal_room_automation.domain_coordinators" not in sys.modules:
    _dc_pkg = _mock_module(
        "custom_components.universal_room_automation.domain_coordinators",
    )
    _dc_pkg.__file__ = os.path.join(
        _ura_root, "domain_coordinators", "__init__.py",
    )
    _dc_pkg.__path__ = [os.path.join(_ura_root, "domain_coordinators")]
    sys.modules[
        "custom_components.universal_room_automation.domain_coordinators"
    ] = _dc_pkg

_load_module(
    "custom_components.universal_room_automation.domain_coordinators.house_state",
    os.path.join(_ura_root, "domain_coordinators", "house_state.py"),
)
_load_module(
    "custom_components.universal_room_automation.fan_veto",
    os.path.join(_ura_root, "fan_veto.py"),
)

_SIBLING_LOAD_ORDER = [
    ("house_state", "domain_coordinators/house_state.py"),
    ("signals", "domain_coordinators/signals.py"),
    ("hvac_const", "domain_coordinators/hvac_const.py"),
    ("base", "domain_coordinators/base.py"),
    ("hvac_zones", "domain_coordinators/hvac_zones.py"),
    ("hvac_fans", "domain_coordinators/hvac_fans.py"),
    ("hvac_covers", "domain_coordinators/hvac_covers.py"),
    ("hvac_egress", "domain_coordinators/hvac_egress.py"),
    ("hvac_preset", "domain_coordinators/hvac_preset.py"),
    ("hvac_setpoint", "domain_coordinators/hvac_setpoint.py"),
    ("hvac_override", "domain_coordinators/hvac_override.py"),
    ("hvac_predict", "domain_coordinators/hvac_predict.py"),
    ("hvac_excursion", "domain_coordinators/hvac_excursion.py"),
]
for _leaf, _rel in _SIBLING_LOAD_ORDER:
    _fq = (
        "custom_components.universal_room_automation.domain_coordinators."
        + _leaf
    )
    _load_module(_fq, os.path.join(_ura_root, _rel))

_load_module(
    "custom_components.universal_room_automation.domain_coordinators.hvac",
    os.path.join(_ura_root, "domain_coordinators", "hvac.py"),
)

import custom_components.universal_room_automation.domain_coordinators.hvac as _hvac_mod  # noqa: E402
import custom_components.universal_room_automation.domain_coordinators.hvac_excursion as _ex_mod  # noqa: E402
from custom_components.universal_room_automation.domain_coordinators.hvac import (  # noqa: E402
    HVACCoordinator,
)
from custom_components.universal_room_automation.const import DOMAIN  # noqa: E402

for _k, _orig in _MODULE_SNAPSHOT.items():
    if _orig is _MISSING:
        sys.modules.pop(_k, None)
    else:
        sys.modules[_k] = _orig

# KEEP the excursion + hvac modules in sys.modules so the runtime
# `from .hvac_excursion import lease_active` inside HVACCoordinator
# resolves to the SAME module instance the tests seed leases on.
# (The generic snapshot restore above would otherwise pop them.)
sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_excursion"
] = _ex_mod
sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac"
] = _hvac_mod

# Pop only `homeassistant.helpers.storage` (not the whole HA tree) so
# test_hvac_excursion_d1_observability's `try: from homeassistant.helpers.storage
# import Store` gate for _HA_REAL doesn't falsely detect a real HA
# install from our mock. Other HA mocks stay resident so sibling tests
# that consume them (e.g. test_hvac_vacancy_sweep_manual_on_guard) still
# work when collected after this file. The d1 gate needs BOTH
# `helpers.storage` AND `util.dt` to succeed; util.dt is already popped
# above (via _HA_DT_ORIG restore).
sys.modules.pop("homeassistant.helpers.storage", None)
if _HA_DT_ORIG is _MISSING:
    sys.modules.pop("homeassistant.util.dt", None)
else:
    sys.modules["homeassistant.util.dt"] = _HA_DT_ORIG


_hvac_dt_util = _hvac_mod.dt_util


def _set_now(dt: datetime) -> None:
    fn = lambda: dt  # noqa: E731
    _dt_mock.now = fn
    _dt_mock.utcnow = fn
    _hvac_dt_util.now = fn
    _hvac_dt_util.utcnow = fn


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# Fixture — HVACCoordinator via __new__ with a single zone.
# ---------------------------------------------------------------------------

class _StubZone:
    """Minimum surface `_apply_house_state_presets` reads on a zone."""

    def __init__(
        self,
        zone_id: str,
        *,
        any_room_occupied: bool,
        last_occupied_time,
        hvac_mode: str = "heat_cool",
        preset_mode: str = "home",
        runtime_exceeded: bool = False,
    ):
        self.zone_id = zone_id
        self.zone_name = f"Zone{zone_id}"
        self.climate_entity = f"climate.zone_{zone_id}"
        self.any_room_occupied = any_room_occupied
        self.last_occupied_time = last_occupied_time
        self.hvac_mode = hvac_mode
        self.preset_mode = preset_mode
        self.runtime_exceeded = runtime_exceeded
        self.continuous_occupied_since = None
        self.current_session_start = None
        self.vacancy_sweep_done = True     # skip sweep code path
        self.vacancy_sweep_enabled = False
        self.zone_persons: list[str] = []


class _StubZoneManager:
    def __init__(self, zones: dict):
        self.zones = zones


class _StubPresetManager:
    def __init__(self, target_preset: str = "home"):
        self._target = target_preset
        self.change_calls: list = []

    def get_preset_for_house_state(self, house_state: str):
        return self._target

    def should_change_preset(self, current: str, target: str) -> bool:
        self.change_calls.append((current, target))
        return current != target


class _StubArrester:
    def __init__(self):
        self.suppress_calls: list = []
        self.unsuppress_calls: list = []

    def _supports_heat_cool(self, entity_id: str) -> bool:
        return True

    def has_active_ac_reset(self, zone_id: str) -> bool:
        return False

    def suppress(self, entity_id: str, **kwargs) -> None:
        self.suppress_calls.append((entity_id, kwargs))

    def unsuppress(self, entity_id: str) -> None:
        self.unsuppress_calls.append(entity_id)

    def comfort_delay_active(self, zone_id: str) -> bool:
        return False


class _StubEgressManager:
    def is_paused(self, zone_id: str) -> bool:
        return False


def _make_coord(zone: _StubZone, target_preset: str = "home"):
    """Return (coord, preset_write_log). All emit_set_preset_mode calls
    are captured in preset_write_log."""
    _ex_mod._test_clear_leases()
    _ex_mod._test_set_kill_switch(True)
    _ex_mod._test_bind(hass=None, db=None)  # in-memory only

    coord = HVACCoordinator.__new__(HVACCoordinator)
    coord._house_state = "home_day"
    coord._defer_gate_enabled = False
    coord._d6_gate_engaged = False
    coord._d6_deferrals_today = 0
    coord._zone_intelligence_enabled = True
    coord._vacancy_grace = 15               # minutes
    coord._vacancy_grace_constrained = 15
    coord._energy_constraint_mode = "normal"
    coord._max_occupancy_hours = 24
    coord._zone_entry_dwell = 0             # skip dwell
    coord._pre_arrival_zones = set()
    coord._vacancy_sweeps_today = 0
    coord._d3_skipped_current_tick = {}
    coord._last_offphase_emit = {}
    coord._night_trust_logged = set()
    coord._night_trust_logged_state = None
    coord._observation_mode = False
    coord._hvac_offphase_honesty_enabled = True
    coord._decision_logger = None
    coord._compliance = None
    coord.coordinator_id = "hvac"
    coord._excursion_primitive_enabled = True

    async def _noop_apply_overrides():
        return None
    coord._async_apply_preset_overrides = _noop_apply_overrides

    coord._zone_manager = _StubZoneManager({zone.zone_id: zone})
    coord._preset_manager = _StubPresetManager(target_preset)
    coord._override_arrester = _StubArrester()
    coord._egress_manager = _StubEgressManager()

    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.states = MagicMock()
    hass.states.get = lambda eid: None
    hass.services = MagicMock()
    async def _svc_call(*a, **kw):
        return None
    hass.services.async_call = _svc_call
    hass.async_create_task = lambda coro: coro.close() if hasattr(coro, "close") else None
    coord.hass = hass

    # Capture preset writes by patching the emit chokepoint at
    # module scope. Signature per hvac_setpoint.emit_set_preset_mode:
    # emit_set_preset_mode(hass, entity_id, preset, *, blocking, gate,
    #                      site, zone_id, reason)
    preset_write_log: list[dict] = []

    async def _capture(hass_, entity_id, preset, *, blocking=False,
                       gate=None, site=None, zone_id=None, reason=None,
                       **extra):
        # If gate says defer, respect it (matches production semantics).
        if gate is not None:
            try:
                if bool(gate()):
                    return False
            except Exception:
                pass
        preset_write_log.append({
            "entity_id": entity_id,
            "preset": preset,
            "site": site,
            "zone_id": zone_id,
            "reason": reason,
        })
        return True

    _hvac_mod.emit_set_preset_mode = _capture

    return coord, preset_write_log


# ---------------------------------------------------------------------------
# AC14 — general path (should_change_preset arm)
# ---------------------------------------------------------------------------

def test_AC14_positive_control_home_to_away_writes_without_lease():
    """No lease active — the general path emits the preset write.

    Not the vacancy arm (that's AC14b); this drives the
    `elif not should_change_preset(...)` arm by keeping the zone
    OCCUPIED and forcing target_preset != current."""
    base = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(base)
    zone = _StubZone(
        zone_id="z1",
        any_room_occupied=True,
        last_occupied_time=base,
        preset_mode="away",  # current
    )
    coord, log = _make_coord(zone, target_preset="home")
    _run(coord._apply_house_state_presets())
    assert any(w["preset"] == "home" for w in log), (
        f"positive control: expected a home preset write; log={log}"
    )


def test_AC14_lease_active_blocks_general_path_write():
    """Lease active — the general path defers, NO preset write.

    Mutation drill for the gate: this test fails if the lease check
    at hvac.py:~1955 is removed (a build with no gate emits normally)."""
    base = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(base)
    zone = _StubZone(
        zone_id="z1",
        any_room_occupied=True,
        last_occupied_time=base,
        preset_mode="away",
    )
    coord, log = _make_coord(zone, target_preset="home")
    _ex_mod._test_seed_lease("z1", duration_s=120)
    assert _ex_mod.lease_active("z1") is True
    _run(coord._apply_house_state_presets())
    assert log == [], (
        f"AC14: lease active must suppress preset write; log={log}"
    )


# ---------------------------------------------------------------------------
# AC14b — vacancy-bypass arm (MANDATORY, rev-5)
# ---------------------------------------------------------------------------

def _make_vacant_zone(base):
    """Zone that will drive the vacancy-bypass arm:
    - any_room_occupied=False + last_occupied_time far enough in the past
      => zone_vacant_past_grace = True (grace=15 min)
    - target_preset="home" + vacant_past_grace => effective_preset="away"
      via hvac.py:1599 path.
    - preset_mode="home" (not already away, so we don't hit the "already
      away" early continue).
    - The vacancy-bypass arm at hvac.py:1906-1909 then fires because
      zi=True, zone_vacant_past_grace=True, effective_preset='away'.
    """
    return _StubZone(
        zone_id="z1",
        any_room_occupied=False,
        last_occupied_time=base - timedelta(minutes=30),  # > grace
        preset_mode="home",
    )


def test_AC14b_vacancy_bypass_arm_positive_control_writes_without_lease():
    """Positive control: with no lease, the vacancy-bypass arm reaches
    the emit and writes preset=away. Confirms the fixture actually
    routes through the arm we care about."""
    base = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(base)
    zone = _make_vacant_zone(base)
    coord, log = _make_coord(zone, target_preset="home")
    _run(coord._apply_house_state_presets())
    # The vacancy arm produces reason="vacant_past_grace" (see the
    # reason ladder at hvac.py:~1949 - `elif effective_preset == "away"
    # and zone_vacant_past_grace`). This lets us confirm we're on the
    # right arm and not some other branch that also happens to write.
    assert any(
        w["preset"] == "away" and w["reason"] == "vacant_past_grace"
        for w in log
    ), (
        "Fixture check: expected a preset=away write from the "
        f"vacancy-bypass arm (reason=vacant_past_grace); log={log}. "
        "If reason is missing/different, the fixture is not routing "
        "through the vacancy-bypass arm and AC14b is not being tested."
    )
    # Also confirm the preset-manager consult was NOT reached — the
    # bypass arm's whole point is to skip it (comment at hvac.py:1905:
    # "Bypass should_change_preset() manual guard for vacancy").
    assert coord._preset_manager.change_calls == [], (
        "AC14b fixture: the vacancy arm must BYPASS should_change_preset; "
        f"but change_calls={coord._preset_manager.change_calls}. Adjust "
        "the fixture so vacancy branch is truly what drives the emit."
    )


def test_AC14b_vacancy_bypass_arm_gate_honoured_MANDATORY():
    """AC14b (mandatory) — with an active lease on Z, a tick that
    otherwise would route through the vacancy-bypass arm and write
    ``preset=away`` MUST write nothing.

    This is the single test that distinguishes the correct (rev-5)
    merge-point placement from the wrong (rev-4) pre-consult placement.
    A gate placed BEFORE should_change_preset is unreachable to this
    arm (the arm skips the consult); the emit would fire and the test
    would fail.
    """
    base = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(base)
    zone = _make_vacant_zone(base)
    coord, log = _make_coord(zone, target_preset="home")
    _ex_mod._test_seed_lease("z1", duration_s=120)
    assert _ex_mod.lease_active("z1") is True
    _run(coord._apply_house_state_presets())
    assert log == [], (
        "AC14b: with an active lease on Z, the vacancy-bypass arm "
        "MUST write nothing on the preset axis (gate at merge point). "
        f"log={log}. If any write appears, the gate is either missing "
        "or placed upstream of the vacancy bypass (rev-4 defect)."
    )


def test_AC14b_kill_switch_off_still_honours_existing_lease():
    """§4.7 BEGIN-ONLY semantics on the tick side: a lease that
    already exists MUST still be honoured whether the kill switch is
    ON or OFF. Flipping OFF only stops NEW excursions; it does not
    strand in-flight ones."""
    base = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
    _set_now(base)
    zone = _make_vacant_zone(base)
    coord, log = _make_coord(zone, target_preset="home")
    _ex_mod._test_seed_lease("z1", duration_s=120)
    _ex_mod._test_set_kill_switch(False)
    _run(coord._apply_house_state_presets())
    assert log == [], (
        "Kill-switch OFF must not strand in-flight leases; the tick "
        f"should still defer. log={log}"
    )
    # Restore for sibling tests
    _ex_mod._test_set_kill_switch(True)
