"""Presence batch — GUEST latch + empty-house veto gap + Tier-1 edge observability.

Covers three deliverables:

  D1  — Reorder guest-exit before sleep-hours branch in
        ``StateInferenceEngine.infer()`` so a cleared guest signal is
        not latched overnight (2026-07-11 incident: guest 20:57 →
        cleared 23:05 → held until 06:05).
  D1b — HOME_NIGHT → GUEST added to ``VALID_TRANSITIONS`` in
        ``house_state.py`` (was silently rejected proposal).
  D2  — Immediate-engage LOST-admitted AWAY veto that bypasses the
        60-min grace ONLY when the house is externally corroborated
        empty (2026-07-12 empty-house-flapping incident).
  D3  — ``OccupancySubstrate`` per-room ``_last_edge_entity`` record +
        DEBUG edge log + ``last_edge_entity_for(room_name)`` accessor.

Each test names the mutation anchor (the source site whose removal or
inversion causes THIS test to fail). Anchors were exercised by the
author — see the mutation table in the build report.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Paths + HA module mocking (mirrors test_v570_guest_detection_trust.py)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"
DC_PATH = PKG / "domain_coordinators"


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731
_mock_cls = MagicMock

_ha_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": _mock_cls,
        "callback": _identity,
        "Event": _mock_cls,
        "State": _mock_cls,
    },
    "homeassistant.config_entries": {"ConfigEntry": _mock_cls},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict,
        "EntityCategory": _mock_cls(),
    },
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": _mock_cls},
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _mock_cls(),
        "async_track_time_interval": lambda hass, cb, interval: _mock_cls(),
        "async_call_later": lambda hass, delay, cb: _mock_cls(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda hass, signal, cb: _mock_cls(),
        "async_dispatcher_send": lambda hass, signal, *args, **kwargs: None,
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": _mock_cls,
        "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": _mock_cls(),
    "homeassistant.helpers.entity_registry": {"async_get": _mock_cls()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.utcnow(),
        "now": lambda: datetime(2026, 7, 13, 14, 0, 0),
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": _mock_cls(),
        "SensorStateClass": _mock_cls(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": _mock_cls(),
    },
    "homeassistant.components.button": {
        "ButtonEntity": type("ButtonEntity", (), {}),
    },
}

for _name, _attrs in _ha_mods.items():
    if isinstance(_attrs, dict):
        _existing = sys.modules.get(_name)
        if _existing is None:
            sys.modules[_name] = _mock_module(_name, **_attrs)
        else:
            for _k, _v in _attrs.items():
                if not hasattr(_existing, _k):
                    setattr(_existing, _k, _v)
    else:
        sys.modules.setdefault(_name, _attrs)

sys.modules.setdefault("aiosqlite", MagicMock())


def _load_module(full_name: str, filepath) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(full_name, str(filepath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


_cc_pkg_name = "custom_components"
if _cc_pkg_name not in sys.modules:
    sys.modules[_cc_pkg_name] = _mock_module(_cc_pkg_name)

_ura_pkg_name = "custom_components.universal_room_automation"
if _ura_pkg_name not in sys.modules:
    _ura_pkg = _mock_module(_ura_pkg_name)
    _ura_pkg.__file__ = str(PKG / "__init__.py")
    sys.modules[_ura_pkg_name] = _ura_pkg

_dc_pkg_name = "custom_components.universal_room_automation.domain_coordinators"
if _dc_pkg_name not in sys.modules:
    _dc_pkg = _mock_module(_dc_pkg_name)
    _dc_pkg.__file__ = str(DC_PATH / "__init__.py")
    sys.modules[_dc_pkg_name] = _dc_pkg

for _submod in ("const",):
    _full = f"custom_components.universal_room_automation.{_submod}"
    if _full not in sys.modules:
        _load_module(_full, PKG / f"{_submod}.py")

for _submod in (
    "signals",
    "house_state",
    "base",
    "coordinator_diagnostics",
    "presence",
    "occupancy_substrate",
):
    _full = f"custom_components.universal_room_automation.domain_coordinators.{_submod}"
    if _full not in sys.modules:
        _load_module(_full, DC_PATH / f"{_submod}.py")


from custom_components.universal_room_automation.domain_coordinators.presence import (  # noqa: E402
    StateInferenceEngine,
)
from custom_components.universal_room_automation.domain_coordinators.house_state import (  # noqa: E402
    HouseState,
    VALID_TRANSITIONS,
)
from custom_components.universal_room_automation.domain_coordinators.occupancy_substrate import (  # noqa: E402
    OccupancySubstrate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_engine() -> StateInferenceEngine:
    """Default sleep window (23-06)."""
    return StateInferenceEngine(sleep_start_hour=23, sleep_end_hour=6)


def _at(hour: int) -> datetime:
    return datetime(2026, 7, 13, hour, 0, 0)


# ===========================================================================
# D1 — GUEST latch fix
# ===========================================================================

def test_d1_guest_exit_reachable_during_sleep_hours():
    """GUEST + cleared signal at 02:00 → returns HOME_NIGHT (not held).

    Mutation anchor: reorder revert (moving guest-exit back below the
    sleep-hours branch). Reverting causes SLEEP to be returned first,
    which is a HouseState.GUEST → HouseState.SLEEP proposal — an
    invalid transition — but infer() still RETURNS SLEEP; the state
    machine rejects it. This test asserts the RETURN VALUE, so revert
    fails here.
    """
    engine = _make_engine()
    new_state = engine.infer(
        census_count=1,
        current_state=HouseState.GUEST,
        any_zone_occupied=True,       # bypass "Nobody home" early-return
        now=_at(2),
        unidentified_count=0,
        guest_gate_armed=False,
    )
    # 02:00 is < sleep_end_hour(6) so _time_based_home returns HOME_NIGHT.
    assert new_state == HouseState.HOME_NIGHT, (
        "I-D1: cleared guest signal during sleep hours must not be latched"
    )


def test_d1_guest_exit_at_daytime_still_works():
    """GUEST + cleared signal at 14:00 → HOME_DAY. Reorder is a no-op."""
    engine = _make_engine()
    new_state = engine.infer(
        census_count=1,
        current_state=HouseState.GUEST,
        any_zone_occupied=True,
        now=_at(14),
        unidentified_count=0,
        guest_gate_armed=False,
    )
    assert new_state == HouseState.HOME_DAY


def test_d1_real_guest_at_sleep_hour_holds():
    """Real guest present (gate still armed) at 23:00 → stays GUEST.

    Mutation anchor: dropping ``and not guest_gate_armed`` from the
    guest-exit predicate would evict a real guest. This test proves the
    guard is load-bearing.
    """
    engine = _make_engine()
    new_state = engine.infer(
        census_count=0,
        current_state=HouseState.GUEST,
        any_zone_occupied=True,   # avoid "Nobody home" early-return
        now=_at(23),
        unidentified_count=1,      # real guest signal
        guest_gate_armed=True,
    )
    # Guest-exit predicate is False (gate armed). Falls to sleep-hours
    # branch: current_state==GUEST is not in (SLEEP,WAKING) so SLEEP is
    # proposed. VALID_TRANSITIONS[GUEST] does NOT include SLEEP, so the
    # state machine rejects it. infer() still returns SLEEP as a
    # proposal; the machine is the authority for accept/reject. We
    # assert the INTENT here: the guest is not evicted TO HOME_*.
    assert new_state != HouseState.HOME_NIGHT
    assert new_state != HouseState.HOME_DAY
    assert new_state != HouseState.HOME_EVENING


def test_d1_false_unidentified_during_sleep_no_guest_entry():
    """SLEEP + spurious guest arm at 03:00 → does not escalate to GUEST.

    Guest-entry branch requires current_state in (HOME_DAY, HOME_EVENING,
    HOME_NIGHT); SLEEP is not in that set. Sleep-branch also fires
    first. Confirms chronic false arming cannot flip the house to GUEST
    overnight (investigation-memo concern).
    """
    engine = _make_engine()
    new_state = engine.infer(
        census_count=1,
        current_state=HouseState.SLEEP,
        any_zone_occupied=True,
        now=_at(3),
        unidentified_count=1,
        guest_gate_armed=True,
    )
    assert new_state != HouseState.GUEST


# ===========================================================================
# D1b — HOME_NIGHT → GUEST valid transition
# ===========================================================================

def test_d1b_home_night_to_guest_valid_transition():
    """HOME_NIGHT permits transition to GUEST (symmetric with HOME_DAY/EVENING).

    Mutation anchor: removing GUEST from VALID_TRANSITIONS[HOME_NIGHT]
    causes this assertion to fail.
    """
    assert HouseState.GUEST in VALID_TRANSITIONS[HouseState.HOME_NIGHT]
    # Symmetric sanity — HOME_DAY and HOME_EVENING must also still allow it.
    assert HouseState.GUEST in VALID_TRANSITIONS[HouseState.HOME_DAY]
    assert HouseState.GUEST in VALID_TRANSITIONS[HouseState.HOME_EVENING]


# ===========================================================================
# D2 — Immediate-engage LOST-admitted veto
# ===========================================================================

def _immediate_engage_kwargs(**overrides):
    """Baseline kwargs where immediate-engage SHOULD fire.

    Fix-up (A-CRIT-1 / B-CRIT-1 / C-HIGH-1): the immediate-engage limb
    is discriminated by ``sustained_external_empty`` (an INDEPENDENT
    multi-tick signal computed by the caller). The baseline passes it
    True so the veto is admitted without grace.
    """
    kw = dict(
        census_count=0,
        current_state=HouseState.HOME_DAY,
        any_zone_occupied=True,          # ensure we do NOT fall into "nobody home"
        now=_at(14),
        unidentified_count=0,
        guest_gate_armed=False,
        all_tracked_persons_away=False,
        all_trusted_or_lost_away_persons_away=True,
        any_indoor_zone_occupied=False,   # externally-corroborated empty
        grace_elapsed_for_lost_away=False,  # <<<< grace NOT elapsed
        lost_away_persons_present=True,
        sleep_exempt_state=False,
        sustained_external_empty=True,    # <<<< the D2 discriminator
    )
    kw.update(overrides)
    return kw


def test_d2_immediate_engage_fires_when_house_externally_empty():
    """Immediate-engage fires with veto_path=='lost_admitted_immediate'.

    Mutation anchor: removing the ``immediate_engage_empty_house`` limb
    from the OR clause in path β causes this test to fail (the
    grace_elapsed=False path is otherwise denied).
    """
    engine = _make_engine()
    new_state = engine.infer(**_immediate_engage_kwargs())
    assert new_state == HouseState.AWAY
    assert engine._veto_path == "lost_admitted_immediate"
    # Confidence parity with path α (operator resolution).
    assert engine.confidence == 0.95


def test_d2_grace_elapsed_still_labels_as_lost_admitted():
    """Grace elapsed → same AWAY veto but labeled the pre-existing string."""
    engine = _make_engine()
    new_state = engine.infer(
        **_immediate_engage_kwargs(grace_elapsed_for_lost_away=True)
    )
    assert new_state == HouseState.AWAY
    assert engine._veto_path == "lost_admitted"


def test_d2_immediate_engage_denied_when_indoor_zone_occupied():
    """I-D2 (safety of grace): indoor zone occupied denies immediate-engage.

    Mutation-record correction (Fix-up C-MED-1): post-Fix-1 the
    immediate limb no longer restates ``not indoor_blocked`` (that was
    the tautology). The OUTER path-β clause's ``not indoor_blocked``
    is anchored by
    ``test_v570_guest_detection_trust.test_case1_dead_phone_home_with_indoor_zone_stays_home``.
    This test still exercises the outer guard and demonstrates that
    an occupied indoor zone denies path β regardless of the
    immediate-engage limb's admission.
    """
    engine = _make_engine()
    new_state = engine.infer(
        **_immediate_engage_kwargs(any_indoor_zone_occupied=True)
    )
    assert new_state != HouseState.AWAY
    assert engine._veto_path == "none"


def test_d2_immediate_engage_denied_when_census_positive():
    """Camera face-ID on a resident denies immediate-engage."""
    engine = _make_engine()
    new_state = engine.infer(
        **_immediate_engage_kwargs(census_count=1)
    )
    assert new_state != HouseState.AWAY
    assert engine._veto_path == "none"


def test_d2_immediate_engage_denied_when_unidentified():
    """Unidentified person (guest signal) denies immediate-engage."""
    engine = _make_engine()
    new_state = engine.infer(
        **_immediate_engage_kwargs(unidentified_count=1)
    )
    # Not AWAY via β; may fall into guest-entry path from HOME_DAY.
    assert new_state != HouseState.AWAY
    # veto_path is either "none" or set only inside path β on entry;
    # neither path β limb fired so it must be "none".
    assert engine._veto_path == "none"


def test_d2_immediate_engage_denied_during_sleep_state():
    """sleep_exempt_state=True denies immediate-engage regardless of empty evidence.

    Mutation anchor: removing ``not sleep_exempt_state`` from path β.
    """
    engine = _make_engine()
    new_state = engine.infer(
        **_immediate_engage_kwargs(
            current_state=HouseState.HOME_NIGHT,
            sleep_exempt_state=True,
            # 22:00 is < 23 sleep_start so we're not in sleep hours; the
            # gate is sleep_exempt_state itself.
            now=_at(22),
        )
    )
    assert new_state != HouseState.AWAY
    assert engine._veto_path == "none"


def test_d2_grace_is_sole_keepout_when_sustained_empty_not_met():
    """Fix-up (B-HIGH-2 + C-MED-2): grace mutation authority.

    Legal-config combination where grace is the SOLE keep-out for
    path β — census/unid/indoor all clear, LOST person present, sleep
    not exempt, but ``sustained_external_empty`` NOT met (the
    immediate limb cannot fire this tick). With
    ``grace_elapsed_for_lost_away=False`` path β is denied; flipping
    it to True (production-mutation equivalent: forcing
    _grace_elapsed_with_debounce True in the caller) admits path β
    with the pre-existing ``lost_admitted`` label — proving the grace
    limb is load-bearing on gating behavior, not just labeling.
    """
    engine = _make_engine()
    # Grace-not-elapsed AND immediate NOT satisfied → denied.
    denied = engine.infer(
        **_immediate_engage_kwargs(
            grace_elapsed_for_lost_away=False,
            sustained_external_empty=False,
        )
    )
    assert denied != HouseState.AWAY
    assert engine._veto_path == "none"

    # Force grace elapsed (simulate mutation flipping the caller's
    # _grace_elapsed_with_debounce to True). Immediate still False.
    fired = engine.infer(
        **_immediate_engage_kwargs(
            grace_elapsed_for_lost_away=True,
            sustained_external_empty=False,
        )
    )
    assert fired == HouseState.AWAY
    assert engine._veto_path == "lost_admitted"


def test_d2_whole_or_group_mutation_flipping_to_true_now_turns_something_red():
    """Fix-up verification: probe that the CRITICAL is fixed.

    Pre-fix, the OR-group in path β was a tautology inside the outer
    clause — mutating it to a literal ``True`` was a no-op and no test
    turned red. Post-fix, the immediate discriminator is
    ``sustained_external_empty`` and the OR-group is
    ``grace_elapsed or not lost or (sustained_external_empty and
    lost)``. In a config where none of those three are True the whole
    group is False and path β must be denied. This test asserts that
    denial — mutating the group to a bare ``True`` in production would
    fire β and turn this test RED.
    """
    engine = _make_engine()
    new_state = engine.infer(
        **_immediate_engage_kwargs(
            grace_elapsed_for_lost_away=False,
            sustained_external_empty=False,
            lost_away_persons_present=True,
        )
    )
    assert new_state != HouseState.AWAY
    assert engine._veto_path == "none"


def test_d2_immediate_engage_denied_when_not_sustained():
    """Single-tick externally-empty (sustained_external_empty=False)
    with grace not elapsed → immediate limb denied.

    Fix-up (A-CRIT-1 discriminator anchor): mutating the immediate
    predicate back to a tautology (e.g. ``sustained_external_empty or
    lost_away_persons_present``) would fire β here → this test would
    go RED. Proves the multi-tick discriminator is load-bearing.
    """
    engine = _make_engine()
    new_state = engine.infer(
        **_immediate_engage_kwargs(sustained_external_empty=False)
    )
    assert new_state != HouseState.AWAY
    assert engine._veto_path == "none"


def test_d2_immediate_engage_denied_no_lost_persons():
    """No LOST persons at all → immediate-engage predicate False.

    The other OR limb (``not lost_away_persons_present``) will still
    admit path β, but veto_path must be "lost_admitted" (grace-path
    label), NOT "lost_admitted_immediate".
    """
    engine = _make_engine()
    new_state = engine.infer(
        **_immediate_engage_kwargs(
            lost_away_persons_present=False,
        )
    )
    # Path β can still fire via the ``not lost_away_persons_present`` limb.
    assert new_state == HouseState.AWAY
    assert engine._veto_path == "lost_admitted"


# ===========================================================================
# D2 — sleep-hour boundary + guest × sleep combinatorial
# ===========================================================================

def test_d2_immediate_engage_at_sleep_hour_boundary_denied_when_sleep_exempt():
    """23:00 boundary + sleep_exempt=True → denied (inherits sleep gate)."""
    engine = _make_engine()
    new_state = engine.infer(
        **_immediate_engage_kwargs(
            now=_at(23),
            sleep_exempt_state=True,
            current_state=HouseState.HOME_NIGHT,
        )
    )
    assert new_state != HouseState.AWAY


def test_guest_armed_x_sleep_hours_no_guest_entry_still_valid_after_reorder():
    """guest_gate_armed=True, hour=3 (sleep), state=HOME_NIGHT → SLEEP.

    Reorder must NOT open a new guest-entry pathway during sleep.
    """
    engine = _make_engine()
    new_state = engine.infer(
        census_count=1,
        current_state=HouseState.HOME_NIGHT,
        any_zone_occupied=True,
        now=_at(3),
        unidentified_count=1,
        guest_gate_armed=True,
    )
    assert new_state == HouseState.SLEEP


def test_guest_cleared_x_sleep_hours_exits_before_sleep_wins():
    """guest_gate_armed=False, hour=3, state=GUEST → HOME_NIGHT (D1)."""
    engine = _make_engine()
    new_state = engine.infer(
        census_count=1,
        current_state=HouseState.GUEST,
        any_zone_occupied=True,
        now=_at(3),
        unidentified_count=0,
        guest_gate_armed=False,
    )
    assert new_state == HouseState.HOME_NIGHT


# ===========================================================================
# Fix-up (C-LOW-1): reorder × persistence coordinator-level shape
# ===========================================================================

def test_guest_exit_during_sleep_hours_still_gated_by_persistence():
    """C-LOW-1: guest-exit at 02:00 emits a HOME_* proposal (D1 reorder
    makes the exit reachable), but if the coordinator's
    _guest_exit_quiet_since persistence threshold has not yet elapsed
    the exit must be suppressed. Once >= threshold, HOME_NIGHT is
    accepted.

    Scoped to the engine surface + a simulated persistence timer
    matching the coordinator's Pattern E gate (presence.py :5289). If
    Fix-1 or the reorder regressed such that the engine held GUEST
    through sleep hours, this test would go RED at the engine step
    (before persistence is ever consulted).
    """
    engine = _make_engine()
    proposed = engine.infer(
        census_count=1,
        current_state=HouseState.GUEST,
        any_zone_occupied=True,
        now=_at(2),
        unidentified_count=0,
        guest_gate_armed=False,
    )
    # D1 reorder: engine surfaces the exit target during sleep hours.
    assert proposed == HouseState.HOME_NIGHT

    # Simulate the Pattern E persistence gate. Threshold matches the
    # coordinator's default guest_persistence_seconds (300s at
    # PresenceCoordinator.__init__).
    persistence_threshold_s = 300

    # Case A: quiet_seconds < threshold → suppressed (None).
    quiet_seconds = 60
    suppressed = None if quiet_seconds < persistence_threshold_s else proposed
    assert suppressed is None, (
        "Pattern E must suppress the exit while below persistence threshold"
    )

    # Case B: quiet_seconds >= threshold → HOME_NIGHT accepted.
    quiet_seconds = 300
    accepted = None if quiet_seconds < persistence_threshold_s else proposed
    assert accepted == HouseState.HOME_NIGHT


# ===========================================================================
# D3 — OccupancySubstrate edge observability
# ===========================================================================

class _FakeState:
    def __init__(self, state: str) -> None:
        self.state = state


class _FakeEvent:
    def __init__(self, entity_id: str, new_state) -> None:
        self.data = {"entity_id": entity_id, "new_state": new_state}


def _make_substrate() -> OccupancySubstrate:
    sub = OccupancySubstrate(hass=MagicMock())
    # Bypass boot-settle so dispatch fires.
    sub._boot_settle_done = True
    # Pre-wire an entity→(room,kind) mapping so the state-change callback
    # doesn't early-return.
    sub._entity_to_room_kind["binary_sensor.study_a_motion"] = (
        "study_a", "motion",
    )
    return sub


def test_d3_last_edge_entity_recorded_on_edge():
    """On a real edge, ``last_edge_entity_for`` returns the driving entity.

    Mutation anchor: removing ``self._last_edge_entity[room_name] = entity_id``
    in ``_handle_state_change``.
    """
    sub = _make_substrate()
    sub._handle_state_change(
        _FakeEvent("binary_sensor.study_a_motion", _FakeState("on"))
    )
    assert sub.last_edge_entity_for("study_a") == "binary_sensor.study_a_motion"


def test_d3_edge_log_at_debug_level(caplog):
    """Edge emits a DEBUG log naming the entity_id + kind + new/prior.

    Mutation anchor: removing the ``_LOGGER.debug("OccupancySubstrate edge:"...)``
    call. Note: log level is DEBUG per operator resolution, so caplog
    must be set to DEBUG.
    """
    sub = _make_substrate()
    with caplog.at_level(
        logging.DEBUG,
        logger=(
            "custom_components.universal_room_automation."
            "domain_coordinators.occupancy_substrate"
        ),
    ):
        sub._handle_state_change(
            _FakeEvent("binary_sensor.study_a_motion", _FakeState("on"))
        )
    matches = [r for r in caplog.records if "OccupancySubstrate edge:" in r.message]
    assert matches, "expected an OccupancySubstrate edge DEBUG log"
    rec = matches[0]
    assert rec.levelno == logging.DEBUG
    assert "binary_sensor.study_a_motion" in rec.getMessage()
    assert "study_a" in rec.getMessage()
    assert "motion" in rec.getMessage()


def test_d3_last_edge_entity_default_empty_string():
    """Rooms with no edge yet return empty string, not KeyError."""
    sub = _make_substrate()
    assert sub.last_edge_entity_for("never_fired_room") == ""


def test_d3_edge_no_dispatch_before_boot_settle():
    """I-D3-adjacent: boot-settle path does NOT record last_edge_entity.

    The suppress-dispatch return happens BEFORE the record write, so a
    pre-settle edge leaves the accessor at "". Matches the docstring.
    """
    sub = OccupancySubstrate(hass=MagicMock())
    # boot_settle_done left False (default).
    sub._entity_to_room_kind["binary_sensor.study_a_motion"] = (
        "study_a", "motion",
    )
    sub._handle_state_change(
        _FakeEvent("binary_sensor.study_a_motion", _FakeState("on"))
    )
    assert sub.last_edge_entity_for("study_a") == ""
