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
_etl_mod = importlib.import_module(
    "custom_components.universal_room_automation.exterior_track_linker"
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
    assert good  # the valid file DID load a map first
    # Review A1 (INV-MUTE-FAILOPEN): a rejected file means no egress mute,
    # while the GRAPH keeps the last good spec.
    assert lk.egress_mute_covers == {}
    assert lk.mute_covers_source == "rejected (no egress mute)"
    assert lk.seam_status()["mute_covers_source"] == "rejected (no egress mute)"
    assert {k: set(v) for k, v in lk._adjacency.items()} == good_adj


def test_mute_covers_valid_then_invalid_reload_stops_muting(tmp_path, monkeypatch):
    """A1 repro end to end: valid map mutes g5_bullet; a typo edit + reload
    is rejected; the old map must no longer be what the mute reads."""
    _hass, lk = _linker(tmp_path, monkeypatch, _spec())
    asyncio.run(lk.async_setup())
    assert "g5_bullet" in lk.egress_mute_covers["garage_a"]
    _write(tmp_path, _spec({"garage_a": ["g5_bulet"]}))
    asyncio.run(lk.async_load_seam_file())
    assert lk.seam_validation.startswith("rejected:")
    assert lk.egress_mute_covers == {}


def test_mute_covers_path_failure_clears_covers(tmp_path, monkeypatch):
    _hass, lk = _linker(tmp_path, monkeypatch, _spec())
    asyncio.run(lk.async_setup())
    assert lk.egress_mute_covers

    def _boom():
        raise OSError("no config dir")
    monkeypatch.setattr(lk, "_seam_file_path", _boom)
    out = asyncio.run(lk.async_load_seam_file())
    assert out.startswith("rejected: load failed")
    assert lk.egress_mute_covers == {}
    assert lk.mute_covers_source == "rejected (no egress mute)"


def test_mute_covers_file_deleted_after_valid_clears_covers(tmp_path, monkeypatch):
    """Review C F5: deleting the file after a valid load must drop the map."""
    _hass, lk = _linker(tmp_path, monkeypatch, _spec())
    asyncio.run(lk.async_setup())
    assert lk.egress_mute_covers
    path = pathlib.Path(lk._seam_file_path())
    path.unlink()
    out = asyncio.run(lk.async_load_seam_file())
    assert out == "file absent"
    assert lk.egress_mute_covers == {}
    assert lk.mute_covers_source == "file absent"


def test_mute_covers_rejects_covered_egress_camera():
    """Review A5: a covered camera that is a declared egress camera is never
    scoped-muted, so naming it is a config error."""
    errs, _w = seams.validate_seam_spec(
        _spec({"garage_a": ["g5_bullet", "madrone_g6_entry"]}), _KNOWN)
    assert any("not perimeter-only" in e and "madrone_g6_entry" in e for e in errs)


def test_mute_covers_rejects_camera_outside_perimeter_set():
    errs, _w = seams.validate_seam_spec(
        _spec(), _KNOWN, perimeter_cameras={"g5_bullet", "front_side_ptz"})
    assert any("not perimeter-only" in e and "back_yard" in e for e in errs)
    errs_ok, _w = seams.validate_seam_spec(
        _spec(), _KNOWN,
        perimeter_cameras={"g5_bullet", "front_side_ptz", "back_yard"})
    assert errs_ok == []


def test_mute_covers_linker_passes_perimeter_only_set(tmp_path, monkeypatch):
    """The linker reads the PerimeterAlertManager's perimeter-only keys and
    rejects a file covering a camera outside them."""
    from types import SimpleNamespace
    hass, lk = _linker(tmp_path, monkeypatch, _spec())
    hass.data.setdefault("universal_room_automation", {})[
        "perimeter_alert_manager"] = SimpleNamespace(
            perimeter_only_camera_keys={"G5_Bullet", "front_side_ptz"},
            _perimeter_allowlist=set(_KNOWN))
    asyncio.run(lk.async_setup())
    assert lk.seam_validation.startswith("rejected:")
    assert "back_yard" in lk.seam_validation
    assert lk.egress_mute_covers == {}


def test_mute_covers_names_normalised(tmp_path, monkeypatch):
    """Review C F14: covers are normalised like every other camera key."""
    _hass, lk = _linker(tmp_path, monkeypatch, _spec(
        {"garage_a": ["g5_bullet"], "madrone_g6_entry": ["front_side_ptz"]}))
    monkeypatch.setattr(_etl_mod, "mute_covers_from_spec",
                        lambda _s: {"Garage_A": ("G5_Bullet ",)})
    asyncio.run(lk.async_setup())
    assert lk.egress_mute_covers == {"garage_a": ("g5_bullet",)}


def test_mute_covers_empty_camera_name_rejects():
    """Review C F16: an empty-string camera name is a shape error."""
    errs, _w = seams.validate_seam_spec(_spec({"garage_a": ["g5_bullet", ""]}), _KNOWN)
    assert any("non-empty list of camera names" in e for e in errs)


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
        "garage_a": ("g5_bullet", "rear_ptz"),
        "madrone_g6_entry": ("front_side_ptz", "sonoffwindow", "utilities_ptz"),
    }
