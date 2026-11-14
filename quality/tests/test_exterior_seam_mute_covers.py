"""PERIMETER-GLOBAL-EGRESS-MUTE-1 D2 — `egress_mute_covers` in exterior_seams.json.

Drives the REAL loader (`ExteriorTrackLinker.async_setup` /
`async_load_seam_file`) against a real file on disk (harness of
test_exterior_seam_loader). Oracles are hand-written.
"""

from __future__ import annotations

import asyncio
import copy
import importlib
import json
import pathlib

from test_exterior_seam_loader import (  # noqa: E402
    _KNOWN,
    _SPEC,
    _SPEC_ADJ,
    _SPEC_EGRESS_ADJ,
    _linker,
    _write,
)

seams = importlib.import_module(
    "custom_components.universal_room_automation.exterior_seams"
)

_COVERS = {
    "garage_a": ["g5_bullet", "back_yard"],
    "madrone_g6_entry": ["front_side_ptz"],
}


def _spec(covers=_COVERS):
    s = copy.deepcopy(_SPEC)
    if covers is not None:
        s["egress_mute_covers"] = covers
    return s


def test_mute_covers_valid_loads(tmp_path, monkeypatch):
    _hass, lk = _linker(tmp_path, monkeypatch, _spec())
    asyncio.run(lk.async_setup())
    assert lk.seam_validation == "ok" or lk.seam_validation.startswith("ok")
    assert lk.egress_mute_covers == {
        "garage_a": ("back_yard", "g5_bullet"),
        "madrone_g6_entry": ("front_side_ptz",),
    }
    assert lk.mute_covers_source == "loaded (2 door(s))"
    assert lk.seam_status()["mute_covers_source"] == "loaded (2 door(s))"


def test_mute_covers_unknown_camera_rejects_file(tmp_path, monkeypatch):
    _hass, lk = _linker(tmp_path, monkeypatch, _spec())
    asyncio.run(lk.async_setup())
    good = dict(lk.egress_mute_covers)
    good_adj = {k: set(v) for k, v in lk._adjacency.items()}
    _write(tmp_path, _spec({"garage_a": ["g5_bullet", "not_a_camera"]}))
    out = asyncio.run(lk.async_load_seam_file())
    assert out.startswith("rejected:") and "not_a_camera" in out
    assert lk.egress_mute_covers == good  # previous good spec kept
    assert {k: set(v) for k, v in lk._adjacency.items()} == good_adj


def test_mute_covers_door_not_egress_rejects_file(tmp_path, monkeypatch):
    _hass, lk = _linker(tmp_path, monkeypatch, _spec({"hot_tub": ["g5_bullet"]}))
    asyncio.run(lk.async_setup())
    assert lk.seam_validation.startswith("rejected:")
    assert "not a declared egress camera" in lk.seam_validation
    assert lk.egress_mute_covers == {}


def test_mute_covers_empty_list_rejects_file(tmp_path, monkeypatch):
    _hass, lk = _linker(tmp_path, monkeypatch, _spec({"garage_a": []}))
    asyncio.run(lk.async_setup())
    assert lk.seam_validation.startswith("rejected:")
    assert lk.egress_mute_covers == {}


def test_mute_covers_not_object_rejects_file(tmp_path, monkeypatch):
    _hass, lk = _linker(tmp_path, monkeypatch, _spec(["garage_a"]))
    asyncio.run(lk.async_setup())
    assert lk.seam_validation.startswith("rejected:")
    errs, _w = seams.validate_seam_spec(_spec(["garage_a"]), _KNOWN)
    assert errs == ["'egress_mute_covers' must be an object of door -> [cameras]"]


def test_mute_covers_door_covering_itself_rejects():
    errs, _w = seams.validate_seam_spec(_spec({"garage_a": ["garage_a"]}), _KNOWN)
    assert any("covers itself" in e for e in errs)


def test_mute_covers_absent_means_no_mute(tmp_path, monkeypatch):
    _hass, lk = _linker(tmp_path, monkeypatch, _spec(None))
    asyncio.run(lk.async_setup())
    assert lk.seam_validation == "ok" or lk.seam_validation.startswith("ok")
    assert lk.egress_mute_covers == {}
    assert lk.mute_covers_source == "absent (no egress mute)"


def test_mute_covers_file_absent(tmp_path, monkeypatch):
    _hass, lk = _linker(tmp_path, monkeypatch, None)
    asyncio.run(lk.async_setup())
    assert lk.egress_mute_covers == {} and lk.mute_covers_source == "file absent"


def test_mute_covers_not_in_adjacency_graph(tmp_path, monkeypatch):
    """Ring, seam count, egress-adjacent, adjacency queries (burst-demote /
    linking / circling read these) are identical with and without the
    section; the garage door stays out of the graph."""
    _h1, without = _linker(tmp_path / "a", monkeypatch, _spec(None))
    asyncio.run(without.async_setup())
    _h2, with_ = _linker(tmp_path / "b", monkeypatch, _spec())
    asyncio.run(with_.async_setup())
    for lk in (without, with_):
        assert {k: set(v) for k, v in lk._adjacency.items()} == _SPEC_ADJ
        assert lk.seam_count == 6
        assert tuple(lk._egress_adjacent) == _SPEC_EGRESS_ADJ
        assert lk.adjacent_cameras("garage_a") == set()
        assert lk.adjacent_cameras("g5_bullet") == {"back_yard", "front_side_ptz"}
    assert seams.graph_from_spec(_spec()) == seams.graph_from_spec(_spec(None))
    assert seams.derive_egress_adjacent(_spec()) == seams.derive_egress_adjacent(_spec(None))


def test_shipped_example_covers_validate_with_live_cameras():
    spec = json.loads(pathlib.Path("docs/examples/exterior_seams.example.json").read_text())
    live_known = {
        "reolinkstudybporchptz", "rear_ptz", "utilities_ptz", "front_side_ptz",
        "armcrest", "hot_tub", "pool_equipment", "g5_bullet", "back_yard",
        "madroneptultra", "sonoffwindow", "madrone_g6_entry", "doorbell_lite",
        "front_door_aerial", "garage_a", "garage_b",
    }
    errors, _w = seams.validate_seam_spec(spec, live_known)
    assert errors == []
    assert seams.mute_covers_from_spec(spec) == {
        "front_door_aerial": ("front_side_ptz", "sonoffwindow", "utilities_ptz"),
        "garage_a": ("doorbell_lite", "g5_bullet", "rear_ptz"),
        "madrone_g6_entry": ("front_side_ptz", "sonoffwindow", "utilities_ptz"),
    }
