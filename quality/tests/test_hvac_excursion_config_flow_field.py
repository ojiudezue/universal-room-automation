"""HVAC-GOVERNED-EXCURSION-1 fix-up r5 — kill switch moved to config flow.

The switch entity (HVACExcursionPrimitiveEnabledSwitch, formerly
`switch.ura_hvac_coordinator_excursion_primitive_enabled`) was removed
per operator ruling. The kill lever now lives as a boolean field in the
HVAC coordinator config/options flow at
``async_step_coordinator_hvac_settings`` alongside its siblings
(``hvac_arrester_enabled``, ``hvac_ac_reset_enabled``). This test file
anchors the round-trip:

  * config-flow schema declares the field (labelled "Governed thermostat
    borrows" via strings.json / translations)
  * form-save writes it to entry.options
  * __init__.py reads it from cm_config and passes it to the coordinator
    constructor as ``excursion_primitive_enabled``
  * coordinator constructor pushes the value into
    ``hvac_excursion.set_kill_switch_enabled``, which drives
    ``begin_excursion``'s kill-branch

Neuter anchors:
  * comment out the field in the config-flow schema → the schema anchor
    test fails.
  * comment out the ``_cfg.get("excursion_primitive_enabled", ...)``
    seed in __init__.py → the seed anchor test fails.
  * comment out the ``_ex_mod.set_kill_switch_enabled`` push in the
    coordinator's ``excursion_primitive_enabled`` setter → the runtime
    anchor test fails.

Kept the drill on source-anchored round-trip pieces (Bug Class #62) —
driving the full config-flow form through pytest would need
HomeAssistant's aiohttp-flow harness, which the bench doesn't have.
"""

from __future__ import annotations

import os
import re
import sys
import types
from unittest.mock import MagicMock


_URA = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation",
)


def _read(name: str) -> str:
    with open(os.path.join(_URA, name), "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Schema declaration — the config-flow step lists the new field.
# ---------------------------------------------------------------------------


def test_config_flow_schema_declares_excursion_primitive_enabled():
    src = _read("config_flow.py")
    # Locate the coordinator_hvac_settings step and slice to the next
    # method definition at class-body indent.
    idx = src.find("async def async_step_coordinator_hvac_settings(")
    assert idx != -1, (
        "could not locate async_step_coordinator_hvac_settings in "
        "config_flow.py"
    )
    m = re.search(r"^    (?:async def|def) ", src[idx + 40:], flags=re.MULTILINE)
    end = idx + 40 + m.start() if m else len(src)
    body = src[idx:end]
    # Constant is imported inside this step's local import block.
    assert "CONF_EXCURSION_PRIMITIVE_ENABLED" in body, (
        "coordinator_hvac_settings must import CONF_EXCURSION_PRIMITIVE_ENABLED"
    )
    assert "DEFAULT_EXCURSION_PRIMITIVE_ENABLED" in body, (
        "coordinator_hvac_settings must import DEFAULT_EXCURSION_PRIMITIVE_ENABLED"
    )
    # Schema declaration must be a BooleanSelector siblinged with the
    # existing HVAC coordinator-level toggles.
    assert re.search(
        r"vol\.Optional\(\s*CONF_EXCURSION_PRIMITIVE_ENABLED",
        body,
    ), "schema does not declare CONF_EXCURSION_PRIMITIVE_ENABLED as Optional"
    assert "selector.BooleanSelector()" in body


def test_config_flow_step_saves_field_to_options():
    """The step's async_create_entry writes user_input onto entry
    options (verifies the field will reach cm_config on save)."""
    src = _read("config_flow.py")
    idx = src.find("async def async_step_coordinator_hvac_settings(")
    m = re.search(r"^    (?:async def|def) ", src[idx + 40:], flags=re.MULTILINE)
    end = idx + 40 + m.start() if m else len(src)
    body = src[idx:end]
    # The step's save shape (established v3.9.0-ish): pass
    # {**self._config_entry.options, **user_input} to async_create_entry.
    # The excursion field rides on that unchanged.
    assert "async_create_entry" in body
    assert (
        "data={**self._config_entry.options, **user_input}" in body
        or "**self._config_entry.options" in body
    ), (
        "coordinator_hvac_settings save shape changed — verify the "
        "field still lands in entry options."
    )


# ---------------------------------------------------------------------------
# Strings + translations use the operator's user-facing word.
# ---------------------------------------------------------------------------


def test_strings_uses_borrows_label_not_excursion():
    """User-visible label reads 'Governed thermostat borrows' (operator
    ruling: user-facing text says 'borrow'; internal identifiers stay
    'excursion')."""
    strings = _read("strings.json")
    trans = _read("translations/en.json")
    for name, text in (("strings.json", strings), ("translations/en.json", trans)):
        assert '"excursion_primitive_enabled": "Governed thermostat borrows"' in text, (
            f"{name}: label missing or does not use the operator's "
            "user-facing 'borrows' wording"
        )


def test_strings_description_states_partial_semantics():
    """Description names the honest limit: OFF does NOT revert the three
    v5.87.1 behaviour changes (snapshot filter deleted, unconditional
    preset restore, blocking=True). Operator: 'the label must not
    overpromise'."""
    strings = _read("strings.json")
    trans = _read("translations/en.json")
    for name, text in (("strings.json", strings), ("translations/en.json", trans)):
        # Anchor on the three keywords the description MUST include so a
        # future edit that softens the honesty regresses this test.
        assert "does NOT revert" in text or "partial" in text.lower(), (
            f"{name}: description missing the partial-back-out warning"
        )
        assert "rollback to v5.87.0" in text, (
            f"{name}: description missing the full-revert escape hatch"
        )


# ---------------------------------------------------------------------------
# Seed path — __init__.py reads the field from cm_config and passes it
# to the coordinator constructor.
# ---------------------------------------------------------------------------


def test_init_seed_path_passes_field_to_coordinator():
    src = _read("__init__.py")
    # Locate the HVACCoordinator( construction and slice to its closing.
    idx = src.find("hvac = HVACCoordinator(")
    assert idx != -1, "HVACCoordinator construction not found in __init__.py"
    # Slice ~4000 chars — the constructor call is one statement, not a
    # method, so structural bound would be the closing paren; grep-in
    # for the specific kwarg is sufficient.
    body = src[idx:idx + 6000]
    assert '"excursion_primitive_enabled": bool(_cfg.get(' in body, (
        "__init__.py must seed excursion_primitive_enabled from "
        "cm_config into the HVACCoordinator kwargs. Removing this "
        "seed silently disables the config-flow toggle."
    )
    assert '"excursion_primitive_enabled", True' in body, (
        "seed must default to True (safe default per DEFAULT_EXCURSION_"
        "PRIMITIVE_ENABLED); a missing config key must NOT read as OFF."
    )


# ---------------------------------------------------------------------------
# Runtime push — coordinator setter drives hvac_excursion's kill flag.
# ---------------------------------------------------------------------------


def test_coordinator_setter_pushes_kill_switch_to_primitive():
    src = _read("domain_coordinators/hvac.py")
    # Slice the property setter.
    idx = src.find("def excursion_primitive_enabled(self, value: bool)")
    if idx == -1:
        idx = src.find("def excursion_primitive_enabled(self, value:")
    assert idx != -1, (
        "excursion_primitive_enabled property setter not found in hvac.py"
    )
    m = re.search(r"^    (?:async def|def|@)", src[idx + 40:], flags=re.MULTILINE)
    end = idx + 40 + m.start() if m else len(src)
    body = src[idx:end]
    assert "_ex_mod.set_kill_switch_enabled" in body, (
        "the setter must push the new value into "
        "hvac_excursion.set_kill_switch_enabled so begin_excursion's "
        "kill branch fires. Removing this call means the config-flow "
        "toggle changes the coordinator field but NOT the runtime behaviour."
    )


def test_coordinator_init_seeds_kill_switch_at_startup():
    """The constructor must ALSO push the seeded value into the primitive
    (not just the runtime setter) so first-tick behaviour matches the
    config value even before the setter is called."""
    src = _read("domain_coordinators/hvac.py")
    # Find the __init__ block that carries the kwarg.
    idx = src.find("self._excursion_primitive_enabled: bool = (")
    assert idx != -1, (
        "coordinator __init__ must set self._excursion_primitive_enabled"
    )
    # Slice a small window forward — the push comes right after.
    body = src[idx:idx + 1500]
    assert "_ex_mod.set_kill_switch_enabled" in body, (
        "constructor must push the seeded value into "
        "hvac_excursion.set_kill_switch_enabled so first-tick gating "
        "matches config value."
    )


# ---------------------------------------------------------------------------
# The switch entity is removed.
# ---------------------------------------------------------------------------


def test_switch_entity_removed():
    """Operator ruling r5: the kill switch moved off the dashboard.
    The HVACExcursionPrimitiveEnabledSwitch class MUST NOT reappear."""
    src = _read("switch.py")
    assert "HVACExcursionPrimitiveEnabledSwitch" not in src, (
        "Switch entity re-added. Operator ruling (fix-up r5): the "
        "kill lever lives in the config flow, not on the dashboard."
    )
    assert "switch.ura_hvac_coordinator_excursion_primitive_enabled" not in src
