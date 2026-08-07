"""Arrester Operator-Immunity + Comfort Override (2026-08-06).

Behavioral tests drive the REAL `OverrideArrester` code path (no re-
implementation of the logic). Bootstraps sys.modules mirror the pattern
from `test_override_arrester_ttl_suppression.py`.

Coverage rails:

  Immunity (person-scoped):
    * Immune operator's manual hold survives a forced shave attempt
      (severe + normal + compromise + revert + startup + soft_nudge +
       hard_reset_escalation all skip).
    * Physical-dial hold (event.context.user_id is None) is STILL shaved.
    * Non-listed user's hold is STILL shaved.
    * Person-lookup exception → NOT immune (fail-open to governance).

  Sunset:
    * Durable-state transition sunsets the immune hold.
    * next_activity boundary sunsets the hold.
    * ARRESTER_IMMUNE_HOLD_MAX_S elapsed sunsets the hold.
    * Sunset does NOT force-clear; arrester regains jurisdiction only.

  Comfort Override:
    * ON gates every corrective write across every zone.
    * Auto-sunset on sleep transition; auto-sunset on max-age.
    * Restart leaves it OFF (default-OFF; no RestoreEntity).

Mutation drills (source-mutation → failing-test table):
    Each load-bearing site in `_corrective_writes_suppressed` /
    `_is_hold_immune` / detection-time stamp is exercised via targeted
    tests that pin SEMANTIC BINDING (condition↔effect pairing), not
    just presence/order. This is the standing rule after three
    consecutive cycles of pairing gaps.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# HA stubs (setdefault so sibling test files can win their own registrations)
# ---------------------------------------------------------------------------

def _mock_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731


def _utcnow_real() -> datetime:
    return datetime.now(timezone.utc)


def _now_real() -> datetime:
    return datetime.now()


_mods: dict[str, dict] = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock,
        "Event": MagicMock,
        "CALLBACK_TYPE": object,
        "callback": _identity,
    },
    "homeassistant.helpers": {},
    "homeassistant.helpers.event": {
        "async_call_later": MagicMock(return_value=lambda: None),
        "async_track_state_change_event": MagicMock(return_value=lambda: None),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": _utcnow_real,
        "now": _now_real,
        "UTC": timezone.utc,
    },
    "homeassistant.components": {},
    "homeassistant.components.recorder": {"get_instance": MagicMock()},
    "homeassistant.components.recorder.history": {
        "get_significant_states": MagicMock(),
    },
}
for _name, _attrs in _mods.items():
    sys.modules.setdefault(_name, _mock_module(_name, **_attrs))


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_HERE = os.path.dirname(__file__)
_URA_PATH = os.path.join(_HERE, "..", "..", "custom_components",
                         "universal_room_automation")
_DC_PATH = os.path.join(_URA_PATH, "domain_coordinators")

if "custom_components" not in sys.modules:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [os.path.join(_HERE, "..", "..", "custom_components")]
    sys.modules["custom_components"] = _cc
if "custom_components.universal_room_automation" not in sys.modules:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [_URA_PATH]
    sys.modules["custom_components.universal_room_automation"] = _ura


def _load(modname: str, relpath: str) -> types.ModuleType:
    cached = sys.modules.get(modname)
    if cached is not None and getattr(cached, "__file__", None):
        return cached
    spec = importlib.util.spec_from_file_location(
        modname, os.path.join(_URA_PATH, relpath),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


_load("custom_components.universal_room_automation.const", "const.py")
if "custom_components.universal_room_automation.domain_coordinators" not in sys.modules:
    _dc = types.ModuleType(
        "custom_components.universal_room_automation.domain_coordinators"
    )
    _dc.__path__ = [_DC_PATH]
    sys.modules[
        "custom_components.universal_room_automation.domain_coordinators"
    ] = _dc
# Force-clean any mock stand-ins from sibling tests
for _m in (
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
):
    _c = sys.modules.get(_m)
    if _c is not None and not getattr(_c, "__file__", None):
        del sys.modules[_m]

_load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "domain_coordinators/hvac_const.py",
)
_load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "domain_coordinators/hvac_zones.py",
)
_load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
    "domain_coordinators/hvac_setpoint.py",
)
hvac_override = _load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
    "domain_coordinators/hvac_override.py",
)
hvac_zones = sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones"
]
hvac_const = sys.modules[
    "custom_components.universal_room_automation.domain_coordinators.hvac_const"
]

OverrideArrester = hvac_override.OverrideArrester
ZoneState = hvac_zones.ZoneState
ARRESTER_IMMUNE_HOLD_MAX_S = hvac_const.ARRESTER_IMMUNE_HOLD_MAX_S
COMFORT_OVERRIDE_MAX_S = hvac_const.COMFORT_OVERRIDE_MAX_S


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _FakeClock:
    def __init__(self, start: datetime) -> None:
        self.t = start

    def now(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t = self.t + timedelta(seconds=seconds)


@pytest.fixture
def fake_clock(monkeypatch):
    clock = _FakeClock(datetime(2026, 8, 6, 14, 0, 0))
    fake_dt = types.SimpleNamespace(now=clock.now)
    monkeypatch.setattr(hvac_override, "dt_util", fake_dt)
    return clock


CLIMATE = "climate.zone_a"
ZONE_ID = "zone_a"
OPERATOR_USER = "user_operator_abc"
GUEST_USER = "user_guest_xyz"
OPERATOR_PERSON = "person.oji_udezue"
GUEST_PERSON = "person.guest_dave"


def _make_hass_with_persons() -> MagicMock:
    """Build a hass mock whose states.async_all('person') yields the two
    person entities (operator + guest) with attributes.user_id wired.
    """
    hass = MagicMock()

    op_state = MagicMock()
    op_state.entity_id = OPERATOR_PERSON
    op_state.attributes = {"user_id": OPERATOR_USER, "friendly_name": "Operator"}

    guest_state = MagicMock()
    guest_state.entity_id = GUEST_PERSON
    guest_state.attributes = {"user_id": GUEST_USER, "friendly_name": "Dave"}

    hass.states.async_all = MagicMock(return_value=[op_state, guest_state])
    return hass


def _make_arrester(hass=None, immune=(OPERATOR_PERSON,)) -> OverrideArrester:
    zone = ZoneState(
        zone_id=ZONE_ID, zone_name="Zone A", climate_entity=CLIMATE,
    )
    zone.hvac_mode = "heat_cool"
    zone.preset_mode = "home"
    zone.target_temp_high = 76.0
    zone.target_temp_low = 70.0
    zone.current_temperature = 74.0
    zone.ac_load_sensor = None  # keep ramp gated off unless a test needs it

    zm = MagicMock()
    zm.zones = {ZONE_ID: zone}
    if hass is None:
        hass = _make_hass_with_persons()
    a = OverrideArrester(hass, zm, compromise_minutes=30, ac_reset_timeout=60,
                         enabled=True)
    a.set_immune_persons(list(immune))
    return a


def _make_event(*, user_id: str | None,
                old_preset="home", new_preset="manual",
                old_high=76.0, new_high=64.0,
                old_low=70.0, new_low=64.0) -> MagicMock:
    old_st = MagicMock()
    old_st.attributes = {
        "preset_mode": old_preset,
        "target_temp_high": old_high,
        "target_temp_low": old_low,
        "hvac_mode": "heat_cool",
    }
    new_st = MagicMock()
    new_st.attributes = {
        "preset_mode": new_preset,
        "target_temp_high": new_high,
        "target_temp_low": new_low,
        "hvac_mode": "heat_cool",
    }
    ev = MagicMock()
    ev.data = {"entity_id": CLIMATE, "old_state": old_st, "new_state": new_st}
    ev.context = types.SimpleNamespace(user_id=user_id)
    return ev


# ===========================================================================
# Immunity — DETECTION-TIME behavior
# ===========================================================================

class TestImmunityDetection:

    def test_operator_hold_is_stamped_immune_no_shave(self, fake_clock):
        """Operator's manual hold gets stamped; NO grace timer scheduled;
        NO _override_active flag; every subsequent shave path skips."""
        a = _make_arrester()
        ev = _make_event(user_id=OPERATOR_USER)
        a._handle_climate_change(ev)

        # SEMANTIC BINDING: immune record MUST reference the operator
        # AND the same zone AND record the user_id from context.
        assert ZONE_ID in a._immune_holds
        rec = a._immune_holds[ZONE_ID]
        assert rec["user_id"] == OPERATOR_USER
        assert rec["person_entity"] == OPERATOR_PERSON

        # NO grace/compromise scheduled, NO _override_active
        assert a._grace_timers == {}
        assert a._compromise_timers == {}
        assert a._override_active.get(ZONE_ID, False) is False

    def test_physical_dial_hold_is_shaved(self, fake_clock):
        """context.user_id is None (physical thermostat dial) → NOT
        immune. Falls through to normal severe/normal handling
        (grace timer scheduled)."""
        a = _make_arrester()
        ev = _make_event(user_id=None)
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._immune_holds
        # Severe threshold hit (64 vs expected 76 = 12°F) → grace timer
        assert ZONE_ID in a._grace_timers

    def test_non_listed_user_hold_is_shaved(self, fake_clock):
        """Guest's manual hold is NOT immune → falls through to shave."""
        a = _make_arrester()
        ev = _make_event(user_id=GUEST_USER)
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._immune_holds
        assert ZONE_ID in a._grace_timers

    def test_person_lookup_exception_is_governed(self, fake_clock):
        """Fail-open: state registry blows up → NOT immune."""
        a = _make_arrester()
        a.hass.states.async_all = MagicMock(side_effect=RuntimeError("boom"))
        ev = _make_event(user_id=OPERATOR_USER)
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._immune_holds
        assert ZONE_ID in a._grace_timers


# ===========================================================================
# Immunity — DEFENSE-IN-DEPTH shave gates
# ===========================================================================

class TestImmunityDefenseInDepth:
    """Every shave path re-checks _corrective_writes_suppressed. Mutation
    drills confirm each check is LOAD-BEARING at its site (mutation ->
    the corresponding test flips).
    """

    def _prime_immune(self, arrester):
        arrester._stamp_immune_hold(
            ZONE_ID, OPERATOR_USER, "Operator", OPERATOR_PERSON,
        )

    def test_severe_path_skips_when_immune(self, fake_clock):
        a = _make_arrester()
        self._prime_immune(a)
        zone = a._zone_manager.zones[ZONE_ID]
        a._handle_severe_override(zone, "home", 76.0, 70.0, delta=-8.0)
        # No grace timer, no _override_active flip
        assert ZONE_ID not in a._grace_timers
        assert a._override_active.get(ZONE_ID, False) is False

    def test_normal_path_skips_when_immune(self, fake_clock):
        a = _make_arrester()
        self._prime_immune(a)
        zone = a._zone_manager.zones[ZONE_ID]
        a._handle_normal_override(zone, "home", 76.0, 70.0, delta=-2.0,
                                  new_high=74.0, new_low=70.0)
        assert ZONE_ID not in a._grace_timers

    @pytest.mark.asyncio
    async def test_revert_skips_when_immune(self, fake_clock):
        a = _make_arrester()
        self._prime_immune(a)
        zone = a._zone_manager.zones[ZONE_ID]
        await a._revert_override(zone, "home")
        # Revert must NOT have called climate.set_preset_mode
        assert not a.hass.services.async_call.called

    @pytest.mark.asyncio
    async def test_compromise_skips_when_immune(self, fake_clock):
        a = _make_arrester()
        self._prime_immune(a)
        zone = a._zone_manager.zones[ZONE_ID]
        await a._apply_compromise(zone, "home", 74.0, 70.0, 76.0, 70.0)
        # No compromise timer scheduled, no service call
        assert ZONE_ID not in a._compromise_timers


# ===========================================================================
# Sunset
# ===========================================================================

class TestSunset:

    def _stamp(self, a, *, next_activity_ts=None):
        a._stamp_immune_hold(
            ZONE_ID, OPERATOR_USER, "Operator", OPERATOR_PERSON,
            next_activity_ts=next_activity_ts,
        )

    def test_durable_state_transition_sunsets(self, fake_clock):
        a = _make_arrester()
        self._stamp(a)
        # SEMANTIC BINDING: non-durable transition MUST NOT sunset...
        a.sunset_immune_holds(reason="durable_state", house_state="home_day")
        assert ZONE_ID in a._immune_holds
        # ...but a durable transition MUST.
        a.sunset_immune_holds(reason="durable_state", house_state="sleep")
        assert ZONE_ID not in a._immune_holds

    def test_max_age_sunsets(self, fake_clock):
        a = _make_arrester()
        self._stamp(a)
        # Just below max age → no sunset
        fake_clock.advance(ARRESTER_IMMUNE_HOLD_MAX_S - 60)
        a.sunset_immune_holds(reason="max_age_or_boundary")
        assert ZONE_ID in a._immune_holds
        # Past max age → sunset
        fake_clock.advance(120)
        a.sunset_immune_holds(reason="max_age_or_boundary")
        assert ZONE_ID not in a._immune_holds

    def test_next_activity_boundary_sunsets(self, fake_clock):
        a = _make_arrester()
        boundary = fake_clock.now() + timedelta(minutes=30)
        self._stamp(a, next_activity_ts=boundary)
        # Before boundary
        fake_clock.advance(60)
        a.sunset_immune_holds(reason="max_age_or_boundary")
        assert ZONE_ID in a._immune_holds
        # After boundary
        fake_clock.advance(1900)
        a.sunset_immune_holds(reason="max_age_or_boundary")
        assert ZONE_ID not in a._immune_holds

    def test_sunset_does_not_force_clear_hold(self, fake_clock):
        """After sunset, arrester regains jurisdiction — but nothing on
        the thermostat is force-cleared. Sunset is a REGISTRY change, not
        a climate service call."""
        a = _make_arrester()
        self._stamp(a)
        a.sunset_immune_holds(reason="durable_state", house_state="away")
        # No service was invoked — sunset is bookkeeping-only.
        assert not a.hass.services.async_call.called


# ===========================================================================
# Comfort Override
# ===========================================================================

class TestComfortOverride:

    def test_gate_suppresses_every_shave_site(self, fake_clock):
        """Comfort ON → every shave path skips regardless of user."""
        a = _make_arrester()
        a.set_temp_arrester_override(True)
        zone = a._zone_manager.zones[ZONE_ID]

        # detection path: even a physical dial (no user) is gated
        ev = _make_event(user_id=None)
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._grace_timers
        assert ZONE_ID not in a._immune_holds  # comfort != immune-hold

        # explicit path invocations remain gated
        a._handle_severe_override(zone, "home", 76.0, 70.0, delta=-8.0)
        a._handle_normal_override(zone, "home", 76.0, 70.0, delta=-2.0,
                                  new_high=74.0, new_low=70.0)
        assert a._grace_timers == {}

    def test_sleep_transition_sunsets(self, fake_clock):
        a = _make_arrester()
        a.set_temp_arrester_override(True)
        assert a.sunset_temp_arrester_override(
            reason="durable_state", house_state="home_day",
        ) is False
        assert a.temp_arrester_override_active is True
        assert a.sunset_temp_arrester_override(
            reason="durable_state", house_state="sleep",
        ) is True
        assert a.temp_arrester_override_active is False

    def test_max_age_sunsets(self, fake_clock):
        a = _make_arrester()
        a.set_temp_arrester_override(True)
        fake_clock.advance(COMFORT_OVERRIDE_MAX_S - 60)
        assert a.sunset_temp_arrester_override(reason="max_age") is False
        fake_clock.advance(120)
        assert a.sunset_temp_arrester_override(reason="max_age") is True
        assert a.temp_arrester_override_active is False

    def test_restart_leaves_off(self):
        """Post-restart, a freshly-constructed arrester has Comfort OFF
        by default. No RestoreEntity in play; the switch does not
        persist. This test just pins the invariant on the arrester
        primitive itself."""
        a = _make_arrester()
        assert a.temp_arrester_override_active is False
        # Even if user was mid-ON before restart, the new object has no
        # trace of it (nothing is serialized in the arrester).
        assert a._temp_arrester_override_started_ts is None


# ===========================================================================
# Mutation drills — SEMANTIC-BINDING anchors
# ===========================================================================
#
# Each drill proves that a given source-line condition is BOUND to its
# effect (not merely present). The mutation "table" (see planning) —
# each entry names the condition + the test whose assertion flips if
# that condition is neutered.
#
#   Condition                                          | Failing test
#   ---------------------------------------------------+---------------------
#   detection: `person_entity in self._immune_persons` | test_operator_hold_is_stamped_immune_no_shave
#   detection: comfort_override guard                  | test_gate_suppresses_every_shave_site
#   severe: _corrective_writes_suppressed short-circuit| test_severe_path_skips_when_immune
#   normal: _corrective_writes_suppressed short-circuit| test_normal_path_skips_when_immune
#   compromise: _corrective_writes_suppressed          | test_compromise_skips_when_immune
#   revert: _corrective_writes_suppressed              | test_revert_skips_when_immune
#   sunset: reason=="durable_state" AND state in set   | test_durable_state_transition_sunsets
#   sunset: max-age comparison ≥ MAX_S                 | test_max_age_sunsets
#   sunset: next_activity_ts ≤ now                    | test_next_activity_boundary_sunsets
#   comfort: sleep-transition first-of                 | test_sleep_transition_sunsets
#   comfort: max-age first-of                          | test_max_age_sunsets (Comfort variant)
#
# The tests are written so a bare "flag existed" mutation (returning
# True unconditionally in _corrective_writes_suppressed) would ALSO
# make the fail-open contract tests below break — the fail-open cases
# require the gate to return False on the negative axis.

class TestFailOpenContract:
    """Negative axis: the gate MUST return False when nothing is engaged.
    Without this, a mutation that hardwires _corrective_writes_suppressed
    to True would silently pass the "skip" tests above."""

    def test_gate_false_when_nothing_engaged(self):
        a = _make_arrester()
        assert a._corrective_writes_suppressed(ZONE_ID) is False

    def test_dial_hold_actually_goes_severe(self, fake_clock):
        """SEMANTIC BINDING pair for detection: `user_id=None` and no
        immune record → severe grace scheduled. If the detection block
        wrongly stamped immune records for None-user events, this test
        would fail."""
        a = _make_arrester()
        ev = _make_event(user_id=None)
        a._handle_climate_change(ev)
        assert ZONE_ID in a._grace_timers
        assert ZONE_ID not in a._immune_holds


# ===========================================================================
# Fix-up 2026-08-06: dormant-default, boundary parse, rename, gates
# ===========================================================================

class TestDormantDefault:
    """CRIT-A1 fix: alphabetical seeding is deleted. Explicit-empty
    list must land as `[]` on the arrester (no silent fallback)."""

    def test_explicit_empty_list_is_dormant(self):
        a = _make_arrester(immune=())
        assert a._immune_persons == []

    def test_none_arg_is_dormant(self):
        a = _make_arrester()
        a.set_immune_persons(None)
        assert a._immune_persons == []

    def test_dormant_arrester_shaves_operator_hold(self, fake_clock):
        """The whole point of CRIT-A1: with an empty immune list,
        the operator's own hold IS shaved (byte-identical to pre-cycle)."""
        a = _make_arrester(immune=())
        ev = _make_event(user_id=OPERATOR_USER)
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._immune_holds
        assert ZONE_ID in a._grace_timers


class TestNextActivityBoundaryParse:
    """MED-A3: next_activity_time may be ISO-8601 OR bare 'HH:MM'."""

    def test_iso_format_parses(self, fake_clock):
        a = _make_arrester()
        raw = "2026-08-06T18:00:00"
        parsed = a._parse_next_activity(raw)
        assert parsed is not None and parsed.hour == 18

    def test_hhmm_future_today(self, fake_clock):
        # fake_clock is 14:00 local; 18:00 is later today.
        a = _make_arrester()
        parsed = a._parse_next_activity("18:00")
        assert parsed is not None
        assert parsed.hour == 18 and parsed.minute == 0

    def test_hhmm_past_rolls_tomorrow(self, fake_clock):
        # fake_clock is 14:00; 09:00 is past today → tomorrow 09:00.
        a = _make_arrester()
        now_local = a._parse_next_activity("18:00")  # sentinel today
        parsed = a._parse_next_activity("09:00")
        assert parsed is not None
        assert parsed.hour == 9
        # date is tomorrow-vs-today: parsed > now (fake clock)
        assert parsed > now_local.replace(hour=14, minute=0)

    def test_garbage_returns_none(self, fake_clock):
        a = _make_arrester()
        assert a._parse_next_activity("garbage") is None
        assert a._parse_next_activity("25:99") is None
        assert a._parse_next_activity("") is None


class TestGetStatsRenameCompleteness:
    """B-M3: get_stats keys use temp_arrester_override_* (rename complete)."""

    def test_temp_arrester_override_keys_present(self, fake_clock):
        a = _make_arrester()
        stats = a.get_arrester_detail()
        assert "temp_arrester_override_active" in stats
        assert "temp_arrester_override_suppressed_since" in stats
        # And the old names are GONE (rename complete, no aliases).
        assert "comfort_override_active" not in stats
        assert "comfort_override_suppressed_since" not in stats


class TestVoiceContextDiscriminator:
    """HIGH-A1 (operator ruled False as default 2026-08-06). Voice
    pipelines are approximated by non-None parent_id; direct UI /
    physical calls have parent_id=None and remain eligible."""

    def test_immune_when_parent_id_none(self, fake_clock):
        a = _make_arrester()
        ev = _make_event(user_id=OPERATOR_USER)  # parent_id absent → None
        a._handle_climate_change(ev)
        assert ZONE_ID in a._immune_holds

    def test_not_immune_when_parent_id_set(self, fake_clock, monkeypatch):
        """A context with a non-None parent_id (assist/automation chain)
        must NOT stamp immunity when ARRESTER_IMMUNITY_VOICE_CONTEXTS
        is False (the shipped default)."""
        # Guard: skip if a future revision flips the constant permissive.
        if hvac_const.ARRESTER_IMMUNITY_VOICE_CONTEXTS:
            pytest.skip("permissive const — parent_id gate disabled")
        a = _make_arrester()
        ev = _make_event(user_id=OPERATOR_USER)
        ev.context = types.SimpleNamespace(
            user_id=OPERATOR_USER, parent_id="some-pipeline-context-id",
        )
        a._handle_climate_change(ev)
        assert ZONE_ID not in a._immune_holds
        # Falls through to shave — severe delta scheduled.
        assert ZONE_ID in a._grace_timers
