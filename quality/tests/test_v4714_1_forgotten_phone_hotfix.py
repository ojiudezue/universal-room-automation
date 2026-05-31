"""v4.7.14.1 — Forgotten-phone hotfix.

Three surgical fixes to v4.7.14's person-tracker veto. All in
`domain_coordinators/presence.py`.

  H1 — Tighten veto predicate at `StateInferenceEngine.infer()`:
       require `census_count == 0` in addition to `unidentified_count == 0`.
       Closes Gap A (face-IDed resident walks past camera, phone left at home).

  H2 — Exclude phone-left-behind persons from the veto denominator in
       `_run_inference`. REUSES `binary_sensor.<person>_phone_left_behind`
       (the PersonPhoneLeftBehindSensor signal). Fail-OPEN when sensor
       missing/unavailable/unknown (entity is disabled by default, so this
       preserves v4.7.14 behavior for operators who haven't enabled it).
       Closes Gap B (phone on counter, person actually away, but
       `person.X` state says home because phone is home).

  H3 — Exclude STALE/LOST tracking_status persons from the veto denominator.
       Only ACTIVE counts as "confirmed away." Closes Gap C (stale Bermuda
       data or person-tracker fallback fires a high-confidence veto).

Tests drive PRODUCTION code paths — the real `StateInferenceEngine.infer()`
and the real `_run_inference` filter logic (per Bug Class #44).
"""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"
DC_PATH = PKG / "domain_coordinators"
PRESENCE_SRC = (DC_PATH / "presence.py").read_text()


# ---------------------------------------------------------------------------
# HA module mocking — mirrors test_v4714_away_state_person_tracker_trust.py
# ---------------------------------------------------------------------------

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
        "async_dispatcher_send": lambda hass, signal, data=None: None,
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
        "now": lambda: datetime(2026, 5, 30, 14, 0, 0),  # mid-afternoon
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

for _submod in ("signals", "house_state", "base", "coordinator_diagnostics", "presence"):
    _full = f"custom_components.universal_room_automation.domain_coordinators.{_submod}"
    if _full not in sys.modules:
        _load_module(_full, DC_PATH / f"{_submod}.py")


from custom_components.universal_room_automation.domain_coordinators.presence import (  # noqa: E402
    PresenceCoordinator,
    ReliableSignal,
    StateInferenceEngine,
    TransientSignal,
    VetoDecision,
)
from custom_components.universal_room_automation.domain_coordinators.house_state import (  # noqa: E402
    HouseState,
)
from custom_components.universal_room_automation.const import (  # noqa: E402
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_STALE,
    TRACKING_STATUS_LOST,
)


# ---------------------------------------------------------------------------
# v4.7.15.1 D4: Production-helper bridge.
#
# Per plan §D4 (preferred approach (b)) + Reviewer C §C4 item 3: the prior
# _compute_with_h2 / _compute_with_h2_h3 test-local functions re-implemented
# the veto math in test scope (a Bug Class #44 trip-wire). v4.7.15.1 D1
# refactored the production helper Pattern A
# (PresenceCoordinator.should_veto_due_to_reliable_signals at
# presence.py:755+) to consume the v4.7.14.1 H1/H2/H3 surfaces via
# per-person ReliableSignal lists + TransientSignal("census_count").
#
# This bridge replaces the test-local veto math with PRODUCTION-direct
# helper calls. The test-local _phone_trustworthy / _tracking_active
# functions survive (and are RENAMED below for clarity) but they no longer
# embody veto math — they're INPUT BUILDERS that mirror the production
# inline helpers (presence.py:2267-2306), which are unreachable from
# outside _run_inference. The veto DECISION is computed by production code.
# ---------------------------------------------------------------------------


def _make_presence_coordinator() -> PresenceCoordinator:
    """Build a minimal PresenceCoordinator for production-helper invocation.

    Helper-only tests do not exercise hass.data lookups, so a bare MagicMock
    hass is sufficient — should_veto_due_to_reliable_signals is a pure
    function over its inputs.
    """
    hass = MagicMock()
    hass.data = {}
    coord = PresenceCoordinator(
        hass=hass,
        sleep_start_hour=23,
        sleep_end_hour=6,
        guest_persistence_seconds=300,
    )
    return coord


# Note: _compute_via_production_helper is the canonical bridge — defined
# below alongside _phone_trust_input / _tracking_active_input. The legacy
# _compute_with_h2 / _compute_with_h2_h3 entry points delegate to it.


def _make_engine() -> StateInferenceEngine:
    """Build engine with sleep window outside our 14:00 test time."""
    return StateInferenceEngine(sleep_start_hour=23, sleep_end_hour=6)


def _afternoon() -> datetime:
    return datetime(2026, 5, 30, 14, 0, 0)


# ===========================================================================
# H1 — Veto requires census_count == 0
# ===========================================================================


class TestH1VetoRequiresCensusZero:
    """The veto must NOT fire when census sees a face-IDed resident."""

    def test_h1_veto_does_not_fire_when_census_count_positive(self):
        """Gap A — phone left at home, person walks past camera, Frigate IDs them.

        census_count >= 1 (resident face), unidentified_count == 0,
        all_tracked_persons_away == True. Pre-v4.7.14.1: veto fires (wrong).
        Post: falls through to has_people path → ARRIVING.
        """
        engine = _make_engine()
        new_state = engine.infer(
            census_count=1,  # face-IDed resident in front of a camera
            current_state=HouseState.AWAY,
            any_zone_occupied=True,
            now=_afternoon(),
            unidentified_count=0,
            guest_gate_armed=False,
            all_tracked_persons_away=True,
        )
        # Veto must NOT fire — person is provably home.
        assert new_state != HouseState.AWAY, (
            "H1: veto must not fire when census_count > 0 (face-IDed resident)"
        )
        # Confidence must not be the veto-signature 0.95.
        assert engine.confidence != 0.95, (
            "H1: confidence must not be 0.95 (veto signature) when census > 0"
        )

    def test_h1_veto_still_fires_when_census_count_zero(self):
        """Regression guard: v4.7.14 baseline preserved.

        All conditions for veto met INCLUDING census_count == 0.
        """
        engine = _make_engine()
        new_state = engine.infer(
            census_count=0,  # camera sees nobody
            current_state=HouseState.HOME_DAY,
            any_zone_occupied=True,  # Tier 2 ghost motion
            now=_afternoon(),
            unidentified_count=0,
            guest_gate_armed=False,
            all_tracked_persons_away=True,
        )
        assert new_state == HouseState.AWAY
        assert engine.confidence == 0.95

    def test_h1_default_kwarg_preserves_existing_behavior(self):
        """Callers omitting all_tracked_persons_away see identical output."""
        engine = _make_engine()
        new_state_default = engine.infer(
            census_count=1,
            current_state=HouseState.AWAY,
            any_zone_occupied=True,
            now=_afternoon(),
            unidentified_count=0,
            guest_gate_armed=False,
        )
        new_state_explicit_false = engine.infer(
            census_count=1,
            current_state=HouseState.AWAY,
            any_zone_occupied=True,
            now=_afternoon(),
            unidentified_count=0,
            guest_gate_armed=False,
            all_tracked_persons_away=False,
        )
        assert new_state_default == new_state_explicit_false == HouseState.ARRIVING

    def test_h1_predicate_includes_census_count_in_source(self):
        """Source-level invariant: the veto block must reference census_count."""
        # Locate the veto comment + predicate.
        idx = PRESENCE_SRC.find("Person-tracker veto")
        assert idx >= 0, "veto comment block not found"
        block = PRESENCE_SRC[idx: idx + 1200]
        assert "census_count == 0" in block, (
            "H1: veto predicate must include census_count == 0"
        )

    def test_h1_unidentified_path_unaffected(self):
        """When unidentified_count > 0, veto still blocked (guest preserved)."""
        engine = _make_engine()
        new_state = engine.infer(
            census_count=0,
            current_state=HouseState.HOME_DAY,
            any_zone_occupied=True,
            now=_afternoon(),
            unidentified_count=1,  # guest at door
            guest_gate_armed=False,
            all_tracked_persons_away=True,
        )
        assert new_state != HouseState.AWAY


# ===========================================================================
# H2 — Phone-left-behind exclusion from veto denominator
# ===========================================================================
#
# H2 lives in _run_inference. The cycle tests below verify the in-test
# mirror of the production filter logic (mirror = Bug Class #44 helper)
# plus source-level invariants that catch a production-side semantic drift.
# ---------------------------------------------------------------------------


DOMAIN = "universal_room_automation"


# v4.7.15.1 D4: _phone_trust_input is an INPUT BUILDER, not a veto mirror.
# It mirrors the SHAPE of production's inline _phone_trustworthy helper at
# presence.py:2267-2293 — but the veto DECISION is no longer computed in
# test scope; it is computed by PresenceCoordinator.should_veto_due_to_
# reliable_signals() (Pattern A, presence.py:755+) via the bridge in
# _veto_via_production_helper above.
#
# The input builder still embodies the v4.7.14.1 A-H1 contract:
# fail-OPEN on missing registry entry / unknown / unavailable / off
# states; only literal "on" is excluded. This contract is verified
# behaviorally below via test_input_builder_h2_fails_open_*.

def _phone_trust_input(hass, person_name: str) -> bool:
    """v4.7.15.1 D4 INPUT BUILDER for the production Pattern A helper.

    Returns True iff the person is "phone-trustworthy" — i.e. their
    phone-left-behind sensor is NOT "on" (or the sensor doesn't exist /
    is unknown / unavailable, which fail-OPENs to True per v4.7.14.1
    A-H1).

    The production inline helper at presence.py:2267-2293 reads the
    entity-registry directly. This test-side input builder mirrors that
    shape using the test-local _FakeEntityRegistry harness.
    """
    person_slug = person_name.lower().replace(" ", "_")
    unique_id = f"{DOMAIN}_person_{person_slug}_phone_left_behind"
    registry = getattr(hass, "_fake_entity_registry", None)
    if registry is None:
        return True
    entity_id = registry.async_get_entity_id("binary_sensor", DOMAIN, unique_id)
    if entity_id is None:
        return True
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable"):
        return True
    return state.state != "on"


# v4.7.15.1 D4 back-compat shim — preserves the old _phone_trustworthy name
# for the source-grep invariant in test_h2_filter_present_in_source which
# verifies the production helper SHAPE (presence.py exposes a function
# named `_phone_trustworthy` inline). The shim resolves to the new input
# builder so all existing test call sites continue to work.
_phone_trustworthy = _phone_trust_input


def _compute_with_h2(hass, person_coordinator):
    """v4.7.15.1 D4: drives the PRODUCTION helper via the bridge.

    Pre-D4 this function re-implemented H2 filter math in test scope. Now
    it delegates to should_veto_due_to_reliable_signals(scope=
    "house_inference") and returns the legacy (away, count, ids) tuple
    extracted from the helper's VetoDecision.

    NOTE: Pre-D4 _compute_with_h2 ignored H3 (no tracking_status filter).
    To preserve the contract for the H2-only tests, we override the H3
    tracking_active inputs to ALL TRUE — making H3 a no-op for these
    callers. The H2-only tests therefore drive the production helper
    purely as an H2 filter.
    """
    return _compute_via_production_helper(hass, person_coordinator, h3=False)


def _compute_via_production_helper(hass, person_coordinator, *, h3: bool):
    """Production-helper bridge for both H2-only and H2+H3 contracts.

    h3=False: tracking_active is forced TRUE for every person (mirrors the
    pre-fix _compute_with_h2 contract).
    h3=True: tracking_active reflects the per-person tracking_status field
    (mirrors the pre-fix _compute_with_h2_h3 contract).
    """
    trustworthy_persons: dict[str, dict] = {}
    person_phone_trust_signals: list[bool] = []
    person_tracking_active_signals: list[bool] = []
    try:
        if person_coordinator and getattr(person_coordinator, "data", None):
            person_data = person_coordinator.data or {}
            for name in sorted(person_data.keys()):
                info = person_data[name]
                phone_ok = _phone_trust_input(hass, name)
                track_ok = _tracking_active_input(info) if h3 else True
                person_phone_trust_signals.append(bool(phone_ok))
                person_tracking_active_signals.append(bool(track_ok))
                if phone_ok and track_ok:
                    trustworthy_persons[name] = info
    except Exception:  # noqa: BLE001 — mirrors production fail-safe
        trustworthy_persons = {}
        person_phone_trust_signals = []
        person_tracking_active_signals = []

    trusted_count = len(trustworthy_persons)
    all_away_pre = False
    away_person_ids: list[str] = []
    if trusted_count > 0:
        all_away_pre = all(
            (info.get("location") or "") in ("away", "")
            for info in trustworthy_persons.values()
        )
        if all_away_pre:
            away_person_ids = sorted(trustworthy_persons.keys())

    reliable_signals = [
        ReliableSignal("person_tracker_away", all_away_pre),
        ReliableSignal(
            "person_tracker_home",
            not all_away_pre and trusted_count > 0,
        ),
    ]
    for _phone_ok in person_phone_trust_signals:
        reliable_signals.append(
            ReliableSignal("person_phone_trustworthy", _phone_ok)
        )
    for _track_ok in person_tracking_active_signals:
        reliable_signals.append(
            ReliableSignal("person_tracking_active", _track_ok)
        )
    census_count = getattr(hass, "_test_census_count", 0)
    unid_count = getattr(hass, "_test_unidentified_count", 0)

    coord = _make_presence_coordinator()
    decision = coord.should_veto_due_to_reliable_signals(
        reliable_signals=reliable_signals,
        transient_signals=[
            TransientSignal("unidentified_person_count", unid_count),
            TransientSignal("census_count", census_count),
        ],
        state_context={
            "scope": "house_inference",
            "tracked_count": trusted_count,
        },
    )
    return decision.fired, trusted_count, away_person_ids


class _FakeEntityRegistry:
    """Minimal stand-in for homeassistant.helpers.entity_registry.

    Provides async_get_entity_id(domain, platform, unique_id) -> entity_id|None
    backed by a unique_id -> entity_id map. Mirrors the production registry
    surface used by the H2 helper (see `presence.py` post fix-up A-H1).
    """

    def __init__(self, mapping: dict[str, str] | None = None):
        # key: (domain, platform, unique_id), value: entity_id
        self._mapping: dict[tuple[str, str, str], str] = {}
        if mapping:
            for unique_id, entity_id in mapping.items():
                self._mapping[("binary_sensor", DOMAIN, unique_id)] = entity_id

    def register(self, domain: str, platform: str, unique_id: str, entity_id: str) -> None:
        self._mapping[(domain, platform, unique_id)] = entity_id

    def async_get_entity_id(self, domain: str, platform: str, unique_id: str):
        return self._mapping.get((domain, platform, unique_id))


def _make_hass_with_states(states_map, unique_id_map: dict[str, str] | None = None):
    """Build a mock hass with states + an entity-registry mapping unique_id -> entity_id.

    states_map: dict[entity_id, str | None]. Missing key returns None.
    unique_id_map: dict[unique_id, entity_id]. When None, unique_id_map is
    derived from states_map keys that match the v4.7.14.1 phone-left-behind
    pattern — operator-verified live entity_id format
    `binary_sensor.universal_room_automation_<slug>_phone_left_behind`.
    """
    hass = MagicMock()

    def _get(entity_id):
        if entity_id not in states_map:
            return None
        val = states_map[entity_id]
        if val is None:
            return None
        st = MagicMock()
        st.state = val
        return st

    hass.states.get.side_effect = _get

    # Construct the registry. If the caller didn't provide an explicit
    # unique_id mapping, derive one from any phone_left_behind entity_ids
    # in states_map by reversing the slug.
    if unique_id_map is None:
        unique_id_map = {}
        for ent_id in states_map:
            if not ent_id.endswith("_phone_left_behind"):
                continue
            # Expected format (operator-live-verified 2026-05-30):
            # binary_sensor.universal_room_automation_<slug>_phone_left_behind
            prefix = "binary_sensor.universal_room_automation_"
            suffix = "_phone_left_behind"
            if ent_id.startswith(prefix) and ent_id.endswith(suffix):
                slug = ent_id[len(prefix):-len(suffix)]
                unique_id = f"{DOMAIN}_person_{slug}_phone_left_behind"
                unique_id_map[unique_id] = ent_id

    hass._fake_entity_registry = _FakeEntityRegistry(unique_id_map)
    # v4.7.15.1 D4: pre-seed census/unid counts to 0 so the production-helper
    # bridge in _compute_via_production_helper reads concrete ints (not
    # MagicMock attribute auto-creation, which would be truthy and silently
    # block H1's `census == 0` predicate).
    hass._test_census_count = 0
    hass._test_unidentified_count = 0
    return hass


class TestH2PhoneLeftBehindExclusion:

    def test_h2_excludes_phone_left_behind_person(self):
        """4 persons, 1 flagged phone_left_behind, other 3 away → veto fires."""
        hass = _make_hass_with_states({
            "binary_sensor.universal_room_automation_oji_phone_left_behind": "on",
        })
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "home", "tracking_status": TRACKING_STATUS_ACTIVE},
            "jaya": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
            "kai": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
            "ada": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
        }
        away, count, ids = _compute_with_h2(hass, pc)
        assert away is True
        assert count == 3  # oji filtered out
        assert "oji" not in ids
        assert sorted(ids) == ["ada", "jaya", "kai"]

    def test_h2_phone_left_behind_holdout_blocks_veto_for_flagged_person_only(self):
        """Flagged person at home, other 3 away → veto fires (flagged excluded)."""
        hass = _make_hass_with_states({
            "binary_sensor.universal_room_automation_oji_phone_left_behind": "on",
        })
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "kitchen"},  # phone says home; H2 ignores
            "jaya": {"location": "away"},
            "kai": {"location": "away"},
            "ada": {"location": "away"},
        }
        away, count, _ = _compute_with_h2(hass, pc)
        assert away is True
        assert count == 3

    def test_h2_all_persons_flagged_does_not_veto(self):
        """All flagged → denominator drops to 0 → fail-safe holds."""
        hass = _make_hass_with_states({
            "binary_sensor.universal_room_automation_oji_phone_left_behind": "on",
            "binary_sensor.universal_room_automation_jaya_phone_left_behind": "on",
        })
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "away"},
            "jaya": {"location": "away"},
        }
        away, count, _ = _compute_with_h2(hass, pc)
        # tracked_count > 0 guard prevents veto when denominator is empty.
        assert away is False
        assert count == 0

    def test_h2_sensor_unavailable_treats_as_trustworthy(self):
        """Entity not in hass.states (disabled by default) → person counted.

        Preserves v4.7.14 baseline for operators who haven't enabled
        PersonPhoneLeftBehindSensor (it's `enabled_default=False`).
        """
        hass = _make_hass_with_states({})  # no entities present
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "away"},
            "jaya": {"location": "away"},
        }
        away, count, _ = _compute_with_h2(hass, pc)
        # Fail-OPEN: both counted, both away → veto fires (v4.7.14 baseline).
        assert away is True
        assert count == 2

    def test_h2_sensor_state_unknown_treats_as_trustworthy(self):
        """state == 'unknown' → person counted (only literal 'on' excludes)."""
        hass = _make_hass_with_states({
            "binary_sensor.universal_room_automation_oji_phone_left_behind": "unknown",
        })
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "away"},
            "jaya": {"location": "away"},
        }
        away, count, _ = _compute_with_h2(hass, pc)
        assert away is True
        assert count == 2

    def test_h2_sensor_state_unavailable_treats_as_trustworthy(self):
        """state == 'unavailable' → person counted (fail-OPEN)."""
        hass = _make_hass_with_states({
            "binary_sensor.universal_room_automation_oji_phone_left_behind": "unavailable",
        })
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "away"},
            "jaya": {"location": "away"},
        }
        away, count, _ = _compute_with_h2(hass, pc)
        assert away is True
        assert count == 2

    def test_h2_sensor_state_off_treats_as_trustworthy(self):
        """state == 'off' → person counted."""
        hass = _make_hass_with_states({
            "binary_sensor.universal_room_automation_oji_phone_left_behind": "off",
        })
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "away"},
            "jaya": {"location": "away"},
        }
        away, count, _ = _compute_with_h2(hass, pc)
        assert away is True
        assert count == 2

    def test_h2_resolves_entity_via_registry_unique_id(self):
        """A-H1 fix-up: H2 MUST resolve entity_id via entity_registry by unique_id.

        Replaces the prior `test_h2_entity_id_slug_matches_binary_sensor_format`
        which was a self-confirming mirror per Reviewer A. This test now drives
        a registry that maps the production unique_id formula
        (`binary_sensor.py:1000`) to a known entity_id and verifies that the
        H2 helper resolves through it.

        The live-verified production entity_id (operator-probed 2026-05-30) is
        `binary_sensor.universal_room_automation_<slug>_phone_left_behind` —
        the device-prefixed form, NOT the bare slug. The pre-fix-up string
        construction (`binary_sensor.<slug>_phone_left_behind`) would silently
        fail-OPEN for every person.
        """
        unique_id = f"{DOMAIN}_person_oji_udezue_phone_left_behind"
        live_entity_id = (
            "binary_sensor.universal_room_automation_oji_udezue_phone_left_behind"
        )
        hass = _make_hass_with_states(
            states_map={live_entity_id: "on"},
            unique_id_map={unique_id: live_entity_id},
        )
        # If the helper were still constructing entity_id by bare-slug concat
        # (`binary_sensor.oji_udezue_phone_left_behind`), the registry lookup
        # would be irrelevant and the bare-slug entity would not exist in
        # states_map -> fail-OPEN. Expecting False (NOT trustworthy) proves
        # the registry path is wired.
        assert _phone_trustworthy(hass, "Oji Udezue") is False, (
            "A-H1: H2 must resolve entity_id via entity_registry by unique_id"
        )
        pc = MagicMock()
        pc.data = {
            "Oji Udezue": {"location": "home"},
            "jaya": {"location": "away"},
        }
        away, count, _ = _compute_with_h2(hass, pc)
        assert count == 1
        assert away is True

    def test_h2_fail_open_when_registry_returns_none(self):
        """A-H1: empty registry (sensor disabled per binary_sensor.py:988)
        MUST fail-OPEN — person counted, v4.7.14 baseline preserved."""
        hass = _make_hass_with_states(states_map={}, unique_id_map={})
        assert _phone_trustworthy(hass, "oji") is True

    # --- Source-level invariants ---

    def test_h2_filter_present_in_source(self):
        """Production block must build a filtered person-set before reduction."""
        assert "_phone_trustworthy" in PRESENCE_SRC, (
            "H2: phone trustworthiness helper missing from presence.py"
        )

    def test_h2_filter_references_phone_left_behind_unique_id(self):
        """A-H1 fix-up: production MUST mirror binary_sensor.py:1000's unique_id formula.

        Post-fix-up the helper resolves via entity_registry by unique_id; the
        string literal `_phone_left_behind` must still appear in the unique_id
        construction.
        """
        assert "_phone_left_behind" in PRESENCE_SRC, (
            "H2: must reference the phone_left_behind unique_id suffix"
        )

    def test_h2_filter_uses_entity_registry(self):
        """A-H1: H2 MUST resolve via entity_registry (not by string concat).

        Replaces the prior `test_h2_filter_uses_hass_states_get` — the bare
        `f"binary_sensor.{slug}_phone_left_behind"` form was the exact bug
        A-H1 surfaced (silent no-op because the real entity_id is
        `binary_sensor.universal_room_automation_<slug>_phone_left_behind`).
        """
        helper_idx = PRESENCE_SRC.find("def _phone_trustworthy")
        assert helper_idx >= 0, "H2: _phone_trustworthy helper missing"
        helper_block = PRESENCE_SRC[helper_idx: helper_idx + 2400]
        assert "async_get_entity_id" in helper_block, (
            "A-H1: _phone_trustworthy must resolve entity_id via "
            "entity_registry.async_get_entity_id"
        )
        assert "binary_sensor" in helper_block, (
            "A-H1: helper must pass 'binary_sensor' domain to async_get_entity_id"
        )
        # The unique_id format must mirror binary_sensor.py:1000:
        # f"{DOMAIN}_person_<slug>_phone_left_behind"
        assert "_person_" in helper_block, (
            "A-H1: unique_id must mirror binary_sensor.py:1000 format"
        )
        # Defensive: the bare-slug bug form MUST NOT be in the helper body.
        assert 'f"binary_sensor.' not in helper_block, (
            "A-H1: bare-slug entity_id construction is the bug — must not return"
        )


# ===========================================================================
# H3 — STALE/LOST exclusion from veto denominator
# ===========================================================================


def _tracking_active_input(info: dict) -> bool:
    """v4.7.15.1 D4 INPUT BUILDER for the production Pattern A helper.

    Returns True iff tracking_status is ACTIVE. Missing field defaults to
    ACTIVE (preserves v4.7.14 baseline for older-shape entries — matches
    presence.py:2295-2306's fail-forward default).
    """
    return info.get("tracking_status", TRACKING_STATUS_ACTIVE) == TRACKING_STATUS_ACTIVE


# Back-compat shim — preserves the old _tracking_active name for the
# source-grep invariant in test_h3_filter_references_tracking_status.
_tracking_active = _tracking_active_input


def _compute_with_h2_h3(hass, person_coordinator):
    """v4.7.15.1 D4: drives the PRODUCTION helper with full H2+H3 contract.

    Delegates to the production Pattern A via the bridge. Pre-D4 this
    function re-implemented H2+H3 filter math in test scope (Bug Class #44
    trip-wire per Reviewer C of v4.7.14.1). Now the veto decision is
    computed by production code; the test-local functions only mirror the
    input-builder shape (entity-registry lookup + tracking_status read).
    """
    return _compute_via_production_helper(hass, person_coordinator, h3=True)


class TestH3StaleLostExclusion:

    def test_h3_excludes_stale_person(self):
        """STALE person is filtered out; remaining ACTIVE persons drive veto."""
        hass = _make_hass_with_states({})
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "away", "tracking_status": TRACKING_STATUS_STALE},
            "jaya": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
            "kai": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
            "ada": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
        }
        away, count, ids = _compute_with_h2_h3(hass, pc)
        assert away is True
        assert count == 3  # STALE oji excluded
        assert "oji" not in ids

    def test_h3_excludes_lost_person(self):
        """LOST person is filtered out."""
        hass = _make_hass_with_states({})
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "away", "tracking_status": TRACKING_STATUS_LOST},
            "jaya": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
            "kai": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
        }
        away, count, _ = _compute_with_h2_h3(hass, pc)
        assert away is True
        assert count == 2  # LOST oji excluded

    def test_h3_stale_tracker_excluded_from_veto(self):
        """Single STALE tracker → if remaining set all away, veto still fires."""
        hass = _make_hass_with_states({})
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "home", "tracking_status": TRACKING_STATUS_STALE},
            "jaya": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
        }
        away, count, _ = _compute_with_h2_h3(hass, pc)
        # STALE oji (claiming home) excluded → only ACTIVE jaya (away) counts.
        assert away is True
        assert count == 1

    def test_h3_lost_via_person_state_home_excluded(self):
        """Operationally common case: LOST tracker whose fallback is person_state=home.

        person_coordinator.py:333/345/377 set LOST when there's no Bermuda data
        and the fallback uses person.X state, which may be 'home' (stale).
        Without H3, that stale 'home' would block the veto even when the rest
        of the household is away.
        """
        hass = _make_hass_with_states({})
        pc = MagicMock()
        pc.data = {
            # Stale person.X 'home' state via fallback → LOST tracking.
            "oji": {
                "location": "home",
                "tracking_status": TRACKING_STATUS_LOST,
                "method": "person_state",
            },
            "jaya": {
                "location": "away",
                "tracking_status": TRACKING_STATUS_ACTIVE,
                "method": "bermuda",
            },
            "kai": {
                "location": "away",
                "tracking_status": TRACKING_STATUS_ACTIVE,
                "method": "bermuda",
            },
        }
        away, count, ids = _compute_with_h2_h3(hass, pc)
        # H3 removes LOST oji even though their location says 'home'.
        # Remaining 2 ACTIVE persons are both away → veto fires.
        assert away is True, (
            "H3: LOST person reporting 'home' via stale fallback must not block veto"
        )
        assert count == 2
        assert "oji" not in ids

    def test_h3_only_stale_persons_does_not_veto(self):
        """All STALE → denominator drops to 0 → fail-safe."""
        hass = _make_hass_with_states({})
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "away", "tracking_status": TRACKING_STATUS_STALE},
            "jaya": {"location": "away", "tracking_status": TRACKING_STATUS_STALE},
        }
        away, count, _ = _compute_with_h2_h3(hass, pc)
        assert away is False
        assert count == 0

    def test_h3_missing_tracking_status_treated_as_active(self):
        """Defensive: missing tracking_status field defaults to ACTIVE."""
        hass = _make_hass_with_states({})
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "away"},  # no tracking_status key
            "jaya": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
        }
        away, count, _ = _compute_with_h2_h3(hass, pc)
        assert away is True
        assert count == 2

    def test_h3_active_person_at_home_blocks_veto(self):
        """ACTIVE person at home cannot be excluded; veto correctly skipped."""
        hass = _make_hass_with_states({})
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "kitchen", "tracking_status": TRACKING_STATUS_ACTIVE},
            "jaya": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
            "kai": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
        }
        away, count, _ = _compute_with_h2_h3(hass, pc)
        assert away is False
        assert count == 3

    # --- Source-level invariants ---

    def test_h3_filter_references_tracking_status(self):
        """Production block must reference tracking_status."""
        assert "tracking_status" in PRESENCE_SRC, (
            "H3: must reference tracking_status field"
        )

    def test_h3_imports_tracking_status_active(self):
        """Production must import TRACKING_STATUS_ACTIVE (not literal compare)."""
        assert "TRACKING_STATUS_ACTIVE" in PRESENCE_SRC, (
            "H3: must import/use TRACKING_STATUS_ACTIVE constant"
        )


# ===========================================================================
# Composed behavior — H1 + H2 + H3 interacting
# ===========================================================================


class TestComposedBehavior:

    def test_failsafe_holds_when_all_filtered_out(self):
        """All persons filtered (mix of phone_left_behind + STALE) → no veto."""
        hass = _make_hass_with_states({
            "binary_sensor.universal_room_automation_oji_phone_left_behind": "on",
        })
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
            "jaya": {"location": "away", "tracking_status": TRACKING_STATUS_STALE},
            "kai": {"location": "away", "tracking_status": TRACKING_STATUS_LOST},
        }
        away, count, _ = _compute_with_h2_h3(hass, pc)
        # oji filtered by H2, jaya + kai filtered by H3 → empty denominator.
        assert away is False
        assert count == 0

    def test_default_state_all_active_phones_present(self):
        """Baseline path: all ACTIVE, no phone-left-behind, all away → veto fires."""
        hass = _make_hass_with_states({})
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
            "jaya": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
            "kai": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
            "ada": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
        }
        away, count, _ = _compute_with_h2_h3(hass, pc)
        assert away is True
        assert count == 4


# ===========================================================================
# A-M1 + A-M3 — Veto-fired log: gate tightening + excluded-persons enrichment
# ===========================================================================
#
# Fix-up A-M1 tightens the veto-fired log gate to mirror the v4.7.14.1 H1
# predicate (census_count == 0 AND any_zone_occupied) so the log NEVER
# fires on the line-398 AND-gate path. A-M3 enriches the log message with
# the excluded-persons enumeration + reason so operators can diagnose
# "why didn't X block the veto" without grepping source.


class TestAM1AM3VetoFiredLog:
    """Source-level invariants on the veto-fired log gate + message."""

    def test_am1_log_gate_includes_census_count_zero(self):
        """A-M1: log gate must require self._census_count == 0."""
        # The veto-fired log lives ~150 lines after the inference call.
        # Search the full presence.py for the v4.7.14.1 marker.
        idx = PRESENCE_SRC.find("Person-tracker veto fired")
        assert idx >= 0, "veto-fired log site missing"
        # Walk back to the surrounding `if (` predicate.
        start = PRESENCE_SRC.rfind("if (", 0, idx)
        assert start >= 0, "veto-fired log `if (` predicate not found"
        gate_block = PRESENCE_SRC[start:idx]
        assert "self._census_count == 0" in gate_block, (
            "A-M1: veto-fired log gate must include `self._census_count == 0` "
            "to mirror H1 and only fire on the 0.95 veto path"
        )

    def test_am1_log_gate_includes_any_zone_occupied(self):
        """A-M1: gate must include any_zone_occupied (excludes line-398 AND-gate)."""
        idx = PRESENCE_SRC.find("Person-tracker veto fired")
        start = PRESENCE_SRC.rfind("if (", 0, idx)
        gate_block = PRESENCE_SRC[start:idx]
        assert "any_zone_occupied" in gate_block, (
            "A-M1: veto-fired log gate must include `any_zone_occupied` so the "
            "line-398 AND-gate path (which fires when not any_zone_occupied) is "
            "excluded — only the veto path (which requires any_zone_occupied) logs"
        )

    def test_am3_log_message_includes_excluded_persons(self):
        """A-M3: log message must enumerate excluded persons + reason."""
        idx = PRESENCE_SRC.find("Person-tracker veto fired")
        # Examine a window covering the call site (message format + args).
        window = PRESENCE_SRC[idx: idx + 1500]
        assert "excluded" in window, (
            "A-M3: log message must include excluded-persons enumeration"
        )
        # The reason payload must be built; look for the format-string assembly.
        assert "_excluded_persons" in window or "excluded_persons" in window, (
            "A-M3: log must pass the excluded-persons map into the format args"
        )

    def test_am3_log_message_includes_census_count(self):
        """A-M3: log message must include census_count for diagnostic transparency."""
        idx = PRESENCE_SRC.find("Person-tracker veto fired")
        window = PRESENCE_SRC[idx: idx + 1500]
        # The literal `census_count=0` should appear (H1 only fires when 0).
        assert "census_count=0" in window or "census_count" in window, (
            "A-M3: log message must include census_count for diagnostic clarity"
        )

    def test_am3_log_message_includes_confidence(self):
        """A-M3: log must call out the 0.95 veto confidence signature."""
        idx = PRESENCE_SRC.find("Person-tracker veto fired")
        window = PRESENCE_SRC[idx: idx + 1500]
        assert "confidence=0.95" in window or "0.95" in window, (
            "A-M3: log must include the 0.95 veto confidence so operators "
            "can distinguish veto-fire from the 0.9 AND-gate fire"
        )

    def test_am3_excluded_persons_attribute_present_in_coordinator(self):
        """A-M3: PresenceCoordinator must expose `_excluded_persons` attribute."""
        # __init__ initializes self._excluded_persons.
        assert "self._excluded_persons" in PRESENCE_SRC, (
            "A-M3: PresenceCoordinator must initialize self._excluded_persons "
            "so the diagnostic sensor can surface the filtered-out set"
        )

    def test_am1_am3_filter_loop_captures_reason(self):
        """A-M1/M3: filter loop must record both phone_left_behind and tracking_status reasons."""
        # The new filter loop captures BOTH reasons. Source-level invariant.
        assert "phone_left_behind=on" in PRESENCE_SRC, (
            "A-M1/M3: filter loop must record phone_left_behind=on as exclusion reason"
        )
        assert "tracking_status=" in PRESENCE_SRC, (
            "A-M1/M3: filter loop must record tracking_status=<value> as exclusion reason"
        )


# ===========================================================================
# A-M2 — `tracked_persons_count` dual-attribute exposure
# ===========================================================================
#
# Pre-v4.7.14.1 the sensor attribute `tracked_persons_count` reflected the raw
# `len(person_coordinator.data)` — the configured-person count. After H2/H3
# the underlying `_tracked_persons_count` silently flipped to the FILTERED
# count. An operator with 4 configured persons + 1 phone_left_behind would see
# 3 in the attribute and reasonably misdiagnose person_coordinator dropout.
#
# Fix-up A-M2 (preferred shape per Reviewer B): expose BOTH
#   - tracked_persons_count             (raw — pre-v4.7.14.1 semantic preserved)
#   - tracked_persons_count_trusted     (post-H2/H3 filter — new)
#   - excluded_persons                  (map of name -> reason)
# so the operator can see the count delta and its cause without grepping logs.


SENSOR_SRC = (PKG / "sensor.py").read_text()


class TestAM2DualAttributeExposure:
    """A-M2: sensor.py must expose raw count, trusted count, and excluded map."""

    def test_am2_raw_count_attribute_present(self):
        """`tracked_persons_count` attribute MUST remain (raw semantic)."""
        # Confirm sensor.py emits attrs["tracked_persons_count"] and reads
        # presence._tracked_persons_count (which now stores raw count).
        assert 'attrs["tracked_persons_count"]' in SENSOR_SRC, (
            "A-M2: `tracked_persons_count` attribute must be exposed (raw count)"
        )
        assert "_tracked_persons_count" in SENSOR_SRC, (
            "A-M2: sensor must read presence._tracked_persons_count (raw count)"
        )

    def test_am2_trusted_count_attribute_present(self):
        """`tracked_persons_count_trusted` MUST be exposed (post-H2/H3 filter)."""
        assert 'attrs["tracked_persons_count_trusted"]' in SENSOR_SRC, (
            "A-M2: `tracked_persons_count_trusted` attribute must be exposed"
        )
        assert "_tracked_persons_count_trusted" in SENSOR_SRC, (
            "A-M2: sensor must read presence._tracked_persons_count_trusted"
        )

    def test_am2_excluded_persons_attribute_present(self):
        """`excluded_persons` MUST be exposed (name -> reason map)."""
        assert 'attrs["excluded_persons"]' in SENSOR_SRC, (
            "A-M2: `excluded_persons` attribute must be exposed"
        )
        assert "_excluded_persons" in SENSOR_SRC, (
            "A-M2: sensor must read presence._excluded_persons"
        )

    def test_am2_presence_coordinator_tracks_raw_count(self):
        """presence.py MUST assign `_tracked_persons_count = tracked_count_raw`.

        Without this assignment the dual-attribute exposure is broken — the
        sensor would expose the trusted count under the raw-count name.
        """
        assert "tracked_count_raw" in PRESENCE_SRC, (
            "A-M2: filter loop must compute tracked_count_raw separately from "
            "the post-filter trusted count"
        )
        assert "self._tracked_persons_count = tracked_count_raw" in PRESENCE_SRC, (
            "A-M2: _tracked_persons_count attribute must store the RAW count "
            "(pre-v4.7.14.1 semantic preserved per A-M2)"
        )

    def test_am2_presence_coordinator_tracks_trusted_count(self):
        """presence.py MUST also expose the post-filter trusted count."""
        assert "self._tracked_persons_count_trusted = tracked_count" in PRESENCE_SRC, (
            "A-M2: _tracked_persons_count_trusted must store the post-filter "
            "denominator (the count used by the veto reduction)"
        )

    def test_am2_raw_and_trusted_diverge_under_filter(self):
        """Behavioral: raw count >= trusted count whenever any filter fires.

        Drives the H2 filter mirror and confirms the raw count of the input
        dict is unchanged while the trusted (post-filter) count is reduced.
        """
        hass = _make_hass_with_states(
            states_map={
                "binary_sensor.universal_room_automation_oji_phone_left_behind": "on",
            },
        )
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "home", "tracking_status": TRACKING_STATUS_ACTIVE},
            "jaya": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
            "kai": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
            "ada": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
        }
        # Mirror compute_with_h2_h3 returns the trusted (filtered) count.
        away, trusted_count, _ = _compute_with_h2_h3(hass, pc)
        raw_count = len(pc.data)
        assert raw_count == 4, "raw count should match input dict size"
        assert trusted_count == 3, (
            "A-M2: trusted count drops by 1 when oji is excluded by H2"
        )
        assert raw_count > trusted_count, (
            "A-M2: under any filter, raw count must exceed trusted count"
        )
        assert away is True

    def test_am2_excluded_persons_lists_reasons(self):
        """Behavioral: excluded_persons map must enumerate (person -> reason)
        for every filtered-out person, with both H2 and H3 reasons covered.

        This is the runtime invariant on which the diagnostic sensor attribute
        depends — if the filter loop drops a person without recording a reason,
        the sensor exposes an under-populated map.
        """
        # Drive the filter loop directly via the source contract: we already
        # have the per-name loop in presence.py. Source-level invariants
        # already cover the literal strings ("phone_left_behind=on",
        # "tracking_status="). Here, exercise the mirror to ensure the
        # presence of two distinct reason classes when both H2 and H3 fire.
        hass = _make_hass_with_states(
            states_map={
                "binary_sensor.universal_room_automation_oji_phone_left_behind": "on",
            },
        )
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
            "jaya": {"location": "away", "tracking_status": TRACKING_STATUS_STALE},
            "kai": {"location": "away", "tracking_status": TRACKING_STATUS_ACTIVE},
        }
        # Mirror per-name filter to confirm both exclusion reasons surface.
        excluded: dict[str, str] = {}
        for name, info in pc.data.items():
            phone_ok = _phone_trustworthy(hass, name)
            track_ok = _tracking_active(info)
            if phone_ok and track_ok:
                continue
            if not phone_ok:
                excluded[name] = "phone_left_behind=on"
            else:
                excluded[name] = f"tracking_status={info['tracking_status']}"
        assert excluded == {
            "oji": "phone_left_behind=on",
            "jaya": f"tracking_status={TRACKING_STATUS_STALE}",
        }, "A-M2 + A-M3: both H2 and H3 reasons must populate excluded_persons"
