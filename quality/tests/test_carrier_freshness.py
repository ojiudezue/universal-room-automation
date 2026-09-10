"""CARRIER-STALE-POLL-REFRESH-1 unit tests.

Exercises the D1/D2/D3 logic on the two new methods
`HVACCoordinator._check_carrier_freshness` and
`HVACCoordinator._reload_ha_carrier_entry` in isolation, using a lightweight
fake `self` (SimpleNamespace) bound to the real unbound methods.

HA stub scaffolding ported from
`test_hvac_vacancy_sweep_manual_on_guard.py` so this file collects on its
own (that sibling snapshots/restores the same stubs at end-of-collection).

Wire-in anchor: `test_stale_and_corroborated_triggers_reload` exercises the
production `_reload_ha_carrier_entry`. Neutering the reload method (adding
`return` at method top) MUST make this test fail. See CALL-NEUTER DRILL
notes at bottom.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# HA module mocking (mirrors test_hvac_vacancy_sweep_manual_on_guard.py)
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

# ---------------------------------------------------------------------------
# Now import the SUT symbols
# ---------------------------------------------------------------------------

from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    hvac as hvac_mod,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_const import (  # noqa: E402
    CARRIER_INTEGRATION_DOMAIN,
    DEFAULT_HVAC_CARRIER_RELOAD_COOLDOWN_S,
    DEFAULT_HVAC_CARRIER_RELOAD_MAX_PER_DAY,
    DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S,
)
from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import (  # noqa: E402
    DailyCounter,
)
from types import SimpleNamespace  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _make_state(state_val, last_reported, hvac_action=None, unit="kW"):
    # Fix-up round 2026-09-09 (A2): SPAN sensors carry `kW` by default so
    # the unit-refusal branch in `_carrier_zone_span_kw` accepts them.
    # Blank/unknown units are now refused (see test_blank_unit_refused_*).
    attrs = {"unit_of_measurement": unit} if unit else {}
    if hvac_action is not None:
        attrs["hvac_action"] = hvac_action
    return SimpleNamespace(
        state=state_val,
        last_reported=last_reported,
        attributes=attrs,
    )


def _make_zone(climate="climate.z1", load="sensor.z1_kw"):
    return SimpleNamespace(
        climate_entity=climate,
        ac_load_sensor=load,
    )


def _make_hass(*, states_by_entity, carrier_entries=None, ura_options=None):
    hass = MagicMock()
    hass.states.get = lambda eid: states_by_entity.get(eid)
    ura_entry = SimpleNamespace(
        domain="universal_room_automation",
        entry_id="ura_entry_1",
        options=(ura_options or {}),
    )
    carrier_entries = (
        carrier_entries
        if carrier_entries is not None
        else [SimpleNamespace(
            domain=CARRIER_INTEGRATION_DOMAIN, entry_id="carrier_1",
        )]
    )

    def _async_entries(domain):
        if domain == "universal_room_automation":
            return [ura_entry]
        if domain == CARRIER_INTEGRATION_DOMAIN:
            return carrier_entries
        return []

    hass.config_entries.async_entries = _async_entries

    service_calls: list[dict] = []

    async def _async_call(domain, service, data, blocking=False):
        service_calls.append(
            {"domain": domain, "service": service, "data": data,
             "blocking": blocking}
        )

    hass.services.async_call = _async_call
    hass.service_calls = service_calls

    hass.data = {"universal_room_automation": {}}

    def _create_task(coro):
        try:
            coro.close()
        except Exception:
            pass
        return MagicMock()
    hass.async_create_task = _create_task
    return hass


def _make_fake_hvac(hass, zones):
    zm = SimpleNamespace(zones=dict(zones))
    obj = SimpleNamespace(
        hass=hass,
        _zone_manager=zm,
        _carrier_reload_lock=asyncio.Lock(),
        _last_carrier_reload_at=None,
        _carrier_reloads_today=DailyCounter(
            name="test.reloads",
            persist=False,
            reason="test",
        ),
        _carrier_reload_suppressed_today=False,
        _carrier_reload_suppress_date="",
        _carrier_stale_ticks_since_reload=0,
        _carrier_freshness_snapshot={},
        _carrier_worst_age_s=None,
        _carrier_stale_zone_count=0,
        _carrier_require_blind_corroboration_default=True,
        _carrier_stale_nm_date="",
        # Fix-up round 2026-09-09: in-flight-fence dependencies. The fake
        # arrester exposes the two predicates the fence reads
        # (`_nudge_in_flight` set + `has_active_ac_reset(zone_id)`); tests
        # can mutate the set / return value to simulate in-flight ops.
        _override_arrester=SimpleNamespace(
            _nudge_in_flight=set(),
            has_active_ac_reset=lambda zid: False,
        ),
    )
    for name in (
        "_check_carrier_freshness",
        "_reload_ha_carrier_entry",
        "_carrier_require_blind_corroboration",
        "_carrier_zone_span_kw",
        "_carrier_in_flight_ops_pending",
        "_trip_wire_carrier_reload_ineffective",
        "_nm_carrier_reload_note",
    ):
        setattr(obj, name, getattr(hvac_mod.HVACCoordinator, name).__get__(obj))
    return obj


def _now_utc():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Freshness predicate table
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fresh_state_not_stale():
    now = _now_utc()
    st = _make_state("cool", now - timedelta(seconds=60), hvac_action="idle")
    hass = _make_hass(states_by_entity={
        "climate.z1": st,
        "sensor.z1_kw": _make_state("2.0", now, hvac_action=None),
    })
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    await hvac._check_carrier_freshness()
    assert hvac._carrier_stale_zone_count == 0
    assert hass.service_calls == []


@pytest.mark.asyncio
async def test_age_stale_no_corroboration_default_true_quiet_idle_no_reload():
    """Discriminator: age-stale but zone is quiet-idle (kW≈0) with
    require_corroboration=True must NOT reload."""
    now = _now_utc()
    st = _make_state(
        "cool",
        now - timedelta(seconds=DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S + 60),
        hvac_action="idle",
    )
    hass = _make_hass(states_by_entity={
        "climate.z1": st,
        "sensor.z1_kw": _make_state("0.02", now),
    })
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    await hvac._check_carrier_freshness()
    assert hvac._carrier_stale_zone_count == 1
    assert hass.service_calls == []


@pytest.mark.asyncio
async def test_stale_and_corroborated_triggers_reload():
    """WIRE-IN ANCHOR TEST — load-bearing behavior of the cycle.

    Neutering `_reload_ha_carrier_entry` (add `return` at the top)
    MUST make this test fail.
    """
    now = _now_utc()
    st = _make_state(
        "cool",
        now - timedelta(seconds=DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S + 60),
        hvac_action="idle",
    )
    hass = _make_hass(states_by_entity={
        "climate.z1": st,
        "sensor.z1_kw": _make_state("1.8", now),
    })
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    await hvac._check_carrier_freshness()
    assert hvac._carrier_stale_zone_count == 1
    assert len(hass.service_calls) == 1
    call = hass.service_calls[0]
    assert call["service"] == "reload_config_entry"
    assert call["data"]["entry_id"] == "carrier_1"
    assert hvac._carrier_reloads_today.value == 1


@pytest.mark.asyncio
async def test_last_reported_none_treated_as_fresh():
    now = _now_utc()
    st = _make_state("cool", None, hvac_action="idle")
    hass = _make_hass(states_by_entity={
        "climate.z1": st,
        "sensor.z1_kw": _make_state("2.0", now),
    })
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    await hvac._check_carrier_freshness()
    assert hass.service_calls == []


@pytest.mark.asyncio
async def test_unavailable_climate_ignored():
    now = _now_utc()
    st = _make_state("unavailable", now - timedelta(hours=1), hvac_action=None)
    hass = _make_hass(states_by_entity={
        "climate.z1": st,
        "sensor.z1_kw": _make_state("2.0", now),
    })
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    await hvac._check_carrier_freshness()
    assert hvac._carrier_stale_zone_count == 0
    assert hass.service_calls == []


# ---------------------------------------------------------------------------
# Cooldown / kill-switch / per-day cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cooldown_blocks_second_reload():
    now = _now_utc()
    st = _make_state(
        "cool",
        now - timedelta(seconds=DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S + 60),
        hvac_action="idle",
    )
    hass = _make_hass(states_by_entity={
        "climate.z1": st,
        "sensor.z1_kw": _make_state("1.8", now),
    })
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    await hvac._check_carrier_freshness()
    assert len(hass.service_calls) == 1
    await hvac._check_carrier_freshness()
    assert len(hass.service_calls) == 1  # cooldown blocked 2nd


@pytest.mark.asyncio
async def test_kill_switch_cooldown_zero_disables_reload():
    now = _now_utc()
    st = _make_state(
        "cool",
        now - timedelta(seconds=DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S + 60),
        hvac_action="idle",
    )
    hass = _make_hass(
        states_by_entity={
            "climate.z1": st,
            "sensor.z1_kw": _make_state("1.8", now),
        },
        ura_options={"hvac_carrier_reload_cooldown_s": 0},
    )
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    await hvac._check_carrier_freshness()
    assert hass.service_calls == []


@pytest.mark.asyncio
async def test_per_day_cap_blocks_after_max():
    now = _now_utc()
    st = _make_state(
        "cool",
        now - timedelta(seconds=DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S + 60),
        hvac_action="idle",
    )
    hass = _make_hass(states_by_entity={
        "climate.z1": st,
        "sensor.z1_kw": _make_state("1.8", now),
    })
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    for _ in range(DEFAULT_HVAC_CARRIER_RELOAD_MAX_PER_DAY):
        hvac._carrier_reloads_today.increment()
    await hvac._check_carrier_freshness()
    assert hass.service_calls == []
    assert hvac._carrier_reload_suppressed_today is True


# ---------------------------------------------------------------------------
# Entry-lookup edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_zero_carrier_entries_no_reload():
    now = _now_utc()
    st = _make_state(
        "cool",
        now - timedelta(seconds=DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S + 60),
        hvac_action="idle",
    )
    hass = _make_hass(
        states_by_entity={
            "climate.z1": st,
            "sensor.z1_kw": _make_state("1.8", now),
        },
        carrier_entries=[],
    )
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    await hvac._check_carrier_freshness()
    assert hass.service_calls == []


@pytest.mark.asyncio
async def test_two_carrier_entries_no_reload():
    now = _now_utc()
    st = _make_state(
        "cool",
        now - timedelta(seconds=DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S + 60),
        hvac_action="idle",
    )
    hass = _make_hass(
        states_by_entity={
            "climate.z1": st,
            "sensor.z1_kw": _make_state("1.8", now),
        },
        carrier_entries=[
            SimpleNamespace(domain=CARRIER_INTEGRATION_DOMAIN, entry_id="a"),
            SimpleNamespace(domain=CARRIER_INTEGRATION_DOMAIN, entry_id="b"),
        ],
    )
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    await hvac._check_carrier_freshness()
    assert hass.service_calls == []


@pytest.mark.asyncio
async def test_zone_without_span_falls_back_to_age_only_when_required():
    """Graceful degrade: zone without ac_load_sensor and require_corroboration=True
    still qualifies on age alone (per plan D1 spec)."""
    now = _now_utc()
    st = _make_state(
        "cool",
        now - timedelta(seconds=DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S + 60),
        hvac_action="idle",
    )
    hass = _make_hass(states_by_entity={
        "climate.z1": st,
    })
    zone = _make_zone(load="")
    hvac = _make_fake_hvac(hass, [("z1", zone)])
    await hvac._check_carrier_freshness()
    assert len(hass.service_calls) == 1


# ---------------------------------------------------------------------------
# Fix-up round 2026-09-09 — mutation-anchored tests for review findings
# ---------------------------------------------------------------------------

def _stale_hass_and_zone(load="sensor.z1_kw", span_kw="1.8"):
    now = _now_utc()
    st = _make_state(
        "cool",
        now - timedelta(seconds=DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S + 60),
        hvac_action="idle",
    )
    states = {"climate.z1": st}
    if load:
        states[load] = _make_state(span_kw, now)
    return states


@pytest.mark.asyncio
async def test_in_flight_nudge_defers_reload_c_critical_1():
    """C-CRITICAL-1: a nudge in flight must FENCE the reload — the
    thermostat is mid-restore and a reload would strand it.

    RED-on-neuter: replace `_carrier_in_flight_ops_pending` with a
    stub returning None (bypass the fence) and this test fails —
    service_calls becomes length 1 with a reload dispatched despite
    the in-flight nudge.
    """
    hass = _make_hass(states_by_entity=_stale_hass_and_zone())
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    hvac._override_arrester._nudge_in_flight = {"z1"}
    await hvac._check_carrier_freshness()
    assert hass.service_calls == []  # deferred, no reload


@pytest.mark.asyncio
async def test_in_flight_ac_reset_defers_reload_c_critical_1():
    hass = _make_hass(states_by_entity=_stale_hass_and_zone())
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    hvac._override_arrester.has_active_ac_reset = lambda zid: True
    await hvac._check_carrier_freshness()
    assert hass.service_calls == []


@pytest.mark.asyncio
async def test_in_flight_excursion_defers_reload_c_critical_1():
    from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
        hvac_excursion as _ex_mod,
    )
    hass = _make_hass(states_by_entity=_stale_hass_and_zone())
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    saved = dict(getattr(_ex_mod, "_rows", {}) or {})
    try:
        _ex_mod._rows = {"tok_1": MagicMock()}
        await hvac._check_carrier_freshness()
        assert hass.service_calls == []
    finally:
        _ex_mod._rows = saved


@pytest.mark.asyncio
async def test_in_flight_clears_then_reload_fires():
    """Fence releases once in-flight ops clear — reload fires next tick."""
    hass = _make_hass(states_by_entity=_stale_hass_and_zone())
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    hvac._override_arrester._nudge_in_flight = {"z1"}
    await hvac._check_carrier_freshness()
    assert hass.service_calls == []
    hvac._override_arrester._nudge_in_flight = set()
    await hvac._check_carrier_freshness()
    assert len(hass.service_calls) == 1
    assert hass.service_calls[0]["service"] == "reload_config_entry"


# ---------------------------------------------------------------------------
# C-HIGH-3: URA parent domain safety guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ura_domain_entry_never_reloaded_c_high_3():
    """SAFETY INVARIANT: if a resolved 'ha_carrier' entry_id somehow points
    at a URA-domain entry, refuse to reload it — parent-reload-watchdog rule.

    RED-on-neuter: comment out the `entry.domain == DOMAIN` guard in
    `_reload_ha_carrier_entry` and this test fails (a reload would be
    dispatched against the URA parent entry_id).
    """
    ura_masquerading = SimpleNamespace(
        domain="universal_room_automation",
        entry_id="ura_parent",
    )
    hass = _make_hass(
        states_by_entity=_stale_hass_and_zone(),
        carrier_entries=[ura_masquerading],
    )
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    await hvac._check_carrier_freshness()
    assert hass.service_calls == []


# ---------------------------------------------------------------------------
# A2: kWh unit reload-storm — cumulative-energy SPAN sensor must not
# produce false corroboration.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kwh_span_unit_refused_a2():
    """A2 fix-up: a SPAN sensor reporting kWh (cumulative) MUST NOT
    corroborate; require_corroboration=True + no other qualifier → no reload.

    RED-on-neuter: remove the `unit in ("kwh", ...)` refusal branch in
    `_carrier_zone_span_kw` and this test fails (huge kWh cumulative
    value produces a false blind_evidence → reload dispatched).
    """
    now = _now_utc()
    st = _make_state(
        "cool",
        now - timedelta(seconds=DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S + 60),
        hvac_action="idle",
    )
    span_state = SimpleNamespace(
        state="4823.5",  # huge cumulative reading
        last_reported=now,
        attributes={"unit_of_measurement": "kWh"},
    )
    hass = _make_hass(states_by_entity={
        "climate.z1": st,
        "sensor.z1_kw": span_state,
    })
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    await hvac._check_carrier_freshness()
    # kWh unit refused -> span_kw=None -> no blind_evidence ->
    # quiet-idle branch -> NO reload
    assert hass.service_calls == []
    row = hvac._carrier_freshness_snapshot["z1"]
    assert row["span_kw"] is None
    assert row["span_unreadable"] is True  # A5 diagnostic


@pytest.mark.asyncio
async def test_blank_unit_refused_not_assumed_kw_a2():
    """Blank unit is refused (unknown), not silently assumed kW."""
    now = _now_utc()
    st = _make_state(
        "cool",
        now - timedelta(seconds=DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S + 60),
        hvac_action="idle",
    )
    span_state = SimpleNamespace(
        state="1.8", last_reported=now,
        attributes={"unit_of_measurement": ""},
    )
    hass = _make_hass(states_by_entity={
        "climate.z1": st,
        "sensor.z1_kw": span_state,
    })
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    await hvac._check_carrier_freshness()
    assert hass.service_calls == []


@pytest.mark.asyncio
async def test_kw_unit_accepted_reloads():
    """Regression: unit explicitly 'kW' still corroborates and triggers reload."""
    now = _now_utc()
    st = _make_state(
        "cool",
        now - timedelta(seconds=DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S + 60),
        hvac_action="idle",
    )
    span_state = SimpleNamespace(
        state="1.8", last_reported=now,
        attributes={"unit_of_measurement": "kW"},
    )
    hass = _make_hass(states_by_entity={
        "climate.z1": st,
        "sensor.z1_kw": span_state,
    })
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    await hvac._check_carrier_freshness()
    assert len(hass.service_calls) == 1


# ---------------------------------------------------------------------------
# C-HIGH-4: stranded-stale age-only NM (INDEPENDENT of reload path)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_age_only_nm_fires_when_reload_impossible_c_high_4():
    """C-HIGH-4: genuinely stale but cannot reload (ambiguous 0 carrier
    entries) — age-only NM MUST fire, once/day.

    RED-on-neuter: delete the C-HIGH-4 age-only NM block in
    `_check_carrier_freshness` and this test fails (nm calls == 0).
    """
    hass = _make_hass(
        states_by_entity=_stale_hass_and_zone(),
        carrier_entries=[],
    )
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    nm_calls: list[dict] = []

    async def _nm(coordinator_id, severity, title, message, hazard_type):
        nm_calls.append({"hazard_type": hazard_type, "title": title})

    hass.data["universal_room_automation"]["notification_manager"] = (
        SimpleNamespace(async_notify=_nm)
    )
    await hvac._check_carrier_freshness()
    assert hass.service_calls == []  # no reload possible
    assert any(c["hazard_type"] == "carrier_stale_age_only" for c in nm_calls)

    # Second tick same day — should NOT fire again (once/day guard)
    nm_calls.clear()
    await hvac._check_carrier_freshness()
    assert all(
        c["hazard_type"] != "carrier_stale_age_only" for c in nm_calls
    )


# ---------------------------------------------------------------------------
# D3 redesign — TIME-based trip-wire (B-HIGH-1/2/3, C-MED-1)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trip_wire_requires_settle_time_elapsed_b_high_2():
    """Trip-wire must NOT fire immediately after reload — needs settle_s.

    RED-on-neuter: replace the `since_reload >= settle_s` guard with
    `True` (fire regardless of time) and this test fails (suppressed
    latches on the same tick as the reload).
    """
    now = _now_utc()
    st = _make_state(
        "cool",
        now - timedelta(seconds=DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S + 60),
        hvac_action="idle",
    )
    hass = _make_hass(states_by_entity={
        "climate.z1": st,
        "sensor.z1_kw": _make_state("1.8", now),
    })
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    await hvac._check_carrier_freshness()
    assert len(hass.service_calls) == 1
    # Immediately re-check (before settle_s elapsed) — trip-wire
    # must NOT have fired yet
    assert hvac._carrier_reload_suppressed_today is False


@pytest.mark.asyncio
async def test_counter_scoped_to_qualifying_stale_b_high_3():
    """Stale-tick counter must NOT advance on quiet-idle (non-qualifying) stale.

    RED-on-neuter: change the counter-increment guard from
    `qualifiers_by_zone` to `stale_count > 0` (the old bug) and this
    test fails (counter latches on quiet-idle after a reload).
    """
    now = _now_utc()
    # First: qualifying-stale zone fires a reload
    st_hot = _make_state(
        "cool",
        now - timedelta(seconds=DEFAULT_HVAC_CARRIER_STALE_MAX_AGE_S + 60),
        hvac_action="idle",
    )
    hass = _make_hass(states_by_entity={
        "climate.z1": st_hot,
        "sensor.z1_kw": _make_state("1.8", now),
    })
    hvac = _make_fake_hvac(hass, [("z1", _make_zone())])
    await hvac._check_carrier_freshness()
    assert hvac._last_carrier_reload_at is not None
    # Now flip to quiet-idle stale (kW=0) — counter must NOT advance
    hass.states.get = lambda eid: {
        "climate.z1": st_hot,
        "sensor.z1_kw": _make_state("0.01", now),
    }.get(eid)
    await hvac._check_carrier_freshness()
    assert hvac._carrier_stale_ticks_since_reload == 0


# ---------------------------------------------------------------------------
# C-HIGH-2: wire-in AST anchor — the call site inside _run_decision_cycle
# ---------------------------------------------------------------------------

def test_wire_in_call_site_present_in_run_decision_cycle_c_high_2():
    """AST anchor: `_check_carrier_freshness` MUST be awaited from within
    `HVACCoordinator._run_decision_cycle`. A source grep is not enough —
    the review flagged the prior anchor as hollow because it never drove
    the enclosing method.

    RED-on-neuter: delete the `await self._check_carrier_freshness()`
    line from `_run_decision_cycle` and this test fails.
    """
    import ast
    import inspect
    src = inspect.getsource(hvac_mod.HVACCoordinator._run_decision_cycle)
    # dedent for ast parsing (method source is indented)
    import textwrap
    tree = ast.parse(textwrap.dedent(src))
    found = False
    for node in ast.walk(tree):
        # await self._check_carrier_freshness()
        if isinstance(node, ast.Await):
            call = node.value
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "_check_carrier_freshness"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "self"
            ):
                found = True
                break
    assert found, (
        "`await self._check_carrier_freshness()` not found in "
        "`_run_decision_cycle` — wire-in was removed. See "
        "hvac.py wire-in anchor comment."
    )


# ---------------------------------------------------------------------------
# CALL-NEUTER DRILL NOTES
# ---------------------------------------------------------------------------
# 1. In domain_coordinators/hvac.py, delete the call site
#      `await self._check_carrier_freshness()`
#    inside `_run_decision_cycle` (search for the wire-in anchor comment).
#    That comment names this test file / this test name — a reviewer will
#    notice a deletion has orphaned the anchor reference.
#
# 2. Neuter `_reload_ha_carrier_entry` by adding `return` at method top.
#    Re-run:
#      PYTHONPATH=quality python3 -m pytest \
#        quality/tests/test_carrier_freshness.py::test_stale_and_corroborated_triggers_reload \
#        -v
#    MUST fail on `assert len(hass.service_calls) == 1`.
#
# 3. Restore both. Full test file expected green (11 passing).
