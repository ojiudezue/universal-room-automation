"""CAMERA-SEAM-VALIDATION-1 — invariants on the exterior seam graph.

The graph is operator-declared physical truth. These guard the two ways it
silently rots: (a) a derived constant drifting away from the graph it is
supposed to be computed from, and (b) a fenced edge being re-added.
"""
# Reuse the sibling fixture's module loader so this file works in the SAME
# environment as the rest of quality/tests/perimeter (that module installs the
# homeassistant stubs before loading const).
from quality.tests.perimeter.test_circling_founding_case import _const


EGRESS_CAMERAS = ("madrone_g6_entry", "doorbell_lite", "front_door_aerial")


def _symmetrized():
    """Symmetrize exactly as ExteriorTrackLinker.__init__ does."""
    adj: dict[str, set[str]] = {}
    for a, neigh in _const.EXTERIOR_ADJACENCY_GRAPH.items():
        adj.setdefault(a, set()).update(neigh)
        for b in neigh:
            adj.setdefault(b, set()).add(a)
    return adj


def test_egress_adjacent_is_derived_from_the_graph():
    """EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS is DERIVED data — it must equal
    the neighbours of the egress cameras, minus the egress cameras themselves.

    Before this guard the two could drift independently, and they had:
    `hot_tub` sat in the list via a front_door_aerial-hot_tub seam the
    operator later struck as physically impossible ("opposite sides of the
    house"), and `front_door_aerial` sat in it despite BEING an egress
    camera. A stale entry here silently upgrades tracks to `approach`.
    """
    adj = _symmetrized()
    computed = set()
    for cam in EGRESS_CAMERAS:
        computed |= adj.get(cam, set())
    computed -= set(EGRESS_CAMERAS)

    declared = set(_const.EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS)
    assert declared == computed, (
        "EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS drifted from the graph.\n"
        f"  missing (in graph, not declared): {sorted(computed - declared)}\n"
        f"  stale   (declared, not in graph): {sorted(declared - computed)}"
    )


def test_no_egress_camera_is_listed_as_egress_adjacent():
    """The list's own definition excludes the egress cameras themselves."""
    overlap = set(EGRESS_CAMERAS) & set(
        _const.EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS
    )
    assert not overlap, (
        f"egress cameras must not appear in the egress-ADJACENT list: {sorted(overlap)}"
    )


def test_ratification_fenced_edges_absent():
    """Edges the operator struck as physically impossible must stay struck.

    Re-adding one silently merges two genuinely separate people into one
    track and suppresses the second alert.
    """
    adj = _symmetrized()
    fenced = [
        # 2026-08-06 ratification removals.
        ("pool_equipment", "rear_ptz"),
        ("rear_ptz", "utilities_ptz"),
        # 2026-09-13 re-ratification removals (operator named an
        # intervening camera, or called them opposite sides of the house).
        ("armcrest", "rear_ptz"),
        ("back_yard", "front_side_ptz"),
        ("back_yard", "rear_ptz"),
        ("front_door_aerial", "hot_tub"),
        ("front_door_aerial", "rear_ptz"),
        ("front_side_ptz", "g5_bullet"),
        ("front_side_ptz", "hot_tub"),
        ("front_side_ptz", "reolinkstudybporchptz"),
        ("g5_bullet", "madrone_g6_entry"),
        ("madrone_g6_entry", "rear_ptz"),
    ]
    live = [(a, b) for a, b in fenced if b in adj.get(a, set())]
    assert not live, f"fenced (physically impossible) seams are live again: {live}"


def test_every_camera_reachable_no_isolated_node():
    """The operator declared a SINGULAR RING covering all exterior cameras,
    so the graph must be connected and no camera may be a dead end.

    A degree-1 camera cannot contribute to `circling` (which needs 3 distinct
    cameras) — that was the pre-ratification state of `pool_equipment`.
    """
    adj = _symmetrized()
    assert adj, "graph is empty"
    for cam, neigh in adj.items():
        assert len(neigh) >= 2, (
            f"{cam} has degree {len(neigh)} — a dead end cannot participate "
            "in circling detection"
        )
    # Connectivity.
    start = next(iter(adj))
    seen, stack = {start}, [start]
    while stack:
        for nb in adj[stack.pop()]:
            if nb not in seen:
                seen.add(nb)
                stack.append(nb)
    assert seen == set(adj), f"graph is disconnected; unreachable: {sorted(set(adj) - seen)}"
