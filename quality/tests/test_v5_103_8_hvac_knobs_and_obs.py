"""HVAC-DEMAND-KNOBS-AND-OBS-GAPS-1 (v5.103.8) — mutation-anchored tests.

Covers D1/D2 resolver overrides + monotonicity clamp + blank fall-through;
D6 chokepoint reason capture (helper + coordinator cache shape);
HVAC_PRESET_REASONS vocabulary completeness.

Each test is designed for the revert-in-suite drill: strip the fix in
production source and the specific test named below MUST RED under a
full-suite run.
"""
from __future__ import annotations

import ast
import asyncio
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
        "ac_reset_preset_restore", "soft_nudge_preset_restore",
        "cancel_nudge_preset_restore",
        "startup_ramp_audit_restore", "banking_release",
        "preheat_boundary", "startup_audit_nudge_preset_restore",
        # Dynamic `_auto_return(trigger=...)` values
        "lease_expiry", "stale_boot_release",
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


# ---------------------------------------------------------------------------
# D1/D2 BEHAVIORAL anchor — entry.options -> meta -> _compute_hvac_occupied
# -> resolver. Reviewer A-MED-5 / B2: without this test, making the knob
# inert (override_day/night -> None in the meta build) stayed GREEN.
# ---------------------------------------------------------------------------


def _make_room_entry(entry_id, room_name, room_type, options=None):
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM, CONF_ROOM_NAME, CONF_ROOM_TYPE,
    )

    class _E:
        pass

    e = _E()
    e.entry_id = entry_id
    e.data = {
        CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
        CONF_ROOM_NAME: room_name,
        CONF_ROOM_TYPE: room_type,
    }
    e.options = dict(options or {})
    return e


def test_entry_options_override_flows_into_hvac_tail_hold_length():
    """D1/D2 BEHAVIORAL — set CONF_HVAC_VACANCY_HOLD=300 on ONE bedroom
    entry's options; drive `update_room_conditions` twice (rising edge
    then release); assert the tail_expires_at reflects the 300s override,
    NOT the 60s ROOM_TYPE_HVAC_HOLD['bedroom'] default. A sibling bedroom
    with no override still gets the 60s table default — proves per-room
    isolation.

    Revert-in-suite: strip the meta build's override read
    (hvac_zones.py near the room_entry_meta assignment: replace
    `_coerce_hold_override(merged.get(CONF_HVAC_VACANCY_HOLD, None))`
    with `None`, and the sibling for night) -> this test REDs on the
    tail_expires_at delta.
    """
    _, hz = _bootstrap()
    from custom_components.universal_room_automation.const import (
        DOMAIN, CONF_HVAC_VACANCY_HOLD, ROOM_TYPE_BEDROOM,
    )

    # Two bedrooms: one with the override, one without.
    bed_a = _make_room_entry(
        "e_bed_a", "bed_a", ROOM_TYPE_BEDROOM,
        options={CONF_HVAC_VACANCY_HOLD: 300},
    )
    bed_b = _make_room_entry(
        "e_bed_b", "bed_b", ROOM_TYPE_BEDROOM, options={},
    )
    entries = [bed_a, bed_b]

    class _CEs:
        def async_entries(self, dom):
            return entries

    class _RoomCoord:
        def __init__(self, occupied):
            self.data = {
                "occupied": occupied,
                "temperature": None, "humidity": None,
            }
            self.config_entry = None

    hass = MagicMock()
    hass.config_entries = _CEs()
    hass.data = {DOMAIN: {
        "e_bed_a": _RoomCoord(True),
        "e_bed_b": _RoomCoord(True),
    }}
    hass.states = MagicMock()
    hass.states.get = lambda ent_id: None

    zm = hz.ZoneManager(hass)
    zone = hz.ZoneState(
        zone_id="z_bed", zone_name="BED", climate_entity="c.bed",
    )
    zone.rooms = ["bed_a", "bed_b"]
    zm._zones["z_bed"] = zone

    # Rising edge — both bedrooms arm.
    zm.update_room_conditions(house_state="home_day")
    assert zm._hvac_armed.get("bed_a") is True
    assert zm._hvac_armed.get("bed_b") is True

    # Release both -> tail schedule. tail_until = now + hold_s. The
    # override-carrying bedroom must schedule further into the future
    # than the sibling (300 vs 60 seconds).
    hass.data[DOMAIN]["e_bed_a"] = _RoomCoord(False)
    hass.data[DOMAIN]["e_bed_b"] = _RoomCoord(False)
    zm.update_room_conditions(house_state="home_day")

    tail_a = zm._hvac_tail_until.get("bed_a")
    tail_b = zm._hvac_tail_until.get("bed_b")
    assert tail_a is not None, "bed_a must have a scheduled tail"
    assert tail_b is not None, "bed_b must have a scheduled tail"
    delta_s = (tail_a - tail_b).total_seconds()
    # Override 300 vs table 60 -> difference ≈ 240s. Allow a few sec
    # slack for the two update passes' `now` divergence.
    assert 200 <= delta_s <= 280, (
        f"expected override to extend tail by ~240s over table default; "
        f"got {delta_s:.1f}s (tail_a={tail_a}, tail_b={tail_b})"
    )


# ---------------------------------------------------------------------------
# D6 CHOKEPOINT BEHAVIORAL anchor — drive emit_set_preset_mode and prove
# the cache write. Reviewer A-MED-5 / B2: neutering the two capture calls
# in emit_set_preset_mode to `pass` stayed GREEN.
# ---------------------------------------------------------------------------


def _load_hvac_setpoint():
    _bootstrap()
    return _load_module(
        "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
        os.path.join(_DC, "hvac_setpoint.py"),
    )


def test_emit_set_preset_mode_populates_last_reason_by_zone_on_success():
    """D6 BEHAVIORAL — drive `emit_set_preset_mode` end-to-end with a
    stub `hass.services.async_call` and assert
    `hvac._last_reason_by_zone[zone_id] == (reason, ts)`.

    Revert-in-suite: replace `_capture_preset_reason(hass, zone_id,
    reason)` at hvac_setpoint.py:399/409 with `pass` (or delete both
    calls) -> this test REDs (cache stays empty). Proves the two
    capture call-sites are ANCHORED, not just the helper.
    """
    hsp = _load_hvac_setpoint()
    from custom_components.universal_room_automation.const import DOMAIN

    calls: list[dict] = []

    class _Services:
        async def async_call(self, domain, service, data, blocking=False):
            calls.append({"domain": domain, "service": service, **data})

    class _HVAC:
        pass

    hvac = _HVAC()

    class _CM:
        coordinators = {"hvac": hvac}

    hass = MagicMock()
    hass.services = _Services()
    hass.data = {DOMAIN: {"coordinator_manager": _CM()}}
    hass.states = MagicMock()
    hass.states.get = lambda ent_id: None

    async def _drive():
        return await hsp.emit_set_preset_mode(
            hass,
            "climate.zone_1",
            "away",
            blocking=False,
            zone_id="zone_1",
            reason="runtime_exceeded",
        )

    ok = asyncio.new_event_loop().run_until_complete(_drive())
    assert ok is True
    # Preset call was actually issued.
    assert any(c["service"] == "set_preset_mode" for c in calls)
    # Cache populated (Bug Class #53 anchor).
    cache = getattr(hvac, "_last_reason_by_zone", None)
    assert cache is not None, (
        "chokepoint success MUST populate _last_reason_by_zone; a "
        "neutered _capture_preset_reason() call would leave this None"
    )
    entry = cache.get("zone_1")
    assert entry is not None and entry[0] == "runtime_exceeded"


# ---------------------------------------------------------------------------
# D6 AST-based completeness — replaces the regex, which stopped at the
# first `)` and missed nested-paren call args (egress_resume via the
# gate=lambda call, severe_override_revert with nested paren). Walks
# every emit_set_preset_mode Call node in the 5 HVAC files.
# ---------------------------------------------------------------------------


def _collect_emit_reason_literals_ast(paths):
    """Return set of string literals passed to `emit_set_preset_mode`
    as `reason=` at every call site. Ignores non-literal `reason=`
    values (they're covered by explicit dynamic-source enumeration
    below)."""
    found: set[str] = set()
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src, filename=p)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            fname = None
            if isinstance(func, ast.Name):
                fname = func.id
            elif isinstance(func, ast.Attribute):
                fname = func.attr
            if fname != "emit_set_preset_mode":
                continue
            for kw in node.keywords:
                if kw.arg != "reason":
                    continue
                if isinstance(kw.value, ast.Constant) and isinstance(
                    kw.value.value, str,
                ):
                    found.add(kw.value.value)
    return found


def _collect_auto_return_trigger_literals_ast(paths):
    """Excursion `_auto_return(trigger=...)` callers feed the
    `reason=trigger` at hvac_excursion.py:675. Walk every call to
    `_auto_return` with a literal `trigger=` and return the set."""
    found: set[str] = set()
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src, filename=p)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            fname = None
            if isinstance(func, ast.Name):
                fname = func.id
            elif isinstance(func, ast.Attribute):
                fname = func.attr
            if fname != "_auto_return":
                continue
            for kw in node.keywords:
                if kw.arg != "trigger":
                    continue
                if isinstance(kw.value, ast.Constant) and isinstance(
                    kw.value.value, str,
                ):
                    found.add(kw.value.value)
    return found


def _collect_s1_ladder_literals_ast(hvac_path):
    """S1 ladder assigns literals to `preset_change_reason` at
    hvac.py:2273-2306. Grep all string literals that are the RHS of an
    assignment to `preset_change_reason`."""
    found: set[str] = set()
    if not os.path.exists(hvac_path):
        return found
    with open(hvac_path, "r", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src, filename=hvac_path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        # look for targets like `preset_change_reason = "..."`
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id == "preset_change_reason":
                if isinstance(node.value, ast.Constant) and isinstance(
                    node.value.value, str,
                ):
                    found.add(node.value.value)
    return found


def test_hvac_preset_reasons_ast_completeness_across_all_call_sites():
    """D6 AST-based completeness. Enumerate every emitted reason via
    AST walk (not regex — which stopped at first `)` and MISSED
    `egress_resume` and `severe_override_revert` through nested-paren
    `gate=(lambda ...)` arg-lists). Union all sources of `reason=` at
    `emit_set_preset_mode`:
      - Literal `reason="..."` kwargs.
      - Dynamic `reason=trigger` at hvac_excursion.py:675 sourced from
        `_auto_return(trigger=...)` callers.
      - Dynamic `reason=preset_change_reason` at hvac.py:2360 sourced
        from the S1 ladder assignments in `_apply_house_state_presets`.

    All of these must be members of HVAC_PRESET_REASONS.

    Revert-in-suite: add `reason="magic_new_reason"` at any call site
    (e.g. hvac_egress.py:801-803, hvac_override.py:3555) -> RED.
    Similarly, add a new `_auto_return(trigger="new_trigger", ...)`
    call -> RED. Or add a new `preset_change_reason = "new"` branch
    in the S1 ladder -> RED.
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
    found = _collect_emit_reason_literals_ast(site_files)
    found |= _collect_auto_return_trigger_literals_ast([
        os.path.join(_DC, "hvac.py"),
        os.path.join(_DC, "hvac_excursion.py"),
        os.path.join(_DC, "hvac_predict.py"),
        os.path.join(_DC, "hvac_override.py"),
    ])
    found |= _collect_s1_ladder_literals_ast(
        os.path.join(_DC, "hvac.py"),
    )
    # Sanity: the AST scan MUST find the load-bearing sentinel names,
    # else the walker itself is broken.
    assert "egress_resume" in found, (
        "AST walker failed to detect hvac_egress.py:803 emission"
    )
    assert "severe_override_revert" in found, (
        "AST walker failed to detect hvac_override.py:3555 emission"
    )
    assert "runtime_exceeded" in found, (
        "AST walker failed to detect S1 ladder literals"
    )
    assert "lease_expiry" in found, (
        "AST walker failed to detect _auto_return(trigger=...) callers"
    )
    missing = found - reasons
    assert not missing, (
        f"reasons emitted at runtime but missing from HVAC_PRESET_REASONS: "
        f"{sorted(missing)}"
    )
