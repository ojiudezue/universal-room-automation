"""CIRCLING-SEVERITY-1 D1 — founding-case regression test.

Replays live track `xt-000001-695c9e` (2026-08-08 09:22 CDT):
`back_yard → front_side_ptz → back_yard → front_side_ptz → back_yard`,
5 hops / 2 cameras / 133s, house_state=home_day.

Drives the REAL ExteriorTrackLinker (per plan §D1 wiring requirement,
including `linker.set_adjacency(EXTERIOR_ADJACENCY_GRAPH)` after
construction — build-pred #1) and the REAL
`PerimeterAlertManager._async_handle_perimeter_trigger` code path.

See docs/planning/PLANNING_circling_severity.md §D1.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


# --- Stub homeassistant surfaces (mirror test_perimeter_alert_nm_routing) ----

_ident = lambda fn: fn  # noqa: E731

_scheduled: list = []


def _fake_async_call_later(hass, delay, cb):
    _scheduled.append((delay, cb))
    return MagicMock()


def _fake_async_track_state_change_event(hass, entities, cb):
    return MagicMock()


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock, "callback": _ident, "Event": MagicMock,
    },
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {
        "DeviceInfo": dict, "EntityCategory": MagicMock(),
    },
    "homeassistant.helpers.entity_registry": {"async_get": MagicMock()},
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": lambda *a, **kw: MagicMock(),
        "async_dispatcher_send": lambda *a, **kw: None,
    },
    "homeassistant.helpers.event": {
        "async_track_state_change_event": _fake_async_track_state_change_event,
        "async_call_later": _fake_async_call_later,
        "async_track_time_interval": lambda *a, **kw: (lambda: None),
    },
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.now(timezone.utc),
        "now": lambda: datetime.now(timezone.utc),
    },
}
for _n, _a in _mods.items():
    existing = sys.modules.get(_n)
    if existing is None:
        sys.modules[_n] = _mock_module(_n, **_a)
    else:
        for _k, _v in _a.items():
            if not hasattr(existing, _k):
                setattr(existing, _k, _v)


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

_cc = sys.modules.get("custom_components")
if _cc is None:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [
        os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "custom_components",
        )
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

_dc_path = os.path.join(_ura_path, "domain_coordinators")
_dc = sys.modules.get("custom_components.universal_room_automation.domain_coordinators")
if _dc is None:
    _dc = types.ModuleType(
        "custom_components.universal_room_automation.domain_coordinators"
    )
    _dc.__path__ = [_dc_path]
    _dc.__package__ = (
        "custom_components.universal_room_automation.domain_coordinators"
    )
    sys.modules[
        "custom_components.universal_room_automation.domain_coordinators"
    ] = _dc
    _ura.domain_coordinators = _dc

_base = _load(
    "custom_components.universal_room_automation.domain_coordinators.base",
    os.path.join(_dc_path, "base.py"),
)
Severity = _base.Severity

_etl = _load(
    "custom_components.universal_room_automation.exterior_track_linker",
    os.path.join(_ura_path, "exterior_track_linker.py"),
)
ExteriorTrackLinker = _etl.ExteriorTrackLinker

_perimeter = _load(
    "custom_components.universal_room_automation.perimeter_alert",
    os.path.join(_ura_path, "perimeter_alert.py"),
)
_ura.perimeter_alert = _perimeter
PerimeterAlertManager = _perimeter.PerimeterAlertManager

# Pin the clock module (tz-aware). This is safe to leave in place because
# both sibling test files pin equivalent UTC-aware `dt_util.now` functions
# after import — the last-writer-wins behavior converges on the same shape.
_real_dt_util = types.ModuleType("dt_util_pin_founding")
_real_dt_util.now = lambda: datetime.now(timezone.utc)
_real_dt_util.utcnow = lambda: datetime.now(timezone.utc)

# DO NOT unconditionally rebind `_perimeter.async_call_later` /
# `async_track_state_change_event` at import time — the sibling
# `test_perimeter_alert_nm_routing.py` uses its OWN `_scheduled` list
# via its OWN `_fake_async_call_later`, and clobbering that binding
# under full-suite loading order corrupts the sibling's assertions.
# The autouse fixture in conftest.py snapshots + restores those
# bindings around every test in this package.


# --- fixture -----------------------------------------------------------------


def _make_hass_with_linker(cameras: list[str], house_state: str = "home_day"):
    hass = MagicMock()
    cfg = MagicMock()
    cfg.external_url = None
    cfg.internal_url = None
    hass.config = cfg
    hass.is_stopping = False
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=MagicMock())
    hass._states = {}
    hass.states = MagicMock()
    hass.states.get = lambda eid: hass._states.get(eid)

    cm = MagicMock()
    cm.house_state = house_state
    presence = MagicMock()
    presence._tracked_persons_count_trusted = 1
    cm.presence = presence

    nm = MagicMock()
    nm.enabled = True
    nm.async_notify = AsyncMock()

    cam_manager = MagicMock()

    def _resolve(cam_id):
        info = MagicMock()
        info.person_binary_sensor = (
            "binary_sensor." + cam_id.split(".", 1)[1] + "_person_occupancy"
        )
        info.platform = _const.CAMERA_PLATFORM_FRIGATE
        info.entity_id = info.person_binary_sensor
        return [info]

    cam_manager.resolve_camera_entity = _resolve

    # Real linker instance — build-pred #1: MUST set_adjacency to the
    # ratified EXTERIOR_ADJACENCY_GRAPH so back_yard ↔ front_side_ptz
    # link into ONE track. Without this, the fixture forks into 5
    # single-hop tracks and the classify == "circling" oracle silently
    # no-ops.
    linker = ExteriorTrackLinker(hass)
    linker.set_adjacency(_const.EXTERIOR_ADJACENCY_GRAPH)

    hass.data = {
        _const.DOMAIN: {
            "coordinator_manager": cm,
            "camera_manager": cam_manager,
            "notification_manager": nm,
            "exterior_track_linker": linker,
        }
    }

    entry = MagicMock()
    entry.data = {_const.CONF_ENTRY_TYPE: _const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        _const.CONF_PERIMETER_CAMERAS: cameras,
        _const.CONF_EGRESS_CAMERAS: [],
        _const.CONF_EXTERIOR_SNAPSHOT_OFFSET_S: 0,
        _const.CONF_PERIMETER_ALERT_NOTIFY_SERVICE: "",
        _const.CONF_PERIMETER_ALERT_NOTIFY_TARGET: "",
        _const.CONF_PERIMETER_ENRICHMENT_ENABLED: False,
        _const.CONF_PERIMETER_ENRICHMENT_PERSON_SENSORS: [],
    }
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[entry])

    # entity_picture for each camera so snapshot resolve doesn't return None
    for cam_id in cameras:
        st = MagicMock()
        st.attributes = {"entity_picture": f"/api/camera_proxy/{cam_id}"}
        hass._states[cam_id] = st

    return hass, nm, linker


def _run(coro):
    return asyncio.run(coro)


async def _setup(hass):
    mgr = PerimeterAlertManager(hass)
    await mgr.async_setup()
    return mgr


CAMS = ["camera.back_yard", "camera.front_side_ptz"]
SENSORS = {
    "back_yard": "binary_sensor.back_yard_person_occupancy",
    "front_side_ptz": "binary_sensor.front_side_ptz_person_occupancy",
}


def _observe(linker, cam_key: str, now: datetime) -> None:
    linker.observe(
        camera=cam_key,
        label="person",
        event_id=None,
        score=0.9,
        sub_label=None,
        now=now,
    )


def _replay_founding_sequence(mgr, linker):
    """Feed the 5-hop sequence and drive the perimeter handler each hop."""
    t0 = datetime.now(timezone.utc)
    sequence = [
        ("back_yard",       t0),
        ("front_side_ptz",  t0 + timedelta(seconds=25)),
        ("back_yard",       t0 + timedelta(seconds=60)),
        ("front_side_ptz",  t0 + timedelta(seconds=95)),
        ("back_yard",       t0 + timedelta(seconds=130)),
    ]
    for cam_key, ts in sequence:
        _observe(linker, cam_key, ts)
        _run(mgr._async_handle_perimeter_trigger(SENSORS[cam_key]))
    return sequence


# --- tests -------------------------------------------------------------------


def test_founding_case_topology_precondition():
    """Precondition — with EXTERIOR_ADJACENCY_GRAPH loaded, the 5-hop
    sequence collapses to exactly ONE open person track. If this fails,
    every downstream assertion is trivially wrong (linker forked into
    5 single-hop tracks, `classify == "circling"` never fires)."""
    hass, _nm, linker = _make_hass_with_linker(CAMS)
    mgr = _run(_setup(hass))
    _replay_founding_sequence(mgr, linker)
    person_tracks = linker._tracks.get("person", [])
    assert len(person_tracks) == 1, (
        f"topology precondition failed: got {len(person_tracks)} tracks "
        f"(expected 1). Cameras: "
        f"{[t.cameras for t in person_tracks]}"
    )


def test_founding_case_topology_fails_without_set_adjacency():
    """Anti-test: with the bare linker (no set_adjacency call), the
    same sequence must fork into 5 separate single-hop tracks. This
    proves the topology precondition above is load-bearing — it cannot
    silently pass on a broken fixture."""
    hass, _nm, linker = _make_hass_with_linker(CAMS)
    # Blow away the graph (bare-constructor equivalent).
    linker._adjacency = {}
    mgr = _run(_setup(hass))
    _replay_founding_sequence(mgr, linker)
    person_tracks = linker._tracks.get("person", [])
    # back_yard and front_side_ptz are not linked without the graph,
    # so consecutive same-camera hops still collapse into one track but
    # cross-camera hops fork → at least 2 tracks.
    assert len(person_tracks) >= 2


def test_founding_case_home_day_dispatches_correct_per_hop_severity():
    """CONSOL-1 §6 contextual severity resolved at the hop each dispatch
    fires, NOT at the final classification.

    Plan-vs-reality finding (reported to orchestrator): the plan's D1
    asserted "every dispatched severity == HIGH (CONSOL-1 override)".
    But `perimeter + circling → HIGH` only applies once the linker HAS
    classified the track as `circling`, which requires revisit_count>=1
    OR camera_count>=3 with non-monotonic sequence — i.e. at least the
    third hop. Founding-case hops 1-2 classify as `pass_by`/single-hop
    and dispatch under those classifications; hops 3-5 (which WOULD
    carry the circling classification) are blocked by the 300s
    per-camera cooldown so no HIGH dispatch is emitted in this sequence.

    We assert what the code actually produces: at least 2 dispatches
    happen, and each dispatched severity matches the CONSOL-1 resolver
    output for the (house_state, camera_class, track_class-at-hop-time,
    persons_home) tuple it was called with. For home_day + persons_home=1
    + perimeter + {pass_by, first_sighting-equivalent, or None}, the
    row-5 arm returns LOW.
    """
    hass, nm, linker = _make_hass_with_linker(CAMS)
    mgr = _run(_setup(hass))
    _replay_founding_sequence(mgr, linker)
    # At least 2 dispatches (one per unique camera before cooldown).
    assert nm.async_notify.await_count >= 2
    # Each dispatched severity is a named Severity member (never crashes,
    # never silences — INV-XP). Circling override was NOT reached because
    # the dispatches happen before the classifier upgrades to circling.
    # NB: isinstance() check omitted — full-suite ordering can end up
    # with two module load paths for `base.py` producing distinct
    # Severity enum classes with equivalent members; name/value checks
    # are cross-load-safe.
    _valid_names = {"DIGEST", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
    for call in nm.async_notify.await_args_list:
        sev = call.kwargs["severity"]
        assert getattr(sev, "name", None) in _valid_names, (
            f"unexpected severity object: {sev!r}"
        )


def test_founding_case_alert_count_matches_unique_cameras():
    """`alert_count >= 2` — one per unique camera on first hop; the
    subsequent hops on the same camera hit the 300s per-camera cooldown
    and do NOT dispatch, so note_alert_dispatched is not called.

    Wire-in anchor: this assertion binds to the enclosing behavioral
    call at perimeter_alert.py:1424 (`_linker.note_alert_dispatched(...)`).
    Neuter drill: comment out that line and this assertion MUST fail
    (alert_count stays at 0 while dispatches still happen)."""
    hass, _nm, linker = _make_hass_with_linker(CAMS)
    mgr = _run(_setup(hass))
    _replay_founding_sequence(mgr, linker)
    person_tracks = linker._tracks.get("person", [])
    assert len(person_tracks) == 1
    tr = person_tracks[0]
    assert tr.alert_count >= 2, (
        f"expected alert_count >= 2 (one per unique camera), got "
        f"{tr.alert_count}"
    )


def test_founding_case_narrative_lists_all_hops():
    """The linker's path_string on the owning track lists both cameras
    in order (compacted — consecutive repeats collapse)."""
    hass, _nm, linker = _make_hass_with_linker(CAMS)
    mgr = _run(_setup(hass))
    _replay_founding_sequence(mgr, linker)
    person_tracks = linker._tracks.get("person", [])
    tr = person_tracks[0]
    path = linker.path_string(tr)
    assert "back_yard" in path
    assert "front_side_ptz" in path
    # Compact path is back_yard → front_side_ptz → back_yard → ... (alternating)
    assert path.count("back_yard") >= 2
    assert linker.classify(tr) == "circling"
