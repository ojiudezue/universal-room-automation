"""Cycle 2 (exterior track linking) tests.

Covers the four cycle-2 load-bearing sites:

  1. Deep-night vehicle policy: car-label event on a perimeter camera
     dispatches HIGH NM alert only when inside the deep-night window AND
     house_state ∈ EXTERIOR_VEHICLE_ALERT_STATES. Outside those gates the
     event still feeds the linker (census) but no NM push.
  2. Seam-split telemetry: a new track opening 2 graph-hops from an open
     same-label track's last hop increments the per-(A,B) seam counter,
     surfaced via linker.seam_split_snapshot().
  3. Fused perimeter sensor sourcing: the same physical event visible on
     both the F1 base sensor AND the F2 `_2` sibling produces exactly ONE
     alert (per-camera cooldown gate dedups).
  4. Animal wiring: an animal binary-sensor rising edge feeds the linker
     (census counter goes up) but NEVER dispatches NM.

Each test is designed to red under a single-site source mutation so the
mutation ledger has an anchored per-site failure.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# Reuse the perimeter test module's HA stubs — its module-level import wires
# the homeassistant.* stubs and pins scheduler/dt onto perimeter_alert.
# Loading it first sets up ambient state we then reuse.
sys.path.insert(0, os.path.dirname(__file__))
import test_perimeter_alert_nm_routing as _pa_mod  # noqa: E402

# Load the linker under the same package to share consts/adjacency.
_ura_path = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation",
)


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_etl = _load(
    "custom_components.universal_room_automation.exterior_track_linker",
    os.path.join(_ura_path, "exterior_track_linker.py"),
)

PerimeterAlertManager = _pa_mod.PerimeterAlertManager
Severity = _pa_mod.Severity
_const = _pa_mod._const
_make_hass = _pa_mod._make_hass


def _run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

class _FakeLinkerHass:
    def __init__(self):
        self.data = {}
        self.bus = MagicMock()
        self.bus.async_listen = MagicMock(return_value=lambda: None)

        def _create_task(coro):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            return loop.create_task(coro)

        self.async_create_task = _create_task


def _make_linker(adjacency=None):
    lk = _etl.ExteriorTrackLinker(_FakeLinkerHass())
    if adjacency is not None:
        lk.set_adjacency(adjacency)
    return lk


# ==================================================================
# 1. Deep-night vehicle policy
# ==================================================================

def _install_time(mgr, hour: int):
    """Pin dt_util.now on the perimeter module to a specific hour."""
    base = datetime(2026, 8, 6, hour, 30, 0, tzinfo=timezone.utc)
    _pa_mod._perimeter.dt_util.now = lambda: base
    # Pretend setup was long enough ago that the boot-settle gate passes.
    mgr._setup_time = base - timedelta(minutes=5)
    return base


def test_vehicle_night_window_computation():
    """_in_vehicle_night_window is inclusive at start, exclusive at end,
    wraps at midnight when start >= end (constants default 22-06).
    """
    hass, _ = _make_hass()
    mgr = _run(_pa_mod._setup_mgr(hass))
    # Constants: 22 <= h or h < 6.
    for h, want in [
        (0, True), (5, True), (6, False), (12, False),
        (21, False), (22, True), (23, True),
    ]:
        assert mgr._in_vehicle_night_window(
            datetime(2026, 8, 6, h, 30, 0)
        ) is want, f"hour {h}"


def test_vehicle_deep_night_away_dispatches_high():
    hass, nm = _make_hass(house_state="away")
    mgr = _run(_pa_mod._setup_mgr(hass))
    _install_time(mgr, 2)  # 02:30 = deep night
    _run(mgr._async_handle_vehicle_trigger(
        "binary_sensor.front_yard_vehicle_detected"
    ))
    assert nm.async_notify.await_count == 1
    kw = nm.async_notify.await_args.kwargs
    assert kw["severity"] == Severity.HIGH
    assert kw["location"] == "front_yard"
    assert "Vehicle" in kw["title"]


def test_vehicle_daytime_away_no_dispatch():
    """Same event outside deep-night → no NM push (digest-only)."""
    hass, nm = _make_hass(house_state="away")
    mgr = _run(_pa_mod._setup_mgr(hass))
    _install_time(mgr, 14)  # 2pm
    _run(mgr._async_handle_vehicle_trigger(
        "binary_sensor.front_yard_vehicle_detected"
    ))
    assert nm.async_notify.await_count == 0


def test_vehicle_deep_night_home_day_no_dispatch():
    """Deep-night but house_state not in EXTERIOR_VEHICLE_ALERT_STATES."""
    hass, nm = _make_hass(house_state="home_day")
    mgr = _run(_pa_mod._setup_mgr(hass))
    _install_time(mgr, 2)
    _run(mgr._async_handle_vehicle_trigger(
        "binary_sensor.front_yard_vehicle_detected"
    ))
    assert nm.async_notify.await_count == 0


def test_vehicle_cooldown_per_camera_independent_of_person():
    """Vehicle cooldown must be a separate namespace from person cooldown."""
    hass, nm = _make_hass(house_state="away")
    mgr = _run(_pa_mod._setup_mgr(hass))
    _install_time(mgr, 2)
    _run(mgr._async_handle_vehicle_trigger(
        "binary_sensor.front_yard_vehicle_detected"
    ))
    # Second call within cooldown → suppressed.
    _run(mgr._async_handle_vehicle_trigger(
        "binary_sensor.front_yard_vehicle_detected"
    ))
    assert nm.async_notify.await_count == 1
    # But a person trigger on the same camera is unaffected — the vehicle
    # cooldown does not touch _last_alert (person namespace).
    assert "front_yard" not in mgr._last_alert


def test_severity_map_car_away_pass_by_is_high():
    """Map surgery anchor: car/away/pass_by must be HIGH (cycle 2 change)."""
    m = _const.NM_HAZARD_EXTERIOR_TRACK_SEVERITY_MAP
    assert m["car"]["away"]["pass_by"] == "HIGH"
    assert m["car"]["sleep"]["pass_by"] == "HIGH"
    # Daytime remains digest/low so the map alone can't fire big alerts
    # (the night-window gate lives in perimeter_alert code).
    assert m["car"]["home_day"]["pass_by"] == "DIGEST"


# ==================================================================
# 2. Seam-split telemetry
# ==================================================================

def test_seam_split_records_two_hop_gap():
    """New track opens on camera 2 graph-hops from an open track's last
    hop → seam counter increments and is surfaced via seam_split_snapshot.

    Chain A—M—B where A and B are NOT directly adjacent but share M.
    """
    lk = _make_linker({
        "a": ["m"],
        "m": ["a", "b"],
        "b": ["m"],
        # unrelated island so `b` is not directly adjacent to `a`.
    })
    t0 = datetime(2026, 8, 6, 12, 0, 0)
    lk.observe("a", "person", None, 0.9, None, t0)
    # 60s later, event on b. Not adjacent to a (2-hop via m). Should open
    # a NEW track AND record the (a,b) seam.
    lk.observe("b", "person", None, 0.9, None, t0 + timedelta(seconds=60))
    snap = lk.seam_split_snapshot()
    assert snap.get("a→b") == 1, snap
    # Direct adjacency does NOT count.
    lk2 = _make_linker({"a": ["b"], "b": ["a"]})
    lk2.observe("a", "person", None, 0.9, None, t0)
    lk2.observe("b", "person", None, 0.9, None, t0 + timedelta(seconds=1000))
    # Long delta beyond link window → new track, but a-b is directly
    # adjacent so no seam-split recorded.
    assert lk2.seam_split_snapshot() == {}


def test_seam_split_does_not_change_track_topology():
    """Observability only — the linker still opens a new track, does not
    magically extend the old one, and no adjacency edge is added."""
    lk = _make_linker({"a": ["m"], "m": ["a", "b"], "b": ["m"]})
    t0 = datetime(2026, 8, 6, 12, 0, 0)
    lk.observe("a", "person", None, 0.9, None, t0)
    lk.observe("b", "person", None, 0.9, None, t0 + timedelta(seconds=60))
    counts = lk.census_counts()
    assert counts["exterior_person_tracks_active"] == 2
    # Adjacency table is unchanged (b still not in a's neighbors).
    assert "b" not in lk._adjacency.get("a", set())


# ==================================================================
# 3. Fused sourcing dedup
# ==================================================================

def test_camera_key_collapses_fused_sensors():
    """Base and `_2` sibling produce the same camera key (cooldown collapse)."""
    hass, _ = _make_hass()
    mgr = _run(_pa_mod._setup_mgr(hass))
    k1 = mgr._camera_key_for_sensor("binary_sensor.back_yard_person_occupancy")
    k2 = mgr._camera_key_for_sensor(
        "binary_sensor.back_yard_person_occupancy_2"
    )
    assert k1 == k2 == "back_yard"
    # Vehicle + animal siblings collapse to the same key too.
    assert mgr._camera_key_for_sensor(
        "binary_sensor.back_yard_vehicle_detected"
    ) == "back_yard"
    assert mgr._camera_key_for_sensor(
        "binary_sensor.back_yard_vehicle_detected_2"
    ) == "back_yard"
    assert mgr._camera_key_for_sensor(
        "binary_sensor.back_yard_animal_detected"
    ) == "back_yard"


def test_fused_sourcing_one_physical_event_one_alert():
    """F1 and F2 both fire — per-camera cooldown yields one NM dispatch."""
    hass, nm = _make_hass(house_state="away")
    mgr = _run(_pa_mod._setup_mgr(hass))
    # First trigger (F1 base sensor).
    _run(mgr._async_handle_perimeter_trigger(
        "binary_sensor.front_yard_person_occupancy"
    ))
    # Second trigger (F2 `_2` sibling) within cooldown → suppressed by
    # camera-key cooldown collapse.
    _run(mgr._async_handle_perimeter_trigger(
        "binary_sensor.front_yard_person_occupancy_2"
    ))
    assert nm.async_notify.await_count == 1
    assert "front_yard" in mgr._last_alert


# ==================================================================
# 4. Animal wiring
# ==================================================================

def test_animal_feed_linker_no_nm_dispatch():
    """Animal rising edge feeds linker (census +1) and never pushes NM."""
    hass, nm = _make_hass(house_state="away")
    mgr = _run(_pa_mod._setup_mgr(hass))
    # Install a linker so _feed_linker exercises real code.
    lk = _make_linker({"front_yard": []})
    hass.data[_const.DOMAIN]["exterior_track_linker"] = lk
    mgr._feed_linker(
        "binary_sensor.front_yard_animal_detected", "animal",
    )
    counts = lk.census_counts()
    assert counts["exterior_animal_tracks_active"] == 1
    assert nm.async_notify.await_count == 0


# ==================================================================
# Mutation-hygiene anchors (source-level; would red under load-bearing
# site mutation with pycache cleared).
# ==================================================================

def test_source_anchor_night_window_gate_present():
    src = open(os.path.join(_ura_path, "perimeter_alert.py")).read()
    assert "_in_vehicle_night_window(now)" in src, (
        "vehicle deep-night gate expression missing"
    )
    assert "EXTERIOR_VEHICLE_ALERT_STATES" in src


def test_source_anchor_seam_split_call_site():
    src = open(os.path.join(_ura_path, "exterior_track_linker.py")).read()
    assert "_record_seam_split_if_any" in src
    # Must be called at the NEW-track site (before the ExteriorTrack ctor).
    idx_call = src.find("self._record_seam_split_if_any(")
    idx_new = src.find("track = ExteriorTrack(", idx_call)
    assert idx_call != -1 and idx_new != -1 and idx_call < idx_new


def test_source_anchor_fused_cooldown_key():
    src = open(os.path.join(_ura_path, "perimeter_alert.py")).read()
    assert (
        "cooldown_key = self._camera_key_for_sensor(entity_id) or entity_id"
        in src
    ), "cooldown-by-camera-key line missing"
    # And the reservation must be by cooldown_key, not entity_id.
    assert "self._last_alert[cooldown_key] = now" in src
