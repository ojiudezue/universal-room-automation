"""EXTERIOR-SEAM-LOADER — the operator seam file actually reaches the linker.

Wire-in anchors (PLANNING_exterior_seam_file_injection.md D4/D5/D6):
  * ExteriorTrackLinker.async_setup() (the enclosing setup method) reads
    exterior_seams.json from a REAL file on disk and installs ITS graph,
    not EXTERIOR_ADJACENCY_GRAPH.
  * missing / invalid file -> const fallback (never an empty graph).
  * button.ura_reload_exterior_seams re-reads + applies without restart; a
    rejected reload keeps the PREVIOUS good graph.
  * _classify consumes the file-derived egress-adjacent set.
  * the Outside: Open Tracks diagnostic sensor carries the seam_* attrs.

Oracles are hand-written adjacency dicts, never re-derived by the code
under test.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

etl = importlib.import_module(
    "custom_components.universal_room_automation.exterior_track_linker"
)
_const = importlib.import_module("custom_components.universal_room_automation.const")
DOMAIN = _const.DOMAIN

# A small, deliberately NON-const ring of real camera keys.
# ring a>b>c>d>e>(a) + skip a-c; egress exterior = [b], interior = [garage_a].
_RING = ["front_side_ptz", "madrone_g6_entry", "hot_tub", "back_yard", "g5_bullet"]
_SPEC = {
    "schema_version": 1,
    "ring": _RING,
    "skips": [["front_side_ptz", "hot_tub"]],
    "fenced": [["front_side_ptz", "back_yard"]],
    "egress_cameras": {"exterior": ["madrone_g6_entry"], "interior": ["garage_a"]},
}
# Hand-written symmetric oracle for _SPEC (6 undirected seams).
_SPEC_ADJ = {
    "front_side_ptz": {"madrone_g6_entry", "g5_bullet", "hot_tub"},
    "madrone_g6_entry": {"front_side_ptz", "hot_tub"},
    "hot_tub": {"madrone_g6_entry", "back_yard", "front_side_ptz"},
    "back_yard": {"hot_tub", "g5_bullet"},
    "g5_bullet": {"back_yard", "front_side_ptz"},
}
# Egress-adjacent oracle: neighbours of madrone_g6_entry minus egress itself.
_SPEC_EGRESS_ADJ = ("front_side_ptz", "hot_tub")

# Second valid spec, for reload: a 3-ring.
_SPEC2 = {
    "schema_version": 1,
    "ring": ["armcrest", "doorbell_lite", "rear_ptz"],
    "egress_cameras": ["doorbell_lite"],
}
_SPEC2_ADJ = {
    "armcrest": {"doorbell_lite", "rear_ptz"},
    "doorbell_lite": {"armcrest", "rear_ptz"},
    "rear_ptz": {"armcrest", "doorbell_lite"},
}

_KNOWN = set(_RING) | {"garage_a"}
_KNOWN_ALL = _KNOWN | {"armcrest", "doorbell_lite", "rear_ptz"}

# The ratified const graph has 21 undirected seams (13 ring + 8 skips,
# const.py provenance block) — hardcoded literal, not re-derived.
_CONST_SEAMS = 21


class _Hass:
    def __init__(self, config_dir):
        self.data = {DOMAIN: {}}
        self.config = SimpleNamespace(path=lambda *p: str(config_dir.joinpath(*p)))

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)

    def async_create_task(self, coro):  # pragma: no cover - unused here
        return asyncio.get_event_loop().create_task(coro)


def _write(config_dir, spec):
    d = config_dir / "universal_room_automation"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "exterior_seams.json"
    f.write_text(spec if isinstance(spec, str) else json.dumps(spec))
    return f


def _linker(tmp_path, monkeypatch, spec=None, known=_KNOWN):
    # Isolate setup from Frigate ingress / timers: only the seam load matters.
    monkeypatch.setattr(etl, "register_frigate_consumer", lambda *a, **k: (lambda: None))
    monkeypatch.setattr(etl, "async_track_time_interval", lambda *a, **k: (lambda: None))
    if spec is not None:
        _write(tmp_path, spec)
    hass = _Hass(tmp_path)
    hass.data[DOMAIN]["perimeter_alert_manager"] = SimpleNamespace(
        _perimeter_allowlist=set(known) if known else set()
    )
    lk = etl.ExteriorTrackLinker(hass)
    hass.data[DOMAIN]["exterior_track_linker"] = lk
    return hass, lk


def _const_adj():
    """Independent symmetrization of the const graph (oracle)."""
    out: dict[str, set[str]] = {}
    for a, ns in _const.EXTERIOR_ADJACENCY_GRAPH.items():
        for b in ns:
            out.setdefault(a, set()).add(b)
            out.setdefault(b, set()).add(a)
    return out


# ------------------------------------------------------------- setup path ---


def test_setup_installs_seam_file_graph_not_const(tmp_path, monkeypatch):
    _hass, lk = _linker(tmp_path, monkeypatch, _SPEC)
    asyncio.run(lk.async_setup())
    assert lk._adjacency == _SPEC_ADJ
    assert lk._adjacency != _const_adj()
    assert lk.seam_count == 6
    assert lk.seam_source == "exterior_seams.json (schema 1, 6 seams)"
    assert lk.seam_validation == "ok"
    assert lk._egress_adjacent == _SPEC_EGRESS_ADJ
    assert len(lk.seam_file_sha256) == 64


def test_setup_missing_file_falls_back_to_const(tmp_path, monkeypatch):
    _hass, lk = _linker(tmp_path, monkeypatch, None)
    lk.set_adjacency({"x": ["y"]})  # poison: missing file must RESTORE const
    asyncio.run(lk.async_setup())
    assert lk._adjacency == _const_adj()
    assert lk.seam_count == _CONST_SEAMS
    assert lk.seam_source == "built-in const"
    assert lk.seam_validation == "file absent"
    assert lk.seam_file_sha256 is None
    assert set(lk._egress_adjacent) == {
        "front_side_ptz", "utilities_ptz", "armcrest", "g5_bullet", "rear_ptz",
    }


@pytest.mark.parametrize(
    "bad, needle",
    [
        ("{not json", "invalid JSON"),
        ({**_SPEC, "skips": [["front_side_ptz", "back_yard"]]}, "fenced"),
        ({**_SPEC, "ring": _RING + ["madroneptultra_typo"]}, "unknown camera"),
        ({**_SPEC, "schema_version": 2}, "schema_version"),
    ],
)
def test_setup_invalid_file_rejected_wholesale_keeps_const(
    tmp_path, monkeypatch, caplog, bad, needle,
):
    _hass, lk = _linker(tmp_path, monkeypatch, bad)
    with caplog.at_level("WARNING"):
        asyncio.run(lk.async_setup())
    assert lk._adjacency == _const_adj()
    assert lk._adjacency  # never empty
    assert lk.seam_source == "built-in const"
    assert lk.seam_validation.startswith("rejected: ")
    assert needle in lk.seam_validation
    rejects = [r for r in caplog.records if "REJECTED" in r.getMessage()]
    assert len(rejects) == 1 and needle in rejects[0].getMessage()


def test_validator_uses_staged_perimeter_allowlist(tmp_path, monkeypatch):
    """RULE 1 runs against the configured cameras: drop a ring camera from
    the staged allowlist -> the file is rejected (not silently admitted)."""
    _hass, lk = _linker(
        tmp_path, monkeypatch, _SPEC, known=_KNOWN - {"back_yard"},
    )
    asyncio.run(lk.async_setup())
    assert "back_yard" in lk.seam_validation
    assert lk._adjacency == _const_adj()


def test_classify_consumes_file_egress_adjacent(tmp_path, monkeypatch):
    """hot_tub is egress-adjacent in the FILE but not in the const set."""
    _hass, lk = _linker(tmp_path, monkeypatch, _SPEC)
    asyncio.run(lk.async_setup())
    track = SimpleNamespace(cameras=["hot_tub"], revisit_count=0, camera_count=1)
    assert lk.classify(track) == "approach"


# ------------------------------------------------------------ reload (D4) ---


def _button(hass):
    btn_mod = importlib.import_module("custom_components.universal_room_automation.button")
    b = btn_mod.ReloadExteriorSeamsButton.__new__(btn_mod.ReloadExteriorSeamsButton)
    b.hass = hass
    return b


def test_reload_button_applies_edited_file_without_restart(tmp_path, monkeypatch):
    hass, lk = _linker(tmp_path, monkeypatch, _SPEC, known=_KNOWN_ALL)
    asyncio.run(lk.async_setup())
    assert lk._adjacency == _SPEC_ADJ
    _write(tmp_path, _SPEC2)
    asyncio.run(_button(hass).async_press())
    assert lk._adjacency == _SPEC2_ADJ
    assert lk.seam_count == 3
    assert lk._egress_adjacent == ("armcrest", "rear_ptz")


def test_reload_invalid_keeps_previous_good_graph(tmp_path, monkeypatch):
    hass, lk = _linker(tmp_path, monkeypatch, _SPEC)
    asyncio.run(lk.async_setup())
    _write(tmp_path, "{broken")
    asyncio.run(_button(hass).async_press())
    assert lk._adjacency == _SPEC_ADJ  # previous FILE graph, not const, not empty
    assert lk.seam_source == "exterior_seams.json (schema 1, 6 seams)"
    assert lk.seam_validation.startswith("rejected: invalid JSON")


def test_reload_button_registered_on_cm_setup(monkeypatch):
    """Wire-in anchor: the CM entry's button platform setup adds the reload button."""
    btn_mod = importlib.import_module("custom_components.universal_room_automation.button")
    from homeassistant.components.button import ButtonEntity
    # Stub every OTHER button class so the CM list builds with a bare hass.
    for _name, _obj in list(vars(btn_mod).items()):
        if (isinstance(_obj, type) and issubclass(_obj, ButtonEntity)
                and _obj is not ButtonEntity
                and _obj is not btn_mod.ReloadExteriorSeamsButton):
            monkeypatch.setattr(btn_mod, _name, lambda *a, **k: object())
    monkeypatch.setattr(btn_mod, "_discover_ac_zones", lambda _h: [], raising=False)
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE, ENTRY_TYPE_COORDINATOR_MANAGER,
    )
    added: list = []
    entry = SimpleNamespace(
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}, options={},
        entry_id="cm", title="CM",
    )
    hass = SimpleNamespace(data={DOMAIN: {}})
    try:
        asyncio.run(btn_mod.async_setup_entry(hass, entry, added.extend))
    except Exception:  # noqa: BLE001 - other buttons may need more hass; the list is built first
        pass
    assert any(isinstance(e, btn_mod.ReloadExteriorSeamsButton) for e in added)


def test_reload_button_entity_id_pinned():
    btn_mod = importlib.import_module("custom_components.universal_room_automation.button")
    b = btn_mod.ReloadExteriorSeamsButton(SimpleNamespace(data={}), SimpleNamespace())
    assert b.entity_id == "button.ura_reload_exterior_seams"
    assert b._attr_unique_id == f"{DOMAIN}_reload_exterior_seams"


# ----------------------------------------------------- provenance (D5) ---


def test_open_tracks_sensor_exposes_seam_attrs(tmp_path, monkeypatch):
    hass, lk = _linker(tmp_path, monkeypatch, _SPEC)
    asyncio.run(lk.async_setup())
    sensor_mod = importlib.import_module("custom_components.universal_room_automation.sensor")
    s_ = sensor_mod.ExteriorOpenTracksDiagnosticSensor.__new__(
        sensor_mod.ExteriorOpenTracksDiagnosticSensor)
    s_.hass = SimpleNamespace(data={DOMAIN: {"exterior_track_linker": lk}})
    attrs = s_.extra_state_attributes
    assert attrs["seam_source"] == "exterior_seams.json (schema 1, 6 seams)"
    assert attrs["seam_count"] == 6
    assert attrs["seam_validation"] == "ok"
    assert attrs["seam_file_sha256"] == lk.seam_file_sha256
    assert attrs["seam_egress_adjacent"] == ["front_side_ptz", "hot_tub"]


def test_live_ratified_file_shape_validates_with_live_cameras():
    """The shipped example (== live ratified rev 2) validates against the
    live configured camera keys (perimeter + egress, 2026-11-12 config)."""
    import pathlib
    seams = importlib.import_module("custom_components.universal_room_automation.exterior_seams")
    spec = json.loads(pathlib.Path("docs/examples/exterior_seams.example.json").read_text())
    live_known = {
        "reolinkstudybporchptz", "rear_ptz", "utilities_ptz", "front_side_ptz",
        "armcrest", "hot_tub", "pool_equipment", "g5_bullet", "back_yard",
        "madroneptultra", "sonoffwindow", "madrone_g6_entry", "doorbell_lite",
        "front_door_aerial", "garage_a", "garage_b",
    }
    errors, warnings = seams.validate_seam_spec(spec, live_known)
    assert errors == []
    assert any("sonoffwindow" in w for w in warnings)


def test_seam_sha_on_rejected_file_unchanged(tmp_path, monkeypatch):
    """FACE-ARRIVAL-REBUILD-1 D7 step 0 (pinned BEFORE the shared-loader
    extraction): a REJECTED seam file still publishes the sha256 of its raw
    bytes (today's behaviour: sha set before validation), and the const graph
    stays installed."""
    import hashlib

    bad = '{"schema_version": 999, "seams": []}'
    _hass, lk = _linker(tmp_path, monkeypatch, bad)
    asyncio.run(lk.async_setup())
    assert lk.seam_validation.startswith("rejected: ")
    assert lk.seam_file_sha256 == hashlib.sha256(bad.encode()).hexdigest()
    assert lk._adjacency == _const_adj()
    assert lk.seam_source == "built-in const"
