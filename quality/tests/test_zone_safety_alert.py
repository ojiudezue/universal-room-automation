"""Tests for backlog #12 zone safety-alert chip split (v5.38.0).

Drives the REAL production helpers in
``custom_components.universal_room_automation.domain_coordinators.safety``:
  * ``resolve_safety_bands(room_type)`` — thin projection over the four
    existing safety-coordinator threshold tables.
  * ``evaluate_zone_chip(rooms, zone_is_outdoor)`` — pure helper the
    aggregation zone chip delegates to.

The HA mock bootstrap that lets ``safety.py`` import is imported here
for its side effects (see ``test_safety_coordinator`` module-level).
"""
from __future__ import annotations

# Import for side effects: installs HA mock modules + safety import.
import test_safety_coordinator  # noqa: F401

import pytest

from custom_components.universal_room_automation.domain_coordinators.safety import (
    HUMIDITY_THRESHOLDS,
    LOW_HUMIDITY_THRESHOLDS,
    NUMERIC_THRESHOLDS,
    HazardType,
    SafetyBands,
    ZONE_CHIP_HUMIDITY_RUNG,
    ZONE_CHIP_TEMP_HIGH_RUNG,
    ZONE_CHIP_TEMP_LOW_RUNG,
    ZONE_CHIP_LOW_HUMIDITY_RUNG,
    ZoneChipRoomInput,
    evaluate_zone_chip,
    resolve_safety_bands,
)
from custom_components.universal_room_automation.domain_coordinators.base import (
    Severity,
)


# =============================================================================
# D1 — resolve_safety_bands: byte-identity with underlying tables
# =============================================================================


class TestResolveSafetyBandsProjection:
    """Prove the helper reads the existing tables (no second copy)."""

    def test_matches_tables_generic(self):
        b = resolve_safety_bands("generic")
        assert b.temp_high_medium == NUMERIC_THRESHOLDS[HazardType.OVERHEAT][ZONE_CHIP_TEMP_HIGH_RUNG]
        assert b.temp_low_medium == NUMERIC_THRESHOLDS[HazardType.FREEZE_RISK][ZONE_CHIP_TEMP_LOW_RUNG]
        assert b.humidity_high_medium == HUMIDITY_THRESHOLDS["normal"][ZONE_CHIP_HUMIDITY_RUNG]
        assert b.humidity_high_high == HUMIDITY_THRESHOLDS["normal"]["high"]
        assert b.humidity_low_medium == LOW_HUMIDITY_THRESHOLDS[ZONE_CHIP_LOW_HUMIDITY_RUNG]
        assert b.humidity_exempt is False
        assert b.temp_exempt is False

    def test_matches_tables_bathroom(self):
        b = resolve_safety_bands("bathroom")
        assert b.humidity_high_medium == HUMIDITY_THRESHOLDS["bathroom"]["medium"]
        assert b.humidity_high_high == HUMIDITY_THRESHOLDS["bathroom"]["high"]

    def test_matches_tables_basement(self):
        b = resolve_safety_bands("basement")
        assert b.humidity_high_medium == HUMIDITY_THRESHOLDS["basement"]["medium"]
        assert b.humidity_high_high == HUMIDITY_THRESHOLDS["basement"]["high"]

    def test_outdoor_fully_exempt(self):
        b = resolve_safety_bands("outdoor")
        assert b.humidity_exempt is True
        assert b.temp_exempt is True
        assert b.humidity_high_medium is None
        assert b.humidity_low_medium is None

    def test_garage_humidity_exempt_temp_default(self):
        b = resolve_safety_bands("garage")
        assert b.humidity_exempt is True
        assert b.temp_exempt is False
        assert b.temp_high_medium == NUMERIC_THRESHOLDS[HazardType.OVERHEAT][Severity.MEDIUM]

    @pytest.mark.parametrize("rt", ["bedroom", "common_area", "closet",
                                    "laundry", "utility", "infrastructure",
                                    "unknown_type", "", None])
    def test_unknown_and_generic_fallback(self, rt):
        b = resolve_safety_bands(rt)
        # Everything not modeled falls back to the "normal" humidity table.
        assert b.humidity_high_medium == HUMIDITY_THRESHOLDS["normal"]["medium"]
        assert b.humidity_exempt is False
        assert b.temp_exempt is False


# =============================================================================
# D2 — evaluate_zone_chip: safety-grade trip logic
# =============================================================================


def _room(name, rt, temp=None, hum=None, leak_id=None,
          leak_on=False, leak_dc="moisture"):
    return ZoneChipRoomInput(
        room_name=name,
        room_type=rt,
        temperature=temp,
        humidity=hum,
        leak_sensor_entity_id=leak_id,
        leak_is_on=leak_on,
        leak_device_class=leak_dc,
    )


class TestEvaluateZoneChipSafety:
    """The core is_on rewrite: Master-suite-away scenario, outdoor, garage."""

    def test_master_suite_away_setback_no_alert(self):
        """Bedroom at 87°F on an away-setback afternoon: NOT a safety trip.

        Old chip fired at temp>85; new chip's MEDIUM=OVERHEAT.MEDIUM (105).
        """
        rooms = [_room("Master Bedroom", "bedroom", temp=87.0, hum=42.0)]
        tripping, drift = evaluate_zone_chip(rooms, zone_is_outdoor=False)
        assert tripping == []
        # Old 85°F line crossed → shows in comfort_drift, not is_on.
        assert drift == ["Master Bedroom"]

    def test_master_suite_101f_still_no_alert_but_extreme_yes(self):
        rooms = [_room("Master Bedroom", "bedroom", temp=101.0, hum=42.0)]
        tripping, _ = evaluate_zone_chip(rooms, zone_is_outdoor=False)
        # 101 < 105 MEDIUM → still not safety-grade.
        assert tripping == []

        rooms = [_room("Master Bedroom", "bedroom", temp=106.0, hum=42.0)]
        tripping, _ = evaluate_zone_chip(rooms, zone_is_outdoor=False)
        assert len(tripping) == 1
        assert tripping[0][0] == "Master Bedroom"
        assert "temperature" in tripping[0][1]

    def test_outdoor_zone_flag_exempts_all(self):
        rooms = [_room("Patio", "generic", temp=98.0, hum=88.0)]
        tripping, drift = evaluate_zone_chip(rooms, zone_is_outdoor=True)
        assert tripping == []
        assert drift == []  # exempt on both axes

    def test_garage_humidity_exempt(self):
        rooms = [_room("Garage A", "garage", temp=102.0, hum=90.0)]
        tripping, _ = evaluate_zone_chip(rooms, zone_is_outdoor=False)
        # Temp 102 < 105 MEDIUM, humidity exempt → no trip.
        assert tripping == []

    def test_bathroom_medium_rung_trips_snapshot(self):
        """Bathroom at 88%: MEDIUM=85 crossed → chip trips.

        The transient WINDOW (4h) is a safety-coordinator concern; the
        chip is deliberately a snapshot evaluator.
        """
        rooms = [_room("Master Bath", "bathroom", hum=88.0)]
        tripping, _ = evaluate_zone_chip(rooms, zone_is_outdoor=False)
        assert len(tripping) == 1
        assert tripping[0][0] == "Master Bath"
        assert "humidity" in tripping[0][1]

    def test_genuine_leak_trips_and_names_room(self):
        rooms = [_room(
            "Master Bath", "bathroom",
            leak_id="binary_sensor.master_bath_leak",
            leak_on=True, leak_dc="moisture",
        )]
        tripping, _ = evaluate_zone_chip(rooms, zone_is_outdoor=False)
        assert len(tripping) == 1
        assert tripping[0][0] == "Master Bath"
        assert "leak" in tripping[0][1]

    def test_leak_empty_string_conf_ignored(self):
        """Clear-checkbox pattern writes '' — falsy, must not trip."""
        rooms = [_room("Room", "bedroom", leak_id="", leak_on=True)]
        tripping, _ = evaluate_zone_chip(rooms, zone_is_outdoor=False)
        assert tripping == []

    def test_leak_wrong_domain_rejected(self):
        """Only binary_sensor. entities count as leak."""
        rooms = [_room("Room", "bedroom",
                       leak_id="sensor.pantry_temp", leak_on=True,
                       leak_dc="temperature")]
        tripping, _ = evaluate_zone_chip(rooms, zone_is_outdoor=False)
        assert tripping == []

    def test_tripping_rooms_sorted_and_named(self):
        rooms = [
            _room("Zeta", "bedroom", temp=110.0),
            _room("Alpha", "bathroom", hum=88.0),
        ]
        tripping, _ = evaluate_zone_chip(rooms, zone_is_outdoor=False)
        assert [r for r, _ in tripping] == ["Alpha", "Zeta"]

    def test_comfort_drift_populated_when_no_safety_trip(self):
        rooms = [_room("Master Bedroom", "bedroom", temp=72.0, hum=72.0)]
        tripping, drift = evaluate_zone_chip(rooms, zone_is_outdoor=False)
        assert tripping == []
        assert drift == ["Master Bedroom"]


# =============================================================================
# Table-pinning + additive-diff guarantee: safety-coordinator tables
# unchanged by this cycle (drift catcher). NOT a mutation-anchored test —
# it pins values; a future cycle changing OVERHEAT.MEDIUM to 106 will
# break this and force a review moment.
# =============================================================================


class TestSafetyCoordinatorTablesPinned:
    def test_humidity_thresholds_values(self):
        assert HUMIDITY_THRESHOLDS["normal"]["medium"] == 85.0
        assert HUMIDITY_THRESHOLDS["bathroom"]["medium"] == 85.0
        assert HUMIDITY_THRESHOLDS["basement"]["medium"] == 75.0

    def test_overheat_medium_still_105(self):
        assert NUMERIC_THRESHOLDS[HazardType.OVERHEAT][Severity.MEDIUM] == 105.0

    def test_freeze_medium_still_40(self):
        assert NUMERIC_THRESHOLDS[HazardType.FREEZE_RISK][Severity.MEDIUM] == 40.0


# =============================================================================
# FIX 6 — REAL by-reference mutation: prove resolve_safety_bands reads
# the tables at call time (not a copy captured at import).
# =============================================================================


class TestResolveSafetyBandsReadsTablesByReference:
    def test_humidity_normal_medium_mutation_flows_through(self, monkeypatch):
        monkeypatch.setitem(HUMIDITY_THRESHOLDS["normal"], "medium", 91.0)
        b = resolve_safety_bands("generic")
        assert b.humidity_high_medium == 91.0

    def test_overheat_medium_mutation_flows_through(self, monkeypatch):
        monkeypatch.setitem(
            NUMERIC_THRESHOLDS[HazardType.OVERHEAT], Severity.MEDIUM, 99.0,
        )
        b = resolve_safety_bands("generic")
        assert b.temp_high_medium == 99.0


# =============================================================================
# FIX 1 (A-HIGH-1) — CM-knob drift closed for the "normal" ladder.
# When hass is threaded through, resolve_safety_bands must resolve the
# normal humidity medium/high via nm_cycle_a_knob (same call the safety
# coordinator uses). No hass → static-table fallback.
# =============================================================================


class TestCMKnobDriftClosedForNormalLadder:
    def _stub_hass(self):
        class _Bag(dict):
            pass
        class _HA:
            def __init__(self):
                self.data = {}
                self.config_entries = None
        return _HA()

    def test_knob_override_medium_flows_into_bands(self, monkeypatch):
        import custom_components.universal_room_automation.domain_coordinators._nm_cycle_a as nm
        from custom_components.universal_room_automation.const import (
            CONF_HUMIDITY_NORMAL_MEDIUM_PCT,
            CONF_HUMIDITY_NORMAL_HIGH_PCT,
        )

        def _fake_knob(hass, key, default):
            overrides = {
                CONF_HUMIDITY_NORMAL_MEDIUM_PCT: 80.0,
                CONF_HUMIDITY_NORMAL_HIGH_PCT: 90.0,
            }
            return overrides.get(key, default)

        monkeypatch.setattr(nm, "nm_cycle_a_knob", _fake_knob)
        b = resolve_safety_bands("generic", hass=self._stub_hass())
        assert b.humidity_high_medium == 80.0
        assert b.humidity_high_high == 90.0

    def test_knob_override_trips_chip_via_evaluate(self, monkeypatch):
        import custom_components.universal_room_automation.domain_coordinators._nm_cycle_a as nm
        from custom_components.universal_room_automation.const import (
            CONF_HUMIDITY_NORMAL_MEDIUM_PCT,
        )

        def _fake_knob(hass, key, default):
            if key == CONF_HUMIDITY_NORMAL_MEDIUM_PCT:
                return 80.0
            return default

        monkeypatch.setattr(nm, "nm_cycle_a_knob", _fake_knob)
        rooms = [_room("Study", "bedroom", hum=82.0)]
        tripping, _ = evaluate_zone_chip(
            rooms, zone_is_outdoor=False, hass=self._stub_hass(),
        )
        assert len(tripping) == 1
        assert "humidity" in tripping[0][1]

    def test_no_hass_falls_back_to_static_table(self):
        # Without hass, the knob path can't be taken — static value.
        b = resolve_safety_bands("generic", hass=None)
        assert b.humidity_high_medium == HUMIDITY_THRESHOLDS["normal"]["medium"]

    def test_bathroom_ignores_knobs(self, monkeypatch):
        # Knob path only applies to the "normal" table.
        import custom_components.universal_room_automation.domain_coordinators._nm_cycle_a as nm
        monkeypatch.setattr(nm, "nm_cycle_a_knob",
                            lambda h, k, d: 1.0)
        b = resolve_safety_bands("bathroom", hass=self._stub_hass())
        assert b.humidity_high_medium == HUMIDITY_THRESHOLDS["bathroom"]["medium"]


# =============================================================================
# FIX 2 (B-H1) sticky-last on evaluate error + FIX 3 (B-H2) evaluate once
# per update — exercised directly on the ZoneSafetyAlertSensor instance
# by bypassing __init__ (avoids full HA bootstrap).
# =============================================================================


def _install_aggregation_mocks():
    """Install the extra HA module mocks aggregation.py needs (superset
    of what test_safety_coordinator installs)."""
    import sys, types
    from unittest.mock import MagicMock

    # Some earlier test may have installed homeassistant.helpers as a
    # plain module (no __path__) — turn it back into a package so
    # `from homeassistant.helpers.restore_state import ...` resolves.
    for pkg in ("homeassistant", "homeassistant.helpers",
                "homeassistant.util", "homeassistant.components"):
        mod = sys.modules.get(pkg)
        if mod is None:
            mod = types.ModuleType(pkg)
            sys.modules[pkg] = mod
        if not hasattr(mod, "__path__"):
            mod.__path__ = []  # mark as package

    extras = {
        "homeassistant.helpers.restore_state": {
            "RestoreEntity": type("RestoreEntity", (), {}),
        },
        "homeassistant.helpers.storage": {"Store": MagicMock()},
        "homeassistant.util.unit_conversion": {
            "TemperatureConverter": MagicMock(),
        },
    }
    for name, attrs in extras.items():
        # Overwrite unconditionally so a prior partial install can't
        # leave RestoreEntity missing.
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    # UnitOfEnergy / UnitOfPower / PERCENTAGE on homeassistant.const.
    import homeassistant.const as _const
    for k in ("UnitOfEnergy", "UnitOfTemperature", "UnitOfPower", "PERCENTAGE"):
        if not hasattr(_const, k):
            setattr(_const, k, MagicMock())


def _bare_chip():
    """Construct a ZoneSafetyAlertSensor without running __init__.

    Populates the fields _refresh_snapshot / properties expect. Used to
    unit-test the sticky-last + evaluate-once machinery without touching
    the HA entity lifecycle.
    """
    _install_aggregation_mocks()
    # Some earlier test may have installed a stub
    # `custom_components.universal_room_automation.aggregation` module
    # (or a partial one). Evict it so the real file loads from disk.
    import sys
    stale = sys.modules.get("custom_components.universal_room_automation.aggregation")
    if stale is not None and not hasattr(stale, "ZoneSafetyAlertSensor"):
        del sys.modules["custom_components.universal_room_automation.aggregation"]
    from custom_components.universal_room_automation.aggregation import (
        ZoneSafetyAlertSensor,
    )
    inst = object.__new__(ZoneSafetyAlertSensor)
    inst._last_is_on = None
    inst._evaluate_error = None
    inst._snapshot_is_on = False
    inst._snapshot_attrs = {
        "tripping_rooms": [],
        "reasons": [],
        "comfort_drift_rooms": [],
        "tripping": [],
        "bands_source": "safety.resolve_safety_bands",
        "chip_semantics": "snapshot; bathroom trips may be transient",
    }
    inst._snapshot_ready = False
    inst.zone = "TestZone"
    return inst


class TestStickyLastOnEvaluateError:
    def test_prior_true_preserved_on_exception(self, monkeypatch):
        chip = _bare_chip()
        # First evaluate: True.
        monkeypatch.setattr(
            chip, "_evaluate",
            lambda: (True, {"tripping_rooms": ["Room"], "reasons": ["x"]}),
        )
        chip._refresh_snapshot()
        assert chip.is_on is True
        assert chip._last_is_on is True

        # Next evaluate: raises. Sticky-last must preserve True.
        def _boom():
            raise RuntimeError("boom")
        monkeypatch.setattr(chip, "_evaluate", _boom)
        chip._refresh_snapshot()
        assert chip.is_on is True
        attrs = chip.extra_state_attributes
        assert "_evaluate_error" in attrs
        assert "boom" in attrs["_evaluate_error"]

    def test_error_before_any_success_reports_false(self, monkeypatch):
        chip = _bare_chip()
        def _boom():
            raise RuntimeError("nope")
        monkeypatch.setattr(chip, "_evaluate", _boom)
        chip._refresh_snapshot()
        assert chip.is_on is False
        assert "_evaluate_error" in chip.extra_state_attributes


class TestEvaluateOncePerUpdate:
    def test_evaluate_called_once_across_is_on_and_attrs(self, monkeypatch):
        chip = _bare_chip()
        calls = {"n": 0}

        def _ev():
            calls["n"] += 1
            return True, {"tripping_rooms": ["R"], "reasons": ["y"],
                          "comfort_drift_rooms": [], "tripping": [],
                          "bands_source": "safety.resolve_safety_bands",
                          "chip_semantics": "snapshot"}

        monkeypatch.setattr(chip, "_evaluate", _ev)
        # Simulate a write cycle: refresh once, then read both properties.
        chip._refresh_snapshot()
        _ = chip.is_on
        _ = chip.extra_state_attributes
        _ = chip.is_on
        assert calls["n"] == 1

    def test_snapshot_is_shared_between_is_on_and_attrs(self, monkeypatch):
        chip = _bare_chip()
        seq = iter([
            (True, {"tripping_rooms": ["A"], "reasons": ["r1"]}),
            (False, {"tripping_rooms": [], "reasons": []}),
        ])
        monkeypatch.setattr(chip, "_evaluate", lambda: next(seq))
        chip._refresh_snapshot()
        on1 = chip.is_on
        attrs1 = chip.extra_state_attributes
        # One snapshot → coherent pair.
        assert on1 is True
        assert attrs1["tripping_rooms"] == ["A"]
        # Second refresh (next write cycle) advances to the second value.
        chip._refresh_snapshot()
        assert chip.is_on is False
        assert chip.extra_state_attributes["tripping_rooms"] == []
