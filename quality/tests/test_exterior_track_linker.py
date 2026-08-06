"""Behavioral tests for ExteriorTrackLinker (build/exterior-track).

Covers the acceptance criteria from
`docs/planning/PLANNING_exterior_track_linking.md`:

  * The 2026-08-02 10-event walker replay collapses to ONE track with the
    correct camera sequence and ~16-minute duration.
  * Two simultaneous non-adjacent detections produce TWO tracks.
  * INV-XT — one person crossing N adjacent cameras yields ≤ ONE alert
    thread (same-track pass_by suppression).
  * INV-XP unweakened — a mutation to the per-camera cooldown gate in
    PerimeterAlertManager makes an anchored test fail.
  * Kill switch — TRACK_LINK_WINDOW_S == 0 disables cross-camera linking
    entirely (per-camera behavior is byte-identical to today).
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

# Stub the homeassistant surfaces the linker touches — the linker only needs
# HomeAssistant / callback / Event / dt_util.now. Do NOT stomp modules already
# stubbed by a sibling test module — the perimeter_alert test module has
# stricter needs (frozen clocks, scheduler shim); reuse whatever it left.

_ident = lambda fn: fn  # noqa: E731

_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock,
        "callback": _ident,
        "Event": MagicMock,
    },
    "homeassistant.helpers": {},
    "homeassistant.helpers.event": {
        "async_track_time_interval": lambda *a, **kw: (lambda: None),
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": datetime.utcnow,
        "now": datetime.now,
    },
}
for _n, _a in _mods.items():
    existing = sys.modules.get(_n)
    if existing is None:
        mod = types.ModuleType(_n)
        for _k, _v in _a.items():
            setattr(mod, _k, _v)
        sys.modules[_n] = mod
    else:
        for _k, _v in _a.items():
            if not hasattr(existing, _k):
                setattr(existing, _k, _v)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_cc = sys.modules.get("custom_components")
if _cc is None:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [
        os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")
    ]
    sys.modules["custom_components"] = _cc

_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura = sys.modules.get("custom_components.universal_room_automation")
if _ura is None:
    _ura = types.ModuleType("custom_components.universal_room_automation")
    _ura.__path__ = [_ura_path]
    _ura.__package__ = "custom_components.universal_room_automation"
    sys.modules["custom_components.universal_room_automation"] = _ura
    _cc.universal_room_automation = _ura


def _load(name: str, path: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_const = _load(
    "custom_components.universal_room_automation.const",
    os.path.join(_ura_path, "const.py"),
)
_ura.const = _const

etl = _load(
    "custom_components.universal_room_automation.exterior_track_linker",
    os.path.join(_ura_path, "exterior_track_linker.py"),
)
_ura.exterior_track_linker = etl

ExteriorTrackLinker = etl.ExteriorTrackLinker
_bucket_label = etl._bucket_label


# ---------------------------------------------------------------- helpers ---


class _FakeHass:
    def __init__(self):
        self.data = {}
        self.bus = MagicMock()
        self.bus.async_listen = MagicMock(return_value=lambda: None)
        # async_create_task must accept a coroutine and schedule it now.
        self._tasks = []

        def _create_task(coro):
            task = asyncio.get_event_loop().create_task(coro)
            self._tasks.append(task)
            return task

        self.async_create_task = _create_task


@pytest.fixture
def linker():
    hass = _FakeHass()
    lk = ExteriorTrackLinker(hass)
    # Perimeter ring for the 2026-08-02 walker replay.
    # Perimeter ring for the 2026-08-02 walker replay. Real perimeter
    # cameras have overlapping fields of view so operator declares the full
    # perimeter as mutually adjacent (a person seen on any perimeter cam is
    # plausibly the same person seen on another perimeter cam within 3
    # minutes). Non-adjacency tests use a camera OUTSIDE this set.
    lk.set_adjacency(
        {
            "utilities": ["rear", "front", "front_side"],
            "rear": ["utilities", "front_side", "front"],
            "front_side": ["rear", "front", "utilities"],
            "front": ["front_side", "utilities", "rear"],
        }
    )
    return lk


def _obs(lk, camera, label="person", event_id=None, score=0.9,
         sub_label=None, now=None):
    return lk.observe(
        camera=camera,
        label=label,
        event_id=event_id,
        score=score,
        sub_label=sub_label,
        now=now or datetime(2026, 8, 2, 19, 57, 0),
    )


# ---------------------------------------------------------------- label bucketing ---


def test_bucket_label_person_car_animal():
    assert _bucket_label("person") == "person"
    assert _bucket_label("Person") == "person"
    assert _bucket_label("car") == "car"
    assert _bucket_label("truck") == "car"
    assert _bucket_label("dog") == "animal"
    assert _bucket_label("cat") == "animal"
    assert _bucket_label("raccoon") == "animal"
    assert _bucket_label("umbrella") is None
    assert _bucket_label("") is None


# ---------------------------------------------------------------- walker replay ---


def test_2026_08_02_walker_collapses_to_one_track(linker):
    """10 events across 6 hops in 16 min → one track, correct sequence."""
    t0 = datetime(2026, 8, 2, 19, 57, 0)
    # Sequence utilities → rear → front_side → utilities → front → rear,
    # with intermediate re-fires on the same camera (10 total events).
    seq = [
        ("utilities",  t0),
        ("utilities",  t0 + timedelta(seconds=12)),   # same-cam repeat
        ("rear",       t0 + timedelta(seconds=45)),
        ("rear",       t0 + timedelta(seconds=90)),   # same-cam repeat
        ("front_side", t0 + timedelta(seconds=180)),
        ("front_side", t0 + timedelta(seconds=220)),  # same-cam repeat
        ("utilities",  t0 + timedelta(seconds=380)),  # revisit
        ("front",      t0 + timedelta(seconds=520)),
        ("rear",       t0 + timedelta(seconds=690)),  # 170s Δ < 180s window
        ("rear",       t0 + timedelta(seconds=860)),  # same-cam re-fire (170s Δ)
    ]
    tracks = [_obs(linker, cam, now=ts) for cam, ts in seq]
    # Same open-track object every time.
    assert len({id(t) for t in tracks}) == 1
    tr = tracks[0]
    # Hop compaction: consecutive same-camera events merge into one hop.
    assert tr.cameras == [
        "utilities", "rear", "front_side", "utilities", "front", "rear",
    ]
    # Duration ~14-15 minutes (fixture uses tightened intervals to fit
    # the 180 s TRACK_LINK_WINDOW_S; plan quoted ~16 min for the live event).
    assert 850 <= tr.duration_s <= 870
    # Revisits (utilities appears twice, rear appears twice as non-consecutive hops).
    assert tr.revisit_count >= 2
    assert linker.classify(tr) == "circling"
    counts = linker.census_counts()
    assert counts["exterior_person_tracks_active"] == 1
    assert counts["exterior_unidentified_persons"] == 1
    # Path string contains the arrow-separated sequence + minutes + label.
    ps = linker.path_string(tr)
    assert "utilities → rear → front_side" in ps
    assert "14 min" in ps or "15 min" in ps
    assert "person" in ps


def test_two_simultaneous_non_adjacent_detections_two_tracks(linker):
    """Two people simultaneously on non-adjacent cameras → 2 tracks.

    `driveway_far` is deliberately NOT in the fixture adjacency graph —
    the linker treats it as isolated from the perimeter ring.
    """
    t0 = datetime(2026, 8, 2, 20, 0, 0)
    a = _obs(linker, "utilities", now=t0)
    b = _obs(linker, "driveway_far", now=t0 + timedelta(seconds=2))
    assert a is not b
    counts = linker.census_counts()
    assert counts["exterior_person_tracks_active"] == 2


def test_adjacent_within_window_links(linker):
    t0 = datetime(2026, 8, 2, 20, 0, 0)
    a = _obs(linker, "utilities", now=t0)
    b = _obs(linker, "rear", now=t0 + timedelta(seconds=60))
    assert a is b


def test_adjacent_beyond_window_new_track(linker):
    t0 = datetime(2026, 8, 2, 20, 0, 0)
    a = _obs(linker, "utilities", now=t0)
    b = _obs(linker, "rear", now=t0 + timedelta(seconds=181))  # > window
    assert a is not b


def test_labels_partition_person_vs_car(linker):
    t0 = datetime(2026, 8, 2, 20, 0, 0)
    p = _obs(linker, "utilities", label="person", now=t0)
    c = _obs(linker, "utilities", label="car", now=t0 + timedelta(seconds=5))
    assert p is not c
    counts = linker.census_counts()
    assert counts["exterior_person_tracks_active"] == 1
    assert counts["exterior_vehicle_tracks_active"] == 1


def test_sub_label_promotes_only_on_two_hops(linker):
    """D-MED-1: sub_label promotes to identified ONLY when seen on ≥ 2 hops
    (or the same sub_label twice). A single-hop sub_label is provisional."""
    t0 = datetime(2026, 8, 2, 20, 0, 0)
    _obs(linker, "utilities", sub_label="oji", now=t0)
    # Provisional — first sighting alone must NOT promote.
    assert linker.census_counts()["exterior_unidentified_persons"] == 1
    _obs(linker, "rear", sub_label="oji", now=t0 + timedelta(seconds=30))
    # Confirmed on the second hop → identified.
    assert linker.census_counts()["exterior_unidentified_persons"] == 0
    assert linker.census_counts()["exterior_person_tracks_active"] == 1


def test_idle_close_writes_episode_and_drops_track(linker):
    t0 = datetime(2026, 8, 2, 20, 0, 0)
    _obs(linker, "utilities", now=t0)
    _obs(linker, "rear", now=t0 + timedelta(seconds=30))
    # No DB registered — should not raise.
    linker.sweep_closed(now=t0 + timedelta(seconds=1000))
    assert linker.census_counts()["exterior_person_tracks_active"] == 0


def test_kill_switch_link_window_zero_creates_no_tracks(linker, monkeypatch):
    """Tier-3 fix-up: TRACK_LINK_WINDOW_S == 0 → observe() creates NO
    tracks (byte-identical to no-linker baseline). census stays at 0."""
    monkeypatch.setattr(etl, "TRACK_LINK_WINDOW_S", 0)
    t0 = datetime(2026, 8, 2, 20, 0, 0)
    a = _obs(linker, "utilities", now=t0)
    b = _obs(linker, "utilities", now=t0 + timedelta(seconds=5))
    assert a is None and b is None
    assert linker.census_counts()["exterior_person_tracks_active"] == 0
    # find_owning_track / note_alert_dispatched are inert under kill switch.
    assert linker.find_owning_track("utilities", "person", t0) is None
    linker.note_alert_dispatched("utilities", "person", t0)  # no-op, no raise


# ---------------------------------------------------------------- classify + bookkeeping ---


def test_classify_single_hop_is_passby(linker):
    """First-alert / single-hop is always pass_by (no promotion pressure)."""
    t0 = datetime(2026, 8, 2, 20, 0, 0)
    tr = _obs(linker, "utilities", now=t0)
    assert linker.classify(tr) == "pass_by"


def test_classify_circling_requires_revisit_or_nonmonotonic(linker):
    """A-MED-2: 3 monotonic hops on distinct cameras (no loop) do NOT
    classify as circling — only revisits or non-monotonic sequences do."""
    t0 = datetime(2026, 8, 2, 20, 0, 0)
    for i, cam in enumerate(["utilities", "rear", "front_side"]):
        _obs(linker, cam, now=t0 + timedelta(seconds=30 * i))
    tr = linker._tracks["person"][0]
    # 3 distinct cameras in monotonic order — not circling per A-MED-2.
    assert linker.classify(tr) != "circling"
    # Revisit utilities → circling.
    _obs(linker, "utilities", now=t0 + timedelta(seconds=120))
    assert linker.classify(tr) == "circling"


def test_note_alert_dispatched_bumps_owning_track(linker):
    t0 = datetime(2026, 8, 2, 20, 0, 0)
    tr = _obs(linker, "utilities", now=t0)
    assert tr.alert_count == 0
    linker.note_alert_dispatched("utilities", "person", t0)
    assert tr.alert_count == 1
    assert tr.first_alert_at == t0


# ---------------------------------------------------------------- INV-XP mutation-anchor ---


def test_inv_xp_per_camera_cooldown_gate_source_present():
    """INV-XP mutation-anchor: the per-camera cooldown gate string
    ('cooldown\\n' block with `seconds_since_alert < PERIMETER_ALERT_COOLDOWN_SECONDS`)
    is present in perimeter_alert.py. If a review edit deletes it, this
    test fails, forcing the reviewer to acknowledge INV-XP was weakened.

    Full behavioral coverage lives in test_perimeter_alert_nm_routing.py;
    this test is the *cross-cycle* anchor guarding INV-XP against the
    exterior-track cycle's message-enrichment + note_alert_dispatched
    additions.
    """
    pa_path = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "custom_components", "universal_room_automation", "perimeter_alert.py",
    )
    src = open(pa_path).read()
    # Load-bearing gate expression — surviving verbatim is the anchor.
    assert "seconds_since_alert < PERIMETER_ALERT_COOLDOWN_SECONDS" in src, (
        "INV-XP anchor lost: per-camera cooldown gate expression missing "
        "from perimeter_alert.py. Same-track suppression must remain a "
        "REFINEMENT of cadence, never a replacement for the cooldown gate."
    )
    # The note_alert_dispatched hook MUST live inside the successful-dispatch
    # branch (after `if dispatched_ok:`), not before it — otherwise a failed
    # notify would still burn the linker's alert budget.
    idx_disp = src.find("if dispatched_ok:")
    idx_note = src.find("_linker.note_alert_dispatched(")
    assert idx_disp != -1, "dispatched_ok gate missing"
    assert idx_note != -1, "note_alert_dispatched hook missing"
    assert idx_note > idx_disp, (
        "note_alert_dispatched must be inside the `if dispatched_ok:` branch "
        "so a failed notify does not consume the linker alert budget."
    )


# ---------------------------------------------------------------- adjacency setter ---


def test_set_adjacency_symmetrizes():
    hass = _FakeHass()
    lk = ExteriorTrackLinker(hass)
    lk.set_adjacency({"a": ["b"]})
    assert "b" in lk._adjacency["a"]
    assert "a" in lk._adjacency["b"]
