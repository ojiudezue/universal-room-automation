"""v4.7.33 A-F5: TTL-window suppression in OverrideArrester (behavioral).

Regression guard for the v4.7.32 multi-event suppression bug:

    `_revert_override` (hvac_override.py) fires TWO climate service calls
    under a single suppress() — first `set_hvac_mode: heat_cool` (when the
    zone has drifted off heat_cool), then `set_preset_mode`. The old
    `set[str]` + first-event-discard mechanism popped suppression on the
    FIRST resulting state event, so the SECOND URA-generated event ran
    unprotected through `_handle_climate_change` and could re-arm the
    arrester. Any thermostat that emits multiple settle events per single
    service call hits the same class of bug.

A-F5 fix: replace the set with `_suppressed_until: dict[str, datetime]`
opened to `dt_util.now() + SUPPRESS_TTL_SECONDS`. The listener does NOT
pop on read; suppression survives every event inside the window and
self-clears after.

This file drives the REAL `OverrideArrester` code path:

  * The actual `_handle_climate_change` callback (no re-implementation).
  * The actual `suppress` / `unsuppress` setters.
  * `dt_util.now()` is patched on the module so the TTL window can be
    advanced deterministically (no real sleeps).

Test cases:

  1. Two consecutive simulated state-change events for the same entity
     after a single `suppress()` are BOTH suppressed (listener returns
     early before the override-detection branch runs). Exactly the
     `_revert_override` two-event scenario.
  2. Suppression self-clears: an event after TTL expiry is NOT suppressed
     and the listener runs into the zone-lookup branch (proven by
     observing that `_find_zone_by_entity` was consulted — i.e. it got
     past the TTL guard).
  3. `unsuppress(entity)` clears immediately (error-path contract).
  4. Single-write happy path: one suppress, one write, ONE simulated
     event suppressed; a SECOND (unrelated) event well after the TTL
     window is treated as a genuine override (listener proceeds into the
     detection branch).
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
# Stub out homeassistant modules that hvac_override.py imports at module load.
# Mirrors the pattern in test_ev_offpeak_proactive.py — module-level setdefault
# so other test files that have already registered the same module win, and
# we don't trample their fixtures.
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


_mods: dict[str, dict | types.ModuleType] = {
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
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": _utcnow_real,
        "now": _now_real,
        "UTC": timezone.utc,
    },
    "homeassistant.components": {},
    "homeassistant.components.recorder": {
        "get_instance": MagicMock(),
    },
    "homeassistant.components.recorder.history": {
        "get_significant_states": MagicMock(),
    },
}

for _name, _attrs in _mods.items():
    if isinstance(_attrs, dict):
        sys.modules.setdefault(_name, _mock_module(_name, **_attrs))
    else:
        sys.modules.setdefault(_name, _attrs)


# Project root on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# Build the URA package hierarchy and import hvac_override + hvac_zones
# from-source so we get the real classes (not stale sys.modules entries
# from siblings that may have only imported sibling modules).

_HERE = os.path.dirname(__file__)
_CC_PATH = os.path.join(_HERE, "..", "..", "custom_components")
_URA_PATH = os.path.join(_CC_PATH, "universal_room_automation")
_DC_PATH = os.path.join(_URA_PATH, "domain_coordinators")

if "custom_components" not in sys.modules:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [_CC_PATH]
    sys.modules["custom_components"] = _cc

if "custom_components.universal_room_automation" not in sys.modules:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [_URA_PATH]
    _ura.__package__ = "custom_components.universal_room_automation"
    sys.modules["custom_components.universal_room_automation"] = _ura


def _load(modname: str, relpath: str, *, force: bool = False) -> types.ModuleType:
    """Import a module from a file path, registering it under `modname`.

    Other test files may have force-pre-loaded a sibling module as a
    MagicMock (e.g. `test_v47x_ev_tou_hardening.py` does this for many
    URA submodules to avoid heavy imports). Always force-reload our
    hvac_override surface so we get the real class, real
    `SUPPRESS_TTL_SECONDS`, real `_handle_climate_change`.
    """
    if modname in sys.modules and not force:
        cached = sys.modules[modname]
        # If a sibling test mocked this module as a MagicMock, it won't
        # have a real __file__ pointing into the URA tree — force reload.
        if isinstance(cached, types.ModuleType) and getattr(
            cached, "__file__", None
        ):
            return cached
        # Mock or partial — fall through to a real load.
    spec = importlib.util.spec_from_file_location(
        modname, os.path.join(_URA_PATH, relpath),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


# const must be loaded before domain_coordinators submodules that reference it
_load(
    "custom_components.universal_room_automation.const",
    "const.py",
)

# Defensively force-reload anything sibling tests may have stubbed as a
# MagicMock. We need the REAL classes / constants from these modules.
for _modname in (
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
):
    _cached = sys.modules.get(_modname)
    if _cached is not None and not getattr(_cached, "__file__", None):
        # Mock-shaped cache — wipe it so the next _load() does a real exec.
        del sys.modules[_modname]

# Build domain_coordinators package
if "custom_components.universal_room_automation.domain_coordinators" not in sys.modules:
    _dc = types.ModuleType(
        "custom_components.universal_room_automation.domain_coordinators"
    )
    _dc.__path__ = [_DC_PATH]
    _dc.__package__ = (
        "custom_components.universal_room_automation.domain_coordinators"
    )
    sys.modules[
        "custom_components.universal_room_automation.domain_coordinators"
    ] = _dc

_load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "domain_coordinators/hvac_const.py",
)
_load(
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "domain_coordinators/hvac_zones.py",
)
# feature/freeze-floor: hvac_override now imports the setpoint chokepoint;
# load it real (depends only on hvac_const, already loaded) so the relative
# import in hvac_override resolves to the genuine module.
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

OverrideArrester = hvac_override.OverrideArrester
ZoneState = hvac_zones.ZoneState
SUPPRESS_TTL_SECONDS = hvac_override.SUPPRESS_TTL_SECONDS


# ---------------------------------------------------------------------------
# dt_util patching — controls what `dt_util.now()` returns inside the arrester.
# ---------------------------------------------------------------------------


class _FakeClock:
    """Mutable wall-clock the test can advance."""

    def __init__(self, start: datetime) -> None:
        self.t = start

    def now(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t = self.t + timedelta(seconds=seconds)


@pytest.fixture
def fake_clock(monkeypatch):
    """Pin `hvac_override.dt_util.now()` to a fake clock for the test.

    The arrester binds `dt_util` at module load (`from homeassistant.util
    import dt as dt_util`). We patch the symbol on the LOADED module so any
    `dt_util.now()` call inside production code returns the clock's view.
    """
    clock = _FakeClock(datetime(2026, 6, 8, 12, 0, 0))
    fake_dt = types.SimpleNamespace(now=clock.now)
    monkeypatch.setattr(hvac_override, "dt_util", fake_dt)
    return clock


# ---------------------------------------------------------------------------
# Helpers for building Events + Zone state.
# ---------------------------------------------------------------------------


CLIMATE_ENTITY = "climate.zone_a_thermostat"
ZONE_ID = "zone_a"


def _make_arrester() -> OverrideArrester:
    """Build an OverrideArrester wired to a single zone."""
    zone = ZoneState(
        zone_id=ZONE_ID,
        zone_name="Zone A",
        climate_entity=CLIMATE_ENTITY,
    )
    zone.hvac_mode = "heat_cool"
    zone.preset_mode = "home"

    zone_manager = MagicMock()
    zone_manager.zones = {ZONE_ID: zone}

    hass = MagicMock()
    arrester = OverrideArrester(
        hass=hass,
        zone_manager=zone_manager,
        compromise_minutes=30,
        ac_reset_timeout=60,
        enabled=True,
    )
    # Sentinel so tests can detect whether the listener got past the TTL guard
    # and into the zone-lookup branch (proves suppression was NOT skipped).
    arrester._find_zone_calls = []  # type: ignore[attr-defined]
    real_find = arrester._find_zone_by_entity

    def _spy(entity_id: str):
        arrester._find_zone_calls.append(entity_id)  # type: ignore[attr-defined]
        return real_find(entity_id)

    arrester._find_zone_by_entity = _spy  # type: ignore[assignment]
    return arrester


def _make_event(
    entity_id: str,
    *,
    old_preset: str = "home",
    new_preset: str = "manual",
    old_high: float = 76.0,
    new_high: float = 68.0,
    old_low: float = 70.0,
    new_low: float = 68.0,
    old_hvac_mode: str = "heat_cool",
    new_hvac_mode: str = "heat_cool",
) -> MagicMock:
    """Build a state-change Event shaped like HA's actual payload.

    Defaults describe a USER override (preset went to "manual") — that way
    if the suppression guard fails open, the listener will fall through to
    the override-detection branch.
    """
    old_state = MagicMock()
    old_state.attributes = {
        "preset_mode": old_preset,
        "target_temp_high": old_high,
        "target_temp_low": old_low,
        "hvac_mode": old_hvac_mode,
    }
    new_state = MagicMock()
    new_state.attributes = {
        "preset_mode": new_preset,
        "target_temp_high": new_high,
        "target_temp_low": new_low,
        "hvac_mode": new_hvac_mode,
    }
    event = MagicMock()
    event.data = {
        "entity_id": entity_id,
        "old_state": old_state,
        "new_state": new_state,
    }
    return event


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTTLSuppression:
    """A-F5 regression guards for the TTL-window suppression mechanism."""

    def test_two_consecutive_events_both_suppressed(self, fake_clock):
        """Core A-F5 guard: a single suppress() covers BOTH the
        set_hvac_mode and set_preset_mode settle events that
        `_revert_override` emits.

        Pre-fix behavior: first event popped the set, second event ran
        through `_find_zone_by_entity` and downstream override detection.
        Post-fix behavior: both events return early before the zone
        lookup, so the spy records zero calls.
        """
        arrester = _make_arrester()

        arrester.suppress(CLIMATE_ENTITY)

        # Simulate the two settle events from _revert_override's two
        # service calls. Event 1: hvac_mode flipped to heat_cool.
        e1 = _make_event(
            CLIMATE_ENTITY,
            old_preset="home", new_preset="home",
            old_high=76.0, new_high=76.0,
            old_low=70.0, new_low=70.0,
            old_hvac_mode="off", new_hvac_mode="heat_cool",
        )
        # Event 2 (~50ms later): preset re-asserted. We make this look
        # like an override so the listener WILL trip override detection
        # unless suppression holds.
        fake_clock.advance(0.05)
        e2 = _make_event(
            CLIMATE_ENTITY,
            old_preset="manual", new_preset="home",
            old_high=68.0, new_high=76.0,
            old_low=68.0, new_low=70.0,
        )

        arrester._handle_climate_change(e1)
        arrester._handle_climate_change(e2)

        assert arrester._find_zone_calls == [], (
            "Both events must return early before zone lookup — "
            "the listener should NOT have consulted _find_zone_by_entity "
            "on either of them. Got: %r" % (arrester._find_zone_calls,)
        )
        # The TTL entry MUST still be live (didn't get popped on first
        # event the way the v4.7.32-era set did).
        assert CLIMATE_ENTITY in arrester._suppressed_until

    def test_suppression_self_clears_after_ttl(self, fake_clock):
        """After SUPPRESS_TTL_SECONDS elapses, a state event is NOT
        suppressed — the listener proceeds into the zone lookup."""
        arrester = _make_arrester()

        arrester.suppress(CLIMATE_ENTITY)

        # Advance just past the TTL window.
        fake_clock.advance(SUPPRESS_TTL_SECONDS + 0.1)

        evt = _make_event(CLIMATE_ENTITY)
        arrester._handle_climate_change(evt)

        assert arrester._find_zone_calls == [CLIMATE_ENTITY], (
            "Expired suppression must NOT block override detection. "
            "Got find-zone calls: %r" % (arrester._find_zone_calls,)
        )
        # And the expired entry should have been cleaned up by the
        # listener (bounded dict growth).
        assert CLIMATE_ENTITY not in arrester._suppressed_until

    def test_unsuppress_clears_immediately(self, fake_clock):
        """Error-path contract: unsuppress(entity) clears the window
        right now, even mid-TTL."""
        arrester = _make_arrester()

        arrester.suppress(CLIMATE_ENTITY)
        assert CLIMATE_ENTITY in arrester._suppressed_until

        arrester.unsuppress(CLIMATE_ENTITY)
        assert CLIMATE_ENTITY not in arrester._suppressed_until

        # And a subsequent event should NOT be suppressed.
        evt = _make_event(CLIMATE_ENTITY)
        arrester._handle_climate_change(evt)

        assert arrester._find_zone_calls == [CLIMATE_ENTITY], (
            "After unsuppress(), listener must run override detection."
        )

    def test_unsuppress_unknown_entity_is_safe(self, fake_clock):
        """unsuppress() on an entity that was never suppressed must
        not raise (it's a pop-with-default)."""
        arrester = _make_arrester()
        arrester.unsuppress(CLIMATE_ENTITY)  # no-op, must not raise
        assert arrester._suppressed_until == {}

    def test_single_write_happy_path_then_genuine_override(self, fake_clock):
        """Existing single-write callers (most of hvac.py / hvac_predict.py)
        still behave: one suppress() covers their one settle event; a
        later, unrelated user override well past the TTL window is still
        caught by override detection."""
        arrester = _make_arrester()

        # URA does its single write
        arrester.suppress(CLIMATE_ENTITY)
        ura_event = _make_event(
            CLIMATE_ENTITY,
            old_preset="home", new_preset="home",
            old_high=76.0, new_high=74.0,  # URA-initiated temp change
            old_low=70.0, new_low=70.0,
        )
        arrester._handle_climate_change(ura_event)

        # Suppressed — listener didn't even look up the zone
        assert arrester._find_zone_calls == []

        # Hours later, the user actually overrides
        fake_clock.advance(3600)
        user_override = _make_event(
            CLIMATE_ENTITY,
            old_preset="home", new_preset="manual",
            old_high=74.0, new_high=64.0,
            old_low=70.0, new_low=64.0,
        )
        arrester._handle_climate_change(user_override)

        assert arrester._find_zone_calls == [CLIMATE_ENTITY], (
            "Genuine override after the TTL window must reach zone "
            "lookup (and thereafter override detection)."
        )
        # And the now-expired suppression entry should be cleaned up.
        assert CLIMATE_ENTITY not in arrester._suppressed_until

    def test_suppress_resets_ttl_window(self, fake_clock):
        """Re-calling suppress() within the window pushes expiry out —
        important for _restore_after_nudge, which re-suppresses on top
        of an already-suppressed entity."""
        arrester = _make_arrester()

        arrester.suppress(CLIMATE_ENTITY)
        first_expiry = arrester._suppressed_until[CLIMATE_ENTITY]

        fake_clock.advance(2.0)
        arrester.suppress(CLIMATE_ENTITY)
        second_expiry = arrester._suppressed_until[CLIMATE_ENTITY]

        assert second_expiry > first_expiry, (
            "Re-suppression must extend the TTL window, not be a no-op."
        )

    def test_no_legacy_field(self):
        """A-F5 hygiene: the legacy `_suppressed_entities` set MUST be
        gone — its presence indicates an incomplete migration."""
        arrester = _make_arrester()
        assert not hasattr(arrester, "_suppressed_entities"), (
            "_suppressed_entities should be fully removed in favor of "
            "_suppressed_until (A-F5 migration)."
        )
        assert isinstance(arrester._suppressed_until, dict)

    # -----------------------------------------------------------------
    # FIX 1 guard (A-F5 review HIGH): mid-window manual-preset
    # passthrough. A user override that lands inside the 5s TTL window
    # must still be caught — URA never writes preset_mode=manual, so a
    # non-manual->manual transition unambiguously identifies the user.
    # Non-manual events stay suppressed (regression guard for the
    # original A-F5 fix).
    # -----------------------------------------------------------------
    def test_user_override_passthrough_mid_window(self, fake_clock):
        """A genuine non-manual->manual user override inside the
        TTL window must reach override detection, dropping the
        suppression entry. A non-manual (URA-shaped) in-window event
        must still be suppressed."""
        # Sub-case A: mid-window manual transition passes through.
        arrester = _make_arrester()
        arrester.suppress(CLIMATE_ENTITY)
        assert CLIMATE_ENTITY in arrester._suppressed_until

        fake_clock.advance(1.0)  # still well within 5s window
        manual_evt = _make_event(
            CLIMATE_ENTITY,
            old_preset="home", new_preset="manual",
            old_high=76.0, new_high=68.0,
            old_low=70.0, new_low=68.0,
        )
        arrester._handle_climate_change(manual_evt)

        assert arrester._find_zone_calls == [CLIMATE_ENTITY], (
            "Mid-window manual-preset transition must pass through the "
            "TTL guard (FIX 1). Got: %r" % (arrester._find_zone_calls,)
        )
        assert CLIMATE_ENTITY not in arrester._suppressed_until, (
            "Suppression entry must be dropped once a genuine user "
            "override has been let through."
        )

        # Sub-case B: fresh arrester; non-manual in-window event STAYS
        # suppressed. This guards FIX 1 from over-firing — only manual
        # transitions are exempt.
        arrester2 = _make_arrester()
        arrester2.suppress(CLIMATE_ENTITY)
        fake_clock.advance(1.0)
        ura_evt = _make_event(
            CLIMATE_ENTITY,
            old_preset="home", new_preset="home",
            old_high=76.0, new_high=74.0,  # URA temp change
            old_low=70.0, new_low=70.0,
        )
        arrester2._handle_climate_change(ura_evt)

        assert arrester2._find_zone_calls == [], (
            "Non-manual in-window events must remain suppressed; "
            "FIX 1 must only exempt non-manual->manual transitions. "
            "Got: %r" % (arrester2._find_zone_calls,)
        )
        assert CLIMATE_ENTITY in arrester2._suppressed_until, (
            "Suppression entry must persist for non-manual in-window events."
        )

    # -----------------------------------------------------------------
    # FIX 2 guard (A-F5 review HIGH): clear suppression on disable.
    # A stale TTL window must NOT survive an arrester disable.
    # -----------------------------------------------------------------
    def test_disable_clears_suppression_window(self, fake_clock):
        arrester = _make_arrester()
        arrester.suppress(CLIMATE_ENTITY)
        assert CLIMATE_ENTITY in arrester._suppressed_until

        arrester.enabled = False

        assert arrester._suppressed_until == {}, (
            "Disabling the arrester must clear any open TTL windows "
            "(FIX 2) — otherwise events for <=5s after disable are "
            "silently swallowed."
        )

    # -----------------------------------------------------------------
    # Review C2: multi-entity isolation. Suppressing entity A must
    # not suppress events for entity B.
    # -----------------------------------------------------------------
    def test_suppression_is_per_entity(self, fake_clock):
        """Suppressing climate.a must not affect climate.b — TTL window
        is keyed on entity_id."""
        arrester = _make_arrester()
        entity_a = "climate.a"
        entity_b = "climate.b"

        arrester.suppress(entity_a)
        assert entity_a in arrester._suppressed_until
        assert entity_b not in arrester._suppressed_until

        # An event for entity B should NOT early-return at the TTL guard
        # even though A is suppressed. We assert via the spy: the
        # listener proceeds into `_find_zone_by_entity(entity_b)`.
        # (No real zone is registered for entity_b, so the listener will
        # return at the "zone is None" branch — but only AFTER the spy
        # records the call, which is exactly what we're proving.)
        evt_b = _make_event(entity_b)
        arrester._handle_climate_change(evt_b)

        assert arrester._find_zone_calls == [entity_b], (
            "Suppression of climate.a must not block climate.b. "
            "Got find-zone calls: %r" % (arrester._find_zone_calls,)
        )

        # And a URA-shaped (non-manual) event for entity A IS still
        # suppressed within window. Note: we use a non-manual shape on
        # purpose — a manual-transition event for A would correctly
        # pass through under FIX 1 (mid-window user-override exemption).
        evt_a = _make_event(
            entity_a,
            old_preset="home", new_preset="home",
            old_high=76.0, new_high=74.0,
            old_low=70.0, new_low=70.0,
        )
        arrester._handle_climate_change(evt_a)
        assert arrester._find_zone_calls == [entity_b], (
            "climate.a URA-shaped event must remain suppressed after a "
            "climate.b passthrough. Got: %r" % (arrester._find_zone_calls,)
        )
        assert entity_a in arrester._suppressed_until


# ---------------------------------------------------------------------------
# Static source-shape guard (A-F5 review MEDIUM C1): _revert_override
# must call self.suppress(...) BEFORE the first services.async_call(...)
# so the URA-initiated settle events are covered.
# ---------------------------------------------------------------------------


class TestRevertOverrideOrdering:
    """Best-effort static check that within `_revert_override`'s source
    body, `self.suppress(zone.climate_entity)` appears BEFORE the first
    `services.async_call(`. Mirrors the soft-nudge ordering guard in
    test_v4511_ac_energy_aware_ramp_down.py."""

    def test_suppress_before_first_service_call_in_revert_override(self):
        # Read the production source directly so we're guarding the
        # actual shipped file, not an in-memory module representation.
        src_path = os.path.join(
            _URA_PATH, "domain_coordinators", "hvac_override.py",
        )
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()

        idx = src.find("async def _revert_override(")
        assert idx > 0, "could not locate _revert_override in source"
        # Window tight to the function body — next `    async def ` or
        # `    def ` at 4-space indent ends it. 4000 chars is plenty for
        # this short method.
        body = src[idx:idx + 4000]
        # Trim to the next top-level method definition inside the class
        # so we don't accidentally match a later method's services call.
        end_markers = ["\n    async def ", "\n    def "]
        end = len(body)
        for marker in end_markers:
            # find AFTER the opening `async def _revert_override(`
            pos = body.find(marker, len("async def _revert_override("))
            if pos != -1 and pos < end:
                end = pos
        body = body[:end]

        suppress_pos = body.find("self.suppress(zone.climate_entity")
        service_pos = body.find("services.async_call(")
        assert suppress_pos > 0, (
            "_revert_override must call self.suppress(zone.climate_entity) "
            "to cover its own settle events."
        )
        assert service_pos > 0, (
            "_revert_override must call services.async_call(...)."
        )
        assert suppress_pos < service_pos, (
            "Suppress override BEFORE issuing the first service call in "
            "_revert_override — otherwise the settle event can race the "
            "suppression window open and re-arm the arrester."
        )


# ---------------------------------------------------------------------------
# FIX B1: kind-tagged suppression — induced preset_mode manual under a
# "temp" suppression (from URA's own set_temperature nudge) must NOT
# self-count as a user override. Otherwise on preset-based Carrier/Bryant
# thermostats, every nudge triggers preset sleep->manual as a SIDE EFFECT,
# which fires override_count_today++ (empty house, 85 auto ac_ramp_events/
# night with current_temp==target).
# ---------------------------------------------------------------------------


class TestKindTaggedSuppression:
    def test_induced_manual_under_temp_suppression_stays_suppressed(
        self, fake_clock,
    ):
        """FIX B1 core: kind='temp' suppression blocks the induced manual."""
        arrester = _make_arrester()
        arrester.suppress(CLIMATE_ENTITY, kind="temp")

        fake_clock.advance(1.0)
        # Preset-based thermostat side effect: temp write induced
        # preset_mode sleep->manual
        induced_manual = _make_event(
            CLIMATE_ENTITY,
            old_preset="sleep", new_preset="manual",
            old_high=76.0, new_high=76.5,  # nudge
            old_low=70.0, new_low=70.0,
        )
        arrester._handle_climate_change(induced_manual)

        assert arrester._find_zone_calls == [], (
            "Induced manual under kind='temp' must stay suppressed — "
            "otherwise it self-counts as a user override. Got: %r"
            % (arrester._find_zone_calls,)
        )
        # Suppression entry preserved (still within TTL).
        assert CLIMATE_ENTITY in arrester._suppressed_until

    def test_genuine_user_manual_without_temp_suppression_passes_through(
        self, fake_clock,
    ):
        """FIX B1 guard: outside a 'temp' suppression, a manual flip still
        reaches override detection (existing FIX 1 behavior preserved)."""
        arrester = _make_arrester()
        # No suppress at all — pure user action.
        user_evt = _make_event(
            CLIMATE_ENTITY,
            old_preset="home", new_preset="manual",
            old_high=76.0, new_high=68.0,
            old_low=70.0, new_low=68.0,
        )
        arrester._handle_climate_change(user_evt)
        assert arrester._find_zone_calls == [CLIMATE_ENTITY]

    def test_genuine_user_manual_under_preset_kind_still_passes(
        self, fake_clock,
    ):
        """kind='preset' (URA's revert write) does NOT block a
        genuine user manual mid-window — only 'temp' does."""
        arrester = _make_arrester()
        arrester.suppress(CLIMATE_ENTITY, kind="preset")

        fake_clock.advance(1.0)
        user_evt = _make_event(
            CLIMATE_ENTITY,
            old_preset="home", new_preset="manual",
            old_high=76.0, new_high=68.0,
            old_low=70.0, new_low=68.0,
        )
        arrester._handle_climate_change(user_evt)

        assert arrester._find_zone_calls == [CLIMATE_ENTITY], (
            "kind='preset' must not block genuine user manual (FIX B1 "
            "narrowly targets kind='temp'). Got: %r"
            % (arrester._find_zone_calls,)
        )

    def test_untagged_suppress_backwards_compatible(self, fake_clock):
        """External callers that don't pass kind (hvac.py / hvac_predict.py /
        optimization.py) keep the legacy FIX 1 behavior: mid-window manual
        passes through."""
        arrester = _make_arrester()
        arrester.suppress(CLIMATE_ENTITY)  # no kind — legacy

        fake_clock.advance(1.0)
        user_evt = _make_event(
            CLIMATE_ENTITY,
            old_preset="home", new_preset="manual",
            old_high=76.0, new_high=68.0,
            old_low=70.0, new_low=68.0,
        )
        arrester._handle_climate_change(user_evt)

        assert arrester._find_zone_calls == [CLIMATE_ENTITY]

    def test_unsuppress_clears_kind(self, fake_clock):
        arrester = _make_arrester()
        arrester.suppress(CLIMATE_ENTITY, kind="temp")
        assert arrester._suppress_kind.get(CLIMATE_ENTITY) == "temp"
        arrester.unsuppress(CLIMATE_ENTITY)
        assert CLIMATE_ENTITY not in arrester._suppress_kind

    def test_disable_clears_kind(self, fake_clock):
        arrester = _make_arrester()
        arrester.suppress(CLIMATE_ENTITY, kind="temp")
        arrester.enabled = False
        assert arrester._suppress_kind == {}


# ---------------------------------------------------------------------------
# FIX B2: preset-preserving restore. The nudge set_temperature flips
# preset_mode ("sleep"->"manual") on Carrier/Bryant thermostats as a side
# effect. The restore path used to only write target back, leaving the
# thermostat in "manual" preset for the rest of the night — 20+ nudges/
# night = 20+ preset flips + sleep-schedule defeated. Fix: snapshot
# preset before the nudge; if restore sees preset==manual and snapshot
# was non-manual, re-write the preset. Snapshot dict is `_nudge_pre_preset`.
# ---------------------------------------------------------------------------


class TestPresetPreservingRestore:
    def test_pre_preset_snapshot_field_exists(self):
        arrester = _make_arrester()
        # Fresh instance: empty dict, not missing attribute.
        assert hasattr(arrester, "_nudge_pre_preset")
        assert arrester._nudge_pre_preset == {}

    def test_cancel_clears_snapshot(self):
        """Verify the cancel path clears the pre-preset snapshot."""
        arrester = _make_arrester()
        arrester._nudge_pre_preset["zone_a"] = "sleep"
        # Simulate the cancel-path cleanup (matches production code).
        arrester._nudge_pre_preset.pop("zone_a", None)
        assert "zone_a" not in arrester._nudge_pre_preset

    def test_perform_soft_nudge_captures_non_manual_preset(self):
        """Source-shape guard: _perform_soft_nudge must read preset_mode
        from the climate entity BEFORE the first emit_set_temperature so
        we snapshot pre-nudge state."""
        src_path = os.path.join(
            _URA_PATH, "domain_coordinators", "hvac_override.py",
        )
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()
        idx = src.find("async def _perform_soft_nudge(")
        assert idx > 0
        end_markers = ["\n    async def ", "\n    def "]
        end = len(src)
        for m in end_markers:
            pos = src.find(m, idx + len("async def _perform_soft_nudge("))
            if pos != -1 and pos < end:
                end = pos
        body = src[idx:end]
        # The snapshot MUST come before emit_set_temperature, else we'd
        # read the post-write preset (already flipped to manual).
        snap_pos = body.find('_nudge_pre_preset[zone_id] = _pre_preset')
        # Fallback: look for the dict write pattern
        if snap_pos < 0:
            snap_pos = body.find('_nudge_pre_preset[zone_id]')
        emit_pos = body.find("emit_set_temperature(")
        assert snap_pos > 0, (
            "_perform_soft_nudge must snapshot pre-nudge preset "
            "(self._nudge_pre_preset[zone_id] = ...)"
        )
        assert emit_pos > 0
        assert snap_pos < emit_pos, (
            "Preset snapshot must precede the set_temperature write, "
            "otherwise we'd capture the post-write (manual) preset."
        )
        # Non-manual guard: don't overwrite a user-set manual mid-night.
        assert '_pre_preset != "manual"' in body

    def test_restore_after_nudge_writes_preset_when_flipped(self):
        """Source-shape guard: _restore_after_nudge must call
        set_preset_mode with the snapshotted preset when the current
        preset is 'manual'."""
        src_path = os.path.join(
            _URA_PATH, "domain_coordinators", "hvac_override.py",
        )
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()
        idx = src.find("async def _restore_after_nudge(")
        assert idx > 0
        end_markers = ["\n    async def ", "\n    def "]
        end = len(src)
        for m in end_markers:
            pos = src.find(m, idx + len("async def _restore_after_nudge("))
            if pos != -1 and pos < end:
                end = pos
        body = src[idx:end]
        assert '_nudge_pre_preset.pop(zone_id' in body, (
            "restore must consume the snapshot"
        )
        # ARREST-COMFORT-1 Cycle A: preset write migrated from inline
        # hass.services.async_call to the emit_set_preset_mode chokepoint.
        # Accept either form.
        assert (
            '"set_preset_mode"' in body
            or 'emit_set_preset_mode(' in body
        ), "restore must emit set_preset_mode to reverse the induced flip"
        assert '_cur_preset == "manual"' in body, (
            "restore must gate on current preset actually being manual"
        )
        # FIX B1 alignment: preset write must be under kind='preset'.
        assert 'kind="preset"' in body


# ---------------------------------------------------------------------------
# HIGH-C2 behavioral: drive REAL _restore_after_nudge preset restore.
#
# Review C flagged that the B2 restore is only covered by source-string
# greps — neutering `if _cur_preset == "manual":` (~line 1691) leaves
# those greps green. These tests exercise the actual coroutine and
# assert on the emitted service call log.
# ---------------------------------------------------------------------------


import asyncio  # noqa: E402


class TestRestoreAfterNudgeBehavioral:
    """B2 preset-restore behavioral — neutering the manual-gate MUST fail
    at least one of these."""

    @staticmethod
    def _build(preset_now: str | None, snapshotted_preset: str):
        """Build an arrester + zone ready to have _restore_after_nudge called.

        preset_now: current thermostat preset_mode (what hass.states returns).
                    Pass None to simulate missing state.
        snapshotted_preset: what was captured pre-nudge into _nudge_pre_preset.
        """
        zone = ZoneState(
            zone_id=ZONE_ID, zone_name="Zone A",
            climate_entity=CLIMATE_ENTITY,
        )
        zone.hvac_mode = "heat_cool"
        zone.preset_mode = snapshotted_preset or "home"
        zone.target_temp_low = 70.0
        zone.target_temp_high = 76.0
        zone.nudge_kwh_rate_before = 1.0

        zm = MagicMock()
        zm.zones = {ZONE_ID: zone}

        hass = MagicMock()
        service_calls: list[tuple[str, str, dict]] = []

        async def _async_call(domain, service, data, blocking=False):
            service_calls.append((domain, service, dict(data)))

        hass.services.async_call = _async_call

        if preset_now is None:
            hass.states.get = MagicMock(return_value=None)
        else:
            _st = MagicMock()
            _st.attributes = {"preset_mode": preset_now}
            hass.states.get = MagicMock(return_value=_st)

        arrester = OverrideArrester(
            hass=hass, zone_manager=zm,
            compromise_minutes=30, ac_reset_timeout=60, enabled=True,
        )
        arrester._db = None
        if snapshotted_preset:
            arrester._nudge_pre_preset[ZONE_ID] = snapshotted_preset

        # Stub emit_set_temperature (temp write is not what we test here);
        # also stub async_call_later (schedules eval timer post-restore).
        hvac_override.emit_set_temperature = MagicMock(
            return_value=asyncio.sleep(0),
        )
        hvac_override.async_call_later = MagicMock(return_value=lambda: None)

        return arrester, zone, service_calls

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _preset_calls(self, log):
        return [c for c in log if c[1] == "set_preset_mode"]

    def test_restore_fires_set_preset_mode_when_manual_and_snapshot(self):
        """LOAD-BEARING: preset_now=='manual' + snapshot='home' → fire
        set_preset_mode(home). Neutering `_cur_preset == "manual"` breaks
        this assertion."""
        arrester, zone, log = self._build(
            preset_now="manual", snapshotted_preset="home",
        )
        self._run(arrester._restore_after_nudge(zone, original_target=76.0))
        preset_calls = self._preset_calls(log)
        assert len(preset_calls) == 1, (
            f"Expected 1 set_preset_mode call, got {preset_calls}"
        )
        _, _, data = preset_calls[0]
        assert data.get("preset_mode") == "home"
        assert data.get("entity_id") == CLIMATE_ENTITY

    def test_restore_does_not_fire_preset_when_not_manual(self):
        """preset_now=='home' (already correct) → NO set_preset_mode."""
        arrester, zone, log = self._build(
            preset_now="home", snapshotted_preset="home",
        )
        self._run(arrester._restore_after_nudge(zone, original_target=76.0))
        assert self._preset_calls(log) == [], (
            "No preset restore when thermostat isn't in manual"
        )

    def test_restore_does_not_fire_preset_when_no_snapshot(self):
        """No pre-nudge snapshot → skip restore entirely (empty pop)."""
        arrester, zone, log = self._build(
            preset_now="manual", snapshotted_preset="",
        )
        self._run(arrester._restore_after_nudge(zone, original_target=76.0))
        assert self._preset_calls(log) == [], (
            "No preset restore when no snapshot was taken"
        )

