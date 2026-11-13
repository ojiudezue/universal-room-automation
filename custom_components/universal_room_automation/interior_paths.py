"""Interior camera path map (INTERIOR-PATH-MAP-1, FACE-ARRIVAL-REBUILD-1 D7).

HA-free: parse, validate and score. Same contract as ``exterior_seams.py``:
a schema version, whole-file rejection on ANY error (never a partial map),
warnings that do not reject. The map is a per-door DAG whose nodes are
PHYSICAL cameras (``camera_resolver.canonical_camera_key``) so the Frigate and
Protect legs of one camera are one node; edges are typed ``approach``
(outside, toward the door) or ``inward`` (door, deeper inside), with an
optional measured ``lag_p90_s``; ``same_view`` pairs never score.

Phase 1 has NO runtime reader of the map: it is loaded, validated and exposed
(provenance attributes) and the pure scorer is shared with the offline D0
scripts. ``door_interior_neighbours`` (lock entry areas, direction, perimeter)
is NOT touched and never reads this map.

Schema v1::

    {"schema_version": 1,
     "doors": {"<door group>": {
         "edges": [{"from": "camera.x", "to": "camera.y",
                    "kind": "approach"|"inward", "lag_p90_s": 25}],
         "same_view": [["camera.a", "camera.b"]]}}}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

SCHEMA_VERSION = 1
KIND_APPROACH = "approach"
KIND_INWARD = "inward"
KINDS = (KIND_APPROACH, KIND_INWARD)
# Interior buffer horizon of the egress tracker (max(entry, exit) + 30 s);
# the exit scorer reads only what that buffer still holds at T.
INTERIOR_BUFFER_S = 75.0


@dataclass(frozen=True)
class PathEdge:
    from_key: str
    to_key: str
    kind: str
    window_s: float
    from_entity: str
    to_entity: str


@dataclass
class DoorMap:
    door: str
    edges: list[PathEdge] = field(default_factory=list)
    same_view: set[frozenset] = field(default_factory=set)
    anchors: frozenset = frozenset()   # egress camera keys of the door group


@dataclass
class PathMap:
    doors: dict[str, DoorMap] = field(default_factory=dict)

    @property
    def edge_count(self) -> int:
        return sum(len(d.edges) for d in self.doors.values())


@dataclass
class ValidationContext:
    """What the validator needs from the live install (all HA-free)."""

    live_groups: set[str]
    resolve_node: Callable[[str], tuple[str | None, bool]]  # entity -> (key, has_person_leg)
    egress_keys_by_group: Mapping[str, set[str]]
    exterior_keys: set[str]
    detached_doors: set[str]
    buffer_s: float
    default_window_s: float


class PathMapError(ValueError):
    """Whole-file rejection."""


def _pairs(raw: Any) -> list[list]:
    return raw if isinstance(raw, list) else []


def validate(spec: Any, ctx: ValidationContext) -> tuple[PathMap, list[str]]:
    """Validate ``spec``; return ``(PathMap, warnings)`` or raise
    ``PathMapError`` naming the FIRST error (rules 1-10, plan rev 11 D7)."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(spec, dict) or spec.get("schema_version") != SCHEMA_VERSION:
        raise PathMapError(f"rule 1: schema_version must be {SCHEMA_VERSION}")
    doors = spec.get("doors")
    if not isinstance(doors, dict):
        raise PathMapError("rule 1: 'doors' must be an object")
    result = PathMap()
    inward_nodes_by_door: dict[str, set[str]] = {}
    for door, body in sorted(doors.items()):
        if door not in ctx.live_groups:
            errors.append(f"rule 2: door '{door}' is not a live door group")
            continue
        body = body if isinstance(body, dict) else {}
        dm = DoorMap(door=door, anchors=frozenset(ctx.egress_keys_by_group.get(door, set())))
        seen: set[tuple[str, str]] = set()
        adj: dict[str, set[str]] = {}
        for raw in _pairs(body.get("edges")):
            if not isinstance(raw, dict):
                errors.append(f"rule 4: door '{door}': edge must be an object")
                continue
            f, t, kind = raw.get("from"), raw.get("to"), raw.get("kind")
            keys = []
            for ent in (f, t):
                key, has_leg = ctx.resolve_node(ent) if isinstance(ent, str) else (None, False)
                if key is None or not has_leg:
                    errors.append(f"rule 3: door '{door}': unknown camera '{ent}'")
                keys.append(key)
            if kind not in KINDS:
                errors.append(f"rule 4: door '{door}': bad kind '{kind}'")
            if None in keys or kind not in KINDS:
                continue
            fk, tk = keys
            if fk == tk:
                errors.append(f"rule 4: door '{door}': self edge '{f}'")
                continue
            if (fk, tk) in seen:
                errors.append(f"rule 4: door '{door}': duplicate edge '{f}' -> '{t}'")
                continue
            seen.add((fk, tk))
            lag = raw.get("lag_p90_s")
            if lag is not None:
                if (isinstance(lag, bool) or not isinstance(lag, (int, float))
                        or not 0 < float(lag) <= ctx.buffer_s):
                    errors.append(
                        f"rule 8: door '{door}': lag_p90_s {lag!r} not in (0, {ctx.buffer_s:g}]")
                    continue
            window = float(lag) if lag is not None else ctx.default_window_s
            if kind == KIND_APPROACH and fk not in ctx.exterior_keys:
                warnings.append(f"rule 7: door '{door}': approach from '{f}' is not a known exterior camera")
            dm.edges.append(PathEdge(fk, tk, kind, window, f, t))
            adj.setdefault(fk, set()).add(tk)
            if kind == KIND_INWARD:
                inward_nodes_by_door.setdefault(door, set()).add(tk)
        if _has_cycle(adj):
            errors.append(f"rule 5: door '{door}': path has a cycle")
        for pair in _pairs(body.get("same_view")):
            if not (isinstance(pair, list) and len(pair) == 2):
                errors.append(f"rule 9: door '{door}': same_view entries are pairs")
                continue
            pk = []
            for ent in pair:
                key, has_leg = ctx.resolve_node(ent) if isinstance(ent, str) else (None, False)
                if key is None:
                    errors.append(f"rule 9: door '{door}': unknown camera '{ent}'")
                pk.append(key)
            if None not in pk:
                dm.same_view.add(frozenset(pk))
        nodes = {e.from_key for e in dm.edges} | {e.to_key for e in dm.edges}
        if dm.edges and not (nodes & dm.anchors):
            warnings.append(f"rule 6: door '{door}': no edge touches its egress camera (skipped)")
        result.doors[door] = dm
    for door in sorted(set(result.doors) & ctx.detached_doors):
        others = set().union(*(inward_nodes_by_door.get(d, set())
                               for d in result.doors if d not in ctx.detached_doors))
        for e in result.doors[door].edges:
            if e.kind == KIND_INWARD and e.to_key in others:
                errors.append(
                    f"rule 10: detached door '{door}' has an inward edge into house camera '{e.to_entity}'")
    if errors:
        raise PathMapError(errors[0])
    return result, warnings


def _has_cycle(adj: Mapping[str, set[str]]) -> bool:
    state: dict[str, int] = {}

    def visit(n: str) -> bool:
        state[n] = 1
        for m in adj.get(n, ()):
            s = state.get(m, 0)
            if s == 1 or (s == 0 and visit(m)):
                return True
        state[n] = 2
        return False

    return any(state.get(n, 0) == 0 and visit(n) for n in list(adj))


def _first_pair(a: Iterable[float], b: Iterable[float], lo: float, hi: float, window: float) -> bool:
    """Is there t1 in a, t2 in b with lo <= t1 < t2 <= hi and t2 - t1 <= window?"""
    bl = sorted(t for t in b if lo <= t <= hi)
    for t1 in a:
        if not lo <= t1 <= hi:
            continue
        for t2 in bl:
            if t2 > t1 and t2 - t1 <= window:
                return True
    return False


def score_path(
    path_map: PathMap | None, door: str, direction: str, t_e: float, t_decision: float,
    events: Mapping[str, Iterable[float]], *, buffer_s: float,
) -> int | None:
    """Pure path score (plan §2B.4). None = no map for this door (G2 skipped),
    never 0. +1 per distinct edge observed in the crossing's direction inside
    its window and horizon, -1 per distinct edge observed against it. Edges
    between two egress cameras of the door group and ``same_view`` pairs never
    score. Only events at or before ``t_decision`` count."""
    if path_map is None or door not in path_map.doors or direction not in ("entry", "exit"):
        return None
    dm = path_map.doors[door]
    ev = {k: [t for t in v if t <= t_decision] for k, v in events.items()}
    score = 0
    for e in dm.edges:
        if e.from_key in dm.anchors and e.to_key in dm.anchors:
            continue
        if frozenset((e.from_key, e.to_key)) in dm.same_view:
            continue
        u, v = ev.get(e.from_key, ()), ev.get(e.to_key, ())
        if direction == "entry":
            lo, hi = ((t_e - buffer_s, t_e) if e.kind == KIND_APPROACH else (t_e, t_decision))
            fwd = _first_pair(u, v, lo, hi, e.window_s)
            back = _first_pair(v, u, lo, hi, e.window_s)
        else:
            if e.kind == KIND_INWARD:
                lo, hi = t_decision - INTERIOR_BUFFER_S, t_e
            else:
                lo, hi = t_e, t_decision
            fwd = _first_pair(v, u, lo, hi, e.window_s)
            back = _first_pair(u, v, lo, hi, e.window_s)
        score += (1 if fwd else 0) - (1 if back else 0)
    return score
