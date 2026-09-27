"""HVAC W1-B shared test harness — REAL modules on the smoke StubHass.

Pattern lifted from test_hvac_live_room_hold_wire_in.py: purge hand-built
sys.modules shims installed by sibling files (module-scoped, restored on
teardown) and load the real HVACCoordinator / OverrideArrester against
`runtime_harness.build_smoke_hass`. Requires the real HA install in
.venv-ha (the W1-B files skip otherwise).
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from typing import Any

_HERE = os.path.dirname(__file__)
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

_SHIM_PREFIXES = (
    "homeassistant",
    "custom_components.universal_room_automation",
)
_REAL_URA_PATH = os.path.abspath(os.path.join(
    _HERE, "..", "..", "custom_components", "universal_room_automation",
))


def shim_keys():
    return [
        k for k in list(sys.modules)
        if any(k == p or k.startswith(p + ".") for p in _SHIM_PREFIXES)
    ]


def purge_shim_modules():
    """Drop sys.modules entries whose __file__ is neither the real URA tree
    nor site-packages (hand-built shims). Real modules are left alone."""
    for k in shim_keys():
        mod = sys.modules[k]
        f = getattr(mod, "__file__", None)
        if f:
            fp = os.path.abspath(f)
            if _REAL_URA_PATH in fp or "site-packages" in fp:
                continue
        del sys.modules[k]


_FUNNEL_NAMES = ("emit_set_temperature", "emit_set_preset_mode", "emit_set_hvac_mode")
_FUNNEL_HOSTS = ("hvac", "hvac_override", "hvac_predict", "hvac_egress")
_DC = "custom_components.universal_room_automation.domain_coordinators."


def snapshot_shims():
    """Snapshot the shim-prefix sys.modules keys AND the funnel bindings on
    the real host modules (sibling files rebind `emit_set_*` to mocks by
    plain attribute assignment and never restore them)."""
    keys = {k: sys.modules[k] for k in shim_keys()}
    attrs = {}
    for host in _FUNNEL_HOSTS:
        m = sys.modules.get(_DC + host)
        if m is None or not getattr(m, "__file__", None):
            continue
        for n in _FUNNEL_NAMES:
            if hasattr(m, n):
                attrs[(host, n)] = getattr(m, n)
    return {"keys": keys, "attrs": attrs}


def restore_shims(baseline):
    keys = baseline["keys"]
    current = set(shim_keys())
    for k, v in keys.items():
        if sys.modules.get(k) is not v:
            sys.modules[k] = v
    for k in current - set(keys):
        sys.modules.pop(k, None)
    for (host, n), v in baseline["attrs"].items():
        m = sys.modules.get(_DC + host)
        if m is not None:
            setattr(m, n, v)


def rebind_real_funnels(mods):
    """Point every host module's `emit_set_*` at the REAL funnel."""
    sp = mods["hvac_setpoint"]
    for host in _FUNNEL_HOSTS:
        m = mods.get(host)
        if m is None:
            continue
        for n in _FUNNEL_NAMES:
            if hasattr(m, n):
                setattr(m, n, getattr(sp, n))


def load_real():
    """Purge shims and import the real HVAC modules; reload the minimal
    set if HVACCoordinator was previously bound to a shim base."""
    purge_shim_modules()
    from custom_components.universal_room_automation.domain_coordinators.hvac import (  # noqa: E402
        HVACCoordinator,
    )
    if HVACCoordinator.__mro__[1:] == (object,):
        for _k in (
            "custom_components.universal_room_automation.domain_coordinators.base",
            "custom_components.universal_room_automation.domain_coordinators.hvac",
        ):
            sys.modules.pop(_k, None)
    import importlib
    mods = {}
    for name in (
        "hvac", "hvac_override", "hvac_preset", "hvac_excursion", "hvac_strategy",
        "hvac_predict", "hvac_egress", "hvac_zones", "hvac_const", "hvac_setpoint",
    ):
        mods[name] = importlib.import_module(
            f"custom_components.universal_room_automation.domain_coordinators.{name}"
        )
    from custom_components.universal_room_automation import const as _const
    mods["const"] = _const
    rebind_real_funnels(mods)
    return mods


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class FakeActivityLogger:
    def __init__(self):
        self.rows: list[dict] = []

    async def log(self, **kw):
        self.rows.append(dict(kw))

    def actions(self, action: str) -> list[dict]:
        return [r for r in self.rows if r.get("action") == action]


class FakeDB:
    def __init__(self):
        self.rows: list[dict] = []

    async def log_activity(self, **kw):
        self.rows.append(dict(kw))

    async def save_excursion_row(self, row):  # begin_excursion persistence
        return None

    async def clear_excursion_row(self, zone_id):
        return None

    async def get_all_excursion_rows(self):
        return []

    async def log_excursion_event(self, **kw):
        return None


class FakeNM:
    def __init__(self):
        self.notes: list[dict] = []

    async def async_notify(self, **kw):
        self.notes.append(dict(kw))


class FakeStore:
    """Stand-in for `homeassistant.helpers.storage.Store` on the coord."""

    def __init__(self, data=None):
        self.data = data
        self.saves: list[dict] = []

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.saves.append(data)
        self.data = data


def install_ledger(hass, mods):
    DOMAIN = mods["const"].DOMAIN
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["activity_logger"] = FakeActivityLogger()
    hass.data[DOMAIN]["database"] = FakeDB()
    hass.data[DOMAIN]["notification_manager"] = FakeNM()
    return hass.data[DOMAIN]


def set_climate(
    hass, entity_id, *, preset_mode="home", hold_activity=None, high=76.0, low=68.0,
    state="heat_cool", preset_modes=("away", "home", "manual", "sleep", "resume"),
    extra=None,
):
    attrs = {
        "preset_mode": preset_mode,
        "preset_modes": list(preset_modes),
        "target_temp_high": high,
        "target_temp_low": low,
        "hvac_modes": ["off", "heat_cool", "cool", "heat"],
        "current_temperature": 74.0,
    }
    if hold_activity is not None:
        attrs["hold_activity"] = hold_activity
    if extra:
        attrs.update(extra)
    hass.states.async_set(entity_id, state, attrs)
    return hass.states.get(entity_id)


def make_coord(mods, zones=("zone_1", "zone_2", "zone_3")):
    from runtime_harness import build_smoke_hass  # noqa: E402
    HVACCoordinator = mods["hvac"].HVACCoordinator
    ZoneState = mods["hvac_zones"].ZoneState
    hass = build_smoke_hass(zones_count=3)
    coord = HVACCoordinator(hass)
    zm = coord.zone_manager
    for idx, zid in enumerate(zones, start=1):
        zm._zones[zid] = ZoneState(
            zone_id=zid, zone_name=f"Zone {idx}",
            climate_entity=f"climate.test_zone_{idx}", rooms=[],
        )
        z = zm._zones[zid]
        z.hvac_mode = "heat_cool"
        z.target_temp_high = 76.0
        z.target_temp_low = 68.0
        z.current_temperature = 74.0
        set_climate(hass, z.climate_entity, preset_mode="home", hold_activity="home")
    install_ledger(hass, mods)
    # StubStates.async_all takes no domain; the arrester's person lookup
    # calls `states.async_all("person")` — widen the stub surface.
    _states = hass.states

    def _async_all(domain=None):
        return [
            s for s in _states._states.values()
            if domain is None or s.entity_id.startswith(domain + ".")
        ]
    _states.async_all = _async_all
    # Excursion primitive: bind to this hass/db, clear registry.
    ex = mods["hvac_excursion"]
    ex._test_clear_leases()
    ex._test_set_kill_switch(True)
    ex._test_bind(hass=hass, db=None)
    mods["hvac_strategy"]._test_reset_cache()
    return coord, hass


def make_event(entity_id, *, old_preset, new_preset, old_high=76.0, new_high=76.0,
               old_low=68.0, new_low=68.0, user_id=None, parent_id=None,
               old_state="heat_cool", new_state="heat_cool", extra_new=None):
    old = types.SimpleNamespace(
        state=old_state,
        attributes={
            "preset_mode": old_preset, "target_temp_high": old_high,
            "target_temp_low": old_low, "current_temperature": 74.0,
        },
        last_updated=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    new_attrs = {
        "preset_mode": new_preset, "target_temp_high": new_high,
        "target_temp_low": new_low, "current_temperature": 74.0,
    }
    if extra_new:
        new_attrs.update(extra_new)
    new = types.SimpleNamespace(
        state=new_state, attributes=new_attrs,
        last_updated=datetime.now(timezone.utc),
    )
    ctx = types.SimpleNamespace(user_id=user_id, parent_id=parent_id, id="ctx")
    return types.SimpleNamespace(
        data={"entity_id": entity_id, "new_state": new, "old_state": old},
        context=ctx,
    )


async def drain(hass, rounds: int = 3):
    """Let fire-and-forget tasks (ledger rows, saves) complete."""
    for _ in range(rounds):
        tasks = [t for t in getattr(hass, "_stub_tasks", []) if not t.done()]
        if not tasks:
            await asyncio.sleep(0)
            continue
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)


def preset_writes(hass, entity_id: str, preset: str | None = None) -> list:
    return [
        c for c in hass.services.calls
        if c[0] == "climate" and c[1] == "set_preset_mode"
        and c[2].get("entity_id") == entity_id
        and (preset is None or c[2].get("preset_mode") == preset)
    ]


def temp_writes(hass, entity_id: str) -> list:
    return [
        c for c in hass.services.calls
        if c[0] == "climate" and c[1] == "set_temperature"
        and c[2].get("entity_id") == entity_id
    ]


def climate_write_rows(hass, mods, site: str | None = None) -> list[dict]:
    import json
    DOMAIN = mods["const"].DOMAIN
    out = []
    for r in hass.data[DOMAIN]["database"].rows:
        if r.get("action") != "climate_write":
            continue
        d = json.loads(r["details_json"])
        if site is None or d.get("site") == site:
            out.append(d)
    return out


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def local_now():
    from homeassistant.util import dt as dt_util
    return dt_util.now()
