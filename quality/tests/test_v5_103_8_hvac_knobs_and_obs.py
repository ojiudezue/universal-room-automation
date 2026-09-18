"""HVAC-DEMAND-KNOBS-AND-OBS-GAPS-1 (v5.103.8) — mutation-anchored tests.

Covers D1/D2 resolver overrides + monotonicity clamp + blank fall-through;
D6 chokepoint reason capture (helper + coordinator cache shape);
HVAC_PRESET_REASONS vocabulary completeness.

Each test is designed for the revert-in-suite drill: strip the fix in
production source and the specific test named below MUST RED under a
full-suite run.
"""
from __future__ import annotations

import importlib.util as _ilu
import os
import re
import sys
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock


_HERE = os.path.dirname(__file__)
_URA = os.path.abspath(os.path.join(_HERE, "..", "..",
                                    "custom_components",
                                    "universal_room_automation"))
_DC = os.path.join(_URA, "domain_coordinators")


def _load_module(mod_name: str, path: str):
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = _ilu.spec_from_file_location(mod_name, path)
    m = _ilu.module_from_spec(spec)
    sys.modules[mod_name] = m
    spec.loader.exec_module(m)
    return m


def _bootstrap():
    # Minimal HA stubs shared with sibling test files.
    if "homeassistant" not in sys.modules:
        for name in ("homeassistant",
                     "homeassistant.core",
                     "homeassistant.config_entries",
                     "homeassistant.const",
                     "homeassistant.util",
                     "homeassistant.util.dt"):
            sys.modules.setdefault(name, types.ModuleType(name))
        sys.modules["homeassistant.core"].HomeAssistant = MagicMock
        sys.modules["homeassistant.core"].callback = lambda f: f
        sys.modules["homeassistant.config_entries"].ConfigEntry = MagicMock
        dt = sys.modules["homeassistant.util.dt"]
        dt.utcnow = lambda: datetime.now(timezone.utc)
        dt.now = lambda: datetime.now(timezone.utc)
        dt.parse_datetime = lambda s: None
    # Package shims.
    if "custom_components" not in sys.modules:
        cc = types.ModuleType("custom_components")
        cc.__path__ = [os.path.abspath(os.path.join(_URA, ".."))]
        sys.modules["custom_components"] = cc
    if "custom_components.universal_room_automation" not in sys.modules:
        ura = types.ModuleType("custom_components.universal_room_automation")
        ura.__path__ = [_URA]
        ura.__package__ = "custom_components.universal_room_automation"
        sys.modules["custom_components.universal_room_automation"] = ura
    if ("custom_components.universal_room_automation.domain_coordinators"
            not in sys.modules):
        dc = types.ModuleType(
            "custom_components.universal_room_automation.domain_coordinators"
        )
        dc.__path__ = [_DC]
        sys.modules[
            "custom_components.universal_room_automation.domain_coordinators"
        ] = dc
    const = _load_module(
        "custom_components.universal_room_automation.const",
        os.path.join(_URA, "const.py"),
    )
    _load_module(
        "custom_components.universal_room_automation.domain_coordinators.hvac_const",
        os.path.join(_DC, "hvac_const.py"),
    )
    hz = _load_module(
        "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
        os.path.join(_DC, "hvac_zones.py"),
    )
    return const, hz


# ---------------------------------------------------------------------------
# D1/D2 — resolver override + blank fall-through + monotonicity clamp
# ---------------------------------------------------------------------------

def _fresh_zm():
    """Fresh ZoneManager with a stubbed hass; D1 resolver is pure."""
    _, hz = _bootstrap()
    return hz.ZoneManager(MagicMock())


def test_coerce_hold_override_maps_blank_and_bad_to_none():
    """_coerce_hold_override must return None for blank / non-numeric /
    negative inputs; must PRESERVE explicit 0 (the legitimate never-hold
    value that hallway rooms use).

    Revert-in-suite: change `if raw is None or raw == ""` to `if raw
    is None or raw == "" or raw == 0` and this test REDs on 0.
    """
    _, hz = _bootstrap()
    coerce = hz._coerce_hold_override
    assert coerce(None) is None
    assert coerce("") is None
    assert coerce("not a number") is None
    assert coerce(-1) is None
    # Zero MUST be preserved — hallway table default is 0.
    assert coerce(0) == 0
    assert coerce("0") == 0
    assert coerce(120) == 120
    assert coerce("180") == 180


def test_effective_hold_prefers_entry_options_over_room_type_table():
    """D1/D2 — override_day / override_night win over the table default.

    Revert-in-suite: delete the `if override_day is not None: day_val
    = int(override_day)` branch in `_effective_hvac_hold_seconds` and
    the test REDs (returns 60 from ROOM_TYPE_HVAC_HOLD['bedroom']).
    """
    zm = _fresh_zm()
    # Non-trust house_state -> day table. Bedroom day default is 60.
    got = zm._effective_hvac_hold_seconds(
        "bedroom", house_state="home_day",
        override_day=300, override_night=1800,
    )
    assert got == 300, f"override_day must win over table 60; got {got}"


def test_effective_hold_blank_falls_through_not_zero():
    """D1/D2 — a blank override MUST fall through to the room-type table,
    NEVER coerced to 0 (0 is the hallway-only never-hold value).

    Revert-in-suite: replace fall-through with `day_val = int(override_day or 0)`
    and the test REDs (returns 0 instead of 60).
    """
    zm = _fresh_zm()
    got = zm._effective_hvac_hold_seconds(
        "bedroom", house_state="home_day",
        override_day=None, override_night=None,
    )
    assert got == 60, f"blank override must fall through to table 60; got {got}"


def test_effective_hold_clamps_night_up_to_day_pure():
    """D1/D2 monotonicity — same as above but without caplog wiring
    (kept as the definitive assertion; a mutation-verify anchor).
    """
    zm = _fresh_zm()
    # Trust states include 'home_night' (see FAN_TRUST_STATES).
    got = zm._effective_hvac_hold_seconds(
        "bedroom", house_state="home_night",
        override_day=600, override_night=300,
    )
    assert got == 600, (
        f"night ({300}) must be clamped up to day ({600}); got {got}"
    )
    # Clamp state is recorded so the log-once discipline is exercised.
    assert getattr(zm, "_hvac_hold_clamp_logged", set()), (
        "clamp path must record the (room_type, 'night_lt_day') key"
    )


# ---------------------------------------------------------------------------
# D6 — HVAC_PRESET_REASONS vocabulary completeness
# ---------------------------------------------------------------------------

def test_hvac_preset_reasons_frozenset_present_and_complete():
    """D6 — vocabulary completeness. Every literal `reason=` string
    passed to `emit_set_preset_mode` at the 11 URA-side sites must be a
    member of HVAC_PRESET_REASONS.

    Revert-in-suite: delete `banking_release` (or any other emitted
    literal) from the frozenset and the test REDs.
    """
    const, _ = _bootstrap()
    reasons = const.HVAC_PRESET_REASONS
    # frozenset invariant.
    assert isinstance(reasons, frozenset)
    # Every documented emission literal (planning §Falsifiable invariant).
    required = {
        # S1 ladder
        "stale_occupancy", "vacant_past_grace", "runtime_exceeded",
        "pre_arrival", "house_state_transition", "comfort_delay_active",
        # Static site literals
        "egress_resume", "severe_override_revert",
        "ac_reset_preset_restore", "cancel_nudge_preset_restore",
        "startup_ramp_audit_restore", "banking_release",
        "preheat_boundary", "startup_audit_nudge_preset_restore",
        # Dynamic excursion trigger values
        "excursion_return", "excursion_timeout", "excursion_settled",
        # Sentinel
        "unknown",
    }
    missing = required - reasons
    assert not missing, f"HVAC_PRESET_REASONS missing: {sorted(missing)}"


def test_hvac_preset_reasons_covers_emit_set_preset_mode_call_literals():
    """D6 — targeted re-enumeration. For every call to
    `emit_set_preset_mode(...)`, if the call passes `reason="..."` as
    a bare literal, that literal MUST be in HVAC_PRESET_REASONS.

    Revert-in-suite: add a new emission site with a new literal (e.g.
    `reason="magic_new_reason"`) and this test REDs.
    """
    const, _ = _bootstrap()
    reasons = const.HVAC_PRESET_REASONS
    site_files = [
        os.path.join(_DC, "hvac.py"),
        os.path.join(_DC, "hvac_egress.py"),
        os.path.join(_DC, "hvac_excursion.py"),
        os.path.join(_DC, "hvac_override.py"),
        os.path.join(_DC, "hvac_predict.py"),
    ]
    # Match only `reason="literal"` occurring within an
    # `emit_set_preset_mode(...)` call (a multi-line arg-list). The
    # non-greedy `.*?` bounded by the closing paren of the call
    # scopes us to the call args, so unrelated `reason="..."` in
    # docstrings / comments elsewhere are ignored.
    call_re = re.compile(
        r"emit_set_preset_mode\s*\((?P<body>.*?)\)",
        re.DOTALL,
    )
    reason_re = re.compile(r'reason\s*=\s*"([^"]+)"')
    found: set[str] = set()
    for path in site_files:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        for call in call_re.finditer(src):
            for m in reason_re.finditer(call.group("body")):
                found.add(m.group(1))
    missing = found - reasons
    assert not missing, (
        f"reason literals passed to emit_set_preset_mode not in "
        f"HVAC_PRESET_REASONS: {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# D6 — chokepoint reason-capture helper populates the coordinator cache
# ---------------------------------------------------------------------------

def test_capture_preset_reason_writes_to_hvac_last_reason_by_zone():
    """D6 — the chokepoint helper populates
    `hvac._last_reason_by_zone[zone_id] = (reason, ts)`.

    Revert-in-suite: remove the `_capture_preset_reason(hass, zone_id,
    reason)` call at the two success returns in `emit_set_preset_mode`
    and any consumer of `retreat_reason` will see `unknown` — this
    test simulates the helper directly and REDs if the helper is
    a no-op.
    """
    _bootstrap()
    # Load hvac_setpoint (needs an extra shim on aiosqlite / etc? No —
    # only imports HomeAssistant type + hvac_const).
    hvac_setpoint = _load_module(
        "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
        os.path.join(_DC, "hvac_setpoint.py"),
    )
    # Stub the HVAC coordinator inside hass.data[DOMAIN].
    class _HVAC:
        pass
    hvac = _HVAC()
    class _CM:
        coordinators = {"hvac": hvac}
    from custom_components.universal_room_automation.const import DOMAIN
    hass = MagicMock()
    hass.data = {DOMAIN: {"coordinator_manager": _CM()}}
    hvac_setpoint._capture_preset_reason(hass, "zone_1", "runtime_exceeded")
    hvac_setpoint._capture_preset_reason(hass, "zone_2", "egress_resume")
    cache = getattr(hvac, "_last_reason_by_zone", None)
    assert cache is not None, "helper must create the cache dict"
    assert cache["zone_1"][0] == "runtime_exceeded"
    assert cache["zone_2"][0] == "egress_resume"
    # Empty reason -> sentinel 'unknown' (never-crash contract).
    hvac_setpoint._capture_preset_reason(hass, "zone_3", "")
    assert cache["zone_3"][0] == "unknown"


def test_capture_preset_reason_never_raises_on_missing_manager():
    """D6 — chokepoint helper is best-effort; a missing coordinator
    manager, missing hvac, or missing DOMAIN key must NEVER raise.
    """
    _bootstrap()
    hvac_setpoint = _load_module(
        "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
        os.path.join(_DC, "hvac_setpoint.py"),
    )
    hass = MagicMock()
    hass.data = {}
    hvac_setpoint._capture_preset_reason(hass, "zone_1", "runtime_exceeded")
    # (no assertion — the test passes iff no exception raised)


def test_capture_preset_reason_no_zone_id_is_noop():
    """D6 — empty zone_id short-circuits (no cache write)."""
    _bootstrap()
    hvac_setpoint = _load_module(
        "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
        os.path.join(_DC, "hvac_setpoint.py"),
    )
    class _HVAC:
        pass
    hvac = _HVAC()
    class _CM:
        coordinators = {"hvac": hvac}
    from custom_components.universal_room_automation.const import DOMAIN
    hass = MagicMock()
    hass.data = {DOMAIN: {"coordinator_manager": _CM()}}
    hvac_setpoint._capture_preset_reason(hass, "", "runtime_exceeded")
    assert not getattr(hvac, "_last_reason_by_zone", None)
