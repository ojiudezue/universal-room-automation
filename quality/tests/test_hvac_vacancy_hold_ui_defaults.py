"""Behavioral test for the per-room HVAC vacancy-hold day/night config_flow
fields (post-C1-fix).

Invariant (falsifiable): in `async_step_climate`'s returned schema, the
`suggested_value` for `CONF_HVAC_VACANCY_HOLD[_NIGHT]` reflects ONLY the
persisted `_get_current` value — it does NOT fall through to the room-TYPE
default. This preserves the "unset -> follows the ROOM_TYPE table" invariant
because a prefilled `suggested_value` is RETURNED in `user_input` on submit
in HA option flows; falling through would silently PIN unset rooms on any
climate-step submit.

DRIVES the real production `async_step_climate` and extracts
`vol.Optional(...).description["suggested_value"]` for the two hold fields
from the returned flow result's `data_schema`.

MUTATION-ANCHOR (report):
- Re-inserting the `ROOM_TYPE_HVAC_HOLD.get(..., DEFAULT_...)` fallthrough
  into the `suggested_value` expression (i.e. the pre-C1 code) flips the
  extracted value for an UNSET bedroom from None -> 60 (day) / 1800 (night),
  reddening `test_unset_bedroom_suggests_blank_day/night`.
- Inverting the effective None-check (e.g. `if current is None` instead of
  `is not None`) similarly reddens the UNSET assertions.
"""

from __future__ import annotations

import asyncio
import os

import pytest
import voluptuous as vol

from custom_components.universal_room_automation import config_flow as _cf
from custom_components.universal_room_automation.const import (
    CONF_HVAC_VACANCY_HOLD,
    CONF_HVAC_VACANCY_HOLD_NIGHT,
    CONF_ROOM_TYPE,
    ROOM_TYPE_BEDROOM,
    ROOM_TYPE_HALLWAY,
)

_CONFIG_FLOW_PY = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation", "config_flow.py",
)


class _StubEntry:
    """Minimal ConfigEntry surrogate with `.options` and `.data` dicts."""

    def __init__(self, options=None, data=None):
        self.entry_id = "test_entry"
        self.options = options or {}
        self.data = data or {}


def _build_flow(options=None, data=None):
    flow = _cf.UniversalRoomAutomationOptionsFlow(_StubEntry(options, data))
    return flow


def _walk_schema(schema):
    """Yield (key_marker, value) pairs recursively across nested vol.Schema
    and HA `Section` wrappers (both expose an inner schema via `.schema`)."""
    inner = None
    if isinstance(schema, dict):
        inner = schema
    elif isinstance(schema, vol.Schema):
        inner = schema.schema
    else:
        sub = getattr(schema, "schema", None)
        if isinstance(sub, (vol.Schema, dict)):
            yield from _walk_schema(sub)
        return
    for marker, value in inner.items():
        yield marker, value
        # Recurse into value if it wraps a nested schema (vol.Schema, dict,
        # or HA Section — Section carries `.schema` too).
        if isinstance(value, (vol.Schema, dict)):
            yield from _walk_schema(value)
        else:
            sub = getattr(value, "schema", None)
            if isinstance(sub, (vol.Schema, dict)):
                yield from _walk_schema(sub)


def _extract_suggested(flow_result, conf_key):
    """Find the vol.Optional(conf_key, ...) marker in the returned schema
    and return its `description["suggested_value"]` (None if unset)."""
    data_schema = flow_result["data_schema"]
    for marker, _value in _walk_schema(data_schema):
        # Voluptuous Optional markers carry `.schema` == the key string.
        if getattr(marker, "schema", None) == conf_key:
            desc = getattr(marker, "description", None)
            if isinstance(desc, dict):
                return desc.get("suggested_value")
    raise AssertionError(f"CONF key {conf_key!r} not found in climate schema")


def _run_climate(options=None, data=None):
    flow = _build_flow(options=options, data=data)
    return asyncio.get_event_loop().run_until_complete(
        flow.async_step_climate(user_input=None)
    ) if False else asyncio.new_event_loop().run_until_complete(
        flow.async_step_climate(user_input=None)
    )


# --------- Behavioral tests: schema-extracted suggested_value ---------

@pytest.mark.parametrize("room_type", [ROOM_TYPE_BEDROOM, ROOM_TYPE_HALLWAY])
def test_unset_bedroom_suggests_blank_day(room_type):
    """UNSET day field must produce suggested_value=None regardless of
    room type — no type-default fallthrough on the suggestion channel."""
    result = _run_climate(data={CONF_ROOM_TYPE: room_type})
    assert _extract_suggested(result, CONF_HVAC_VACANCY_HOLD) is None


@pytest.mark.parametrize("room_type", [ROOM_TYPE_BEDROOM, ROOM_TYPE_HALLWAY])
def test_unset_bedroom_suggests_blank_night(room_type):
    result = _run_climate(data={CONF_ROOM_TYPE: room_type})
    assert _extract_suggested(result, CONF_HVAC_VACANCY_HOLD_NIGHT) is None


def test_explicit_zero_is_preserved_day():
    result = _run_climate(
        options={CONF_HVAC_VACANCY_HOLD: 0},
        data={CONF_ROOM_TYPE: ROOM_TYPE_BEDROOM},
    )
    assert _extract_suggested(result, CONF_HVAC_VACANCY_HOLD) == 0


def test_explicit_zero_is_preserved_night():
    result = _run_climate(
        options={CONF_HVAC_VACANCY_HOLD_NIGHT: 0},
        data={CONF_ROOM_TYPE: ROOM_TYPE_BEDROOM},
    )
    assert _extract_suggested(result, CONF_HVAC_VACANCY_HOLD_NIGHT) == 0


def test_explicit_value_is_preserved_day():
    result = _run_climate(
        options={CONF_HVAC_VACANCY_HOLD: 300},
        data={CONF_ROOM_TYPE: ROOM_TYPE_BEDROOM},
    )
    assert _extract_suggested(result, CONF_HVAC_VACANCY_HOLD) == 300


def test_explicit_value_is_preserved_night():
    result = _run_climate(
        options={CONF_HVAC_VACANCY_HOLD_NIGHT: 300},
        data={CONF_ROOM_TYPE: ROOM_TYPE_BEDROOM},
    )
    assert _extract_suggested(result, CONF_HVAC_VACANCY_HOLD_NIGHT) == 300


# --------- Source-level: help text describes reject-on-below (C3) ---------

def test_help_text_describes_reject_on_night_below_day():
    en_path = os.path.join(
        os.path.dirname(_CONFIG_FLOW_PY), "translations", "en.json",
    )
    with open(en_path, "r") as fh:
        en = fh.read()
    # C3: reworded from "auto-clamped to >= day" to reject-on-form,
    # runtime-clamp-blank-only wording.
    assert "rejects a night below day" in en, (
        "help text must state the form rejects a night below day"
    )
    assert "0 = disabled" in en
