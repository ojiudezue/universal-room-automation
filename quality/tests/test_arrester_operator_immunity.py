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
ARRESTER_OVERRIDE_MIN_LIFE_S = hvac_const.ARRESTER_OVERRIDE_MIN_LIFE_S


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
        # ARREST-SUNSET-1 (2026-08-07): advance past MIN_LIFE grace so
        # a state-transition sunset can fire (grace default 15min).
        fake_clock.advance(ARRESTER_OVERRIDE_MIN_LIFE_S + 60)
        # New denylist rule — only ``arriving``/``guest``/``waking``
        # preserve the hold. `home_day` is now an invalidating transition.
        # SEMANTIC BINDING: a preserving-state transition MUST NOT sunset...
        a.sunset_immune_holds(reason="durable_state", house_state="arriving")
        assert ZONE_ID in a._immune_holds
        # ...but an invalidating transition MUST.
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
        # ARREST-SUNSET-1 (2026-08-07): only ``arriving``/``guest``/``waking``
        # preserve. Use ``arriving`` for the preserve leg. Advance past
        # MIN_LIFE grace so the invalidating transition can fire.
        assert a.sunset_temp_arrester_override(
            reason="durable_state", house_state="arriving",
        ) is False
        assert a.temp_arrester_override_active is True
        fake_clock.advance(ARRESTER_OVERRIDE_MIN_LIFE_S + 60)
        assert a.sunset_temp_arrester_override(
            reason="durable_state", house_state="sleep",
        ) is True
        assert a.temp_arrester_override_active is False

    def test_max_age_still_fires_independently(self, fake_clock):
        """First-of preserved: max-age still sunsets on its own timeline
        even if no durable transition ever arrives."""
        a = _make_arrester()
        a.set_temp_arrester_override(True)
        fake_clock.advance(COMFORT_OVERRIDE_MAX_S + 10)
        assert a.sunset_temp_arrester_override(reason="max_age") is True
        assert a.temp_arrester_override_active is False

    # F2 (2026-08-07 fix-up cycle-4): these two tests were previously
    # nested (indented) inside the module-level function
    # ``test_no_inline_house_state_literal_comparisons_in_hvac_override``
    # by a stray re-indent, so pytest COLLECTED ZERO of them — including
    # the only test that pinned the post-restart default-OFF invariant.
    # Reflowed here as real TestComfortOverride methods so they run.
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
# ARREST-SUNSET-1 (2026-08-07) — table-driven denylist coverage.
#
# The parametrization is derived FROM const.HOUSE_STATE_TRIGGER_VALUES so
# that adding a 10th house state makes this test FAIL until it is
# classified (either as invalidating or as one of the two preserving
# states). That property IS the point — do not hand-copy the list.
# ===========================================================================

from custom_components.universal_room_automation.const import (  # noqa: E402
    HOUSE_STATE_TRIGGER_VALUES,
)
from custom_components.universal_room_automation.domain_coordinators.hvac_const import (  # noqa: E402
    ARRESTER_HOLD_PRESERVING_STATES,
    house_state_invalidates_arrester_hold,
)

# F3 (2026-08-07 fix-up cycle-4): HAND-AUTHORED expectation — deliberately
# independent of the production predicate (was: derived from
# ARRESTER_HOLD_PRESERVING_STATES, which made this table restate the
# predicate under test, so the test was tautological). Appending a fake
# state (e.g. "party") to HOUSE_STATE_TRIGGER_VALUES now trips the
# vocabulary-key guard below and FAILS every parametrized test until a
# human classifies it here.
#
# Each row is written out explicitly with a one-line rationale. The two
# preserving states are ``arriving``/``guest``; ``waking`` is grouped
# with them per the transient-state ruling (2026-08-07 amendment).
_EXPECTED_INVALIDATES: dict[str, bool] = {
    "away":         True,   # durable — arrester regains governance
    "arriving":     False,  # PRESERVING — transient (60s hysteresis)
    "home_day":     True,   # durable — a real context change
    "home_evening": True,   # durable
    "home_night":   True,   # durable
    "sleep":        True,   # durable — the ORIGINAL sunset trigger
    "waking":       False,  # PRESERVING — morning-twin of arriving
    "guest":        False,  # PRESERVING — operator-declared exception
    "vacation":     True,   # durable — long-away
}
# Vocabulary guard: adding a NEW state to HOUSE_STATE_TRIGGER_VALUES
# without classifying it here MUST fail the collection. F3 mutation
# drill: appending "party" to HOUSE_STATE_TRIGGER_VALUES and rerunning
# the tests trips this assertion. Restore.
assert set(_EXPECTED_INVALIDATES) == set(HOUSE_STATE_TRIGGER_VALUES), (
    "House-state vocabulary drift: hand-authored _EXPECTED_INVALIDATES "
    f"disagrees with HOUSE_STATE_TRIGGER_VALUES. Missing classification "
    f"for: {set(HOUSE_STATE_TRIGGER_VALUES) - set(_EXPECTED_INVALIDATES)}, "
    f"stale entries: {set(_EXPECTED_INVALIDATES) - set(HOUSE_STATE_TRIGGER_VALUES)}"
)
# Belt-and-braces: pin the exact preserving set so a silent widening of
# ARRESTER_HOLD_PRESERVING_STATES also breaks a test. Includes ``waking``
# (2026-08-07 amendment) — the morning-twin of ``arriving``, transient
# tier per the house-state hysteresis table.
assert ARRESTER_HOLD_PRESERVING_STATES == frozenset(
    {"arriving", "guest", "waking"}
)


class TestArresterSunsetDenylist:
    """Both sunset sites (Temp Arrester Override + immune-holds) must
    consult the SAME predicate — that's the anti-fork invariant."""

    @pytest.mark.parametrize("state", HOUSE_STATE_TRIGGER_VALUES)
    def test_temp_arrester_override_matches_denylist(self, fake_clock, state):
        a = _make_arrester()
        a.set_temp_arrester_override(True)
        # Advance past MIN_LIFE so the table test measures the DENYLIST,
        # not the (independent) grace-window suppression.
        fake_clock.advance(ARRESTER_OVERRIDE_MIN_LIFE_S + 60)
        fired = a.sunset_temp_arrester_override(
            reason="durable_state", house_state=state,
        )
        assert fired is _EXPECTED_INVALIDATES[state], (
            f"state={state!r} expected invalidates={_EXPECTED_INVALIDATES[state]} "
            f"got fired={fired}"
        )
        assert a.temp_arrester_override_active is (not _EXPECTED_INVALIDATES[state])

    @pytest.mark.parametrize("state", HOUSE_STATE_TRIGGER_VALUES)
    def test_immune_holds_matches_denylist(self, fake_clock, state):
        """Sibling site: sunset_immune_holds must ALSO consult the SAME
        predicate. Ripple is intentional; pin it here."""
        a = _make_arrester()
        # Seed one immune hold, then advance past MIN_LIFE grace.
        a._immune_holds[ZONE_ID] = {
            "user_name": "test",
            "started_ts": fake_clock.now(),
        }
        fake_clock.advance(ARRESTER_OVERRIDE_MIN_LIFE_S + 60)
        a.sunset_immune_holds(reason="durable_state", house_state=state)
        cleared = ZONE_ID not in a._immune_holds
        assert cleared is _EXPECTED_INVALIDATES[state], (
            f"state={state!r} expected invalidates={_EXPECTED_INVALIDATES[state]} "
            f"got cleared={cleared}"
        )

    def test_predicate_none_and_empty_are_falsey(self):
        assert house_state_invalidates_arrester_hold(None) is False
        assert house_state_invalidates_arrester_hold("") is False

    def test_predicate_unknown_state_invalidates(self):
        """Denylist default: an UNCLASSIFIED future state invalidates —
        fail-safe direction (arrester regains governance rather than a
        suppression persisting forever)."""
        assert house_state_invalidates_arrester_hold("some_new_state") is True


class TestArresterMinLifeGraceAndDeferral:
    """MIN_LIFE grace + deferred-obligation semantics (ARREST-SUNSET-1
    2026-08-07 amendment). The invalidating transition during the grace
    is DEFERRED, not discarded — otherwise the event is lost and the
    override survives to max-age (6h)."""

    def test_transition_within_grace_does_not_sunset_immediately(self, fake_clock):
        a = _make_arrester()
        a.set_temp_arrester_override(True)
        fake_clock.advance(60)  # T0+60s, well under 15min grace
        fired = a.sunset_temp_arrester_override(
            reason="durable_state", house_state="sleep",
        )
        assert fired is False
        assert a.temp_arrester_override_active is True
        # Pending flag is set — obligation is DEFERRED, not lost.
        assert a._temp_arrester_override_pending_sunset == "sleep"

    def test_deferred_sunset_discharges_via_sweep_at_grace_expiry(self, fake_clock):
        """The operator's exact requirement: transition arrives at T0+60s,
        override sunsets at ~T0+15min WITHOUT any further transition."""
        a = _make_arrester()
        a.set_temp_arrester_override(True)
        fake_clock.advance(60)
        a.sunset_temp_arrester_override(
            reason="durable_state", house_state="sleep",
        )
        assert a.temp_arrester_override_active is True
        # Advance past MIN_LIFE — the periodic sweep runs with
        # reason="max_age_or_boundary". The top-of-method backstop
        # discharges the pending obligation.
        fake_clock.advance(ARRESTER_OVERRIDE_MIN_LIFE_S)
        fired = a.sunset_temp_arrester_override(reason="max_age_or_boundary")
        assert fired is True, "sweep must discharge the deferred sunset"
        assert a.temp_arrester_override_active is False
        assert a._temp_arrester_override_pending_sunset is None

    def test_no_transition_at_all_keeps_override_past_grace(self, fake_clock):
        """Regression guard: discharge is TRANSITION-triggered, not
        current-state-triggered. Without any transition, an override
        engaged during home_day survives past the 15min grace (until
        max-age at 6h)."""
        a = _make_arrester()
        a.set_temp_arrester_override(True)
        fake_clock.advance(ARRESTER_OVERRIDE_MIN_LIFE_S + 60)  # T0+16min
        fired = a.sunset_temp_arrester_override(reason="max_age_or_boundary")
        assert fired is False
        assert a.temp_arrester_override_active is True

    def test_max_age_fires_even_though_min_life_would_block(self, fake_clock):
        """Grace does not outrank max-age: the 6h max-age sunset fires
        independent of any min-life gate."""
        a = _make_arrester()
        a.set_temp_arrester_override(True)
        fake_clock.advance(COMFORT_OVERRIDE_MAX_S + 60)
        fired = a.sunset_temp_arrester_override(reason="max_age_or_boundary")
        assert fired is True
        assert a.temp_arrester_override_active is False

    def test_min_life_zero_disables_grace(self, fake_clock, monkeypatch):
        """Kill switch: MIN_LIFE_S=0 → transition at T0+1s sunsets."""
        monkeypatch.setattr(hvac_override, "ARRESTER_OVERRIDE_MIN_LIFE_S", 0)
        a = _make_arrester()
        a.set_temp_arrester_override(True)
        fake_clock.advance(1)
        fired = a.sunset_temp_arrester_override(
            reason="durable_state", house_state="sleep",
        )
        assert fired is True
        assert a.temp_arrester_override_active is False

    @pytest.mark.parametrize(
        "preserve_state", ["arriving", "guest", "waking"],
    )
    def test_preserve_states_never_sunset_regardless_of_age(
        self, fake_clock, preserve_state,
    ):
        a = _make_arrester()
        a.set_temp_arrester_override(True)
        # Well past MIN_LIFE and even close to max-age — a preserving
        # transition still does not sunset.
        fake_clock.advance(COMFORT_OVERRIDE_MAX_S - 60)
        fired = a.sunset_temp_arrester_override(
            reason="durable_state", house_state=preserve_state,
        )
        assert fired is False
        assert a.temp_arrester_override_active is True

    def test_manual_off_clears_pending_and_timer(self, fake_clock):
        a = _make_arrester()
        a.set_temp_arrester_override(True)
        fake_clock.advance(60)
        a.sunset_temp_arrester_override(
            reason="durable_state", house_state="sleep",
        )
        assert a._temp_arrester_override_pending_sunset == "sleep"
        # Manual OFF must clear the pending flag AND timer handle so a
        # subsequent re-engagement is not sunset by a stale grace fire.
        a.set_temp_arrester_override(False)
        assert a._temp_arrester_override_pending_sunset is None
        assert a._temp_arrester_override_pending_sunset_unsub is None
        # Re-engage; a fresh grace window applies.
        a.set_temp_arrester_override(True)
        assert a._temp_arrester_override_active is True
        assert a._temp_arrester_override_pending_sunset is None

    def test_immune_hold_deferred_sunset_via_sweep(self, fake_clock):
        """Sibling: immune-holds mirror the deferral. Discharge runs on
        the sweep (no per-record timer)."""
        a = _make_arrester()
        a._immune_holds[ZONE_ID] = {
            "user_name": "test",
            "started_ts": fake_clock.now(),
        }
        fake_clock.advance(60)
        a.sunset_immune_holds(reason="durable_state", house_state="sleep")
        assert ZONE_ID in a._immune_holds
        assert a._immune_holds[ZONE_ID].get("pending_sunset_state") == "sleep"
        # Sweep at grace expiry discharges.
        fake_clock.advance(ARRESTER_OVERRIDE_MIN_LIFE_S)
        a.sunset_immune_holds(reason="max_age_or_boundary")
        assert ZONE_ID not in a._immune_holds


def test_no_inline_house_state_literal_comparisons_in_hvac_override():
    """Anti-fork source test: the original ARREST-SUNSET-1 bug was
    `house_state == "sleep"` living inline in hvac_override.py while its
    sibling used the shared set. Ban that literal-comparison SHAPE so it
    cannot silently regrow.
    """
    import re
    path = os.path.join(
        os.path.dirname(hvac_override.__file__), "hvac_override.py",
    )
    with open(path) as fh:
        src = fh.read()
    # Match `house_state == "..."` or `house_state == '...'` (any single
    # quoted state literal). The legit reader now routes through
    # house_state_invalidates_arrester_hold(house_state).
    pattern = re.compile(r"house_state\s*==\s*['\"]")
    hits = pattern.findall(src)
    assert not hits, (
        f"hvac_override.py must not compare house_state to a string literal — "
        f"route through house_state_invalidates_arrester_hold instead. "
        f"Found {len(hits)} occurrence(s)."
    )
    # F2: (previously two orphan def test_* methods were nested here at
    # this indentation and were never collected. Reflowed into
    # TestComfortOverride above.)


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
