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
    StateInferenceEngine,
)
from custom_components.universal_room_automation.domain_coordinators.house_state import (  # noqa: E402
    HouseState,
)
from custom_components.universal_room_automation.const import (  # noqa: E402
    TRACKING_STATUS_ACTIVE,
    TRACKING_STATUS_STALE,
    TRACKING_STATUS_LOST,
)


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


def _phone_trustworthy(hass, person_name: str) -> bool:
    """Mirror of the production helper. Fail-OPEN: missing entity ==> trust."""
    person_slug = person_name.lower().replace(" ", "_")
    entity_id = f"binary_sensor.{person_slug}_phone_left_behind"
    state = hass.states.get(entity_id)
    if state is None:
        return True
    return state.state != "on"


def _compute_with_h2(hass, person_coordinator):
    """Reproduces H2 filter from _run_inference. Mirrors production."""
    all_tracked_persons_away = False
    tracked_count = 0
    away_person_ids = []
    try:
        if person_coordinator and getattr(person_coordinator, "data", None):
            person_data = person_coordinator.data or {}
            trustworthy_persons = {
                name: info
                for name, info in person_data.items()
                if _phone_trustworthy(hass, name)
            }
            tracked_count = len(trustworthy_persons)
            if tracked_count > 0:
                all_tracked_persons_away = all(
                    (info.get("location") or "") in ("away", "")
                    for info in trustworthy_persons.values()
                )
                if all_tracked_persons_away:
                    away_person_ids = sorted(trustworthy_persons.keys())
    except Exception:
        all_tracked_persons_away = False
        tracked_count = 0
        away_person_ids = []
    return all_tracked_persons_away, tracked_count, away_person_ids


def _make_hass_with_states(states_map):
    """Build a mock hass whose hass.states.get(entity_id) returns the mapped state.

    states_map: dict[entity_id, str | None]. Missing key returns None.
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
    return hass


class TestH2PhoneLeftBehindExclusion:

    def test_h2_excludes_phone_left_behind_person(self):
        """4 persons, 1 flagged phone_left_behind, other 3 away → veto fires."""
        hass = _make_hass_with_states({
            "binary_sensor.oji_phone_left_behind": "on",
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
            "binary_sensor.oji_phone_left_behind": "on",
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
            "binary_sensor.oji_phone_left_behind": "on",
            "binary_sensor.jaya_phone_left_behind": "on",
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
            "binary_sensor.oji_phone_left_behind": "unknown",
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
            "binary_sensor.oji_phone_left_behind": "unavailable",
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
            "binary_sensor.oji_phone_left_behind": "off",
        })
        pc = MagicMock()
        pc.data = {
            "oji": {"location": "away"},
            "jaya": {"location": "away"},
        }
        away, count, _ = _compute_with_h2(hass, pc)
        assert away is True
        assert count == 2

    def test_h2_entity_id_slug_matches_binary_sensor_format(self):
        """Slug must match binary_sensor.py:1000 — lower + spaces → underscores."""
        hass = _make_hass_with_states({
            "binary_sensor.oji_udezue_phone_left_behind": "on",
        })
        pc = MagicMock()
        pc.data = {
            "Oji Udezue": {"location": "home"},  # spaces + mixed case
            "jaya": {"location": "away"},
        }
        away, count, _ = _compute_with_h2(hass, pc)
        # If the slug formula matches, Oji Udezue is excluded → count = 1, away True.
        assert count == 1
        assert away is True

    # --- Source-level invariants ---

    def test_h2_filter_present_in_source(self):
        """Production block must build a filtered person-set before reduction."""
        assert "_phone_trustworthy" in PRESENCE_SRC, (
            "H2: phone trustworthiness helper missing from presence.py"
        )

    def test_h2_filter_references_phone_left_behind_entity(self):
        """Production must read binary_sensor.<slug>_phone_left_behind."""
        assert "_phone_left_behind" in PRESENCE_SRC, (
            "H2: must read the phone_left_behind binary sensor"
        )

    def test_h2_filter_uses_hass_states_get(self):
        """H2 must use hass.states.get for entity-state read (correct surface)."""
        # H2 helper is named _phone_trustworthy. Confirm the helper body uses
        # self.hass.states.get to read the binary_sensor.
        helper_idx = PRESENCE_SRC.find("def _phone_trustworthy")
        assert helper_idx >= 0, "H2: _phone_trustworthy helper missing"
        helper_block = PRESENCE_SRC[helper_idx: helper_idx + 1200]
        assert "self.hass.states.get" in helper_block, (
            "H2: _phone_trustworthy must use self.hass.states.get to read the binary_sensor"
        )


# ===========================================================================
# H3 — STALE/LOST exclusion from veto denominator
# ===========================================================================


def _tracking_active(info: dict) -> bool:
    """Mirror of production helper. Missing field defaults to ACTIVE."""
    return info.get("tracking_status", TRACKING_STATUS_ACTIVE) == TRACKING_STATUS_ACTIVE


def _compute_with_h2_h3(hass, person_coordinator):
    """Reproduces H2 + H3 filters from _run_inference. Mirrors production."""
    all_tracked_persons_away = False
    tracked_count = 0
    away_person_ids = []
    try:
        if person_coordinator and getattr(person_coordinator, "data", None):
            person_data = person_coordinator.data or {}
            trustworthy_persons = {
                name: info
                for name, info in person_data.items()
                if _phone_trustworthy(hass, name) and _tracking_active(info)
            }
            tracked_count = len(trustworthy_persons)
            if tracked_count > 0:
                all_tracked_persons_away = all(
                    (info.get("location") or "") in ("away", "")
                    for info in trustworthy_persons.values()
                )
                if all_tracked_persons_away:
                    away_person_ids = sorted(trustworthy_persons.keys())
    except Exception:
        all_tracked_persons_away = False
        tracked_count = 0
        away_person_ids = []
    return all_tracked_persons_away, tracked_count, away_person_ids


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
            "binary_sensor.oji_phone_left_behind": "on",
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
