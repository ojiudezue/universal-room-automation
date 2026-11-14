"""Person-awareness layer leak guard engine (ship 3a D7, plan
PLANNING_person_awareness_layer_ship3.md rev 3.2 §5 D7, rules R1-R14).

AST ONLY: it parses source text (and the string constants of ``const.py`` /
``signals.py``); it imports no production module. ``scan_tree(sources)`` takes
``{relative path: source text}`` (so a test can scan an in-memory copy of the
tree with one site reverted) and returns a list of ``Hit``.

Key of a hit: ``(rule, file, symbol)``; ``symbol`` = the qualified name of the
enclosing function (enclosing classes and defs joined by ``.``, ``<module>`` at
top level, a lambda attributed to its enclosing def) + ``:`` + the accessed
name / channel / callee.

Stated limits (plan §5 D7): dynamic ``getattr(x, name_var)`` is not seen;
dataflow is followed one hop inside one module (no cross-module dataflow);
``quality/`` and ``scripts/`` are not scanned; a G1 callback defined in another
module is not budget-checked (R14).

Interpretation notes (where the plan text admits two readings; each chosen to
match the plan's own sizing and recorded in the builder report):
* R2 ``.data`` counts on receivers bound to the person coordinator (the
  dry-run's ``person_coordinator.data`` / ``pc.data`` shape), not on every
  receiver (``entry.data`` / ``event.data`` / ``hass.data`` are not stores).
* R5 counts every positional literal view (``"trust"`` included): plan §9 #6
  pins the six display callers as six R5 rows.
* R3 / R9 / R2 apply to non-member modules only (§2.7: identity vetoes and the
  owner's own reads are layer-internal); the R3 A13 row is reserved.
* ``CONSUMER_CLASSES`` does not exist in ``const.py``; R5 derives the class set
  from the ``CONSUMER_CLASS_*`` string constants.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

URA = Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"

# --------------------------------------------------------------- the layer
MEMBER_CLASSES: dict[str, str] = {
    "PersonCensus": "camera_census.py",
    "EgressDirectionTracker": "transit_validator.py",
    "TransitValidator": "transit_validator.py",
    "PersonTrackingCoordinator": "person_coordinator.py",
    "PersonSightingProducer": "person_sighting.py",
    "CrossingVisionShadow": "crossing_vision.py",
    "CrossingLedger": "crossing_ledger.py",
    "PresenceCoordinator": "domain_coordinators/presence.py",
    "ResidencyTracker": "domain_coordinators/residency.py",
    "ZonePresenceTracker": "domain_coordinators/presence.py",
}
MEMBER_MODULES: frozenset[str] = frozenset(set(MEMBER_CLASSES.values()) | {
    "domain_coordinators/signals.py", "census_view.py", "person_ids.py",
    "arrival_edges.py", "domain_coordinators/camera_stream_health.py",
    "census_deconflict.py", "crossing_ledger.py", "nvr_witness.py",
})
# Kind of object a receiver is bound to (one hop, by value).
KIND_OF_CLASS = {
    "PersonTrackingCoordinator": "PC", "PersonCensus": "CENSUS",
    "EgressDirectionTracker": "EGRESS", "TransitValidator": "TRANSIT",
    "PresenceCoordinator": "PRESENCE", "TransitionDetector": "TD",
}
HDATA_KEYS = {
    "person_coordinator": "PC", "census": "CENSUS", "egress_tracker": "EGRESS",
    "transit_validator": "TRANSIT", "transition_detector": "TD",
}
ATTR_FORMS = {"person_coordinator": "PC", "transition_detector": "TD"}
PRESENCE_KEY = "presence"

# Contract §4 read list (public methods a non-member may call), per kind.
READ_LIST: dict[str, frozenset[str]] = {
    "PC": frozenset({
        "get_person_location", "get_person_previous_seen", "persons_in_room",
        "persons_in_room_or_scanner_areas", "location_moves_since",
        "location_moves_truncated_since", "async_add_listener", "get_zone_occupants",
        "get_bermuda_resolve_stats",
        # Plan rev 3.3 §12 / §17 (b): public reads ruled legitimate.
        "get_person_confidence", "get_persons_in_zone", "get_tracked_person_count",
        "get_person_previous_location", "get_person_previous_location_time",
        "get_diagnostic_data", "should_veto_due_to_reliable_signals",
    }),
    "PRESENCE": frozenset({
        "get_residents_home", "get_residents_home_count", "get_recent_resident_arrival",
        "get_residency_snapshot", "subscribe_person_edges", "get_person_edges_since",
        "person_edges_truncated_since", "get_house_census", "view_for_class",
        "min_confidence", "get_last_crossing", "get_crossings_since", "get_crossing",
        "get_last_arrival_record", "door_camera_device_ids", "door_entry_entities",
        "door_neighbours_for_stem", "get_last_person_sighting", "get_last_person_sightings",
        "get_layer_diagnostics",
        # Plan rev 3.3 §12 / §17 (b).
        "should_veto_due_to_reliable_signals", "check_zone_occupancy_confidence",
    }),
    "EGRESS": frozenset({
        "get_last_crossing", "get_crossings_since", "get_crossing",
        "door_camera_device_ids", "door_entry_entities", "door_neighbours_for_stem",
    }),
    "CENSUS": frozenset({
        "resolve_face_legs", "resolve_ble_legs", "tracked_person_slugs",
        "egress_identity_enabled", "canonical_person_slug", "known_face_guests",
        "face_person_would_be_vetoed", "face_suppressed_now",
    }),
    "TRANSIT": frozenset(),
}

STREAM_HEALTH_NAMES = frozenset({
    "camera_input_stream_dead", "camera_stream_dead", "camera_input_stream_hold_expired",
    "camera_stream_hold_expired", "camera_input_stream_unavailable_held",
    "camera_input_room_quarantined", "_camera_stream_health",
})

# R6 / R10 channels by constant name (value read from const/signals) + owner.
CHANNEL_CONSTS: dict[str, tuple[str, str | None]] = {
    "SIGNAL_PERSON_ARRIVING": ("domain_coordinators/signals.py", "dispatch_person_arriving"),
    "SIGNAL_RESIDENCY_EVENT": ("domain_coordinators/presence.py", "PresenceCoordinator._feed_residency"),
    "SIGNAL_CENSUS_UPDATED": ("camera_census.py", None),
    "SIGNAL_EGRESS_RECORD_AMENDED": ("transit_validator.py", "_send_record_amended"),
    "SIGNAL_PERSON_SIGHTING": ("person_sighting.py", "PersonSightingProducer._emit"),
}
# Channels that are string literals in code (bus events) + owner.
CHANNEL_LITERALS: dict[str, tuple[str, str | None]] = {
    "ura_person_egress_event": ("transit_validator.py", "EgressDirectionTracker._resolve_direction"),
    "ura_person_location_change": ("person_coordinator.py", "PersonTrackingCoordinator._async_update_data"),
}
# The census-p2 residency-channel value shim (plan rev 3.3 §16) is removed:
# SIGNAL_RESIDENCY_EVENT is on develop (v5.108.23, bc4f462b).
CHANNEL_FALLBACK_VALUES: dict[str, str] = {}

R13_CALLEES = frozenset({
    "dispatch_person_arriving", "attach_crossing_attribute", "amend_crossing",
    "set_pre_arrival_enabled", "register_face_latch_callback", "note_face",
})
LATCH_KEY = "face_latch_callbacks"
PERSON_PREFIXES = ("person.", "device_tracker.", "sensor.bermuda")
PERSON_UID_SUFFIXES = ("_phone_left_behind", "_camera_person_detected", "persons_in_house",
                       "_person_location", "_likely_next_room")
STORE_ATTRS_OWNER = {
    "last_result": "camera_census.py",
    "_gps_home_overruled": "person_coordinator.py",
    "_last_sightings": "person_sighting.py",
    "_crossing_ring": "transit_validator.py",
    "_last_crossing": "transit_validator.py",
    "_last_crossing_by_camera": "transit_validator.py",
}
CENSUS_COUNT_FIELDS = frozenset({
    "identified_count", "unidentified_count", "total_persons", "identified_persons",
    "frigate_count", "unifi_count", "wifi_guest_floor", "camera_unrecognized",
})
RECORD_OWNERS = {
    "CrossingRecord": ("transit_validator.py",),
    "CensusZoneResult": ("camera_census.py", "census_deconflict.py"),
    "CensusResult": ("camera_census.py", "census_deconflict.py"),
    "PersonSighting": ("person_sighting.py",),
}
CLASS_THRESHOLDS = (0.75, 0.9)
# R2 store reads: attribute -> the modules allowed to read it.
R2_STORE_OWNERS: dict[str, tuple[str, ...]] = {
    "last_result": ("camera_census.py", "census_view.py", "census_deconflict.py"),
    "_last_sightings": ("person_sighting.py",),
    "_camera_sightings": ("transit_validator.py",),
}
R2_PRIVATE_STORES = frozenset({"_last_sightings", "_camera_sightings"})
# Plan rev 3.3 §5 D7 (ruled 4d337e44): lifecycle callees only, by name; a
# person-fact read during setup still counts.
R2_LIFECYCLE_EXACT = frozenset({
    "async_init", "async_teardown", "async_shutdown", "rebind",
    # Coordinator ruling on the six first-run lifecycle rows (explicit names,
    # no pattern): listener (un)registration / memory load / task cancel.
    "register_ble_transition_listeners", "async_register_frigate_face_listener",
    "async_load_fleet_memory", "async_cancel_pending_backfill_tasks",
    "async_teardown_ble_transition_listeners", "async_teardown_frigate_face_listener",
})
R2_LIFECYCLE_PREFIXES = ("async_setup", "async_unload")


def _is_lifecycle(name: str) -> bool:
    return name in R2_LIFECYCLE_EXACT or name.startswith(R2_LIFECYCLE_PREFIXES)


# Plan rev 3.3 §5 D7: member names that answer no F1-F5 fact.
LAYER_NON_PERSON_PRIVATES = frozenset({"_boot_settle_done"})
LAYER_NON_PERSON_PUBLIC = frozenset({
    "tracker_for_room", "get_fan_last_transition", "is_room_mmwave_fan_demoted",
    "set_fan_interference_hold_s", "set_house_state_override", "get_house_state_override",
    "get_house_occupancy", "get_next_state_prediction", "is_room_direct_ble", "get_ble_tier",
    "path_map_status", "get_stuck_cameras",
})
# R3 (iii) / R9: Bermuda fleet-health entities are not per-person.
FLEET_HEALTH_PREFIX = "sensor.bermuda_global"
# R9: the ONE person.* listener (presence geofence edges) and the ledger.
R9_OWNERS = {
    "domain_coordinators/presence.py": ("PresenceCoordinator._subscribe_geofence",
                                         "PresenceCoordinator._track_geofence_persons",
                                         "PresenceCoordinator._handle_person_added"),
    "domain_coordinators/residency.py": ("ResidencyTracker",),
}


def _nonmember_source(e) -> bool:
    """``hass.data[...]["k"]`` / ``.get("k")`` with a key that is not a layer
    member key (``camera_manager`` ...)."""
    k = None
    if isinstance(e, ast.Subscript):
        k = _str_const(e.slice)
    elif isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute) and e.func.attr == "get" and e.args:
        k = _str_const(e.args[0])
    elif isinstance(e, ast.BoolOp):
        return any(_nonmember_source(v) for v in e.values)
    if k is None or k in HDATA_KEYS or k == PRESENCE_KEY:
        return False
    return "data" in _receiver_text(e.value if isinstance(e, ast.Subscript) else e.func.value)


def _r3_membership_only(call, func) -> bool:
    """R3 (i): the person read yields ids only (``async_entity_ids``, or a
    comprehension whose element is ``x.entity_id``) and the result is used only
    for ``in`` / ``not in`` membership or returned (a picker)."""
    if func is None:
        return False
    target = None
    for st in ast.walk(func):
        if isinstance(st, ast.Assign) and any(c is call for c in ast.walk(st.value)):
            v = st.value
            ids_only = (v is call and _call_name(call) == "async_entity_ids") or (
                isinstance(v, (ast.SetComp, ast.ListComp)) and isinstance(v.elt, ast.Attribute)
                and v.elt.attr == "entity_id" and any(g.iter is call for g in v.generators))
            if ids_only and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                target = st.targets[0].id
            break
        if isinstance(st, ast.Return) and st.value is not None and any(c is call for c in ast.walk(st.value)):
            return _call_name(call) == "async_entity_ids" or (
                isinstance(st.value, (ast.SetComp, ast.ListComp)) and isinstance(st.value.elt, ast.Attribute)
                and st.value.elt.attr == "entity_id")
    if target is None:
        return False
    for n in ast.walk(func):
        if isinstance(n, ast.Name) and n.id == target and isinstance(n.ctx, ast.Load):
            parent_ok = False
            for c in ast.walk(func):
                if isinstance(c, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in c.ops) \
                        and any(x is n for x in c.comparators):
                    parent_ok = True
                if isinstance(c, ast.Return) and c.value is n:
                    parent_ok = True
            if not parent_ok:
                return False
    return True


def _r3_actor_identity(func) -> bool:
    """R3 (ii): the function filters person states on ``attributes["user_id"]``."""
    if func is None:
        return False
    return any(isinstance(c, ast.Constant) and c.value == "user_id" for c in ast.walk(func))


R5_OWNER_DELEGATES = {
    "domain_coordinators/presence.py": ("PresenceCoordinator.get_house_census",
                                         "PresenceCoordinator.view_for_class"),
    "census_view.py": ("house_census_view",),
}


def _r5_owner_delegate(rel: str, qual: str) -> bool:
    return qual in R5_OWNER_DELEGATES.get(rel, ())


def _is_values_iter(e) -> bool:
    """``d.values()`` / ``d.items()``, possibly wrapped in list/tuple/sorted."""
    if isinstance(e, ast.Call):
        name = e.func.attr if isinstance(e.func, ast.Attribute) else getattr(e.func, "id", None)
        if name in ("values", "items") and isinstance(e.func, ast.Attribute):
            return True
        if name in ("list", "tuple", "sorted") and e.args:
            return _is_values_iter(e.args[0])
    return False


def _r9_owner(rel: str, qual: str) -> bool:
    return any(qual == q or qual.startswith(q + ".") for q in R9_OWNERS.get(rel, ()))


def _is_ura_uid_call(e) -> bool:
    """``async_get_entity_id(..., DOMAIN, <uid with a person-awareness suffix>)``."""
    if not (isinstance(e, ast.Call) and isinstance(e.func, (ast.Attribute, ast.Name))):
        return False
    name = e.func.attr if isinstance(e.func, ast.Attribute) else e.func.id
    if name != "async_get_entity_id":
        return False
    for a in list(e.args) + [k.value for k in e.keywords]:
        parts = [a] if not isinstance(a, ast.JoinedStr) else list(a.values)
        for p in parts:
            if isinstance(p, ast.Constant) and isinstance(p.value, str) \
                    and p.value.endswith(PERSON_UID_SUFFIXES):
                return True
    return False
R14_FORBIDDEN_CALL_RE = re.compile(
    r"(^|\.)(services\.|async_add_executor_job|database\.|recorder|get_instance\()")


@dataclass(frozen=True)
class Hit:
    rule: str
    file: str
    symbol: str
    line: int
    kind: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.rule, self.file, self.symbol)


# ------------------------------------------------------------ AST helpers
def _docstring_ids(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(n, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                out.add(id(body[0].value))
    return out


_SCOPED_CACHE: dict[int, list] = {}


def iter_scoped(tree: ast.AST) -> list:
    """(node, qualname, func_node) for every node. qualname = enclosing classes
    and defs joined by '.', '<module>' at top level; a def / class node itself
    carries the OUTER qualname; a lambda is attributed to its enclosing def."""
    cached = _SCOPED_CACHE.get(id(tree))
    if cached is not None and cached[0] is tree:
        return cached[1]
    out: list = []
    _SCOPED_CACHE[id(tree)] = (tree, out)

    def rec(node, stack, func):
        out.append((node, ".".join(stack) or "<module>", func))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for d in node.decorator_list:
                rec(d, stack, func)
            if not isinstance(node, ast.ClassDef):
                rec(node.args, stack, func)
                if node.returns is not None:
                    rec(node.returns, stack, func)
            else:
                for b in node.bases:
                    rec(b, stack, func)
            inner_func = func if isinstance(node, ast.ClassDef) else node
            for b in node.body:
                rec(b, stack + [node.name], inner_func)
            return
        for child in ast.iter_child_nodes(node):
            rec(child, stack, func)

    for top in ast.iter_child_nodes(tree):
        rec(top, [], None)
    return out


def _call_name(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _str_const(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _module_str_consts(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for st in tree.body:
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
            v = _str_const(st.value)
            if v is not None:
                out[st.targets[0].id] = v
        elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and st.value is not None:
            v = _str_const(st.value)
            if v is not None:
                out[st.target.id] = v
    return out


def _module_num_consts(tree: ast.Module) -> list[tuple[str, float, int]]:
    out = []
    for st in tree.body:
        tgt = val = None
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
            tgt, val = st.targets[0].id, st.value
        elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
            tgt, val = st.target.id, st.value
        if tgt and isinstance(val, ast.Constant) and isinstance(val.value, (int, float)) \
                and not isinstance(val.value, bool):
            out.append((tgt, float(val.value), st.lineno))
    return out


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    """local name -> imported name (``from x import A as B`` -> B: A)."""
    out: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                out[a.asname or a.name] = a.name
    return out


# --------------------------------------------------------------- harvest
@dataclass
class Harvest:
    private_by_class: dict[str, set[str]] = field(default_factory=dict)
    public_by_kind: dict[str, set[str]] = field(default_factory=dict)
    nonmember_private: set[str] = field(default_factory=set)
    member_unique: set[str] = field(default_factory=set)
    consts: dict[str, str] = field(default_factory=dict)
    consumer_classes: frozenset[str] = frozenset()
    person_conf_lists: frozenset[str] = frozenset()


def _class_names(cls: ast.ClassDef) -> tuple[set[str], set[str]]:
    private, public = set(), set()
    for n in cls.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if n.name.startswith("__"):
                continue
            (private if n.name.startswith("_") else public).add(n.name)
    for n in ast.walk(cls):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self" \
                and isinstance(n.ctx, ast.Store) and n.attr.startswith("_") \
                and not n.attr.startswith("__"):
            private.add(n.attr)
    return private, public


def harvest(trees: dict[str, ast.Module]) -> Harvest:
    h = Harvest()
    all_member_names: set[str] = set()
    nonmember_all: set[str] = set()
    for rel, tree in trees.items():
        for n in ast.walk(tree):
            if not isinstance(n, ast.ClassDef):
                continue
            private, public = _class_names(n)
            if MEMBER_CLASSES.get(n.name) == rel:
                h.private_by_class[n.name] = private - LAYER_NON_PERSON_PRIVATES
                kind = KIND_OF_CLASS.get(n.name)
                if kind:
                    h.public_by_kind.setdefault(kind, set()).update(public)
                all_member_names |= private | public
            else:
                if n.name == "TransitionDetector" and rel == "transitions.py":
                    h.public_by_kind.setdefault("TD", set()).update(public)
                h.nonmember_private |= private
                nonmember_all |= private | public
    h.member_unique = {n for n in all_member_names - nonmember_all if len(n) > 6}
    for rel in ("const.py", "domain_coordinators/signals.py"):
        if rel in trees:
            h.consts.update(_module_str_consts(trees[rel]))
    h.consumer_classes = frozenset(
        v for k, v in h.consts.items() if k.startswith("CONSUMER_CLASS_") and isinstance(v, str))
    h.person_conf_lists = frozenset(
        k for k in h.consts if k.startswith("CONF_") and "PERSONS" in k)
    return h


# --------------------------------------------------------------- binding
def _hdata_key_kind(expr) -> str | None:
    """A source expression that yields a member object (one hop)."""
    if isinstance(expr, ast.Subscript):
        k = _str_const(expr.slice)
        if k in HDATA_KEYS:
            return HDATA_KEYS[k]
        if k == PRESENCE_KEY and "coordinators" in ast.unparse(expr.value):
            return "PRESENCE"
    if isinstance(expr, ast.Call):
        name = _call_name(expr)
        if name == "get" and expr.args:
            k = _str_const(expr.args[0])
            if k in HDATA_KEYS:
                return HDATA_KEYS[k]
            if k == PRESENCE_KEY and "coordinators" in ast.unparse(expr.func):
                return "PRESENCE"
        if name == "getattr" and len(expr.args) >= 2:
            k = _str_const(expr.args[1])
            if k in HDATA_KEYS:
                return HDATA_KEYS[k]
    if isinstance(expr, ast.Attribute) and expr.attr in ATTR_FORMS:
        return ATTR_FORMS[expr.attr]
    if isinstance(expr, ast.Call) and _call_name(expr) in KIND_OF_CLASS:
        return KIND_OF_CLASS[_call_name(expr)]
    if isinstance(expr, ast.BoolOp):
        for v in expr.values:
            k = _hdata_key_kind(v)
            if k:
                return k
    if isinstance(expr, ast.IfExp):
        return _hdata_key_kind(expr.body) or _hdata_key_kind(expr.orelse)
    return None


class Binder:
    """Per module: names (per function) and ``self.X`` attrs bound to member
    kinds, one hop (``x = hass.data[DOMAIN]["person_coordinator"]``,
    ``self._pc = ...``, ``getattr(m, "person_coordinator")`` ...)."""

    def __init__(self, tree: ast.Module):
        self.local: dict[int, dict[str, str]] = {}
        self.self_attrs: dict[str, str] = {}
        self.nonmember_local: dict[int, set[str]] = {}
        self.nonmember_attrs: set[str] = set()
        for node, _q, func in iter_scoped(tree):
            if isinstance(node, ast.Assign) and _nonmember_source(node.value):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.nonmember_local.setdefault(id(func), set()).add(t.id)
                    elif isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) \
                            and t.value.id == "self":
                        self.nonmember_attrs.add(t.attr)
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                if value is None:
                    continue
                kind = _hdata_key_kind(value)
                if kind is None and isinstance(value, ast.Name):
                    kind = self.local.get(id(func), {}).get(value.id)
                if kind is None:
                    continue
                for t in targets:
                    if isinstance(t, ast.Name):
                        self.local.setdefault(id(func), {})[t.id] = kind
                    elif isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) \
                            and t.value.id == "self":
                        self.self_attrs[t.attr] = kind

    def nonmember(self, expr, func) -> bool:
        """The receiver is bound (by value, one hop) to a NON-member object
        from hass.data (e.g. ``camera_manager``): R1 does not count it."""
        if isinstance(expr, ast.Name):
            return expr.id in self.nonmember_local.get(id(func), set())
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name) \
                and expr.value.id == "self":
            return expr.attr in self.nonmember_attrs
        return _nonmember_source(expr)

    def kind(self, expr, func) -> str | None:
        k = _hdata_key_kind(expr)
        if k:
            return k
        if isinstance(expr, ast.Name):
            return self.local.get(id(func), {}).get(expr.id)
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name) \
                and expr.value.id == "self":
            return self.self_attrs.get(expr.attr) or ATTR_FORMS.get(expr.attr)
        return None


_MEMBERISH = re.compile(
    r"(cens|person_coord|\bpc\b|presence|egress_tracker|transit|sighting|zone_tracker|"
    r"\btracker\b|residency)")


# --------------------------------------------------------------- taint (R3)
class Taint:
    def __init__(self, tree: ast.Module, h: Harvest):
        self.h = h
        self.names: dict[int, set[str]] = {}
        self.self_attrs: set[str] = set()
        self.funcs: set[str] = set()
        scoped = iter_scoped(tree)
        defs: dict[str, list] = {}
        for node, _q, _f in scoped:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs.setdefault(node.name, []).append(node)
        # Phase A: intrinsic taint (assignments, loops, function returns),
        # no parameter taint, so a helper's return is tainted only by its
        # own body. Phase B: one hop of call-site parameter taint, which
        # reaches sinks inside the callee but never feeds a return back.
        self._propagate(scoped, defs=None)
        self._propagate(scoped, defs=defs)

    def _propagate(self, scoped, defs) -> None:
        for _ in range(5):  # fixed point, small
            changed = False
            if defs is not None:
                for node, _q, func in scoped:
                    if not isinstance(node, ast.Call):
                        continue
                    name = _call_name(node)
                    if name not in defs:
                        continue
                    for fn in defs[name]:
                        params = [a.arg for a in fn.args.args]
                        if params and params[0] in ("self", "cls") and isinstance(node.func, ast.Attribute):
                            params = params[1:]
                        pairs = list(zip(params, node.args)) + [
                            (k.arg, k.value) for k in node.keywords if k.arg]
                        for pname, arg in pairs:
                            if self.expr(arg, func):
                                s = self.names.setdefault(id(fn), set())
                                if pname not in s:
                                    s.add(pname)
                                    changed = True
            for node, _q, func in scoped:
                if isinstance(node, ast.Assign):
                    # ``out[<tainted key>] = v`` taints the container
                    for t in node.targets:
                        if isinstance(t, ast.Subscript) and self.expr(t.slice, func):
                            base = t.value
                            if isinstance(base, ast.Name):
                                s = self.names.setdefault(id(func), set())
                                if base.id not in s:
                                    s.add(base.id)
                                    changed = True
                if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    if self.expr(node.value, func):
                        for t in targets:
                            for nm in ast.walk(t):
                                if isinstance(nm, ast.Name):
                                    s = self.names.setdefault(id(func), set())
                                    if nm.id not in s:
                                        s.add(nm.id)
                                        changed = True
                                elif isinstance(nm, ast.Attribute) and isinstance(nm.value, ast.Name) \
                                        and nm.value.id == "self" and nm.attr not in self.self_attrs:
                                    self.self_attrs.add(nm.attr)
                                    changed = True
                elif isinstance(node, (ast.For, ast.AsyncFor)) and self.expr(node.iter, func):
                    for nm in ast.walk(node.target):
                        if isinstance(nm, ast.Name):
                            s = self.names.setdefault(id(func), set())
                            if nm.id not in s:
                                s.add(nm.id)
                                changed = True
                elif defs is None and isinstance(node, ast.Return) and node.value is not None \
                        and func is not None and self.expr(node.value, func) \
                        and func.name not in self.funcs:
                    self.funcs.add(func.name)
                    changed = True
            if not changed:
                break

    def const(self, s: str) -> bool:
        if s.startswith(FLEET_HEALTH_PREFIX):
            return False  # R3 (iii): fleet health, not a person
        return s.startswith(PERSON_PREFIXES) or "states.person" in s \
            or "is_state('person." in s or 'is_state("person.' in s

    def expr(self, e, func) -> bool:
        if e is None:
            return False
        if isinstance(e, ast.Constant) and isinstance(e.value, str):
            return self.const(e.value)
        if isinstance(e, ast.JoinedStr):
            first = e.values[0] if e.values else None
            return isinstance(first, ast.Constant) and isinstance(first.value, str) \
                and self.const(first.value)
        if isinstance(e, ast.BinOp) and isinstance(e.op, ast.Add):
            return self.expr(e.left, func) or (
                not isinstance(e.left, (ast.Constant, ast.JoinedStr)) and self.expr(e.right, func))
        if isinstance(e, ast.BinOp) and isinstance(e.op, (ast.BitOr, ast.BitAnd, ast.Sub)):
            return self.expr(e.left, func) or self.expr(e.right, func)
        if isinstance(e, ast.Name):
            return e.id in self.names.get(id(func), set())
        if isinstance(e, ast.Attribute):
            if isinstance(e.value, ast.Name) and e.value.id == "self" and e.attr in self.self_attrs:
                return True
            if e.attr in ("entity_id", "attributes") and isinstance(e.value, ast.Name) \
                    and e.value.id in self.names.get(id(func), set()):
                return True  # a tainted State's entity_id / attributes
            return False
        if isinstance(e, ast.Subscript):
            k = e.slice
            if isinstance(k, ast.Name) and k.id in self.h.person_conf_lists:
                return True
            return self.expr(e.value, func) if isinstance(e.value, ast.Name) else False
        if isinstance(e, ast.Call):
            name = _call_name(e)
            if name == "tracked_person_entity_id":
                return True
            if name == "async_get_entity_id":
                for a in list(e.args) + [k.value for k in e.keywords]:
                    s = _str_const(a)
                    if s is None and isinstance(a, ast.JoinedStr):
                        s = "".join(_str_const(v) or "" for v in a.values)
                    if s and s.endswith(PERSON_UID_SUFFIXES):
                        return True
                    if isinstance(a, ast.JoinedStr) and any(
                            (_str_const(v) or "").endswith(PERSON_UID_SUFFIXES) for v in a.values):
                        return True
                return False
            if name == "get" and e.args and isinstance(e.args[0], ast.Name) \
                    and e.args[0].id in self.h.person_conf_lists:
                return True
            if name in self.funcs:
                return True
            if name in ("async_all", "async_entity_ids") and e.args and _str_const(e.args[0]) == "person":
                return True
            if name in ("list", "sorted", "set", "tuple", "frozenset") and e.args:
                return self.expr(e.args[0], func)
            f = e.func
            # ``hass.states.get(<tainted>)`` returns a tainted State; a method
            # of a tainted value (``st.attributes.get(...)``) stays tainted.
            if name == "get" and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute) \
                    and f.value.attr == "states" and e.args and self.expr(e.args[0], func):
                return True
            if name in ("keys", "values", "items", "copy", "get") and isinstance(f, ast.Attribute) \
                    and isinstance(f.value, ast.Name) and self.expr(f.value, func):
                return True
            if name == "getattr" and len(e.args) >= 2 and _str_const(e.args[1]) in ("attributes", "entity_id") \
                    and self.expr(e.args[0], func):
                return True
            if name == "str" and e.args:
                return self.expr(e.args[0], func)
            # ``<tainted state>.attributes.get("device_trackers")``
            if name == "get" and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute) \
                    and f.value.attr == "attributes" and self.expr(f.value, func):
                return True
            return False
        if isinstance(e, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            elt = e.key if isinstance(e, ast.DictComp) else e.elt
            if isinstance(elt, (ast.Constant, ast.JoinedStr, ast.BinOp)) and self.expr(elt, func):
                return True
            for g in e.generators:
                if self.expr(g.iter, func):
                    return True
                for cond in g.ifs:
                    for c in ast.walk(cond):
                        if isinstance(c, ast.Call) and _call_name(c) == "startswith" and c.args \
                                and self.expr(c.args[0], func):
                            return True
            return False
        if isinstance(e, (ast.List, ast.Tuple, ast.Set)):
            return any(self.expr(x, func) for x in e.elts)
        if isinstance(e, ast.BoolOp):
            return any(self.expr(v, func) for v in e.values)
        if isinstance(e, ast.IfExp):
            return self.expr(e.body, func) or self.expr(e.orelse, func)
        return False


# --------------------------------------------------------------- the scan
def _resolve_value(e, local_consts: dict[str, str], aliases: dict[str, str], h: Harvest) -> str | None:
    s = _str_const(e)
    if s is not None:
        return s
    if isinstance(e, ast.Name):
        if e.id in local_consts:
            return local_consts[e.id]
        name = aliases.get(e.id, e.id)
        return h.consts.get(name) or CHANNEL_FALLBACK_VALUES_VALUE.get(name)
    if isinstance(e, ast.Attribute):
        return h.consts.get(e.attr) or CHANNEL_FALLBACK_VALUES_VALUE.get(e.attr)
    return None


CHANNEL_FALLBACK_VALUES_VALUE = dict(CHANNEL_FALLBACK_VALUES)


def channel_owners(h: Harvest) -> dict[str, tuple[str, str | None]]:
    out = dict(CHANNEL_LITERALS)
    for cname, owner in CHANNEL_CONSTS.items():
        v = h.consts.get(cname) or CHANNEL_FALLBACK_VALUES.get(cname)
        if v:
            out[v] = owner
    return out


def _owner_ok(owner: tuple[str, str | None], rel: str, qual: str) -> bool:
    f, q = owner
    if rel != f:
        return False
    return q is None or qual == q or qual.startswith(q + ".")


def _receiver_text(node) -> str:
    try:
        return ast.unparse(node).lower()
    except Exception:  # noqa: BLE001
        return ""


def scan_module(rel: str, tree: ast.Module, h: Harvest) -> list[Hit]:
    hits: list[Hit] = []
    member = rel in MEMBER_MODULES
    binder = Binder(tree)
    taint = Taint(tree, h)
    local_consts = _module_str_consts(tree)
    aliases = _import_aliases(tree)
    owners = channel_owners(h)
    docs = _docstring_ids(tree)
    own_classes = {c for c, m in MEMBER_CLASSES.items() if m == rel}
    foreign_private: dict[str, str] = {}
    for c, names in h.private_by_class.items():
        if c in own_classes:
            continue
        for n in names:
            foreign_private.setdefault(n, c)
    r7_nodes: set[int] = set()
    # Injectable tracker aliases (``self._track_state = track_state or
    # ha_event.async_track_state_change_event``), resolved by value.
    tracker_aliases: dict[str, str] = {}
    ura_uid_names: dict[int, set[str]] = {}
    # R4: names holding a dict's ``.values()`` / ``.items()`` (one hop).
    values_names: dict[int, set[str]] = {}
    for n, _q, f in iter_scoped(tree):
        if isinstance(n, ast.Assign) and _is_values_iter(n.value):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    values_names.setdefault(id(f), set()).add(t.id)
    for n, _q, f in iter_scoped(tree) + iter_scoped(tree):  # two passes: alias chains
        if isinstance(n, ast.Assign) and n.value is not None:
            txt = _receiver_text(n.value)
            if isinstance(n.value, ast.Name) and n.value.id in tracker_aliases:
                txt = tracker_aliases[n.value.id]
            for canon in ("async_track_state_change_event", "async_track_state_added_domain"):
                if canon in txt and not isinstance(n.value, ast.Call):
                    for t in n.targets:
                        if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) \
                                and t.value.id == "self":
                            tracker_aliases[t.attr] = canon
                        elif isinstance(t, ast.Name):
                            tracker_aliases[t.id] = canon
            if _is_ura_uid_call(n.value):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        ura_uid_names.setdefault(id(f), set()).add(t.id)

    def add(rule, qual, name, node, kind=""):
        hits.append(Hit(rule, rel, f"{qual}:{name}", getattr(node, "lineno", 0), kind))

    def r1_kind(name, recv, func):
        """A name also private on a non-member class is a collision: a leak
        only when the receiver resolves (by value, one hop) to a member."""
        if name in h.nonmember_private:
            return "leak" if binder.kind(recv, func) else "name_collision"
        return "leak"

    def member_receiver(recv, func) -> bool:
        return bool(binder.kind(recv, func)) or bool(_MEMBERISH.search(_receiver_text(recv)))

    scoped = list(iter_scoped(tree))
    # CoordinatorEntity classes built with the person coordinator: their
    # ``super().__init__(<arg>)`` passes a PC-bound value or a parameter whose
    # name names the person coordinator (one hop).
    pc_entity_classes: set[str] = set()
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for c in ast.walk(cls):
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) \
                    and c.func.attr == "__init__" and isinstance(c.func.value, ast.Call) \
                    and _call_name(c.func.value) == "super" and c.args:
                a = c.args[0]
                if (isinstance(a, ast.Name) and "person_coord" in a.id) or _hdata_key_kind(a) == "PC":
                    pc_entity_classes.add(cls.name)
    # Functions that read a tainted person state (R9 polling-ledger anchor).
    tainted_read_funcs: set[int] = set()
    if not member:
        for c, _q, f in scoped:
            if isinstance(c, ast.Call) and _call_name(c) == "get" and isinstance(c.func, ast.Attribute) \
                    and isinstance(c.func.value, ast.Attribute) and c.func.value.attr == "states" \
                    and c.args and taint.expr(c.args[0], f):
                tainted_read_funcs.add(id(f))
    # ---------------- R7 first (store writes take precedence over R1)
    for node, qual, func in scoped:
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                base = t
                while isinstance(base, ast.Subscript):
                    base = base.value
                if isinstance(base, ast.Attribute):
                    recv_self = isinstance(base.value, ast.Name) and base.value.id == "self"
                    owner = STORE_ATTRS_OWNER.get(base.attr)
                    if owner and rel != owner and not recv_self:
                        add("R7", qual, base.attr, node)
                        r7_nodes.add(id(base))
                    elif base.attr in CENSUS_COUNT_FIELDS and not recv_self \
                            and rel not in ("camera_census.py", "census_deconflict.py") \
                            and (_MEMBERISH.search(_receiver_text(base.value))
                                 or "result" in _receiver_text(base.value)):
                        add("R7", qual, base.attr, node)
                        r7_nodes.add(id(base))
                    elif base.attr == "data" and binder.kind(base.value, func) == "PC" \
                            and rel != "person_coordinator.py":
                        add("R7", qual, "data", node)
                        r7_nodes.add(id(base))
                    elif rel == "transit_validator.py" and base.attr == "_crossing_ring" \
                            and isinstance(t, ast.Subscript) \
                            and qual not in ("EgressDirectionTracker._record_crossing",
                                             "EgressDirectionTracker.attach_crossing_attribute"):
                        add("R7", qual, "_crossing_ring", node)
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in RECORD_OWNERS and rel not in RECORD_OWNERS[name]:
                add("R7", qual, name, node)
            if name == "setattr" and len(node.args) >= 2:
                s = _str_const(node.args[1])
                if s in STORE_ATTRS_OWNER and rel != STORE_ATTRS_OWNER[s]:
                    add("R7", qual, s, node)
                    r7_nodes.add(id(node))
            if name in ("replace", "_dc_replace") and (
                    "dataclasses" in _receiver_text(node.func) or name == "_dc_replace"
                    or isinstance(node.func, ast.Name)):
                if rel == "transit_validator.py":
                    if qual != "EgressDirectionTracker.attach_crossing_attribute":
                        add("R7", qual, "replace", node)
                elif any(imp in aliases for imp in ("CrossingRecord", "CensusZoneResult", "PersonSighting")) \
                        and rel not in ("camera_census.py", "person_sighting.py", "census_deconflict.py"):
                    add("R7", qual, "replace", node)
            if name == "update" and isinstance(node.func, ast.Attribute) \
                    and isinstance(node.func.value, ast.Attribute) \
                    and node.func.value.attr == "__dict__" and not member:
                add("R7", qual, "__dict__.update", node)

    for node, qual, func in scoped:
        # ---------------- R1 private member access
        if isinstance(node, ast.Attribute) and node.attr in foreign_private and id(node) not in r7_nodes \
                and node.attr not in R2_PRIVATE_STORES:
            recv = node.value
            if not (isinstance(recv, ast.Name) and recv.id in ("self", "cls")) \
                    and not binder.nonmember(recv, func):
                add("R1", qual, node.attr, node, r1_kind(node.attr, recv, func))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ("getattr", "hasattr", "setattr", "delattr") \
                and len(node.args) >= 2 and id(node) not in r7_nodes:
            s = _str_const(node.args[1])
            if s in foreign_private:
                recv = node.args[0]
                if not (isinstance(recv, ast.Name) and recv.id in ("self", "cls")) \
                        and not binder.nonmember(recv, func):
                    add("R1", qual, s, node, r1_kind(s, recv, func))
        if not member:
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "vars" \
                    and node.args and member_receiver(node.args[0], func):
                add("R1", qual, "vars", node, "vars")
            if isinstance(node, ast.Attribute) and node.attr == "__dict__" \
                    and not (isinstance(node.value, ast.Name) and node.value.id in ("self", "cls")) \
                    and member_receiver(node.value, func):
                add("R1", qual, "__dict__", node, "vars")

        # ---------------- R2 store reads (outside the store owner) and
        # member PUBLIC methods off the contract read list (non-member modules)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            owner = R2_STORE_OWNERS.get(node.attr)
            if owner is not None and rel not in owner:
                add("R2", qual, node.attr, node)
            elif node.attr == "data" and rel != "person_coordinator.py" \
                    and binder.kind(node.value, func) == "PC":
                add("R2", qual, "data", node)
            elif node.attr == "data" and rel != "person_coordinator.py" \
                    and _receiver_text(node.value) == "self.coordinator" \
                    and qual.split(".", 1)[0] in pc_entity_classes:
                add("R2", qual, "coordinator.data", node)
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name == "getattr" and len(node.args) >= 2 and _str_const(node.args[1]) == "data" \
                    and rel != "person_coordinator.py" and binder.kind(node.args[0], func) == "PC":
                add("R2", qual, "data", node)
            if not member and isinstance(node.func, ast.Attribute):
                kind = binder.kind(node.func.value, func)
                if kind and kind != "TD" and kind in h.public_by_kind \
                        and name in h.public_by_kind[kind] \
                        and name not in READ_LIST.get(kind, frozenset()) \
                        and name not in R13_CALLEES and name != "async_add_listener" \
                        and name not in LAYER_NON_PERSON_PUBLIC and not _is_lifecycle(name):
                    add("R2", qual, name, node)

        # ---------------- R3 raw person-entity reads: every taint source in a
        # non-member module; a URA person-awareness entity read anywhere
        if isinstance(node, ast.Call):
            name = _call_name(node)
            f = node.func
            if name == "get" and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute) \
                    and f.value.attr == "states" and node.args:
                a0 = node.args[0]
                if not member and taint.expr(a0, func):
                    add("R3", qual, "states.get", node)
                elif member and (
                        (isinstance(a0, ast.Name) and a0.id in ura_uid_names.get(id(func), set()))
                        or _is_ura_uid_call(a0)):
                    add("R3", qual, "states.get(ura_entity)", node, "ura_entity")
            elif not member and name in ("async_all", "async_entity_ids") and node.args \
                    and _str_const(node.args[0]) == "person" \
                    and not _r3_membership_only(node, func) and not _r3_actor_identity(func):
                add("R3", qual, name, node)
            elif not member and name in ("Template", "async_track_template_result") and node.args \
                    and any(taint.expr(a, func) for a in node.args[:2]):
                add("R3", qual, name, node)
        if not member and isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            for g in node.generators:
                if isinstance(g.iter, ast.Call) and _call_name(g.iter) == "async_all":
                    for cond in g.ifs:
                        for c in ast.walk(cond):
                            if isinstance(c, ast.Call) and _call_name(c) == "startswith" and c.args \
                                    and taint.expr(c.args[0], func):
                                add("R3", qual, "async_all_filter", node)

        # ---------------- R4 hass.data scans (non-member modules + the owner)
        if (not member or rel == "domain_coordinators/camera_stream_health.py") \
                and isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            it = node.iter
            if _is_values_iter(it) or (isinstance(it, ast.Name)
                                       and it.id in values_names.get(id(func), set())):
                targets = {n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)}
                body = node.body if isinstance(node, (ast.For, ast.AsyncFor)) else []
                scope_nodes = []
                for b in body:
                    scope_nodes.extend(ast.walk(b))
                if isinstance(node, ast.comprehension):
                    scope_nodes = list(ast.walk(_COMP_PARENT.get(id(node), node)))
                for c in scope_nodes:
                    nm = None
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) \
                            and c.func.id in ("getattr", "hasattr") and len(c.args) >= 2 \
                            and isinstance(c.args[0], ast.Name) and c.args[0].id in targets:
                        nm = _str_const(c.args[1])
                    elif isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "isinstance" \
                            and len(c.args) >= 2 and isinstance(c.args[0], ast.Name) and c.args[0].id in targets:
                        cls_txt = ast.unparse(c.args[1])
                        nm = next((k for k in MEMBER_CLASSES if k in cls_txt), None)
                    elif isinstance(c, ast.Attribute) and isinstance(c.value, ast.Name) \
                            and c.value.id in targets:
                        nm = c.attr
                    # Member privates reached this way are R1 hits already;
                    # R4 counts the scan pattern for public / stream names.
                    if nm and (nm in STREAM_HEALTH_NAMES or nm in MEMBER_CLASSES
                               or (nm in h.member_unique and not nm.startswith("_"))):
                        add("R4", qual, nm, c)

        # ---------------- R5 class literal
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in ("house_census_view", "get_house_census", "view_for_class", "min_confidence"):
                cls_args = [k.value for k in node.keywords if k.arg == "cls"]
                if name in ("view_for_class", "min_confidence") and node.args:
                    cls_args.append(node.args[0])
                for a in ([] if _r5_owner_delegate(rel, qual) else cls_args):
                    s = _str_const(a)
                    if s is None or s not in h.consumer_classes:
                        add("R5", qual, f"{name}(cls)", node, "class_not_literal")
                view_pos = None
                if name == "house_census_view" and len(node.args) >= 2:
                    view_pos = node.args[1]
                elif name == "get_house_census" and node.args:
                    view_pos = node.args[0]
                if view_pos is not None and not _r5_owner_delegate(rel, qual):
                    s = _str_const(view_pos)
                    vkind = "literal_view" if s == "trust" else "view_not_trust"
                    add("R5", qual, f"{name}(view:{vkind})", node, vkind)
            if name == "partial" and node.args and isinstance(node.args[0], (ast.Name, ast.Attribute)) \
                    and _call_name(ast.Call(func=node.args[0], args=[], keywords=[])) in (
                        "house_census_view", "get_house_census", "view_for_class", "min_confidence"):
                add("R5", qual, "partial", node, "partial")

        # ---------------- R6 sends / R10 listeners
        if isinstance(node, ast.Call):
            name = _call_name(node)
            chan_arg = None
            is_send = is_listen = False
            if name in ("async_dispatcher_send", "dispatcher_send") and len(node.args) >= 2:
                chan_arg, is_send = node.args[1], True
            elif name in ("async_fire", "fire") and isinstance(node.func, ast.Attribute) \
                    and _receiver_text(node.func.value).endswith("bus") and node.args:
                chan_arg, is_send = node.args[0], True
            elif name in ("async_dispatcher_connect", "dispatcher_connect") and len(node.args) >= 2:
                chan_arg, is_listen = node.args[1], True
            elif name in ("async_listen", "async_listen_once") and isinstance(node.func, ast.Attribute) \
                    and _receiver_text(node.func.value).endswith("bus") and node.args:
                chan_arg, is_listen = node.args[0], True
            if chan_arg is not None:
                v = _resolve_value(chan_arg, local_consts, aliases, h)
                if v in owners:
                    if is_send and not _owner_ok(owners[v], rel, qual):
                        add("R6", qual, v, node)
                    if is_listen:
                        add("R10", qual, v, node)
            if name == "async_add_listener" and isinstance(node.func, ast.Attribute):
                k = binder.kind(node.func.value, func)
                if k in ("PC", "TD"):
                    add("R10", qual, f"async_add_listener[{k}]", node)
            if name == "getattr" and len(node.args) >= 2 and _str_const(node.args[1]) == "async_add_listener":
                k = binder.kind(node.args[0], func)
                if k in ("PC", "TD"):
                    add("R10", qual, f"async_add_listener[{k}]", node)

        # ---------------- R9 person listeners (every module but the one owner)
        if isinstance(node, ast.Call) and not _r9_owner(rel, qual):
            name = _call_name(node)
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id == "self" and node.func.attr in tracker_aliases:
                name = tracker_aliases[node.func.attr]
            elif isinstance(node.func, ast.Name) and node.func.id in tracker_aliases:
                name = tracker_aliases[node.func.id]
            if name in ("async_track_state_change_event", "async_track_state_change_filtered") \
                    and len(node.args) >= 2 and taint.expr(node.args[1], func):
                add("R9", qual, name, node)
            if name == "async_track_state_added_domain" and len(node.args) >= 2 \
                    and _str_const(node.args[1]) == "person":
                add("R9", qual, name, node)
            if name in ("async_listen",) and node.args and (
                    _str_const(node.args[0]) == "state_changed"
                    or (isinstance(node.args[0], ast.Name) and node.args[0].id == "EVENT_STATE_CHANGED")):
                cb = node.args[1] if len(node.args) > 1 else None
                cb_name = cb.attr if isinstance(cb, ast.Attribute) else getattr(cb, "id", None)
                for fn in ast.walk(tree):
                    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == cb_name:
                        if any(isinstance(c, ast.Call) and _call_name(c) == "startswith" and c.args
                               and _str_const(c.args[0]) in ("person.",) for c in ast.walk(fn)):
                            add("R9", qual, "state_changed_person", node)
        if not member and isinstance(node, ast.Assign) and id(func) in tainted_read_funcs:
            for t in node.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Attribute) \
                        and isinstance(t.value.value, ast.Name) and t.value.value.id == "self" \
                        and taint.expr(t.slice, func):
                    add("R9", qual, "polling_ledger", node)

        # ---------------- R11 latch key
        if isinstance(node, ast.Constant) and node.value == LATCH_KEY and id(node) not in docs \
                and rel != "domain_coordinators/signals.py":
            add("R11", qual, LATCH_KEY, node)

        # ---------------- R12 inline person id
        if rel != "person_ids.py":
            if isinstance(node, ast.JoinedStr) and node.values:
                first = _str_const(node.values[0])
                if first is not None and first.startswith("person.") and len(node.values) > 1:
                    add("R12", qual, "fstring", node)
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                s = _str_const(node.left)
                if s is not None and s.startswith("person."):
                    add("R12", qual, "concat", node)
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
                s = _str_const(node.left)
                if s is not None and s.startswith("person."):
                    add("R12", qual, "percent", node)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "format":
                    s = _str_const(node.func.value)
                    if s is not None and s.startswith("person."):
                        add("R12", qual, "format", node)
                elif node.func.attr == "join" and _str_const(node.func.value) == "." and node.args \
                        and isinstance(node.args[0], (ast.List, ast.Tuple)) and node.args[0].elts \
                        and _str_const(node.args[0].elts[0]) == "person":
                    add("R12", qual, "join", node)

        # ---------------- R13 ingest feeders (+ missing_source)
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in R13_CALLEES:
                add("R13", qual, name, node)
                if name == "dispatch_person_arriving" and len(node.args) >= 2:
                    p = node.args[1]
                    if isinstance(p, ast.Call) and _call_name(p) == "PersonArrivingPayload":
                        src = [k.value for k in p.keywords if k.arg == "source"]
                        if len(p.args) >= 2:
                            src.append(p.args[1])
                        if not src or _str_const(src[0]) in ("", None) and isinstance(src[0], ast.Constant):
                            add("R13", qual, "missing_source", node, "missing_source")

        # ---------------- R14 G1 callback budget
        if isinstance(node, ast.Call) and _call_name(node) == "subscribe_person_edges" and len(node.args) >= 2:
            cb = node.args[1]
            cb_name = cb.attr if isinstance(cb, ast.Attribute) else getattr(cb, "id", None)
            for fn in ast.walk(tree):
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == cb_name:
                    bad = isinstance(fn, ast.AsyncFunctionDef) or any(
                        isinstance(c, ast.Await) for c in ast.walk(fn))
                    for c in ast.walk(fn):
                        if isinstance(c, (ast.For, ast.AsyncFor)) and "states" in _receiver_text(c.iter):
                            bad = True
                        if isinstance(c, ast.Call) and R14_FORBIDDEN_CALL_RE.search(_receiver_text(c.func)):
                            bad = True
                    if bad:
                        add("R14", qual, f"slow_callback:{cb_name}", node)

    # ---------------- R8 confidence thresholds
    if rel == "const.py":
        for name, val, line in _module_num_consts(tree):
            if "CONFIDENCE" in name or name.endswith("_BOOST"):
                if any(abs(val - t) < 1e-9 for t in CLASS_THRESHOLDS):
                    hits.append(Hit("R8", rel, f"<module>:{name}", line, "class_threshold_const"))
    for node, qual, func in scoped:
        if isinstance(node, ast.Compare):
            sides = [node.left] + list(node.comparators)
            names_conf = [s for s in sides if "identity_confidence" in _receiver_text(s)]
            if not names_conf:
                continue
            others = [s for s in sides if s not in names_conf]
            ok = all("consumer_class_min_confidence" in _receiver_text(o)
                     or "min_confidence(" in _receiver_text(o)
                     or (isinstance(o, ast.Constant) and o.value is None) for o in others)
            if not ok:
                hits.append(Hit("R8", rel, f"{qual}:identity_confidence", node.lineno, "inline_threshold"))
    return hits


_COMP_PARENT: dict[int, ast.AST] = {}


def _index_comprehensions(tree: ast.AST) -> None:
    for n in ast.walk(tree):
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            for g in n.generators:
                _COMP_PARENT[id(g)] = n


def load_tree(root: Path = URA) -> dict[str, str]:
    return {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*.py"))}


_PARSE_CACHE: dict[tuple[str, int], ast.Module] = {}
_SCAN_CACHE: dict[tuple[str, int, int], list[Hit]] = {}
_HARVEST_CACHE: dict[tuple, tuple] = {}


def _harvest_fingerprint(h: Harvest) -> int:
    return hash((
        tuple(sorted((c, tuple(sorted(v))) for c, v in h.private_by_class.items())),
        tuple(sorted((k, tuple(sorted(v))) for k, v in h.public_by_kind.items())),
        tuple(sorted(h.nonmember_private)), tuple(sorted(h.member_unique)),
        tuple(sorted(h.consts.items())),
    ))


def scan_tree(sources: dict[str, str]) -> tuple[list[Hit], Harvest]:
    """Scan ``{rel: source}``. Parsed modules and per-module hits are cached by
    source text (and by the harvest they were scanned against), so a test that
    changes one file re-scans only what the change can affect."""
    trees: dict[str, ast.Module] = {}
    for rel, src in sources.items():
        key = (rel, hash(src))
        tree = _PARSE_CACHE.get(key)
        if tree is None:
            tree = ast.parse(src)
            _PARSE_CACHE[key] = tree
            _index_comprehensions(tree)
        trees[rel] = tree
    hkey = tuple(sorted((rel, hash(src)) for rel, src in sources.items()))
    cached = _HARVEST_CACHE.get(hkey)
    if cached is None:
        h = harvest(trees)
        cached = (h, _harvest_fingerprint(h))
        _HARVEST_CACHE[hkey] = cached
    h, fp = cached
    hits: list[Hit] = []
    for rel, tree in trees.items():
        skey = (rel, hash(sources[rel]), fp)
        mod_hits = _SCAN_CACHE.get(skey)
        if mod_hits is None:
            mod_hits = scan_module(rel, tree, h)
            _SCAN_CACHE[skey] = mod_hits
        hits.extend(mod_hits)
    return hits, h


def count_by_key(hits: Iterable[Hit]) -> dict[tuple[str, str, str], int]:
    out: dict[tuple[str, str, str], int] = {}
    for x in hits:
        out[x.key] = out.get(x.key, 0) + 1
    return out


def compare(hits: list[Hit], allowlist: dict, listed: dict, total: int | None) -> list[str]:
    """Violations: unlisted hit, count over max, stale non-reserved row,
    row-max sum != total, any missing_source hit (never allowlistable)."""
    problems: list[str] = []
    counts = count_by_key(hits)
    for key, n in sorted(counts.items()):
        if key in listed:
            if n > listed[key]:
                problems.append(f"over listed max {key}: {n} > {listed[key]}")
            continue
        row = allowlist.get(key)
        if row is None:
            problems.append(f"unlisted {key} x{n}")
        elif n > row["max"]:
            problems.append(f"over max {key}: {n} > {row['max']}")
    for key, row in allowlist.items():
        if not row.get("reserved") and counts.get(key, 0) == 0:
            problems.append(f"stale row {key}")
    for key in listed:
        if counts.get(key, 0) == 0:
            problems.append(f"stale listed listener {key}")
    for x in hits:
        if x.kind == "missing_source":
            problems.append(f"missing source {x.key} line {x.line}")
    if total is not None:
        s = sum(int(r["max"]) for r in allowlist.values())
        if s != total:
            problems.append(f"row-max sum {s} != LAYER_ALLOWLIST_TOTAL {total}")
    return problems
