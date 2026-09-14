"""D1/D2 — exterior seam file parser + validator.

The load-bearing property under test: **a bad spec is rejected WHOLESALE**.
There is no partial-apply path, because a half-applied seam graph is exactly
the wrong-seam failure mode — a seam that should not exist merges two
different people into one track and suppresses the second alert.
"""
from custom_components.universal_room_automation.exterior_seams import (
    SEAM_SCHEMA_VERSION,
    build_edges,
    derive_egress_adjacent,
    graph_from_spec,
    validate_seam_spec,
)

# The operator's re-ratified ring (2026-09-13), written as the file would be.
RING = [
    "front_side_ptz", "madrone_g6_entry", "front_door_aerial", "utilities_ptz",
    "madroneptultra", "pool_equipment", "hot_tub", "reolinkstudybporchptz",
    "armcrest", "back_yard", "g5_bullet", "doorbell_lite", "rear_ptz",
]
SKIPS = [
    ["armcrest", "doorbell_lite"], ["armcrest", "g5_bullet"],
    ["armcrest", "hot_tub"], ["back_yard", "hot_tub"],
    ["front_door_aerial", "front_side_ptz"], ["front_side_ptz", "utilities_ptz"],
    ["g5_bullet", "rear_ptz"], ["madrone_g6_entry", "utilities_ptz"],
]
FENCED = [
    ["pool_equipment", "rear_ptz"], ["rear_ptz", "utilities_ptz"],
    ["back_yard", "front_side_ptz"], ["front_side_ptz", "hot_tub"],
]
EGRESS = {
    # Operator ruling 2026-09-14: not every egress camera is an EXTERIOR camera.
    "exterior": ["madrone_g6_entry", "doorbell_lite", "front_door_aerial"],
    "interior": ["garage_a", "garage_b"],
}
KNOWN = set(RING) | {"garage_a", "garage_b"}


def _spec(**over):
    spec = {
        "schema_version": SEAM_SCHEMA_VERSION,
        "ring": list(RING),
        "skips": [list(p) for p in SKIPS],
        "fenced": [list(p) for p in FENCED],
        "egress_cameras": {k: list(v) for k, v in EGRESS.items()},
    }
    spec.update(over)
    return spec


def _ok(spec, known=KNOWN):
    errors, warnings = validate_seam_spec(spec, known)
    assert errors == [], f"expected no errors, got {errors}"
    return warnings


# --- D1: format -> edges ----------------------------------------------------

def test_ring_alone_yields_exactly_the_cycle_edges():
    spec = {"schema_version": 1, "ring": list(RING)}
    assert len(build_edges(spec)) == len(RING)


def test_skips_add_exactly_the_named_edges():
    ring_only = build_edges({"schema_version": 1, "ring": list(RING)})
    full = build_edges(_spec())
    added = full - ring_only
    assert len(full) == 21, f"expected 21 seams, got {len(full)}"
    assert added == {tuple(sorted(p)) for p in SKIPS}


def test_graph_declares_each_edge_once_not_pre_symmetrized():
    """ExteriorTrackLinker symmetrizes on load. Pre-symmetrizing here would put
    the same truth in two places, which is how the two layers drift apart."""
    graph = graph_from_spec(_spec())
    seen = set()
    for a, neigh in graph.items():
        for b in neigh:
            pair = tuple(sorted((a, b)))
            assert pair not in seen, f"{pair} declared twice"
            seen.add(pair)
    assert len(seen) == 21


# --- D2: validation rules ---------------------------------------------------

def test_valid_spec_passes_clean():
    assert _ok(_spec()) == []


def test_rule1_unknown_camera_is_rejected_and_named():
    """The rule that would have caught the `madroneptultra` mismatch: a camera
    the operator named that the integration does not actually watch."""
    spec = _spec(ring=RING[:-1] + ["madroneptultra"])
    errors, _ = validate_seam_spec(spec, KNOWN)
    assert errors, "unknown camera must be rejected"
    assert any("madroneptultra" in e for e in errors), errors


def test_rule3_dead_end_is_rejected():
    """Degree-1 camera can never reach the 3-distinct-camera circling
    threshold, so it is an error, not a warning."""
    spec = {"schema_version": 1, "ring": ["a", "b", "c"],
            "skips": [], "egress_cameras": []}
    # Break the cycle into a path a-b-c by removing one edge via a 2-node ring
    # is not expressible; instead assert the healthy ring has no dead ends...
    assert validate_seam_spec(spec, {"a", "b", "c"})[0] == []
    # ...and that an explicit degree-1 node (via a disconnected pendant) fails.
    spec2 = {"schema_version": 1, "ring": ["a", "b", "c"],
             "skips": [["c", "d"]], "egress_cameras": []}
    errors, _ = validate_seam_spec(spec2, {"a", "b", "c", "d"})
    assert any("dead end" in e for e in errors), errors


def test_rule5_fenced_pair_present_is_an_ERROR_not_a_silent_drop():
    """A struck seam creeping back must be loud. Silent dropping is how a
    physically-impossible seam returns unnoticed."""
    spec = _spec(skips=[list(p) for p in SKIPS] + [["back_yard", "front_side_ptz"]])
    errors, _ = validate_seam_spec(spec, KNOWN)
    assert any("fenced" in e for e in errors), errors
    assert any("back_yard" in e and "front_side_ptz" in e for e in errors), errors


def test_rule5_fenced_pair_is_not_quietly_removed_from_the_edge_set():
    """Discriminator for the test above: prove the implementation does not
    just drop it. build_edges must still contain it (so validation can see it)."""
    spec = _spec(skips=[["back_yard", "front_side_ptz"]])
    assert ("back_yard", "front_side_ptz") in build_edges(spec)


def test_rule6_implausible_skip_span_warns_but_does_not_reject():
    """The operator is the oracle on physical adjacency — a long skip is a
    smell to surface, not grounds for refusing their file."""
    spec = _spec(skips=[["front_side_ptz", "hot_tub"]], fenced=[])
    errors, warnings = validate_seam_spec(spec, KNOWN)
    assert errors == [], errors
    assert any("spans" in w for w in warnings), warnings


def test_schema_version_mismatch_is_rejected():
    errors, _ = validate_seam_spec(_spec(schema_version=99), KNOWN)
    assert any("schema_version" in e for e in errors), errors
    errors, _ = validate_seam_spec({"ring": list(RING)}, KNOWN)
    assert any("schema_version" in e for e in errors), errors


def test_malformed_input_is_rejected_not_crashed():
    for bad in (None, [], "nope", 42, {"schema_version": 1}):
        errors, _ = validate_seam_spec(bad, KNOWN)
        assert errors, f"{bad!r} should be rejected"


def test_ring_with_duplicate_camera_is_rejected():
    errors, _ = validate_seam_spec(_spec(ring=RING + ["armcrest"]), KNOWN)
    assert any("repeats" in e for e in errors), errors


def test_camera_absent_from_ring_warns():
    errors, warnings = validate_seam_spec(_spec(), KNOWN | {"side_gate_cam"})
    assert errors == [], errors
    assert any("side_gate_cam" in w for w in warnings), warnings


def test_interior_egress_camera_in_the_ring_is_rejected():
    """Operator ruling 2026-09-14: the garage cameras are egress but sit INSIDE
    the garage — they see crossings into the house, not outdoor movement. Ringing
    one would fabricate outdoor transits."""
    spec = _spec(ring=RING + ["garage_a"])
    errors, _ = validate_seam_spec(spec, KNOWN)
    assert any("interior egress" in e for e in errors), errors
    assert any("garage_a" in e for e in errors), errors


def test_egress_adjacent_ignores_INTERIOR_egress_cameras():
    """The derivation must use EXTERIOR egress only. Deriving from the full
    egress list would drag interior cameras into the outdoor adjacency model."""
    spec = _spec(skips=[list(p) for p in SKIPS] + [["garage_a", "back_yard"]])
    derived = derive_egress_adjacent(spec)
    assert "back_yard" not in derived, (
        "back_yard neighbours garage_a, but garage_a is INTERIOR egress — it "
        "must not confer egress-adjacency"
    )


# --- D2: derived egress-adjacent -------------------------------------------

def test_egress_adjacent_is_derived_and_excludes_egress_cameras_themselves():
    """The structural fix for the drift found 2026-09-13: the shipped list had
    `hot_tub` (whose only qualifying seam had been struck) and
    `front_door_aerial` (itself an egress camera)."""
    derived = derive_egress_adjacent(_spec())
    assert "front_door_aerial" not in derived, "an egress camera is not egress-ADJACENT"
    assert "hot_tub" not in derived, (
        "hot_tub only qualified via the struck front_door_aerial<->hot_tub seam"
    )
    assert set(derived) == {
        "front_side_ptz", "utilities_ptz", "armcrest", "g5_bullet", "rear_ptz",
    }, derived


def test_egress_adjacent_follows_the_egress_list_not_a_hardcoded_three():
    """Adding the garage cameras as egress must change the derived set — the
    5-vs-3 drift becomes impossible when the set is computed."""
    spec = _spec(egress_cameras={
        "exterior": EGRESS["exterior"] + ["armcrest"], "interior": [],
    })
    derived = derive_egress_adjacent(spec)
    assert "back_yard" in derived, (
        "back_yard neighbours armcrest, newly declared an EXTERIOR egress camera"
    )
    assert "armcrest" not in derived
