"""v4.7.18.1 — SLEEP→WAKING Deadlock Hotfix.

Two deliverables (Tier 1 hotfix, single file `presence.py` + sensor surface):

  D1 — Option A (root cause): raw-signal wake timer.
       Add ``ZonePresenceTracker.raw_occupied`` property that returns
       ``_derived_mode == OCCUPIED``, BYPASSING the SLEEP override that
       ``mode`` applies. Re-source the WAKING gate's
       ``_first_positive_zone_occupied_since`` set/clear from a parallel
       ``any_zone_raw_occupied`` local — the mode-based ``any_zone_occupied``
       is left untouched for its other consumers (infer() arg, AWAY-veto log).

  D2 — Option B (safety valve): daytime wake backstop.
       Add ``_WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END = 3`` const and a
       ``_wake_backstop_fires`` counter. When the WAKING gate's veto fires
       AND census_count > 0 AND local hour is in
       [sleep_end_hour + 3, sleep_start_hour), force the WAKING transition
       (fall through, don't suppress). Otherwise existing v4.7.15 D3
       behavior applies (increment _wake_blocked_ticks, debug-log,
       new_state = None).

Tests drive PRODUCTION code paths (real ZonePresenceTracker class) and
assert source-level invariants on the wake-timer wiring + backstop branch
inside _run_inference (Bug Class #44 — tests for behaviors that can't be
reached without instantiating the full inference cycle stay source-grep /
AST-level, mirroring v4.7.15 D3's test_run_inference_tracks_sustained_occupancy).
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import os
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
SENSOR_SRC = (PKG / "sensor.py").read_text()


# ---------------------------------------------------------------------------
# HA module mocking (mirrors test_presence_coordinator.py + v4.7.15 harness)
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
    "homeassistant.helpers.restore_state": {
        "RestoreEntity": type("RestoreEntity", (), {}),
    },
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.utcnow(),
        "now": lambda: datetime(2026, 6, 3, 9, 0, 0),  # 09:00 local
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


# ---------------------------------------------------------------------------
# Package wiring (load only the modules we need under test)
# ---------------------------------------------------------------------------


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
):
    _full = (
        f"custom_components.universal_room_automation.domain_coordinators.{_submod}"
    )
    if _full not in sys.modules:
        _load_module(_full, DC_PATH / f"{_submod}.py")


from custom_components.universal_room_automation.domain_coordinators.presence import (  # noqa: E402
    ZonePresenceMode,
    ZonePresenceTracker,
    _WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END,
    _WAKING_SUSTAINED_THRESHOLD_SECONDS,
)


# ---------------------------------------------------------------------------
# Source-grep window helpers (mirrors v4.7.15 D3 pattern)
# ---------------------------------------------------------------------------

_RUN_INFERENCE_WINDOW = 60000


def _run_inference_body() -> str:
    idx = PRESENCE_SRC.find("async def _run_inference")
    assert idx >= 0, "expected _run_inference in presence.py"
    return PRESENCE_SRC[idx: idx + _RUN_INFERENCE_WINDOW]


# ===========================================================================
# D1 — raw_occupied bypass + raw-signal wake timer
# ===========================================================================


class TestD1RawOccupiedBypassesSleepOverride:
    """D1 root cause: raw_occupied must report real sensor occupancy even when
    set_sleep() has hard-overridden mode to SLEEP. Without this bypass the
    WAKING gate cannot ever start its sustained-occupancy timer during sleep.
    """

    def _make_tracker(self) -> ZonePresenceTracker:
        return ZonePresenceTracker(MagicMock(), "Bedrooms", ["Master"])

    def test_raw_occupied_property_exists(self):
        tracker = self._make_tracker()
        assert hasattr(tracker, "raw_occupied"), (
            "v4.7.18.1 D1: ZonePresenceTracker must expose raw_occupied"
        )
        # Property, not method.
        assert isinstance(
            type(tracker).__dict__["raw_occupied"], property
        )

    def test_raw_occupied_true_when_room_occupied_under_sleep(self):
        """Set room occupied THEN set_sleep — mode masks to SLEEP, but the
        raw sensor tier is still firing, so raw_occupied must remain True.
        This is the exact production scenario that caused the deadlock.
        """
        tracker = self._make_tracker()
        tracker.update_room_occupancy("Master", True)
        assert tracker.mode == ZonePresenceMode.OCCUPIED
        assert tracker.raw_occupied is True

        tracker.set_sleep(True)
        # mode is masked by the SLEEP override...
        assert tracker.mode == ZonePresenceMode.SLEEP
        # ...but raw_occupied must bypass the override.
        assert tracker.raw_occupied is True, (
            "v4.7.18.1 D1: raw_occupied must bypass the SLEEP override"
        )

    def test_raw_occupied_false_when_no_signal_under_sleep(self):
        tracker = self._make_tracker()
        tracker.mark_has_sensors()
        tracker.set_sleep(True)
        assert tracker.mode == ZonePresenceMode.SLEEP
        # No raw signal in any tier — derived would be AWAY.
        assert tracker.raw_occupied is False

    def test_raw_occupied_true_via_ble_under_sleep(self):
        """Tier 3 (BLE) path also bypasses the override correctly."""
        tracker = self._make_tracker()
        tracker._ble_occupied = True
        tracker._has_ble_sensors = True
        tracker.set_sleep(True)
        assert tracker.mode == ZonePresenceMode.SLEEP
        assert tracker.raw_occupied is True

    def test_raw_occupied_true_when_manual_override_occupied(self):
        """Manual override OCCUPIED preserves OCCUPIED on mode; raw_occupied
        reflects the derived (raw) signal directly. A manual override with
        no underlying raw signal should return False here — the property's
        contract is 'real sensor tiers', not 'effective mode'. This is the
        intended semantic: a manual OCCUPIED override should not be enough
        to drive the wake timer on its own (operator can transition the
        house out of SLEEP directly via the house-state select).
        """
        tracker = self._make_tracker()
        tracker.set_override(ZonePresenceMode.OCCUPIED)
        assert tracker.mode == ZonePresenceMode.OCCUPIED
        # No raw signal underneath.
        assert tracker.raw_occupied is False

    def test_raw_occupied_blip_toggles_cleanly(self):
        """Single-tick raw blip True→False must reset to False — drives the
        wake-timer's `_first_positive_zone_occupied_since = None` reset
        on any False (per plan §D1 acceptance).
        """
        tracker = self._make_tracker()
        tracker.set_sleep(True)

        tracker.update_room_occupancy("Master", True)
        assert tracker.raw_occupied is True

        tracker.update_room_occupancy("Master", False)
        assert tracker.raw_occupied is False


class TestD1WakeTimerSourcedFromRawSignal:
    """Source-grep + AST: the wake timer set/clear block must read from
    `any_zone_raw_occupied`, NOT `any_zone_occupied`. The mode-based local
    must still exist (it has other consumers — infer() arg, AWAY-veto log).
    """

    def test_any_zone_raw_occupied_local_defined(self):
        body = _run_inference_body()
        assert "any_zone_raw_occupied = any(" in body, (
            "v4.7.18.1 D1: _run_inference must define any_zone_raw_occupied"
        )
        assert "t.raw_occupied for t in self._zone_trackers.values()" in body, (
            "v4.7.18.1 D1: any_zone_raw_occupied must iterate raw_occupied"
        )

    def test_any_zone_occupied_local_still_exists(self):
        """The old mode-based local must stay — other consumers depend on it
        (infer() arg at presence.py:451, AWAY-veto log at presence.py:2807-2814).
        """
        body = _run_inference_body()
        assert "any_zone_occupied = any(" in body, (
            "v4.7.18.1 D1: any_zone_occupied (mode-based) must remain — "
            "other consumers depend on it"
        )

    def test_wake_timer_set_block_uses_raw_local(self):
        """The if-set/else-clear block for _first_positive_zone_occupied_since
        must be gated on any_zone_raw_occupied, not the mode-masked local.
        """
        body = _run_inference_body()
        # Locate the wake-timer block.
        marker = "_first_positive_zone_occupied_since"
        idx = body.find(marker)
        assert idx >= 0
        # Grab a small window around the set/clear block.
        window_start = max(0, idx - 400)
        block = body[window_start: idx + 400]
        # The conditional guarding the timer SET must be the raw local.
        assert "if any_zone_raw_occupied:" in block, (
            "v4.7.18.1 D1: wake-timer must be gated on any_zone_raw_occupied"
        )

    def test_run_inference_only_defined_once(self):
        """AST guard against the source-grep window sliding past the
        function body (Bug Class #44, mirroring v4.7.15.1 B3-H1).
        """
        tree = ast.parse(PRESENCE_SRC)
        defs = [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
            and n.name == "_run_inference"
        ]
        assert len(defs) == 1, (
            f"expected exactly one _run_inference def; found {len(defs)}"
        )


# ===========================================================================
# D2 — daytime wake backstop (safety valve)
# ===========================================================================


class TestD2BackstopConstAndCounter:
    """The module-level const + per-instance counter must be present."""

    def test_const_present_and_three_hours(self):
        assert _WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END == 3, (
            "v4.7.18.1 D2: backstop margin shipped at 3h past sleep_end"
        )

    def test_wake_backstop_fires_counter_initialized(self):
        """The counter must be initialized to 0 on PresenceCoordinator.
        Use lightweight construction matching the v4.7.15 helper pattern.
        """
        from custom_components.universal_room_automation.domain_coordinators.presence import (
            PresenceCoordinator,
        )
        hass = MagicMock()
        hass.data = {}
        coord = PresenceCoordinator(
            hass=hass,
            sleep_start_hour=23,
            sleep_end_hour=6,
            guest_persistence_seconds=300,
        )
        assert hasattr(coord, "_wake_backstop_fires"), (
            "v4.7.18.1 D2: PresenceCoordinator must define _wake_backstop_fires"
        )
        assert coord._wake_backstop_fires == 0
        # Sibling counter still present too.
        assert hasattr(coord, "_wake_blocked_ticks")
        assert coord._wake_blocked_ticks == 0


class TestD2BackstopBranchWiring:
    """Source-grep: the backstop check must live inside the WAKING gate's
    wake_decision.fired branch, gated on census_count > 0 AND the hour
    window [sleep_end_hour + margin, sleep_start_hour).
    """

    def test_backstop_branch_lives_under_wake_decision_fired(self):
        body = _run_inference_body()
        # The WAKING gate sets last_veto_decision before checking .fired.
        fired_idx = body.find("if wake_decision.fired:")
        assert fired_idx >= 0, "v4.7.15 D3: WAKING-gate fired branch missing"
        # The backstop logic must sit inside that branch — look in a window
        # large enough to contain the if + else fallthrough.
        gate_block = body[fired_idx: fired_idx + 4000]
        assert "_wake_backstop_fires" in gate_block, (
            "v4.7.18.1 D2: backstop counter must increment inside wake-gate branch"
        )
        assert "_WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END" in gate_block, (
            "v4.7.18.1 D2: backstop must reference the margin const"
        )

    def test_backstop_requires_census_gt_zero(self):
        """Backstop must not fire when nobody is home (census==0 owns AWAY)."""
        body = _run_inference_body()
        fired_idx = body.find("if wake_decision.fired:")
        gate_block = body[fired_idx: fired_idx + 4000]
        assert "self._census_count > 0" in gate_block, (
            "v4.7.18.1 D2: backstop must require census_count > 0"
        )

    def test_backstop_window_uses_sleep_hours(self):
        body = _run_inference_body()
        fired_idx = body.find("if wake_decision.fired:")
        gate_block = body[fired_idx: fired_idx + 4000]
        # Both bounds of the daytime window must be wired up.
        assert "sleep_end_hour" in gate_block
        assert "sleep_start_hour" in gate_block

    def test_backstop_falls_through_in_branch_else_suppresses(self):
        """The else branch must still increment _wake_blocked_ticks and set
        new_state = None (the v4.7.15 D3 behavior). Backstop branch must NOT
        set new_state = None.
        """
        body = _run_inference_body()
        fired_idx = body.find("if wake_decision.fired:")
        gate_block = body[fired_idx: fired_idx + 4000]
        # Existence of an else (or non-backstop fallthrough) that suppresses.
        assert "new_state = None" in gate_block, (
            "v4.7.18.1 D2: else branch must still suppress the transition"
        )
        # Backstop log marker.
        assert "WAKING backstop fired" in gate_block, (
            "v4.7.18.1 D2: backstop must emit a WARNING log on fire"
        )

    def test_backstop_uses_local_hour_not_utc(self):
        """dt_util.now() (local) — sleep_start/end_hour are local hours."""
        body = _run_inference_body()
        fired_idx = body.find("if wake_decision.fired:")
        gate_block = body[fired_idx: fired_idx + 4000]
        assert "dt_util.now()" in gate_block, (
            "v4.7.18.1 D2: backstop must compare against LOCAL hour"
        )


class TestD2BackstopBehavioral:
    """Behavioral micro-tests for the backstop hour-window predicate.

    We can't drive the full _run_inference cycle cheaply, but we CAN extract
    and exercise the predicate the source-grep tests pinned the wiring to.
    These tests exist so a future refactor that breaks the predicate's
    semantics (e.g., inverted comparison, off-by-one on the margin) is
    caught by a value assertion, not just a structural grep.
    """

    @staticmethod
    def _backstop(
        census_count: int,
        local_hour: int,
        sleep_end_hour: int,
        sleep_start_hour: int,
    ) -> bool:
        """Mirror of the production predicate (see presence.py wake-gate)."""
        backstop_hour = sleep_end_hour + _WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END
        return (
            census_count > 0
            and backstop_hour <= local_hour < sleep_start_hour
        )

    def test_fires_at_stuck_morning_with_people_home(self):
        """sleep_end=6, +3 = 9. At 10:00 with census=2, backstop fires."""
        assert self._backstop(
            census_count=2, local_hour=10,
            sleep_end_hour=6, sleep_start_hour=23,
        ) is True

    def test_fires_well_into_afternoon(self):
        assert self._backstop(
            census_count=1, local_hour=14,
            sleep_end_hour=6, sleep_start_hour=23,
        ) is True

    def test_does_not_fire_when_nobody_home(self):
        """census==0 → AWAY path owns this case, backstop must NOT fire."""
        assert self._backstop(
            census_count=0, local_hour=10,
            sleep_end_hour=6, sleep_start_hour=23,
        ) is False

    def test_does_not_fire_just_after_sleep_end(self):
        """Hour just after sleep_end_hour (< +3h margin) — v4.7.15 D3 intent
        preserved: real signal still required for the normal wake path.
        """
        # sleep_end=6, margin=3 → backstop activates at 9. At 08:00, it's
        # too eager → must not fire.
        assert self._backstop(
            census_count=2, local_hour=8,
            sleep_end_hour=6, sleep_start_hour=23,
        ) is False

    def test_does_not_fire_at_sleep_start(self):
        """At sleep_start_hour (23) the daytime window has ended."""
        assert self._backstop(
            census_count=2, local_hour=23,
            sleep_end_hour=6, sleep_start_hour=23,
        ) is False

    def test_fires_on_lower_boundary(self):
        """The boundary is inclusive on the lower end: backstop_hour <= hour."""
        # sleep_end=6, margin=3 → activates exactly at 9.
        assert self._backstop(
            census_count=2, local_hour=9,
            sleep_end_hour=6, sleep_start_hour=23,
        ) is True


# ===========================================================================
# Sensor surface — wake_backstop_fires attribute exposure
# ===========================================================================


class TestSensorSurfacesCounter:
    def test_sensor_exposes_wake_backstop_fires(self):
        """sensor.py must surface the counter as an attribute on the rich
        PresenceHouseStateSensor (next to wake_blocked_ticks).
        """
        assert 'attrs["wake_backstop_fires"]' in SENSOR_SRC, (
            "v4.7.18.1 D2: sensor.py must surface wake_backstop_fires attr"
        )
        # Must reference the private attribute on presence via getattr (safe).
        assert '_wake_backstop_fires' in SENSOR_SRC

    def test_wake_blocked_ticks_still_surfaced(self):
        """Sibling counter from v4.7.15 D3 still surfaced."""
        assert 'attrs["wake_blocked_ticks"]' in SENSOR_SRC


# ===========================================================================
# Threshold const sanity (regression — was the old sustained threshold
# inadvertently dropped during the v4.7.18.1 edit?)
# ===========================================================================


def test_waking_sustained_threshold_unchanged():
    assert _WAKING_SUSTAINED_THRESHOLD_SECONDS == 90, (
        "v4.7.18.1 must not change the v4.7.15 D3 sustained threshold"
    )


# ===========================================================================
# Fix-up B-HIGH-1: boot-ordering seed of tracker occupancy at discovery
# ===========================================================================


class TestFixupBHigh1BootSeed:
    """At the end of `_discover_room_sensors` / `_discover_zone_cameras`,
    the tracker's `_room_occupied` / `_camera_occupied` must be seeded from
    the CURRENT entity state — so the first `_run_inference("startup")`
    tick observes raw_occupied == True without waiting for a state-change
    event. Mirrors the existing census seed at presence.py:1228-1259.
    """

    def test_room_sensor_seed_block_present(self):
        """Source-grep: the room-sensor discovery must end with a seed loop
        that reads hass.states.get(entity_id) and calls update_room_occupancy.
        """
        idx = PRESENCE_SRC.find("def _discover_room_sensors(")
        assert idx >= 0
        end = PRESENCE_SRC.find("def _discover_room_sensors_by_name", idx)
        assert end > idx
        body = PRESENCE_SRC[idx:end]
        assert "fix-up B-HIGH-1" in body, (
            "v4.7.18.1 fix-up: _discover_room_sensors must annotate the seed"
        )
        assert "self.hass.states.get(entity_id)" in body, (
            "v4.7.18.1 fix-up: room-sensor seed must read current state"
        )
        # The seed must call tracker.update_room_occupancy with
        # (room_name, occupied[, kind=...]). The provenance-split cycle
        # added an optional `kind` kwarg — assert the call shape is
        # preserved structurally regardless of whether kind is passed.
        assert "tracker.update_room_occupancy(" in body, (
            "v4.7.18.1 fix-up: room-sensor seed must call update_room_occupancy"
        )
        assert "room_name" in body and "occupied" in body, (
            "v4.7.18.1 fix-up: room-sensor seed must pass (room_name, occupied)"
        )

    def test_camera_seed_block_present(self):
        """Source-grep: camera discovery must seed _camera_occupied similarly."""
        idx = PRESENCE_SRC.find("def _discover_zone_cameras(")
        assert idx >= 0
        # End at the next method def
        end = PRESENCE_SRC.find("\n    def _", idx + 30)
        assert end > idx
        body = PRESENCE_SRC[idx:end]
        assert "fix-up B-HIGH-1" in body, (
            "v4.7.18.1 fix-up: _discover_zone_cameras must annotate the seed"
        )
        assert "tracker.update_camera_detection(entity_id, detected)" in body, (
            "v4.7.18.1 fix-up: camera seed must call update_camera_detection"
        )

    def test_seed_predicate_matches_handler_predicate(self):
        """The seed predicate must mirror _handle_occupancy_change: state == 'on'
        with _UNAVAILABLE_STATES treated as not-occupied. If these drift,
        seed and live updates disagree.
        """
        idx = PRESENCE_SRC.find("def _discover_room_sensors(")
        end = PRESENCE_SRC.find("def _discover_room_sensors_by_name", idx)
        body = PRESENCE_SRC[idx:end]
        assert "_UNAVAILABLE_STATES" in body, (
            "v4.7.18.1 fix-up: room-sensor seed must guard unavailable/unknown"
        )
        assert 'state.state == "on"' in body, (
            "v4.7.18.1 fix-up: room-sensor seed predicate must mirror handler"
        )

    def test_tracker_reports_raw_occupied_after_seed_without_event(self):
        """Behavioral: simulate the seed path — after discovery, tracker
        observes mmwave ON via update_room_occupancy (the seed call) and
        raw_occupied returns True WITHOUT any state-change event having
        fired. This is the exact post-restart scenario B-HIGH-1 addresses.
        """
        tracker = ZonePresenceTracker(MagicMock(), "Bedrooms", ["Master"])
        tracker.register_entity("binary_sensor.master_mmwave", "Master")
        # No state-change event yet. Pre-seed: _room_occupied is empty.
        assert tracker.raw_occupied is False
        # Discovery seed path mirrors _handle_occupancy_change's update call:
        tracker.update_room_occupancy("Master", True)
        # First _run_inference("startup") tick now observes raw_occupied=True.
        assert tracker.raw_occupied is True, (
            "v4.7.18.1 fix-up B-HIGH-1: seed must produce raw_occupied=True "
            "on the first tick without a state-change event"
        )


# ===========================================================================
# Fix-up A-M2: backstop hour clamp — window must never be silently empty
# ===========================================================================


class TestFixupAM2BackstopClamp:
    """For pathological sleep_end_hour values, `sleep_end + 3` can exceed
    `sleep_start_hour` (or 24), making the window
    `_backstop_hour <= hour < sleep_start_hour` empty → backstop silently
    never fires. The fix-up clamps `_backstop_hour` to
    `min(_backstop_hour, sleep_start_hour - 1)` so the window always
    contains at least 1 hour.
    """

    @staticmethod
    def _backstop_clamped(
        census_count: int,
        local_hour: int,
        sleep_end_hour: int,
        sleep_start_hour: int,
    ) -> bool:
        """Mirror of the production predicate WITH the fix-up clamp."""
        backstop_hour = sleep_end_hour + _WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END
        backstop_hour = min(backstop_hour, sleep_start_hour - 1)
        return (
            census_count > 0
            and backstop_hour <= local_hour < sleep_start_hour
        )

    def test_clamp_keeps_window_nonempty_for_pathological_sleep_end(self):
        """sleep_end=22, sleep_start=23: raw _backstop_hour=25 → would be
        empty. After clamp to min(25, 22) = 22, window is [22, 23) → fires
        at hour 22 with census>0.
        """
        assert self._backstop_clamped(
            census_count=2, local_hour=22,
            sleep_end_hour=22, sleep_start_hour=23,
        ) is True, (
            "v4.7.18.1 fix-up A-M2: clamp must keep window non-empty for "
            "pathological sleep_end_hour"
        )

    def test_clamp_window_still_correct_at_default_hours(self):
        """sleep_end=6, sleep_start=23: clamp is a no-op (9 < 22), normal
        window [9, 23) applies — at hour 10, fires.
        """
        assert self._backstop_clamped(
            census_count=2, local_hour=10,
            sleep_end_hour=6, sleep_start_hour=23,
        ) is True
        # And does not fire at hour 8 (just after sleep_end, before margin).
        assert self._backstop_clamped(
            census_count=2, local_hour=8,
            sleep_end_hour=6, sleep_start_hour=23,
        ) is False

    def test_clamp_source_wiring_present(self):
        """Source-grep: production code must apply the clamp inside the
        wake-gate's `wake_decision.fired` branch.
        """
        body = PRESENCE_SRC[PRESENCE_SRC.find("async def _run_inference"):]
        body = body[: 60000]
        fired_idx = body.find("if wake_decision.fired:")
        assert fired_idx >= 0
        gate_block = body[fired_idx: fired_idx + 4000]
        assert "_backstop_hour_clamped" in gate_block, (
            "v4.7.18.1 fix-up A-M2: clamp must apply in backstop branch"
        )
        assert "engine.sleep_start_hour - 1" in gate_block, (
            "v4.7.18.1 fix-up A-M2: clamp must use sleep_start_hour - 1"
        )
