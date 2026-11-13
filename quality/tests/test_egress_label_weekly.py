"""FACE-ARRIVAL-REBUILD-1 D8a: the weekly egress-outcome labeller's pure
functions over a canned recorder extract (plan rev 11 §7 P7, M6)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from custom_components.universal_room_automation import const as ura_const

_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts" / "probes" / "egress_outcome_label_weekly.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("_ura_egress_label_weekly", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T = 1_800_000_000.0


def _row(slug, outcome, person_state, *, direction="entry", provenance=None):
    return {"crossing_ts": T, "attrs": {
        "slug": slug, "outcome": outcome, "person_state": person_state,
        "direction": direction, "provenance": provenance,
        "egress_camera": "binary_sensor.garage_a_person_occupancy_2",
        "crossing_ts": "2027-01-15T08:00:00+00:00", "tier": 0.6, "synthetic": False,
    }}


def test_row_carries_raw_path_and_gps_inputs():
    """A would-be candidate row carries raw_inputs_v 1, the path-node person
    edges inside [T-180, T+75] (outside dropped), and every GPS fix of the
    person inside [T-86400, T+600] with both timestamps."""
    m = _load()
    cands = m.would_be_candidates([_row("jaya", "vetoed", "not_home")])
    path = {
        "binary_sensor.staircase_person_occupancy": [
            (T - 200, "on"), (T - 30, "on"), (T + 40, "off"), (T + 90, "on"),
        ],
    }
    gps = {"jaya": {"device_tracker.jaya_phone": [
        (T - 90_000, T - 90_000, 30.1, -97.1, 20),
        (T - 600, T - 900, 30.2, -97.2, 15),
        (T + 300, T + 300, 30.25, -97.25, 10),
    ]}}
    rows = m.build_rows(cands, {"jaya": [(T + 240, "tracker")]}, path, gps)
    assert len(rows) == 1
    r = rows[0]
    assert r["raw_inputs_v"] == 1
    assert r["path_edges"]["binary_sensor.staircase_person_occupancy"] == [
        [T - 30, "on"], [T + 40, "off"],
    ]
    fixes = r["gps_fixes"]["device_tracker.jaya_phone"]
    assert [(f["last_updated"], f["last_changed"]) for f in fixes] == [
        (T - 600, T - 900), (T + 300, T + 300),
    ]
    assert fixes[0]["gps_accuracy"] == 15 and fixes[0]["lat"] == 30.2
    assert r["auto_label"] == "true" and r["lead_s"] == 240.0
    assert r["confirmed_by"] == "tracker"
    assert r["within"] == {"120": False, "300": True, "600": True, "1800": True}
    assert r["review"] is None


def test_candidate_selection_and_labels():
    m = _load()
    rows = [
        _row("jaya", "vetoed", "not_home"),                     # candidate
        _row("oji_udezue", "attached", "work", provenance="face"),  # zone attach: candidate
        _row("oji_udezue", "attached", "home", provenance="face"),  # home: not
        _row("jaya", "vetoed", "not_home", direction="exit"),   # exit: not
        _row(None, "no_leg", None),                             # no slug: not
        _row("ezinne", "attached_ble", "work", provenance="ble"),  # ble: not
    ]
    c = m.would_be_candidates(rows)
    assert [(x["attrs"]["slug"], x["attrs"]["outcome"]) for x in c] == [
        ("jaya", "vetoed"), ("oji_udezue", "attached"),
    ]
    assert m.label(T, [(T + 1200, "gps")])["auto_label"] == "late"
    assert m.label(T, [(T - 5, "tracker")])["auto_label"] == "mis_or_phoneless"
    assert m.label(T, [])["lead_s"] is None


def test_merge_dedups_by_crossing_key():
    m = _load()
    a = [{"crossing_key": "k1"}]
    assert m.merge(a, [{"crossing_key": "k1"}, {"crossing_key": "k2"}]) == [
        {"crossing_key": "k1"}, {"crossing_key": "k2"},
    ]


def test_label_windows_mirror_const():
    assert tuple(_load().LABEL_WINDOWS_S) == tuple(ura_const.EGRESS_OUTCOME_LABEL_WINDOWS_S)
