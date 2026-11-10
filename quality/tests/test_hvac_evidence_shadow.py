"""HVAC evidence-rule shadow recording (HVAC-GUEST-EVIDENCE-RULE-1 phase 1).

Plan: docs/planning/PLANNING_hvac_evidence_shadow_recording_2026_11.md rev 2.

INV-SHADOW (plan §2): the producer's every pre-existing output is identical
to a golden captured on PRE-BUILD source, with the recorder const True AND
False. The only allowed differences are the new shadow dicts and rows in
`hvac_evidence_shadow`.
"""
from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _hvac_ev_shadow_replay as R  # noqa: E402
from custom_components.universal_room_automation.domain_coordinators import (  # noqa: E402
    hvac_const as HC,
)


# ==========================================================================
# D0: INV-SHADOW golden (captured on pre-build source)
# ==========================================================================

def _diff_first(golden: list[dict], got: list[dict]) -> str:
    assert len(golden) == len(got), f"pass count {len(got)} != golden {len(golden)}"
    for i, (g, o) in enumerate(zip(golden, got)):
        if g != o:
            for k in g:
                if g[k] != o.get(k):
                    return f"pass {i + 1} ({g['_pass']}): key {k} differs"
            return f"pass {i + 1}: extra keys {set(o) - set(g)}"
    return ""


def test_inv_shadow_golden_const_on(monkeypatch):
    monkeypatch.setattr(HC, "HVAC_EVIDENCE_SHADOW_ENABLED", True, raising=False)
    golden = R.load_golden()["passes"]
    got = R.run_replay()
    assert got == golden, _diff_first(golden, got)


def test_inv_shadow_golden_const_off(monkeypatch):
    monkeypatch.setattr(HC, "HVAC_EVIDENCE_SHADOW_ENABLED", False, raising=False)
    golden = R.load_golden()["passes"]
    got = R.run_replay()
    assert got == golden, _diff_first(golden, got)


def test_golden_records_capture_commit_and_coverage():
    """The golden names its capture commit and covers what the plan lists:
    every house state, a zone-filtered pass, an absent room, a hallway
    re-type, a D5 pending room and a restart (pass 120)."""
    g = R.load_golden()
    assert len(g["capture_commit"]) == 40
    passes = g["passes"]
    states = {p["_pass"]["house_state"] for p in passes}
    assert states == {
        "home_day", "home_evening", "home_night", "sleep", "waking",
        "guest", "arriving", "away", None,
    }
    assert any(p["_pass"]["zone_ids"] for p in passes)
    assert any(p["_coordinator_absent_this_pass"] for p in passes)
    assert any(p["_hvac_arm_source"].get("clo") == "hallway_excluded" for p in passes)
    assert any(any(p["_hvac_pending"].values()) for p in passes)
    assert passes[119]["_pass"]["n"] == 120
