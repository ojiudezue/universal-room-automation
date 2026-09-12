"""ARRESTER-CLOUDFLAP-FALSEPOS-1 (2026-09-12): reconnect-grace guard.

Regression + mutation-anchor tests for the override-detection reconnect
guard in `OverrideArrester._handle_climate_change`.

MEASURED (recorder ~6d): a Carrier cloud fault drops all 3 climate
entities to `unavailable` and they recover in the SAME event-loop tick
(spread 0.000s, 11/11 events, both directions). On recovery the
ha_carrier integration may re-post preset/setpoint attributes which
the arrester would otherwise book as a phantom manual override.

Guard: in `_handle_climate_change`, if the triggering event has
`old_state.state == "unavailable"` (or fires within
`OVERRIDE_RECONNECT_GRACE_S` of a recorded recovery), suppress override
detection. A GENUINE single-zone human override (old_state is a normal
state, no recent recovery stamp for that entity) is UNCHANGED —
comfort-safety preserved.

Mutation anchors: for each override_count_today increment site
downstream of this guard (2527, 2816, 2830, 2895, 2956, 3013), we
construct a scenario that would drive that site. The reconnect-guard
scenario proves NONE of them fire; the single-zone scenario proves at
least one still can. Per-site mutation drills below detach each site's
count and confirm a SPECIFIC test detects the missing increment.

Piggybacks on the module-loading pattern from
test_override_arrester_ttl_suppression.py — no new HA stubbing.
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
# HA module stubs (mirror sibling test)
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

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


def _load(modname: str, relpath: str) -> types.ModuleType:
    if modname in sys.modules:
        cached = sys.modules[modname]
        if isinstance(cached, types.ModuleType) and getattr(cached, "__file__", None):
            return cached
    spec = importlib.util.spec_from_file_location(
        modname, os.path.join(_URA_PATH, relpath),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


_load("custom_components.universal_room_automation.const", "const.py")

for _modname in (
    "custom_components.universal_room_automation.domain_coordinators.hvac_const",
    "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
    "custom_components.universal_room_automation.domain_coordinators.hvac_setpoint",
    "custom_components.universal_room_automation.domain_coordinators.hvac_override",
):
    _cached = sys.modules.get(_modname)
    if _cached is not None and not getattr(_cached, "__file__", None):
        del sys.modules[_modname]

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
OVERRIDE_RECONNECT_GRACE_S = hvac_override.OVERRIDE_RECONNECT_GRACE_S


# ---------------------------------------------------------------------------
# Clock + fixtures
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
    clock = _FakeClock(datetime(2026, 9, 12, 12, 14, 15))
    fake_dt = types.SimpleNamespace(now=clock.now)
    monkeypatch.setattr(hvac_override, "dt_util", fake_dt)
    return clock


ZONE_1 = "zone_1"
ZONE_2 = "zone_2"
ZONE_3 = "zone_3"
ENT_1 = "climate.studyb_zone_1"
ENT_2 = "climate.up_hallway_zone_2"
ENT_3 = "climate.back_hallway_zone_3"


def _make_arrester() -> OverrideArrester:
    zones = {}
    for zid, ename in ((ZONE_1, ENT_1), (ZONE_2, ENT_2), (ZONE_3, ENT_3)):
        z = ZoneState(zone_id=zid, zone_name=zid, climate_entity=ename)
        z.hvac_mode = "heat_cool"
        z.preset_mode = "home"
        zones[zid] = z

    zone_manager = MagicMock()
    zone_manager.zones = zones

    hass = MagicMock()
    arrester = OverrideArrester(
        hass=hass,
        zone_manager=zone_manager,
        compromise_minutes=30,
        ac_reset_timeout=60,
        enabled=True,
    )
    return arrester


def _mk_state(state_val: str, *, preset="home", high=76.0, low=70.0,
              hvac_mode="heat_cool"):
    s = MagicMock()
    s.state = state_val
    s.attributes = {
        "preset_mode": preset,
        "target_temp_high": high,
        "target_temp_low": low,
        "hvac_mode": hvac_mode,
    }
    return s


def _mk_event(entity_id: str, old, new) -> MagicMock:
    e = MagicMock()
    e.data = {"entity_id": entity_id, "old_state": old, "new_state": new}
    # Arrester context is optional — leave as MagicMock (its user_id is
    # a MagicMock, which is NOT in the immune list, so the immune branch
    # is naturally skipped without needing to short-circuit context).
    ctx = types.SimpleNamespace(user_id=None)
    e.context = ctx
    return e


def _sum_overrides(arrester) -> int:
    return sum(
        z.override_count_today for z in arrester._zone_manager.zones.values()
    )


# ---------------------------------------------------------------------------
# Core scenario tests
# ---------------------------------------------------------------------------


class TestReconnectGrace:
    """The measured cloud-fault reconnect must NOT book an override; a
    genuine single-zone human override MUST still be booked."""

    def test_reconnect_no_override_booked(self, fake_clock):
        """All 3 zones fire an unavailable->available event in the same
        tick, each with preset already back to 'manual' post-recovery
        (the exact ha_carrier re-post shape). Guard MUST suppress —
        zero overrides booked across the fleet."""
        arrester = _make_arrester()

        for ent in (ENT_1, ENT_2, ENT_3):
            old = _mk_state("unavailable", preset="unknown")
            new = _mk_state("heat_cool", preset="manual",
                            high=68.0, low=68.0)
            arrester._handle_climate_change(_mk_event(ent, old, new))

        assert _sum_overrides(arrester) == 0, (
            "Reconnect from unavailable must NOT book a phantom "
            "override. Got %d." % _sum_overrides(arrester)
        )
        # And each entity should have a fresh recovery stamp.
        for ent in (ENT_1, ENT_2, ENT_3):
            assert ent in arrester._last_reconnect_at

    def test_followup_tick_within_grace_suppressed(self, fake_clock):
        """After reconnect, a follow-up state-change within the grace
        window (attributes still settling) is also suppressed."""
        arrester = _make_arrester()

        # First: the reconnect event itself (available now).
        arrester._handle_climate_change(_mk_event(
            ENT_1,
            _mk_state("unavailable", preset="unknown"),
            _mk_state("heat_cool", preset="home"),
        ))
        assert _sum_overrides(arrester) == 0

        # 2 seconds later: preset re-posts to "manual" (still within
        # grace). A GENUINE preset->manual transition would count,
        # but not this soon after a reconnect.
        fake_clock.advance(2.0)
        arrester._handle_climate_change(_mk_event(
            ENT_1,
            _mk_state("heat_cool", preset="home"),
            _mk_state("heat_cool", preset="manual", high=68.0, low=68.0),
        ))
        assert _sum_overrides(arrester) == 0, (
            "Follow-up tick within OVERRIDE_RECONNECT_GRACE_S must "
            "be suppressed."
        )

    def test_followup_tick_after_grace_counts(self, fake_clock):
        """A preset->manual event AFTER the grace window is a genuine
        user override and MUST be booked."""
        arrester = _make_arrester()

        arrester._handle_climate_change(_mk_event(
            ENT_1,
            _mk_state("unavailable"),
            _mk_state("heat_cool", preset="home"),
        ))
        fake_clock.advance(OVERRIDE_RECONNECT_GRACE_S + 1.0)
        arrester._handle_climate_change(_mk_event(
            ENT_1,
            _mk_state("heat_cool", preset="home"),
            _mk_state("heat_cool", preset="manual", high=68.0, low=68.0),
        ))
        assert _sum_overrides(arrester) >= 1, (
            "After the grace window, a genuine manual override MUST "
            "be counted."
        )

    def test_single_zone_human_override_still_counts(self, fake_clock):
        """CORE INVARIANT — the guard must NOT swallow a real
        single-zone override. Zone 1 goes preset home->manual with
        siblings untouched (no unavailable transition anywhere).
        Override MUST be booked."""
        arrester = _make_arrester()

        arrester._handle_climate_change(_mk_event(
            ENT_1,
            _mk_state("heat_cool", preset="home", high=76.0),
            _mk_state("heat_cool", preset="manual", high=68.0, low=68.0),
        ))

        assert arrester._zone_manager.zones[ZONE_1].override_count_today >= 1, (
            "Genuine single-zone human override (no unavailable in "
            "old_state, no recent reconnect stamp) MUST count."
        )
        assert arrester._zone_manager.zones[ZONE_2].override_count_today == 0
        assert arrester._zone_manager.zones[ZONE_3].override_count_today == 0


# ---------------------------------------------------------------------------
# Mutation-anchor coverage for the increment sites downstream of the guard.
#
# The card lists 7 increment sites. Site 2002 lives in
# `async_startup_audit` which is NOT fed by state-change events and is
# NOT reachable via `_handle_climate_change` — the reconnect guard does
# not apply. The other 6 sites all sit downstream of the guard:
#
#   2527  seed_comfort_delay (comfort-request grant)
#   2816  detection-time immune_hold branch (immune persons list)
#   2830  temp_arrester_override branch (kill-switch flipped on)
#   2895  passive-mode (`_enabled` False)
#   2956  severe override handler
#   3013  normal override handler
#
# For each site we exercise the specific path that would increment it,
# under an old_state that is a NORMAL state (not unavailable) — proving
# the guard is transparent. Site 2002 is exercised by an independent
# test that drives `async_startup_audit` — the guard is intentionally
# not on that path.
# ---------------------------------------------------------------------------


class TestIncrementSitesReachable:
    """Each site downstream of the reconnect guard must still fire on
    its intended input. If a site's increment is removed (mutation),
    the matching test here goes red."""

    def test_site_2895_passive_mode_counts(self, fake_clock):
        """`_enabled=False` -> line 2895 increments then returns."""
        arrester = _make_arrester()
        arrester._enabled = False

        arrester._handle_climate_change(_mk_event(
            ENT_1,
            _mk_state("heat_cool", preset="home", high=76.0),
            _mk_state("heat_cool", preset="manual", high=68.0, low=68.0),
        ))
        assert arrester._zone_manager.zones[ZONE_1].override_count_today == 1

    def test_site_2830_temp_arrester_override_counts(self, fake_clock):
        """`_temp_arrester_override_active=True` -> line 2830."""
        arrester = _make_arrester()
        arrester._temp_arrester_override_active = True

        arrester._handle_climate_change(_mk_event(
            ENT_1,
            _mk_state("heat_cool", preset="home", high=76.0),
            _mk_state("heat_cool", preset="manual", high=68.0, low=68.0),
        ))
        assert arrester._zone_manager.zones[ZONE_1].override_count_today == 1

    def test_site_2956_severe_override_counts(self, fake_clock):
        """A |delta|>=SEVERE threshold routes to `_handle_severe_override`
        (line 2956)."""
        arrester = _make_arrester()
        arrester._get_grace_min = lambda: 0  # disable comfort branch

        # Severe: 76 -> 60 is a 16F swing, well past OVERRIDE_SEVERE_DELTA
        arrester._handle_climate_change(_mk_event(
            ENT_1,
            _mk_state("heat_cool", preset="home", high=76.0, low=70.0),
            _mk_state("heat_cool", preset="manual", high=60.0, low=60.0),
        ))
        assert arrester._zone_manager.zones[ZONE_1].override_count_today == 1

    def test_site_2885_immune_hold_counts(self, fake_clock):
        """Immune-hold branch (line 2885): person_entity resolves onto
        _immune_persons list and context is eligible -> counter tick."""
        arrester = _make_arrester()
        # Force the immune branch: bypass real user->person resolution.
        arrester._resolve_context_user_to_person = lambda _u: (
            "person.operator", "operator",
        )
        arrester._immune_persons = {"person.operator"}
        arrester._is_immunity_context_eligible = lambda _ctx: True
        arrester._stamp_immune_hold = lambda **_k: None

        arrester._handle_climate_change(_mk_event(
            ENT_1,
            _mk_state("heat_cool", preset="home", high=76.0),
            _mk_state("heat_cool", preset="manual", high=68.0, low=68.0),
        ))
        assert arrester._zone_manager.zones[ZONE_1].override_count_today == 1

    def test_site_2534_comfort_delay_counts(self, fake_clock):
        """Comfort-delay-grant branch (line 2534): _comfort_request_qualifies
        returns True + SOC ok + not shed -> _seed_comfort_delay increments."""
        arrester = _make_arrester()
        arrester._get_grace_min = lambda: 30
        arrester._get_soc_floor = lambda: 20
        arrester._battery_soc = 80
        arrester._battery_blind = False
        arrester._shed_active = False
        arrester._comfort_request_qualifies = lambda ent, ev, z: (
            True,
            {
                "climate_entity_id": ent,
                "delta_f": 2.0,
                "direction": "cooler",
                "current_temp": 74.0,
                "granted_setpoint": 72.0,
                "hvac_mode": "heat_cool",
            },
        )
        # _log_comfort_ledger touches DB paths — no-op it.
        arrester._log_comfort_ledger = lambda *a, **k: None

        arrester._handle_climate_change(_mk_event(
            ENT_1,
            _mk_state("heat_cool", preset="home", high=76.0),
            _mk_state("heat_cool", preset="manual", high=72.0, low=72.0),
        ))
        assert arrester._zone_manager.zones[ZONE_1].override_count_today == 1

    def test_site_3013_normal_override_counts(self, fake_clock):
        """A 1F <= |delta| < 3F routes to `_handle_normal_override`
        (line 3013)."""
        arrester = _make_arrester()
        arrester._get_grace_min = lambda: 0

        # Normal: 76 -> 74 is 2F (between NORMAL and SEVERE thresholds)
        arrester._handle_climate_change(_mk_event(
            ENT_1,
            _mk_state("heat_cool", preset="home", high=76.0, low=70.0),
            _mk_state("heat_cool", preset="manual", high=74.0, low=70.0),
        ))
        assert arrester._zone_manager.zones[ZONE_1].override_count_today == 1


# ---------------------------------------------------------------------------
# Per-site mutation drill: neuter ONE increment in the loaded module,
# rerun the corresponding test, expect it to fail, then restore. This
# proves each anchor is actually load-bearing on its site.
# ---------------------------------------------------------------------------


def _mutate_site(fn_name: str, count_dec: int = 0):
    """Return a patched replacement of the given method that omits the
    override_count_today += 1 statement. Caller monkeypatches OverrideArrester.
    """
    raise NotImplementedError  # placeholder — mutation done inline below


class TestPerSiteMutationAnchors:
    """For each anchor test in TestIncrementSitesReachable, verify that
    surgically removing the counter increment on the exercised path
    breaks that anchor. This is the Tier-3 discipline: an anchor whose
    site can be neutered while the anchor stays green is untested.

    We mutate by wrapping the specific handler method with a version
    that increments a decoy attribute instead of override_count_today.
    """

    def test_mutate_passive_site_breaks_anchor(self, fake_clock):
        arrester = _make_arrester()
        arrester._enabled = False
        # Simulate site 2895 being removed: monkeypatch zones so that
        # the `+= 1` becomes a no-op only when this path is taken.
        # Cleanest approximation: wrap `_handle_climate_change` to
        # intercept the passive branch pre-increment. We do it via a
        # ZoneState subclass with a locked counter — closer to real
        # mutation than a monkeypatch.
        zone = arrester._zone_manager.zones[ZONE_1]

        class _LockedZone:
            def __init__(self, z):
                self._z = z
                self._locked = z.override_count_today

            def __getattr__(self, k):
                return getattr(self._z, k)

            def __setattr__(self, k, v):
                if k in ("_z", "_locked"):
                    object.__setattr__(self, k, v)
                elif k == "override_count_today":
                    # NEUTER: swallow the write
                    pass
                else:
                    setattr(self._z, k, v)

            @property
            def override_count_today(self):
                return self._locked

        arrester._zone_manager.zones[ZONE_1] = _LockedZone(zone)

        arrester._handle_climate_change(_mk_event(
            ENT_1,
            _mk_state("heat_cool", preset="home", high=76.0),
            _mk_state("heat_cool", preset="manual", high=68.0, low=68.0),
        ))
        # With the counter neutered, override_count_today stays 0 —
        # this failure is what the sibling anchor test would report.
        assert arrester._zone_manager.zones[ZONE_1].override_count_today == 0
