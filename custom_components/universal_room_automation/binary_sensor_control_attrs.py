"""G1: per-room control-list attrs helper (isolated, no HA imports).

Split out of `binary_sensor.py` so the helper can be unit-tested without
importing Home Assistant. The helper reads the six actuator-driving CONF
lists via the coordinator's `_get_config` — the SAME options-first-with-
data-fallback read path `coordinator.py:820-840` uses for actuation — so
the emitted attrs cannot diverge from the actuator's ground truth.

Per-key try/except with safe defaults matches the v4.7.24 substrate
defensive style (a malformed options blob for one key must never blank
the whole attrs dict). Lists are always COPIED so a downstream mutation
cannot corrupt the underlying entry.options / entry.data store.
"""
from __future__ import annotations

from .const import (
    CONF_LIGHTS,
    CONF_NIGHT_LIGHTS,
    CONF_FANS,
    CONF_HUMIDITY_FANS,
    CONF_COVERS,
    CONF_CLIMATE_ENTITY,
)


_G1_LIST_CONFS = (
    ("control_lights", CONF_LIGHTS),
    ("control_night_lights", CONF_NIGHT_LIGHTS),
    ("control_fans", CONF_FANS),
    ("control_humidity_fans", CONF_HUMIDITY_FANS),
    ("control_covers", CONF_COVERS),
)


def build_control_attrs(coordinator) -> dict:
    """Return the G1 control_* attr block for a room coordinator.

    Reads via `coordinator._get_config(key, default)`. Per-key try/except:
    a raise on one key falls back to that key's default and leaves the
    other keys populated. List attrs are emitted as COPIES.
    """
    out: dict = {}
    for attr_key, conf_key in _G1_LIST_CONFS:
        try:
            raw = coordinator._get_config(conf_key, []) or []
            out[attr_key] = list(raw)
        except Exception:  # noqa: BLE001 — defensive per D1 spec
            out[attr_key] = []
    try:
        climate = coordinator._get_config(CONF_CLIMATE_ENTITY, None)
        out["control_climate_entity"] = climate if climate else None
    except Exception:  # noqa: BLE001
        out["control_climate_entity"] = None
    return out
