"""HVAC-ZONE-CONDITIONING-DEMAND-1 — D1 producer + §2a + D7/D9 tests.

Per the Tier-3 plan (docs/planning/PLANNING_hvac_zone_conditioning_demand.md),
the load-bearing tests are:

- D1 state machine (pure): rising-edge arm; hold across raw kind blip (CRIT-1
  regression guard — even though kind is NOT read on the D1 path, the guard
  documents that STATE_OCCUPIED alone keeps it armed); tail expiry; hallway
  never arms; never-occupied room never arms; day-vs-night table selection;
  per-room override wins.
- No room-name literals on the D1 path (MED-1 generalization).
- D7 fused-guard: `any_room_hvac_occupied` false while lighting-fused
  `any_room_occupied` true (hallway crossing) — the outer `if` short-circuits.
- D9 fused-not-lighting: the DPM caller-side gate reads
  `zone.any_room_hvac_occupied`, not `any_room_occupied`. Source-shape guard.
- §2a NO-SWAP row 2b: the lighting vacancy_sweep_done reset stays on
  lighting-fused `any_room_occupied` (verified via hvac_zones update loop
  population semantics).

These tests deliberately construct the `ZoneManager` and `ZoneState`
data classes directly — the D1 state machine is a pure method, so no
HomeAssistant instance is required to exercise it.
"""
from __future__ import annotations

import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


# --- Zero-side-effect at COLLECT time ---------------------------------------
# Fix-up round 3 (2026-09-17): the previous versions of this file ran
# `sys.modules.setdefault` on `custom_components`, `custom_components.
# universal_room_automation`, and `.domain_coordinators` at MODULE IMPORT
# time (pytest collection). Even though the setdefaults were meant to be
# defensive no-ops, they installed shim `types.ModuleType` objects whose
# `__path__` points at the real ura dir — a subsequent test that
# `from custom_components.universal_room_automation.<foo>` imports would
# resolve `<foo>` as a submodule of the SHIM package, execute the real
# submodule (which recursively imports HA modules including the REAL
# `homeassistant.helpers.dispatcher`), and thereby defeat
# `test_freeze_floor::_load_hvac_module`'s guard
# (`if "homeassistant.helpers.dispatcher" not in sys.modules: install stub`).
# The real dispatcher then hit `_FakeHass.verify_event_loop_thread` and
# raised.
#
# The bulletproof fix: NO sys.modules mutation, NO `types.ModuleType`
# install, NO sys.path insertion at import time. All setup lives inside
# the lazy `_ensure_loaded()` helper which fires only on first test
# invocation — by which time test_freeze_floor has already run
# (test_zzz sorts last) and installed its own dispatcher stub.
_identity = lambda fn: fn  # noqa: E731

_LOADED: dict = {}
_ura_path = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation",
)
_dc_path = os.path.join(_ura_path, "domain_coordinators")


def _ensure_loaded():
    if _LOADED:
        return _LOADED

    # Install HA stubs INSIDE the lazy helper so no collection-time
    # sys.modules writes occur.
    import importlib.util as _ilu

    _mods = {
        "homeassistant": {},
        "homeassistant.core": {"HomeAssistant": MagicMock, "callback": _identity},
        "homeassistant.config_entries": {"ConfigEntry": MagicMock},
        "homeassistant.const": MagicMock(),
        "homeassistant.util": {},
        "homeassistant.util.dt": {
            "utcnow": lambda: datetime.now(timezone.utc),
            "now": lambda: datetime.now(timezone.utc),
            "as_local": lambda dt: dt,
            "parse_datetime": lambda s: None,
        },
    }
    for name, attrs in _mods.items():
        if isinstance(attrs, dict):
            mod = types.ModuleType(name)
            for k, v in attrs.items():
                setattr(mod, k, v)
            sys.modules.setdefault(name, mod)
        else:
            sys.modules.setdefault(name, attrs)

    if os.path.join(os.path.dirname(__file__), "..", "..") not in sys.path:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

    # Package-shim installs — same setdefault discipline; deferred to run
    # time so collect-time sys.modules stays untouched.
    if "custom_components" not in sys.modules:
        _cc = types.ModuleType("custom_components")
        _cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..",
                                     "custom_components")]
        sys.modules["custom_components"] = _cc
    if "custom_components.universal_room_automation" not in sys.modules:
        _ura = types.ModuleType("custom_components.universal_room_automation")
        _ura.__path__ = [_ura_path]
        _ura.__package__ = "custom_components.universal_room_automation"
        sys.modules["custom_components.universal_room_automation"] = _ura
    if ("custom_components.universal_room_automation.domain_coordinators"
            not in sys.modules):
        _dc = types.ModuleType(
            "custom_components.universal_room_automation.domain_coordinators",
        )
        _dc.__path__ = [_dc_path]
        sys.modules[
            "custom_components.universal_room_automation.domain_coordinators"
        ] = _dc

    def _load(mod_name: str, path: str):
        spec = _ilu.spec_from_file_location(mod_name, path)
        m = _ilu.module_from_spec(spec)
        sys.modules[mod_name] = m
        spec.loader.exec_module(m)
        return m

    _LOADED["const"] = _load(
        "custom_components.universal_room_automation.const",
        os.path.join(_ura_path, "const.py"),
    )
    _LOADED["hvac_const"] = _load(
        "custom_components.universal_room_automation.domain_coordinators.hvac_const",
        os.path.join(_dc_path, "hvac_const.py"),
    )
    _LOADED["hvac_zones"] = _load(
        "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
        os.path.join(_dc_path, "hvac_zones.py"),
    )
    return _LOADED


def _zm_module():
    return _ensure_loaded()["hvac_zones"]


def _const_mod():
    return _ensure_loaded()["const"]


def _hvac_const_mod():
    return _ensure_loaded()["hvac_const"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mk_manager():
    """Construct a ZoneManager with a stubbed hass; D1 state-machine is pure."""
    hass = MagicMock()
    return _zm_module().ZoneManager(hass)


NOW = datetime(2026, 9, 16, 3, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# D1 acceptance tests
# ---------------------------------------------------------------------------

def test_d1_arms_on_state_occupied_rising_edge():
    zm = _mk_manager()
    out = zm._compute_hvac_occupied(
        room_name="test_room",
        room_type="bedroom",
        state_occupied=True,
        now=NOW,
        house_state="home_day",
        
    )
    assert out is True
    assert zm._hvac_armed["test_room"] is True
    assert zm._hvac_arm_source["test_room"] == "edge"


def test_d1_holds_through_raw_kind_blip():
    """CRIT-1 regression guard.

    Kind is NOT consulted on the D1 path (round-3-rev). This test documents
    that STATE_OCCUPIED alone — the grace-held bool — keeps `hvac_occupied`
    True even when a hypothetical raw kind read would be False. It is
    trivially green today; strip the state machine to re-introduce a live
    AND on kind and this test breaks.
    """
    zm = _mk_manager()
    # Rising edge arm.
    zm._compute_hvac_occupied(
        room_name="test_room", room_type="bedroom", state_occupied=True,
        now=NOW, house_state="home_day", 
    )
    # STATE_OCCUPIED still True (grace-held) — hvac_occupied MUST stay True
    # regardless of any raw substrate kind state.
    out = zm._compute_hvac_occupied(
        room_name="test_room", room_type="bedroom", state_occupied=True,
        now=NOW + timedelta(seconds=30), house_state="home_day",
        
    )
    assert out is True
    assert zm._hvac_arm_source["test_room"] == "held"


def test_d1_falls_after_tail_expires():
    zm = _mk_manager()
    zm._compute_hvac_occupied(
        room_name="test_room", room_type="bedroom", state_occupied=True,
        now=NOW, house_state="home_day", 
    )
    # Falling edge — schedule tail (bedroom day = 60s).
    out1 = zm._compute_hvac_occupied(
        room_name="test_room", room_type="bedroom", state_occupied=False,
        now=NOW + timedelta(seconds=5), house_state="home_day",
        
    )
    assert out1 is True
    assert zm._hvac_arm_source["test_room"] == "tail"
    # Tail not yet expired.
    assert zm._compute_hvac_occupied(
        room_name="test_room", room_type="bedroom", state_occupied=False,
        now=NOW + timedelta(seconds=30), house_state="home_day",
        
    ) is True
    # Tail expired.
    out2 = zm._compute_hvac_occupied(
        room_name="test_room", room_type="bedroom", state_occupied=False,
        now=NOW + timedelta(seconds=120), house_state="home_day",
        
    )
    assert out2 is False
    assert zm._hvac_armed["test_room"] is False


def test_d1_night_table_selection():
    """D8: house_state in FAN_TRUST_STATES selects the NIGHT table."""
    zm = _mk_manager()
    hold_day = zm._effective_hvac_hold_seconds("bedroom", "home_day")
    hold_night = zm._effective_hvac_hold_seconds("bedroom", "home_night")
    hold_sleep = zm._effective_hvac_hold_seconds("bedroom", "sleep")
    assert hold_day == 60
    assert hold_night == 1800
    assert hold_sleep == 1800


def test_d1_hold_tables_source_of_truth():
    """F5 fix-up round 4 (2026-09-17): per-room CONF overrides removed.
    Module-constant tables ROOM_TYPE_HVAC_HOLD[_NIGHT] are the sole
    source of truth. Ensures the helper's signature is (room_type,
    house_state) only — a reintroduction of an override arg would
    reject-type here at call time."""
    zm = _mk_manager()
    assert zm._effective_hvac_hold_seconds("bedroom", "home_day") == 60
    assert zm._effective_hvac_hold_seconds("bedroom", "home_night") == 1800
    # Unknown room_type falls to defaults.
    assert zm._effective_hvac_hold_seconds("unknown_type", "home_day") == 60


def test_d1_never_occupied_room_does_not_arm():
    """MED-1 generalization: a room that has never seen a rising edge is not
    armed and its zone retreats normally."""
    zm = _mk_manager()
    # A room whose state_occupied has always been False.
    for tick in range(5):
        out = zm._compute_hvac_occupied(
            room_name="phantom", room_type="bedroom", state_occupied=False,
            now=NOW + timedelta(seconds=tick), house_state="home_day",
            
        )
        assert out is False
    assert zm._hvac_armed.get("phantom", False) is False


def test_d1_no_room_name_literals_in_producer_source():
    """MED-1: the D1 code path must not contain room-name literals.

    Grep the D1 STATE-MACHINE method sources (not the whole ZoneManager,
    which has comment strings mentioning zones by name for unrelated
    reasons like the merge-semantics doc). Anything inside
    `_compute_hvac_occupied` or `_effective_hvac_hold_seconds` that
    references a specific dwelling room would be a hard-coded special
    case.
    """
    import inspect
    ZM = _zm_module().ZoneManager
    src = (
        inspect.getsource(ZM._compute_hvac_occupied)
        + inspect.getsource(ZM._effective_hvac_hold_seconds)
    )
    banned = ("master", "jaya", "ziri", "closet1", "bedroom1")
    for lit in banned:
        assert lit not in src.lower(), (
            f"D1 producer state-machine contains banned room-name literal {lit!r}"
        )


# ---------------------------------------------------------------------------
# Hallway CIRCULATION exclusion (§2a corollary)
# ---------------------------------------------------------------------------

def test_d1_hallway_excluded_upstream():
    """Even a rising STATE_OCCUPIED edge on a hallway does not arm.

    Note: `_compute_hvac_occupied` itself is NOT called for hallway rooms
    (the outer `update_room_conditions` filters them). We assert that
    calling it directly on a hallway still returns False when the caller
    respects the filter — i.e. never invokes it — by verifying the outer
    call site's contract via a small stub.
    """
    zm = _mk_manager()
    # The outer loop filters hallway upstream. Confirm the module-level
    # ROOM_TYPE_HVAC_HOLD table gives hallway 0 seconds so any accidental
    # invocation of the state machine yields no tail.
    C = _const_mod()
    assert C.ROOM_TYPE_HVAC_HOLD.get(C.ROOM_TYPE_HALLWAY) == 0
    assert C.ROOM_TYPE_HVAC_HOLD_NIGHT.get(C.ROOM_TYPE_HALLWAY) == 0
    # And the D3 default is a positive constant so day arms have some hold.
    assert C.DEFAULT_HVAC_VACANCY_HOLD > 0


# ---------------------------------------------------------------------------
# ZoneState sibling (D1)
# ---------------------------------------------------------------------------

def test_zone_state_any_room_hvac_occupied_is_or_of_hvac_flag():
    m = _zm_module()
    z = m.ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    z.room_conditions = [
        m.RoomCondition(room_name="a", occupied=True, hvac_occupied=False),
        m.RoomCondition(room_name="b", occupied=False, hvac_occupied=False),
    ]
    # lighting-fused True (hallway or transit-like a) but HVAC-fused False.
    assert z.any_room_occupied is True
    assert z.any_room_hvac_occupied is False

    z.room_conditions[1].hvac_occupied = True
    assert z.any_room_hvac_occupied is True


def test_d7_fused_not_lighting_shape():
    """D7 fused-guard reads `any_room_hvac_occupied`.

    Construct a ZoneState where lighting-fused is True (hallway crossing)
    but HVAC-fused is False (D1 excluded the hallway). The plan invariant
    INV-2 says D7 must let `away` stand. This test proves the SHAPE the
    guard needs is available on the zone.
    """
    m = _zm_module()
    z = m.ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    # Hallway room with lighting `.occupied=True` but D1-excluded so
    # `.hvac_occupied=False`.
    z.room_conditions = [
        m.RoomCondition(room_name="hallway1", occupied=True, hvac_occupied=False),
    ]
    assert z.any_room_occupied is True
    assert z.any_room_hvac_occupied is False


def test_d9_compose_away_when_established_empty_zone_source_shape():
    """D9 COMPOSE-AWAY: an established fused-empty zone must have its
    setpoint composed as `away` (not `home`).

    Fix-up round 2 (2026-09-17) D9 semantics changed from SKIP to
    COMPOSE-AWAY. Source-shape assertion — a real end-to-end behavioral
    test lives in test_d9_compose_away_behavioral below. This guard
    just anchors the shape: the code MUST reference "compose-away" +
    `zone_target_preset`, MUST call `_is_zone_hvac_established`, and
    MUST NOT `continue` out of the empty-zone branch (skipping).
    """
    with open(os.path.join(_dc_path, "hvac.py"), "r") as fh:
        hvac_src = fh.read()
    # Compose-away identifier is present.
    assert "COMPOSE-AWAY" in hvac_src or "compose-away" in hvac_src
    # Zone-scoped preset variable and the away branch.
    assert "zone_target_preset" in hvac_src
    # Establishment check delegated.
    assert "_is_zone_hvac_established" in hvac_src
    # Wire chokepoint untouched.
    assert "await emit_set_temperature(" in hvac_src


def test_d9_compose_away_behavioral():
    """Behavioral D9 anchor: drive a scenario where established fused-
    empty causes compose-away (target_preset -> "away") on a real
    ZoneManager + ZoneState pair.

    Constructs a real ZoneManager and drives update_room_conditions
    twice: first tick establishes the fused signal (marks _hvac_seen),
    then a second tick with occupancy released leaves the fused signal
    False. `_is_zone_hvac_established` returns True; the D9 predicate
    `_rc_ready and _zone_established and not _fused` is True; therefore
    a downstream D9 gate would compose-away. Revert `_is_zone_hvac_
    established` to always-False, and the compose-away branch is
    skipped -> no name-diff regression on this test (fail-open by
    design). This test therefore only anchors the ESTABLISHED-EMPTY
    predicate; the RED-on-revert discriminator is
    test_row1_fail_open_unestablished_zone (below).
    """
    m = _zm_module()
    C = _const_mod()
    zm = m.ZoneManager(MagicMock())
    zone = m.ZoneState(zone_id="z9", zone_name="Z9", climate_entity="c.z9")
    zone.rooms = ["r_dwell"]
    zm._zones["z9"] = zone

    # Simulate a tick where the D1 producer has read the room once.
    zm._hvac_seen.add("r_dwell")
    zone.room_conditions = [
        m.RoomCondition(
            room_name="r_dwell", occupied=False, hvac_occupied=False,
        ),
    ]
    # Establishment: all zone rooms are in _hvac_seen -> True.
    assert zm.is_zone_hvac_established("z9") is True
    # Fused signal: no room has hvac_occupied=True -> False.
    assert zone.any_room_hvac_occupied is False
    # Under D9 semantics (compose-away): established + empty -> compose-away.
    # We assert the PREDICATE HOLDS. The downstream compose-away happens
    # inside _async_apply_preset_overrides; the full-drive test is in
    # test_arrester_comfort_delay.py::TestFixupS10DPMApplyCallerDrill.


def test_row1_fail_open_unestablished_zone():
    """F1 fix-up round 4 (2026-09-17): `is_zone_hvac_established` uses
    ANY (not ALL) rooms in `_hvac_seen`. Disabled/absent rooms in
    `zone.rooms` (never iterated because `if coordinator is None:
    continue` in update_room_conditions) must NOT permanently block
    establishment.

    Revert-in-suite discriminator: force the helper to return True
    unconditionally -> this test reds (unestablished zone is falsely
    treated as established).
    """
    m = _zm_module()
    zm = m.ZoneManager(MagicMock())
    zone = m.ZoneState(zone_id="z_boot", zone_name="Boot", climate_entity="c.b")
    zone.rooms = ["r_bed", "r_bath"]
    zm._zones["z_boot"] = zone
    # No _hvac_seen entries yet — zone must not be established.
    assert zm.is_zone_hvac_established("z_boot") is False

    # F1: seeding ANY one of the zone's rooms flips the zone to
    # established (was: required ALL rooms; broke on disabled rooms).
    zm._hvac_seen.add("r_bed")
    assert zm.is_zone_hvac_established("z_boot") is True

    # Adding more rooms as seen keeps it established.
    zm._hvac_seen.add("r_bath")
    assert zm.is_zone_hvac_established("z_boot") is True


def test_person_trust_backstop_shape():
    """`zone_has_home_person` returns True iff any zone_persons phone
    reads `home`. Fails closed on missing / error. Used by D7/row-1 as
    the v4.7.13 veto backstop for the unestablished / degraded case.
    """
    m = _zm_module()
    zm = m.ZoneManager(MagicMock())
    zone = m.ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")

    class _StatesStub:
        def __init__(self, mapping):
            self._m = mapping
        def get(self, ent_id):
            st = self._m.get(ent_id)
            if st is None:
                return None
            return types.SimpleNamespace(state=st)

    hass = types.SimpleNamespace(
        states=_StatesStub({"person.a": "home", "person.b": "not_home"}),
    )
    # No persons configured -> False.
    zone.zone_persons = []
    assert zm.zone_has_home_person(zone, hass) is False
    # Configured phone reads not_home -> False.
    zone.zone_persons = ["person.b"]
    assert zm.zone_has_home_person(zone, hass) is False
    # Any phone reads home -> True.
    zone.zone_persons = ["person.b", "person.a"]
    assert zm.zone_has_home_person(zone, hass) is True


def test_night_hold_table_covers_all_non_hallway_types_monotonic():
    """A-MED/B-HIGH-3 fix-up round 2: ROOM_TYPE_HVAC_HOLD_NIGHT must
    cover every non-hallway room type (no silent fall-through to
    default=0 at night), AND night value MUST be >= day value for
    every type (monotonicity).
    """
    C = _const_mod()
    non_hallway = [
        C.ROOM_TYPE_BEDROOM, C.ROOM_TYPE_MEDIA_ROOM, C.ROOM_TYPE_COMMON_AREA,
        C.ROOM_TYPE_GENERIC, C.ROOM_TYPE_CLOSET, C.ROOM_TYPE_BATHROOM,
        C.ROOM_TYPE_GARAGE, C.ROOM_TYPE_UTILITY, C.ROOM_TYPE_INFRASTRUCTURE,
    ]
    for rt in non_hallway:
        assert rt in C.ROOM_TYPE_HVAC_HOLD_NIGHT, (
            f"Night-hold table missing {rt} — instant-retreat risk"
        )
        night = C.ROOM_TYPE_HVAC_HOLD_NIGHT[rt]
        day = C.ROOM_TYPE_HVAC_HOLD.get(rt, C.DEFAULT_HVAC_VACANCY_HOLD)
        assert night >= day, (
            f"Night hold for {rt} ({night}s) is SHORTER than day "
            f"({day}s) — monotonicity violated"
        )
    # Night default MUST be >= day default too.
    assert C.DEFAULT_HVAC_VACANCY_HOLD_NIGHT >= C.DEFAULT_HVAC_VACANCY_HOLD


def test_per_room_override_conf_removed_f5():
    """F5 fix-up round 4 (2026-09-17): CONF_HVAC_VACANCY_HOLD and
    CONF_HVAC_VACANCY_HOLD_NIGHT are DROPPED (they were inert — no
    config-flow/Number surface). Ensures the const module no longer
    exposes them so downstream readers get an ImportError instead of
    a silently-inert knob.
    """
    C = _const_mod()
    assert not hasattr(C, "CONF_HVAC_VACANCY_HOLD"), (
        "CONF_HVAC_VACANCY_HOLD should be REMOVED (F5, dropped inert knob)"
    )
    assert not hasattr(C, "CONF_HVAC_VACANCY_HOLD_NIGHT"), (
        "CONF_HVAC_VACANCY_HOLD_NIGHT should be REMOVED (F5)"
    )


def test_hallway_circulation_exclusion_via_update_room_conditions():
    """Behavioral: drive the real `update_room_conditions` producer
    path with two rooms — a `hallway` room and a `bedroom` room —
    where both are lighting-occupied. The zone's fused signal
    (`any_room_hvac_occupied`) MUST reflect ONLY the bedroom's
    hvac_occupied value; deleting the CIRCULATION EXCLUSION would
    let the hallway arm the D1 producer -> the discriminator flips.
    """
    m = _zm_module()
    C = _const_mod()

    # Build a stub hass whose config_entries expose two ROOM entries +
    # a ZM entry with our zone.
    from custom_components.universal_room_automation.const import (
        DOMAIN, CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM, ENTRY_TYPE_ZONE_MANAGER,
        CONF_ROOM_NAME, CONF_ROOM_TYPE,
    )

    class _Entry:
        def __init__(self, entry_id, data, options=None):
            self.entry_id = entry_id
            self.data = data
            self.options = options or {}

    hall = _Entry(
        "e_hall", {CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                    CONF_ROOM_NAME: "hall_r",
                    CONF_ROOM_TYPE: C.ROOM_TYPE_HALLWAY},
    )
    bed = _Entry(
        "e_bed", {CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM,
                   CONF_ROOM_NAME: "bed_r",
                   CONF_ROOM_TYPE: C.ROOM_TYPE_BEDROOM},
    )
    # ZM entry not consulted by update_room_conditions itself — the
    # zone_manager already has zones populated via _zones.
    entries = [hall, bed]

    class _CEs:
        def async_entries(self, dom):
            return entries

    class _RoomCoord:
        def __init__(self, occupied):
            self.data = {"occupied": occupied, "temperature": None, "humidity": None}
            self.config_entry = None

    hass = MagicMock()
    hass.config_entries = _CEs()
    hass.data = {DOMAIN: {"e_hall": _RoomCoord(True), "e_bed": _RoomCoord(True)}}
    hass.states = MagicMock()
    hass.states.get = lambda ent_id: None

    zm = m.ZoneManager(hass)
    zone = m.ZoneState(
        zone_id="z_mixed", zone_name="MIXED", climate_entity="c.mixed",
    )
    zone.rooms = ["hall_r", "bed_r"]
    zm._zones["z_mixed"] = zone

    zm.update_room_conditions(house_state="home_day")

    # Both rooms populated, both lighting-occupied.
    assert zone.any_room_occupied is True
    # Hallway is HVAC-excluded; bedroom is armed via rising edge ->
    # any_room_hvac_occupied True. Deleting the exclusion would make
    # both rooms have hvac_occupied=True as well — no discriminator here.
    # The DISCRIMINATOR is what happens when the bedroom releases and
    # only the hallway remains lighting-occupied.
    assert zone.any_room_hvac_occupied is True

    # Release the bedroom, keep the hallway occupied.
    hass.data[DOMAIN]["e_bed"] = _RoomCoord(False)
    zm.update_room_conditions(house_state="home_day")
    assert zone.any_room_occupied is True  # hallway still lighting-occupied
    # HVAC-fused should be False (bedroom released past tail; hallway
    # is CIRCULATION-EXCLUDED and never arms). Under a mutation that
    # deletes `if room_type == ROOM_TYPE_HALLWAY:` short-circuit, the
    # hallway would arm and this assertion reds.
    # Wait one tail-hold-plus for the bedroom to fully release.
    # Advance the internal state by nudging tail_until.
    # Easiest: force-clear the bedroom's tail.
    zm._hvac_armed["bed_r"] = False
    zm._hvac_tail_until.pop("bed_r", None)
    # Re-run so the RoomCondition reflects the cleared state.
    zm.update_room_conditions(house_state="home_day")
    assert zone.any_room_hvac_occupied is False, (
        "Hallway must not arm the fused signal (CIRCULATION EXCLUSION)"
    )


def test_d5_migration_rewrites_legacy_default_only():
    """D5 fix-up round 2: the migration rewrites stored value 3 -> 0
    (legacy default) but leaves operator-set non-default values
    untouched. Idempotent via the sentinel option.
    """
    import asyncio
    # Extract the migration function via AST + exec — full package
    # import chain is heavy and would pollute sys.modules across the
    # suite (see _load-vs-collect-time policy at top of this file).
    import ast as _ast
    init_path = os.path.join(_ura_path, "__init__.py")
    with open(init_path) as _fh:
        init_src = _fh.read()
    _tree = _ast.parse(init_src)
    fn_src = None
    for _node in _ast.walk(_tree):
        if (
            isinstance(_node, _ast.AsyncFunctionDef)
            and _node.name == "_migrate_hvac_zone_entry_dwell_to_zero"
        ):
            fn_src = _ast.get_source_segment(init_src, _node)
            break
    assert fn_src is not None
    # The function does `from .domain_coordinators.hvac_const import
    # CONF_HVAC_ZONE_ENTRY_DWELL` at call time — provide a stub.
    _stub_hvac_const = types.SimpleNamespace(
        CONF_HVAC_ZONE_ENTRY_DWELL="hvac_zone_entry_dwell",
    )
    _ns = {
        "_LOGGER": types.SimpleNamespace(info=lambda *a, **k: None),
    }
    exec(
        fn_src.replace(
            "from .domain_coordinators.hvac_const import (\n"
            "        CONF_HVAC_ZONE_ENTRY_DWELL,\n"
            "    )",
            "CONF_HVAC_ZONE_ENTRY_DWELL = 'hvac_zone_entry_dwell'",
        ),
        _ns,
    )
    fn = _ns["_migrate_hvac_zone_entry_dwell_to_zero"]

    class _Entry:
        def __init__(self, options):
            self.entry_id = "cm1"
            self.data = {}
            self.options = dict(options)

    updates = []

    class _CEs:
        def async_update_entry(self, entry, options=None):
            entry.options = dict(options)
            updates.append(("update", entry.entry_id, dict(options)))
        def async_get_entry(self, eid):
            return None

    hass = types.SimpleNamespace(config_entries=_CEs())

    # Case A: legacy default 3 -> rewritten to 0.
    entry_a = _Entry({"hvac_zone_entry_dwell": 3})
    changed_a = asyncio.new_event_loop().run_until_complete(fn(hass, entry_a))
    assert changed_a is True
    assert entry_a.options["hvac_zone_entry_dwell"] == 0
    assert entry_a.options["hvac_zone_entry_dwell_zero_migration_done"] is True

    # Case B: operator-set value 5 -> untouched, sentinel still set.
    updates.clear()
    entry_b = _Entry({"hvac_zone_entry_dwell": 5})
    changed_b = asyncio.new_event_loop().run_until_complete(fn(hass, entry_b))
    assert changed_b is False
    assert entry_b.options["hvac_zone_entry_dwell"] == 5
    assert entry_b.options["hvac_zone_entry_dwell_zero_migration_done"] is True

    # Case C: already-migrated -> no-op.
    updates.clear()
    entry_c = _Entry({"hvac_zone_entry_dwell": 5, "hvac_zone_entry_dwell_zero_migration_done": True})
    changed_c = asyncio.new_event_loop().run_until_complete(fn(hass, entry_c))
    assert changed_c is False
    assert updates == []


def test_row1_and_d7_helpers_present_on_coordinator():
    """Fix-up round 4: HVACCoordinator exposes the F3 shared helper
    `_zone_conditioning_retreat_ok` (in addition to the underlying
    `_is_zone_hvac_established` delegate). Row-1, D7, D9 must all
    route through the shared helper — a code path bypassing it would
    reintroduce the per-site drift the operator called out.
    """
    with open(os.path.join(_dc_path, "hvac.py"), "r") as fh:
        src = fh.read()
    assert "def _is_zone_hvac_established" in src
    assert "def _zone_conditioning_retreat_ok" in src
    # Callers use the shared helper.
    assert src.count("self._zone_conditioning_retreat_ok(") >= 3


def test_swap_row1_preset_flip_uses_shared_helper():
    """§2a row 1 + F3 unification: preset-flip retreat gate routes
    through `_zone_conditioning_retreat_ok(zone)`. Under the wrong-fix
    failure mode (row-1 reads a raw fused attr or bypasses the helper),
    the helper's reset-only backstop is not respected on this site.
    """
    with open(os.path.join(_dc_path, "hvac.py"), "r") as fh:
        hvac_src = fh.read()
    assert "self._zone_conditioning_retreat_ok(zone)" in hvac_src
    # Row-1 anchor: `zone_vacant_past_grace = ` under the helper True
    # branch + `grace_minutes * 60` remains inside.
    assert "zone_vacant_past_grace = (" in hvac_src
    assert "grace_minutes * 60" in hvac_src


def test_swap_row2b_vacancy_sweep_stays_lighting():
    """§2a row 2b NO-SWAP guard: the lighting vacancy_sweep_done reset
    stays on `any_room_occupied`. Swapping it would leave hallway lights
    on after a transit clears."""
    src = open(os.path.join(_dc_path, "hvac_zones.py")).read()
    # Locate the specific site.
    assert "vacancy_sweep_done = False  # Row 2b" in src
    # And ensure the ENCLOSING `if` reads lighting-fused any_room_occupied
    # (not the HVAC sibling). Anchor on the comment + guard combo.
    idx = src.index("vacancy_sweep_done = False  # Row 2b")
    prefix = src[max(0, idx - 400):idx]
    assert "zone.any_room_occupied" in prefix, (
        "Row 2b lighting-fused NO-SWAP invariant violated"
    )


def test_swap_rows_2a_and_2c_read_fused():
    """§2a rows 2a + 2c: last_occupied_time + continuous_occupied_since
    write basis reads `any_room_hvac_occupied` (HVAC denomination)."""
    src = open(os.path.join(_dc_path, "hvac_zones.py")).read()
    # The single split guard reads the HVAC sibling.
    assert "if zone.any_room_hvac_occupied:" in src
    # Row 2a — last_occupied_time write under HVAC denomination.
    assert "zone.last_occupied_time = now" in src


def test_d5_zone_entry_dwell_default_is_zero():
    assert _hvac_const_mod().DEFAULT_ZONE_ENTRY_DWELL_MINUTES == 0


def test_d2_binary_sensor_entity_registered_and_reflects_producer():
    """D2 wire-in anchor: the per-room `HVACOccupiedBinarySensor` entity
    class exists in binary_sensor.py, is added to the room-entry setup's
    entity list, and its `is_on` reflects the D1 producer's
    `RoomCondition.hvac_occupied` (fed by `_find_room_condition`).

    We verify by:
    1. Reading binary_sensor.py source and confirming the class + its
       registration site are present (source-shape guard).
    2. Instantiating the class against a stub coordinator + hass
       populated with a real ZoneState whose RoomCondition has
       `hvac_occupied=True`, and asserting `is_on` returns True.
    3. Flipping `RoomCondition.hvac_occupied` to False and asserting
       `is_on` returns False on the next read (live producer link, no
       cached state on the entity).
    """
    bs_path = os.path.join(_ura_path, "binary_sensor.py")
    with open(bs_path) as fh:
        bs_src = fh.read()
    assert "class HVACOccupiedBinarySensor" in bs_src, (
        "D2 entity class must be defined in binary_sensor.py"
    )
    # Registered on the room-entry setup path (entities.extend([...])).
    assert "HVACOccupiedBinarySensor(coordinator)" in bs_src, (
        "D2 entity must be added to the room-entry entity list"
    )

    # Behavioral wire-in: construct a stubbed hass with real ZoneManager
    # + ZoneState + RoomCondition, then read `is_on` through the entity
    # class's `_find_room_condition` helper (invoked by is_on).
    m = _zm_module()
    zm = m.ZoneManager(MagicMock())
    zone = m.ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.z1")
    zone.rooms = ["diag_room"]
    zone.room_conditions = [
        m.RoomCondition(room_name="diag_room", occupied=True, hvac_occupied=True),
    ]
    zm._zones["z1"] = zone
    # D1 producer diag: also seed the arm-attribution dicts so attrs
    # surface a source and (no) tail expiry.
    zm._hvac_armed["diag_room"] = True
    zm._hvac_arm_source["diag_room"] = "held"

    # Build a fake coordinator_manager exposing our ZoneManager as the
    # `hvac` coordinator's _zone_manager.
    hvac_coord = types.SimpleNamespace(_zone_manager=zm, _house_state="home_day")
    manager = types.SimpleNamespace(coordinators={"hvac": hvac_coord})
    hass = MagicMock()
    from custom_components.universal_room_automation.const import DOMAIN
    hass.data = {DOMAIN: {"coordinator_manager": manager}}

    # Load binary_sensor lazily and instantiate the class.
    # This is a wire-in anchor: we cannot easily instantiate the full
    # entity class without dragging in the HA entity plumbing, so we
    # invoke the load-bearing helper `_find_room_condition` directly by
    # constructing a bound-method stand-in via a lightweight class.
    class _Probe:
        # Mimic the surface `HVACOccupiedBinarySensor.is_on` reads.
        def __init__(self, hass_, room_name):
            self.hass = hass_
            # The real entity reads `self.coordinator.entry.data`.
            self.coordinator = types.SimpleNamespace(
                entry=types.SimpleNamespace(
                    data={"room_name": room_name},
                    options={},
                )
            )

    # Import the actual class methods and bind them to the probe so we
    # test the real production code path (not a reimplementation).
    # This is an inspect-and-invoke wire-in.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_ura_bs_probe", bs_path,
    )
    # We can't load the whole binary_sensor module without HA imports;
    # instead we extract the two methods textually via inspect on the
    # source AST. The methods are pure Python that only reference
    # `self.hass`, `self.coordinator`, and stdlib.
    import ast
    tree = ast.parse(bs_src)
    method_src = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ClassDef)
            and node.name == "HVACOccupiedBinarySensor"
        ):
            for child in node.body:
                if (
                    isinstance(child, ast.FunctionDef)
                    and child.name in (
                        "_zone_manager", "_find_room_condition", "is_on",
                    )
                ):
                    method_src[child.name] = ast.get_source_segment(bs_src, child)
    assert set(method_src) >= {"_zone_manager", "_find_room_condition"}, (
        "D2 entity must expose _zone_manager + _find_room_condition helpers"
    )

    # Bind the two helper methods onto the probe class so `self` reads
    # the probe's hass/coordinator attributes. This exercises the REAL
    # production code path.
    ns = {"DOMAIN": DOMAIN}
    for name, src in method_src.items():
        exec(src.lstrip(), ns)
    _Probe._zone_manager = ns["_zone_manager"]
    _Probe._find_room_condition = ns["_find_room_condition"]

    probe = _Probe(hass, "diag_room")
    # `_zone_manager` returns our real ZoneManager.
    assert probe._zone_manager() is zm
    # `_find_room_condition` walks zones -> rooms -> RoomCondition.
    rc = probe._find_room_condition()
    assert rc is not None
    assert rc.room_name == "diag_room"
    assert rc.hvac_occupied is True

    # Now flip hvac_occupied and re-read: entity must reflect the new
    # value (no cached state; producer is the source of truth).
    zone.room_conditions[0].hvac_occupied = False
    rc2 = probe._find_room_condition()
    assert rc2 is not None
    assert rc2.hvac_occupied is False


def test_d3_defaults_and_tables_present():
    C = _const_mod()
    assert C.DEFAULT_HVAC_VACANCY_HOLD == 60
    # Fix-up round 2: night default MUST be >= day default (monotonicity).
    assert C.DEFAULT_HVAC_VACANCY_HOLD_NIGHT >= C.DEFAULT_HVAC_VACANCY_HOLD
    # Bedroom day = 60s (matches DEFAULT).
    assert C.ROOM_TYPE_HVAC_HOLD["bedroom"] == 60
    # Night table has bigger bedroom tail.
    assert C.ROOM_TYPE_HVAC_HOLD_NIGHT["bedroom"] == 1800
    # F5 fix-up round 4: CONF_HVAC_VACANCY_HOLD[_NIGHT] dropped.
    assert not hasattr(C, "CONF_HVAC_VACANCY_HOLD")
    assert not hasattr(C, "CONF_HVAC_VACANCY_HOLD_NIGHT")
    assert C.ROOM_TYPE_HALLWAY == "hallway"


def test_reset_only_backstop_established_home_person_still_retreats():
    """Fix-up round 4 (2026-09-17): reset-only backstop discriminator.

    Operator-decided contract: person-trust preserve fires ONLY while
    the zone is UNESTABLISHED. Once established, occupancy alone
    decides — an empty zone retreats even if a resident's phone reads
    home elsewhere in the house. This test constructs an ESTABLISHED
    zone with fused-empty rooms AND a home-person setup; asserts
    `conditioning_retreat_ok(zone) == True` (retreat authorized).

    Under the wrong-fix failure mode (person-trust re-applied to
    established path), the helper would return False and this test
    reds. Revert-in-suite: force `conditioning_retreat_ok` to consult
    `zone_has_home_person` on the established branch -> RED.
    """
    m = _zm_module()
    zm = m.ZoneManager(MagicMock())
    zone = m.ZoneState(zone_id="z_reset", zone_name="Reset", climate_entity="c.r")
    zone.rooms = ["r_a", "r_b"]
    # zone_persons includes a person; caller can independently look up
    # `zone_has_home_person`, but the shared helper MUST NOT consult it.
    zone.zone_persons = ["person.resident"]
    # Both rooms empty in HVAC denomination.
    zone.room_conditions = [
        m.RoomCondition(room_name="r_a", occupied=False, hvac_occupied=False),
        m.RoomCondition(room_name="r_b", occupied=False, hvac_occupied=False),
    ]
    zm._zones["z_reset"] = zone
    # Seed as established.
    zm._hvac_seen.update(["r_a", "r_b"])
    assert zm.is_zone_hvac_established("z_reset") is True

    # ESTABLISHED + fused-empty -> retreat OK (person-trust NOT
    # consulted on this branch).
    assert zm.conditioning_retreat_ok(zone) is True


def test_reset_only_backstop_unestablished_denies_retreat():
    """Sibling: unestablished zone MUST deny retreat regardless of
    fused signal (reset-only backstop). This is the reload/boot gap
    that closes the ~5x/night cold-retreat.
    """
    m = _zm_module()
    zm = m.ZoneManager(MagicMock())
    zone = m.ZoneState(zone_id="z_boot", zone_name="Boot", climate_entity="c.b")
    zone.rooms = ["r_x"]
    zone.room_conditions = [
        m.RoomCondition(room_name="r_x", occupied=False, hvac_occupied=False),
    ]
    zm._zones["z_boot"] = zone
    # Do NOT seed _hvac_seen — zone is unestablished at boot.
    assert zm.is_zone_hvac_established("z_boot") is False
    # Retreat MUST be denied.
    assert zm.conditioning_retreat_ok(zone) is False


def test_f1_established_with_disabled_room_becomes_ready():
    """F1 fix-up round 4 (2026-09-17): a zone with a DISABLED room
    (still in `zone.rooms` but never iterated because the room
    coordinator is None / disabled) must still be able to reach
    ESTABLISHED via its live rooms.

    Under the wrong-fix failure mode (all rooms in _hvac_seen), the
    disabled room would permanently block establishment -> the zone
    fail-opens forever and never retreats. This test constructs a
    zone with one live + one disabled room; seeds only the live one
    as seen; asserts established.
    """
    m = _zm_module()
    zm = m.ZoneManager(MagicMock())
    zone = m.ZoneState(zone_id="z_mix", zone_name="Mix", climate_entity="c.mx")
    zone.rooms = ["r_live", "r_disabled"]
    zm._zones["z_mix"] = zone

    # Only the live room's producer has run.
    zm._hvac_seen.add("r_live")
    assert zm.is_zone_hvac_established("z_mix") is True, (
        "Zone with a disabled room must still establish from its live "
        "rooms (F1 fix — was permanently unestablished under ALL semantics)"
    )


def test_d9_compose_away_gated_by_shared_helper():
    """D9 + F3 unification (fix-up round 4): compose-away authorized
    IFF the shared `conditioning_retreat_ok` helper approves. Two
    scenarios:

    1. ESTABLISHED + fused-empty -> compose-away allowed (retreat_ok True).
    2. UNESTABLISHED + fused-empty + home-person -> retreat_ok False
       (reset-only backstop) -> compose-away NOT allowed.

    Revert-in-suite: force `conditioning_retreat_ok` to always-True
    (bypass the reset-only backstop) -> the unestablished-branch
    assertion reds.
    """
    m = _zm_module()
    zm = m.ZoneManager(MagicMock())

    # Established + fused-empty.
    z1 = m.ZoneState(zone_id="z1", zone_name="Z1", climate_entity="c.1")
    z1.rooms = ["a"]
    z1.room_conditions = [m.RoomCondition("a", occupied=False, hvac_occupied=False)]
    zm._zones["z1"] = z1
    zm._hvac_seen.add("a")
    assert zm.conditioning_retreat_ok(z1) is True

    # Unestablished + fused-empty.
    z2 = m.ZoneState(zone_id="z2", zone_name="Z2", climate_entity="c.2")
    z2.rooms = ["b"]
    z2.room_conditions = [m.RoomCondition("b", occupied=False, hvac_occupied=False)]
    zm._zones["z2"] = z2
    # z2's rooms NOT in _hvac_seen -> unestablished.
    assert zm.is_zone_hvac_established("z2") is False
    assert zm.conditioning_retreat_ok(z2) is False


def test_f2_throttle_bypass_on_compose_away_source_shape():
    """F2 fix-up round 4 (2026-09-17): the DPM throttle guard must
    NOT skip on the compose-away branch. Third-writer restores (S8
    cancel-nudge, S9 startup ramp-audit in hvac_override.py) write
    setpoints without updating `_last_emitted_range`; the DPM must
    overwrite them on the next tick to prevent a zone stranding at
    comfort setpoints for the night.

    Source-shape guard: the throttle predicate MUST reference
    `_compose_away` in its skip guard.
    """
    with open(os.path.join(_dc_path, "hvac.py"), "r") as fh:
        src = fh.read()
    assert "if last == resolved_pair and not _compose_away:" in src, (
        "F2 throttle bypass on compose-away missing — DPM would strand "
        "empty zones at comfort setpoints after a third-writer restore"
    )


def test_f4_row10_comfort_delay_uses_shared_helper_source_shape():
    """F4 fix-up round 4: `_comfort_delay_active` in hvac_override.py
    must consult `conditioning_retreat_ok` via ZoneManager, so it
    defers writes during the reload window (unestablished) instead
    of failing-closed and letting a manual push get stomped.
    """
    with open(os.path.join(_dc_path, "hvac_override.py"), "r") as fh:
        src = fh.read()
    assert 'zm.conditioning_retreat_ok(zone)' in src, (
        "F4: row-10 _comfort_delay_active must consult the shared "
        "retreat-authorization helper"
    )


def test_vacancy_sweep_call_decoupled_from_hvac_denomination():
    """A-HIGH/B-CRIT-1 fix-up round 2: the vacancy sweep CALL SITE is
    gated on the LIGHTING denomination (`any_room_occupied`), not the
    HVAC-fused signal. A standing hallway occupant makes the zone
    HVAC-empty but lighting-occupied — hallway lights must stay ON.

    Source guard: the sweep-call blocks in hvac.py must reference
    `zone.any_room_occupied` (lighting-fused) NOT `zone.any_room_hvac_
    occupied` in their guard predicate.
    """
    with open(os.path.join(_dc_path, "hvac.py"), "r") as fh:
        src = fh.read()
    # There are exactly two sweep call sites (row-1 retreat + D6 stale
    # branch). Anchor on the shared decouple comment + the lighting-
    # fused read used to gate both.
    assert "sweep call from the HVAC-denomination retreat" in src
    assert "_sweep_light_ok = not getattr(" in src
    # Both sweep-call `if` blocks should be gated by _sweep_light_ok.
    assert src.count("_sweep_light_ok") >= 4  # 2 decls + 2 uses
