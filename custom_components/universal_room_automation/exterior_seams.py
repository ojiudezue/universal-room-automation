"""Operator-declared exterior camera seam file — parser + validator (D1/D2).

A "seam" is an adjacency edge between two exterior cameras: *a person leaving
camera A can plausibly appear next on camera B*. The seam graph is what lets
``ExteriorTrackLinker`` treat N sightings as ONE tracked walk instead of N
independent alerts, and it gates ``circling`` (which needs >= 3 distinct
cameras).

Why this module exists
----------------------
The graph is **operator-declared physical truth**, not something to infer.
Runtime/observation-based learning was evaluated and KILLED (2026-09-13): of
the 27 seams a co-firing probe produced, the operator struck 10 (37%) as
physically impossible — several with observed counts of 3-4 *after* the
probe's simultaneity filter. Co-firing measures household movement patterns,
not physical adjacency. Crucially the failure is **asymmetric**:

* a WRONG seam merges two different people into one track and SUPPRESSES the
  second alert — a silent security failure;
* a MISSING seam only fragments one person into several weaker alerts — noisy,
  never silent.

Inference biases toward *adding* edges, i.e. toward the silent side. So this
module only ever *parses and validates what a human declared*. See
``docs/planning/PLANNING_exterior_seam_file_injection.md`` §6.

Design contract (mirrors the TOU rate-file loader, with its defects fixed)
-------------------------------------------------------------------------
* **Whole-file rejection.** ANY validation error rejects the ENTIRE spec. The
  TOU loader is inconsistent here (unknown period => warn+skip, missing
  ``off_peak`` => reject all); for seams a partially-applied graph is exactly
  the wrong-seam/merge failure above, so there is no partial-apply path.
* **Fail-safe to the built-in const, never to empty.** An empty graph silently
  disables cross-camera linking, which looks like "working" while every track
  fragments. Callers MUST keep the previous good graph on rejection (D6).
* **Ring-first.** The operator thinks in a walking order, so the file declares
  a ring plus validated shortcuts, and edges are *derived*.
* **Derived data is derived.** ``egress_cameras`` is declared; the
  egress-ADJACENT set is computed from it and the graph, never hand-listed.
"""

from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

SEAM_SCHEMA_VERSION = 1

# Canonical location, relative to the HA config dir — mirrors
# DEFAULT_TOU_RATE_FILE. This is also the landing path the config-flow file
# picker writes to (D3), so the drop-a-file and upload routes converge on ONE
# location rather than diverging.
DEFAULT_EXTERIOR_SEAM_FILE = "universal_room_automation/exterior_seams.json"

# A skip joining cameras this many ring positions apart is physically
# suspicious — the 2026-09-13 re-ratification found every operator-validated
# skip sat 2-3 positions apart, while the struck ones spanned further or
# crossed the property. Warned, not rejected: the operator is the oracle.
SKIP_SPAN_WARN_THRESHOLD = 4


class SeamSpecError(ValueError):
    """Raised when a seam spec cannot be turned into a usable graph."""


def _pairs(raw: Any, field: str) -> list[tuple[str, str]]:
    """Coerce a list-of-2-lists into tuples, with precise errors."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SeamSpecError(f"'{field}' must be a list of [a, b] pairs")
    out: list[tuple[str, str]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise SeamSpecError(
                f"'{field}'[{i}] must be a pair [camera_a, camera_b]"
            )
        a, b = item
        if not isinstance(a, str) or not isinstance(b, str):
            raise SeamSpecError(f"'{field}'[{i}] entries must be camera names")
        if a == b:
            raise SeamSpecError(f"'{field}'[{i}] joins '{a}' to itself")
        out.append((a, b))
    return out


def _undirected(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def split_egress(spec: dict) -> tuple[list[str], list[str]]:
    """Return (exterior_egress, interior_egress).

    NOT every egress camera is an exterior camera. Operator ruling 2026-09-14:
    the garage cameras are egress — they watch a way into the house — but they
    sit INSIDE the garage and "do not normally see external people; they see
    crossings into the house". The door-adjacent ones (overhead front door, the
    doorbells) sit outside.

    That distinction is load-bearing. `EXTERIOR_TRACK_EGRESS_ADJACENT_CAMERAS`
    means "perimeter cameras one hop from a way out", and it must be derived
    from the EXTERIOR egress cameras only — deriving it from the full egress
    list would drag interior cameras into the outdoor adjacency model and
    upgrade unrelated tracks to `approach`.

    Accepts either the split form ``{"exterior": [...], "interior": [...]}`` or
    a bare list (treated as all-exterior) for forward compatibility.
    """
    raw = spec.get("egress_cameras") or []
    if isinstance(raw, dict):
        return (
            list(raw.get("exterior") or []),
            list(raw.get("interior") or []),
        )
    return list(raw), []


def build_edges(spec: dict) -> set[tuple[str, str]]:
    """Derive the undirected edge set from a spec.

    ring -> the N cycle edges; skips -> extra operator-validated shortcuts.
    ``fenced`` is NOT subtracted here — it is a validation rule, so that a
    fenced pair appearing in ring/skips is reported as an ERROR rather than
    silently dropped. Silent dropping is how a struck seam creeps back.
    """
    ring = spec.get("ring") or []
    edges: set[tuple[str, str]] = set()
    for i, cam in enumerate(ring):
        edges.add(_undirected(cam, ring[(i + 1) % len(ring)]))
    for a, b in _pairs(spec.get("skips"), "skips"):
        edges.add(_undirected(a, b))
    return edges


def _symmetrized(edges: set[tuple[str, str]]) -> dict[str, set[str]]:
    adj: dict[str, set[str]] = {}
    for a, b in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    return adj


def validate_seam_spec(
    spec: Any, known_cameras: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Validate a parsed seam spec.

    Returns ``(errors, warnings)``. A non-empty ``errors`` list means the spec
    MUST be rejected wholesale and the previous graph kept.

    ``known_cameras`` is the set of configured exterior camera keys (perimeter
    + egress). When supplied, every name in the spec is checked against it —
    this is the rule that catches an operator naming a camera the integration
    does not actually watch.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(spec, dict):
        return ["seam file must be a JSON object"], warnings

    version = spec.get("schema_version")
    if version is None:
        errors.append("missing 'schema_version'")
    elif version != SEAM_SCHEMA_VERSION:
        errors.append(
            f"unsupported 'schema_version' {version!r} "
            f"(this build understands {SEAM_SCHEMA_VERSION})"
        )

    ring = spec.get("ring")
    if not isinstance(ring, list) or not ring:
        errors.append("'ring' must be a non-empty list of camera names")
        return errors, warnings
    if not all(isinstance(c, str) for c in ring):
        errors.append("'ring' entries must be camera names")
        return errors, warnings
    if len(ring) < 3:
        errors.append(f"'ring' needs at least 3 cameras to form a cycle (got {len(ring)})")
    dupes = sorted({c for c in ring if ring.count(c) > 1})
    if dupes:
        errors.append(f"'ring' repeats camera(s): {dupes}")

    try:
        skips = _pairs(spec.get("skips"), "skips")
        fenced = _pairs(spec.get("fenced"), "fenced")
        _pairs(spec.get("close_pairs"), "close_pairs")
    except SeamSpecError as exc:
        errors.append(str(exc))
        return errors, warnings

    raw_egress = spec.get("egress_cameras")
    if raw_egress is not None and not isinstance(raw_egress, (list, dict)):
        errors.append(
            "'egress_cameras' must be a list, or an object with "
            "'exterior'/'interior' lists"
        )
        raw_egress = []
    ext_egress, int_egress = split_egress(spec)
    if not all(isinstance(c, str) for c in ext_egress + int_egress):
        errors.append("'egress_cameras' entries must be camera names")
        ext_egress, int_egress = [], []
    egress = ext_egress + int_egress

    if errors:
        return errors, warnings

    edges = build_edges(spec)
    adj = _symmetrized(edges)

    # RULE 1 — every named camera must be one the integration actually watches.
    if known_cameras:
        named = set(ring) | {c for pair in skips + fenced for c in pair} | set(egress)
        unknown = sorted(named - known_cameras)
        if unknown:
            errors.append(
                "unknown camera(s) not in the configured exterior camera list: "
                f"{unknown}"
            )

    # RULE 2 — every configured EXTERIOR camera should appear in the ring.
    # Interior egress cameras are excluded by design: they are declared so the
    # egress model is complete, but they must NOT be ringed (RULE 2b).
    if known_cameras:
        missing = sorted(known_cameras - set(ring) - set(int_egress))
        if missing:
            warnings.append(
                f"configured exterior camera(s) absent from the ring: {missing} "
                "— they can never be linked into a track"
            )

    # RULE 2b — an INTERIOR egress camera must not sit in the exterior ring.
    # It cannot see outdoor traffic, so linking it into an outdoor walk would
    # fabricate transits. Declaring it is right; ringing it is not.
    inside_ring = sorted(set(int_egress) & set(ring))
    if inside_ring:
        errors.append(
            f"interior egress camera(s) present in the exterior ring: {inside_ring} "
            "— they watch crossings into the house, not outdoor movement"
        )

    # RULE 3 — no dead ends. Degree < 2 can never reach the circling threshold.
    for cam in sorted(adj):
        if len(adj[cam]) < 2:
            errors.append(
                f"'{cam}' has only {len(adj[cam])} seam(s) — a dead end cannot "
                "participate in circling detection"
            )

    # RULE 4 — connected.
    start = next(iter(adj))
    seen, stack = {start}, [start]
    while stack:
        for nb in adj[stack.pop()]:
            if nb not in seen:
                seen.add(nb)
                stack.append(nb)
    unreachable = sorted(set(adj) - seen)
    if unreachable:
        errors.append(f"graph is disconnected; unreachable from '{start}': {unreachable}")

    # RULE 5 — a fenced pair must not be present. ERROR, never silently dropped.
    live_fenced = sorted(
        f"{a}<->{b}" for a, b in fenced if _undirected(a, b) in edges
    )
    if live_fenced:
        errors.append(
            f"fenced (physically impossible) seam(s) present in ring/skips: {live_fenced}"
        )

    # RULE 6 — implausible skip span. WARN: the operator is the oracle.
    pos = {c: i for i, c in enumerate(ring)}
    n = len(ring)
    for a, b in skips:
        if a in pos and b in pos:
            d = abs(pos[a] - pos[b])
            span = min(d, n - d)
            if span >= SKIP_SPAN_WARN_THRESHOLD:
                warnings.append(
                    f"skip {a}<->{b} spans {span} ring positions — verify this is "
                    "really a line of sight and not a mis-ordered ring"
                )

    return errors, warnings


def graph_from_spec(spec: dict) -> dict[str, tuple[str, ...]]:
    """Render the spec as an EXTERIOR_ADJACENCY_GRAPH-shaped mapping.

    Declares each edge once (``ExteriorTrackLinker`` symmetrizes on load, so a
    one-direction declaration is sufficient — do NOT pre-symmetrize here or the
    two layers can disagree).
    """
    out: dict[str, list[str]] = {}
    for a, b in sorted(build_edges(spec)):
        out.setdefault(a, []).append(b)
    return {k: tuple(sorted(v)) for k, v in sorted(out.items())}


def derive_egress_adjacent(
    spec: dict, graph: dict[str, tuple[str, ...]] | None = None,
) -> tuple[str, ...]:
    """Compute the egress-ADJACENT camera set from the spec.

    Definition: cameras with a seam to ANY egress camera, EXCLUDING the egress
    cameras themselves. Computing this (rather than hand-listing it) is the
    structural fix for the drift found 2026-09-13, where the shipped list still
    contained a camera whose only qualifying seam had been struck, and another
    that was itself an egress camera.
    """
    edges = build_edges(spec) if graph is None else {
        _undirected(a, b) for a, ns in graph.items() for b in ns
    }
    adj = _symmetrized(edges)
    ext_egress, _interior = split_egress(spec)
    egress = set(ext_egress)
    out: set[str] = set()
    for cam in egress:
        out |= adj.get(cam, set())
    return tuple(sorted(out - egress))
