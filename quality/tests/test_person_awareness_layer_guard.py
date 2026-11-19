"""Person-awareness layer leak guard, R1-R14 (ship 3a D7 SCAFFOLDING; plan
PLANNING_person_awareness_layer_ship3.md rev 3.2 §5 D7).

AST only: the engine (``_layer_guard_engine``) parses source text; nothing here
imports a production module. The real-tree test compares the scan with the
PROVISIONAL allowlist (``person_awareness_layer_allowlist_PROVISIONAL``): the
final allowlist and ``LAYER_ALLOWLIST_TOTAL`` wait for census-p2 on develop.

Extends ship 2's census guard (``test_person_awareness_read_api_ship2.py::
test_no_private_census_reads_outside_module``): its 41 rows are this guard's
group #7 (R1), checked exactly here as well.

Anti-hollow: every rule has positive and negative snippets scanned through the
same engine, a per-rule minimum of real-tree hits, an injected-leak control on
a copied clean module, a ratchet case, and one reverted-site case per ship 3a
fix (the 3a change undone in an in-memory copy of the real tree must make the
guard fail). Stated limits are pinned as tests too.
"""
from __future__ import annotations

import pytest

import _layer_guard_engine as E
import person_awareness_layer_allowlist_PROVISIONAL as A

_REAL: dict | None = None


def _real_tree() -> dict[str, str]:
    global _REAL
    if _REAL is None:
        _REAL = E.load_tree()
    return dict(_REAL)


def _scan(sources):
    hits, _h = E.scan_tree(sources)
    return hits


def _problems(sources):
    return E.compare(_scan(sources), A.ROWS, _listed(), A.LAYER_ALLOWLIST_TOTAL)


def _listed():
    return {k: v for k, v in A.LISTED.items() if k not in set(A.LISTED_RESERVED)}


# ------------------------------------------------------------------ real tree
def test_guard_matches_provisional_allowlist():
    """Every hit on the real tree is a listed listener or an allowlist row
    within its max; no non-reserved row is stale; the row-max sum equals the
    (provisional) total."""
    problems = _problems(_real_tree())
    assert problems == [], "\n".join(problems)


def test_allowlist_is_final_post_census_p2():
    """The final allowlist and LAYER_ALLOWLIST_TOTAL (plan §8, §17) come from
    the run on the post-census-p2 tree (develop bc4f462b merged)."""
    assert A.PROVISIONAL is False
    # 259/231 at ship 3a; -3 at the music-following repair merge (three #23
    # music_following.py person_coordinator.data reads moved to the public API).
    # +1 at crossing vision P3-D3 (the G3 feeder _amend_vision_direction, R13).
    # +2 at step 7 S1 (edge-anchor confidence const R8, trip-wire delegate R2).
    # -5 at LAYER-LEAK-CLEANUP-1 L4 (the five identity-veto person.<slug>
    # f-strings, #31, now resolve through person_ids.person_entity_for_slug).
    assert A.LAYER_ALLOWLIST_TOTAL == 254 and len(A.ROWS) == 226
    assert A.LAYER_ALLOWLIST_TOTAL == sum(r["max"] for r in A.ROWS.values())


def test_provisional_rows_all_explained():
    """Every row is ruled (plan rev 3.3 §17 + the coordinator's lifecycle ruling)."""
    unexplained = sorted(k for k, r in A.ROWS.items() if not r["explained"])
    assert unexplained == []


def test_residency_shim_removed_once_census_p2_lands():
    """Plan rev 3.3 §16: the residency channel value shim goes when census-p2
    puts SIGNAL_RESIDENCY_EVENT on the tree."""
    _hits, h = E.scan_tree(_real_tree())
    if "SIGNAL_RESIDENCY_EVENT" in h.consts:
        assert E.CHANNEL_FALLBACK_VALUES == {}, "remove the census-p2 residency shim"
    else:
        assert E.CHANNEL_FALLBACK_VALUES == {"SIGNAL_RESIDENCY_EVENT": "ura_residency_event"}


# ---------------------------------- rev 3.3 tightenings: negative + positive
_P = ("def f(manager):\n    presence = manager.coordinators['presence']\n")
_PRES_EXTRA = {"domain_coordinators/presence.py": (
    "class PresenceCoordinator:\n"
    "    def __init__(self):\n"
    "        self._census_count = 0\n"
    "        self._boot_settle_done = False\n"
    "    def tracker_for_room(self, r): return None\n"
    "    def get_ble_occupants(self, r): return []\n"
    "    def get_house_census(self, view='trust'):\n"
    "        return house_census_view(self.hass, view)\n")}

TIGHTEN = [
    # (name, negative snippet (no hit), positive snippet (same shape, person fact), rule)
    ("non_person_private",
     _P + "    return presence._boot_settle_done\n",
     _P + "    return presence._census_count\n", "R1"),
    ("non_person_public",
     _P + "    return presence.tracker_for_room('r')\n",
     _P + "    return presence.get_ble_occupants('r')\n", "R2"),
    ("non_member_receiver",
     "def f(hass):\n    cm = hass.data['d'].get('camera_manager')\n    return cm._census_count\n",
     "def f(hass):\n    cm = hass.data['d'].get('person_coordinator')\n    return cm._census_count\n", "R1"),
    ("r3_membership_only",
     "def f(hass, p):\n    known = {s.entity_id for s in hass.states.async_all('person')}\n"
     "    return p in known\n",
     "def f(hass, p):\n    known = [s for s in hass.states.async_all('person')]\n"
     "    return known[0].state\n", "R3"),
    ("r3_actor_identity",
     "def f(hass, uid):\n    for s in hass.states.async_all('person'):\n"
     "        if s.attributes.get('user_id') == uid:\n            return s.entity_id\n",
     "def f(hass, uid):\n    for s in hass.states.async_all('person'):\n"
     "        if s.attributes.get('source') == uid:\n            return s.entity_id\n", "R3"),
    ("fleet_health_listener",
     "def f(hass, cb):\n    async_track_state_change_event(hass, ['sensor.bermuda_global_total_device_count'], cb)\n",
     "def f(hass, cb):\n    async_track_state_change_event(hass, ['sensor.bermuda_oji_area'], cb)\n", "R9"),
    ("lifecycle_callee",
     "def async_setup_entry(hass):\n    pc = hass.data['d']['person_coordinator']\n    pc.async_setup()\n",
     "def async_setup_entry(hass):\n    pc = hass.data['d']['person_coordinator']\n"
     "    return pc.get_persons_in_room('k')\n", "R2"),
    ("named_lifecycle_callee",
     "async def async_setup_entry(hass):\n    pc = hass.data['d']['person_coordinator']\n"
     "    await pc.async_load_fleet_memory()\n",
     "async def async_setup_entry(hass):\n    pc = hass.data['d']['person_coordinator']\n"
     "    await pc.async_load_fleet_memory()\n    return pc.get_persons_in_room('k')\n", "R2"),
]


@pytest.mark.parametrize("name, neg, pos, rule", TIGHTEN, ids=[t[0] for t in TIGHTEN])
def test_tightening_negative_and_positive(name, neg, pos, rule):
    assert rule not in _rules(neg, extra=_PRES_EXTRA), (name, _snippet_hits(neg, extra=_PRES_EXTRA))
    assert rule in _rules(pos, extra=_PRES_EXTRA), (name, _snippet_hits(pos, extra=_PRES_EXTRA))


def test_r5_owner_delegate_exempt_but_other_presence_method_hits():
    rel = "domain_coordinators/presence.py"
    src = _PRES_EXTRA[rel]
    assert not [h for h in _snippet_hits(src, rel=rel) if h[0] == "R5"]
    bad = src + "    def other(self, view):\n        return house_census_view(self.hass, view)\n"
    assert ("R5", "PresenceCoordinator.other:house_census_view(view:view_not_trust)",
            "view_not_trust") in _snippet_hits(bad, rel=rel)


@pytest.mark.parametrize("rule, floor", [
    ("R1", 100), ("R2", 40), ("R3", 5), ("R4", 1), ("R5", 6), ("R8", 3),
    ("R9", 4), ("R10", 20), ("R12", 4), ("R13", 8),
])
def test_rule_real_tree_minimum(rule, floor):
    """Anti-vacuous: each rule still sees at least its first-run floor on the
    real tree (R6, R7, R11, R14 have no real hits after 3a; their snippets
    below prove detection)."""
    n = sum(1 for x in _scan(_real_tree()) if x.rule == rule)
    assert n >= floor, (rule, n)


@pytest.mark.parametrize("cls, floor", [
    ("PersonCensus", 100), ("PresenceCoordinator", 100), ("PersonTrackingCoordinator", 40),
    ("EgressDirectionTracker", 25), ("PersonSightingProducer", 25), ("ZonePresenceTracker", 15),
    ("TransitValidator", 5), ("ResidencyTracker", 0), ("CrossingVisionShadow", 20),
])
def test_harvest_floor_per_present_member_class(cls, floor):
    """The harvester found each present member class (absent classes, e.g.
    CrossingLedger before census-p2, are tolerated)."""
    _hits, h = E.scan_tree(_real_tree())
    assert cls in h.private_by_class
    assert len(h.private_by_class[cls]) >= floor


def test_census_display_rows_are_ship2s_41():
    """Ship 2's 41 census display reads are group #7 here, exactly."""
    rows = [k for k, r in A.ROWS.items() if r["group"] == "#7"]
    assert len(rows) == 41
    assert all(k[0] == "R1" and k[1] in ("sensor.py", "binary_sensor.py") for k in rows)


# ------------------------------------------------------------ snippet harness
_MEMBERS = {
    "person_coordinator.py": (
        "class PersonTrackingCoordinator:\n"
        "    def __init__(self):\n"
        "        self._pre_arrival_enabled = True\n"
        "        self._gps_home_overruled = frozenset()\n"
        "    def _is_room_occupied(self, room): return True\n"
        "    def get_person_location(self, name): return None\n"
        "    def get_persons_in_room(self, room): return []\n"
        "    def set_pre_arrival_enabled(self, v): self._pre_arrival_enabled = v\n"
        "    def async_add_listener(self, cb): return lambda: None\n"
        "    def async_setup(self): return None\n"
        "    def async_load_fleet_memory(self): return None\n"),
    "domain_coordinators/presence.py": (
        "class PresenceCoordinator:\n"
        "    def __init__(self):\n"
        "        self._census_count = 0\n"
        "    def get_house_census(self, view='trust'): return None\n"),
    "transitions.py": (
        "class TransitionDetector:\n"
        "    def async_add_listener(self, cb): return lambda: None\n"),
    "camera_census.py": (
        "class PersonCensus:\n"
        "    def __init__(self):\n"
        "        self._ble_legs_abstained_count = 0\n"
        "        self.last_result = None\n"),
    "domain_coordinators/signals.py": (
        "SIGNAL_PERSON_ARRIVING = 'ura_person_arriving'\n"
        "SIGNAL_EGRESS_RECORD_AMENDED = 'ura_egress_record_amended'\n"
        "SIGNAL_PERSON_SIGHTING = 'ura_person_sighting'\n"
        "SIGNAL_CENSUS_UPDATED = 'ura_census_updated'\n"
        "SIGNAL_RESIDENCY_EVENT = 'ura_residency_event'\n"),
    "const.py": (
        "CONSUMER_CLASS_DISPLAY = 'display'\n"
        "CONSUMER_CLASS_SECURITY = 'security'\n"
        "CONF_TRACKED_PERSONS = 'tracked_persons'\n"),
    "other.py": (
        "class Unrelated:\n"
        "    def __init__(self):\n"
        "        self._ready_event = None\n"),
}


def _snippet_hits(src: str, rel: str = "probe.py", extra: dict | None = None):
    sources = dict(_MEMBERS)
    sources.update(extra or {})
    sources[rel] = src
    return sorted((x.rule, x.symbol, x.kind) for x in _scan(sources) if x.file == rel)


def _rules(src, rel="probe.py", extra=None):
    return sorted({r for r, _s, _k in _snippet_hits(src, rel, extra)})


POSITIVE = [
    # R1 private member access (receiver-agnostic; getattr / setattr forms)
    ("helper_passed_object", "def f(pc):\n    return pc._is_room_occupied('x')\n", "R1"),
    ("getattr_private", "def f(x):\n    return getattr(x, '_census_count', 0)\n", "R1"),
    ("setattr_private", "def f(pc):\n    setattr(pc, '_pre_arrival_enabled', False)\n", "R1"),
    ("vars_member", "def f(hass):\n    pc = hass.data['d']['person_coordinator']\n"
                    "    return vars(pc)['_x']\n", "R1"),
    ("coordinator_manager_reach",
     "def f(manager):\n    p = manager.coordinators['presence']\n    return p._census_count\n", "R1"),
    ("p5_private_write", "def f(pc):\n    pc._pre_arrival_enabled = True\n", "R1"),
    # R2 store / member public method reads
    ("pc_data_read", "def f(hass):\n    pc = hass.data['d'].get('person_coordinator')\n"
                     "    return pc.data\n", "R2"),
    ("member_public_off_list", "def f(hass):\n    pc = hass.data['d']['person_coordinator']\n"
                               "    return pc.get_persons_in_room('k')\n", "R2"),
    ("census_last_result", "def f(census):\n    return census.last_result\n", "R2"),
    # R3 raw person reads (non-member module)
    ("template_read", "def f(hass):\n    return Template('{{ states.person.oji }}', hass)\n", "R3"),
    ("registry_resolved_plb_id",
     "def f(hass, reg, s):\n    eid = reg.async_get_entity_id('binary_sensor', 'd', "
     "f'd_person_{s}_phone_left_behind')\n    return hass.states.get(eid)\n", "R3"),
    ("person_domain_all", "def f(hass):\n    return hass.states.async_all('person')\n", "R3"),
    ("conf_person_list",
     "def f(hass, entry):\n    for p in entry.options.get(CONF_TRACKED_PERSONS):\n"
     "        hass.states.get(p)\n", "R3"),
    # R4 hass.data scans
    ("domain_data_scan",
     "def f():\n    for c in _domain_data().values():\n"
     "        if hasattr(c, 'camera_input_stream_dead'):\n            return c\n", "R4"),
    # R5 class literal
    ("name_view", "def f(hass, view):\n    return house_census_view(hass, view)\n", "R5"),
    ("partial_view", "import functools\nF = functools.partial(house_census_view, None)\n", "R5"),
    ("non_literal_class", "def f(p, c):\n    return p.min_confidence(c)\n", "R5"),
    # R6 sends outside the owner (aliased signal, module-local event, bus fire)
    ("aliased_signal",
     "from .domain_coordinators.signals import SIGNAL_PERSON_ARRIVING as S\n"
     "def f(hass):\n    async_dispatcher_send(hass, S, {})\n", "R6"),
    ("module_local_event",
     "EV = 'ura_person_egress_event'\ndef f(hass):\n    hass.bus.async_fire(EV, {})\n", "R6"),
    ("bus_async_fire_location",
     "def f(hass):\n    hass.bus.async_fire('ura_person_location_change', {})\n", "R6"),
    # R7 store writes
    ("setattr_store", "def f(census, r):\n    setattr(census, 'last_result', r)\n", "R7"),
    ("dataclasses_replace",
     "import dataclasses\nfrom .transit_validator import CrossingRecord\n"
     "def f(rec):\n    return dataclasses.replace(rec, person_id='x')\n", "R7"),
    ("record_constructor", "def f():\n    return CrossingRecord('c')\n", "R7"),
    ("pc_data_item_write", "def f(hass):\n    pc = hass.data['d']['person_coordinator']\n"
                           "    pc.data['oji']['location'] = 'x'\n", "R7"),
    # R8 confidence thresholds
    ("const_0750", "X_CONFIDENCE = 0.750\n", "R8"),
    ("inline_identity_threshold",
     "def f(e):\n    return e['identity_confidence'] >= 0.75\n", "R8"),
    # R9 person listeners
    ("polling_ledger",
     "class L:\n    def tick(self, hass):\n        for p in hass.states.async_all('person'):\n"
     "            st = hass.states.get(p.entity_id)\n"
     "            self._seen[p.entity_id] = st\n", "R9"),
    ("person_added_domain",
     "def f(hass, cb):\n    async_track_state_added_domain(hass, 'person', cb)\n", "R9"),
    ("tracked_id_listener",
     "def f(hass, cb, slug):\n    async_track_state_change_event(hass, [tracked_person_entity_id(slug)], cb)\n",
     "R9"),
    # R10 listeners (raw connect; async_add_listener by value, one hop)
    ("raw_residency_connect",
     "def f(hass, cb):\n    async_dispatcher_connect(hass, 'ura_residency_event', cb)\n", "R10"),
    ("add_listener_via_getattr",
     "def f(hass, cb):\n    getattr(hass.data['d']['person_coordinator'], 'async_add_listener')(cb)\n",
     "R10"),
    ("add_listener_via_get_alias",
     "def f(d, cb):\n    pc = d.get('person_coordinator')\n    x = pc\n    x.async_add_listener(cb)\n",
     "R10"),
    ("add_listener_via_self_td",
     "class M:\n    def s(self, cb):\n        self.transition_detector.async_add_listener(cb)\n", "R10"),
    # R11 latch key (and a module-level alias)
    ("latch_key_alias", "KEY = 'face_latch_callbacks'\n", "R11"),
    # R12 inline person id (+ / % / join / format)
    ("plus_person_id", "def f(s):\n    return 'person.' + s\n", "R12"),
    ("percent_person_id", "def f(s):\n    return 'person.%s' % s\n", "R12"),
    ("join_person_id", "def f(s):\n    return '.'.join(['person', s])\n", "R12"),
    ("format_person_id", "def f(s):\n    return 'person.{}'.format(s)\n", "R12"),
    # R13 feeders + missing source
    ("feeder_call", "def f(hass, p):\n    note_face('oji', None)\n", "R13"),
    # R14 slow G1 callback
    ("slow_g1_callback",
     "async def cb(rec):\n    await x()\n"
     "def setup(hass):\n    subscribe_person_edges(hass, cb)\n", "R14"),
]


@pytest.mark.parametrize("name, src, rule", POSITIVE, ids=[p[0] for p in POSITIVE])
def test_rule_flags_known_bad_shape(name, src, rule):
    if name.startswith("const_"):  # R8 constants are checked in const.py
        src, rel = _MEMBERS["const.py"] + src, "const.py"
        assert rule in _rules(src, rel=rel), (name, _snippet_hits(src, rel=rel))
        return
    assert rule in _rules(src), (name, _snippet_hits(src))


NEGATIVE = [
    ("own_private_on_self", "class Unrelated:\n    def f(self):\n        return self._ready_event\n"),
    ("read_list_method", "def f(hass):\n    pc = hass.data['d']['person_coordinator']\n"
                         "    return pc.get_person_location('oji')\n"),
    ("entry_data_not_a_store", "def f(entry, event, hass):\n    return entry.data, event.data, hass.data\n"),
    ("docstring_latch_key", "'''Mentions face_latch_callbacks in prose only.'''\n"),
    ("class_literal_view", "def f(p):\n    return p.min_confidence('display')\n"),
    ("own_signal_listener_constant_other",
     "def f(hass, cb):\n    async_dispatcher_connect(hass, 'ura_house_state_changed', cb)\n"),
    ("person_prefix_not_a_builder", "X = 'person.'\n"),
    ("table_threshold",
     "def f(e, T):\n    return e['identity_confidence'] >= CONSUMER_CLASS_MIN_CONFIDENCE['notification']\n"),
    ("sync_g1_callback",
     "def cb(rec):\n    hass_schedule(rec)\ndef setup(hass):\n    subscribe_person_edges(hass, cb)\n"),
    ("non_person_listener", "def f(hass, cb):\n    async_track_state_change_event(hass, ['light.x'], cb)\n"),
]


@pytest.mark.parametrize("name, src", NEGATIVE, ids=[n[0] for n in NEGATIVE])
def test_rule_ignores_good_shape(name, src):
    hits = _snippet_hits(src)
    assert hits == [], (name, hits)


def test_r6_send_at_owner_is_not_a_hit():
    sig = "domain_coordinators/signals.py"
    src = _MEMBERS[sig] + "def dispatch_person_arriving(hass, p):\n" \
                          "    async_dispatcher_send(hass, SIGNAL_PERSON_ARRIVING, p)\n"
    assert _snippet_hits(src, rel=sig) == []


def test_r11_key_allowed_only_in_signals():
    src = _MEMBERS["domain_coordinators/signals.py"] + "_K = 'face_latch_callbacks'\n"
    assert _snippet_hits(src, rel="domain_coordinators/signals.py") == []


def test_r13_missing_source_is_never_allowlistable():
    src = ("def f(hass, e):\n"
           "    dispatch_person_arriving(hass, PersonArrivingPayload(person_entity=e))\n")
    hits = _snippet_hits(src)
    assert ("R13", "f:missing_source", "missing_source") in hits
    probs = E.compare([h for h in _scan({**_MEMBERS, "probe.py": src}) if h.file == "probe.py"],
                      {("R13", "probe.py", "f:dispatch_person_arriving"): {"max": 1},
                       ("R13", "probe.py", "f:missing_source"): {"max": 1}}, {}, None)
    assert any(p.startswith("missing source") for p in probs)


def test_nested_function_symbol_is_full_qualname():
    src = ("class A:\n    def m(self, pc):\n        def _inner():\n"
           "            return pc._is_room_occupied('r')\n        return _inner\n")
    assert ("R1", "A.m._inner:_is_room_occupied", "leak") in _snippet_hits(src)


def test_lambda_attributed_to_enclosing_def():
    src = "def outer(pc):\n    return lambda: pc._is_room_occupied('r')\n"
    assert ("R1", "outer:_is_room_occupied", "leak") in _snippet_hits(src)


def test_name_collision_kind_split():
    """A private name also defined on a non-member class: a leak only when the
    receiver resolves to a member (by value)."""
    member = ("def f(manager):\n    p = manager.coordinators.get('presence')\n"
              "    return p._ready_event\n")
    other = "def f(x):\n    return x._ready_event\n"
    extra = {"domain_coordinators/presence.py": _MEMBERS["domain_coordinators/presence.py"]
             + "    def _x(self):\n        self._ready_event = None\n"}
    assert ("R1", "f:_ready_event", "leak") in _snippet_hits(member, extra=extra)
    assert ("R1", "f:_ready_event", "name_collision") in _snippet_hits(other, extra=extra)


# ---------------------------------------------------------------- limits
def test_stated_limit_dynamic_getattr_not_seen():
    """Stated limit (plan §5 D7): a dynamic attribute name is not resolved."""
    assert _snippet_hits("def f(pc, n):\n    return getattr(pc, n)\n") == []


def test_stated_limit_cross_module_dataflow():
    """Stated limit: a member object handed in from another module under a
    neutral name is not bound (one hop, one module)."""
    assert _snippet_hits("def f(obj):\n    return obj.get_persons_in_room('k')\n") == []


# ------------------------------------------------- ratchet + injected leak
def test_ratchet_removed_hit_without_lowering_total_is_red():
    """Closing a leak must lower the total in the same change: a row whose hit
    disappears is stale, and dropping the row without the total is a sum
    mismatch."""
    tree = _real_tree()
    rel = "person_sighting.py"
    src = tree[rel]
    needle = 'person_entity = f"person.{mapped}"'
    assert src.count(needle) == 1
    tree[rel] = src.replace(needle, "person_entity = tracked_person_entity_id(mapped)")
    probs = E.compare(_scan(tree), A.ROWS, _listed(), A.LAYER_ALLOWLIST_TOTAL)
    assert any(p.startswith("stale row ('R12', 'person_sighting.py'") for p in probs), probs
    rows = {k: v for k, v in A.ROWS.items()
            if k != ("R12", "person_sighting.py", "PersonSightingProducer._emit:fstring")}
    probs2 = E.compare(_scan(tree), rows, _listed(), A.LAYER_ALLOWLIST_TOTAL)
    assert any("!= LAYER_ALLOWLIST_TOTAL" in p for p in probs2), probs2
    probs3 = E.compare(_scan(tree), rows, _listed(), A.LAYER_ALLOWLIST_TOTAL - 1)
    assert probs3 == [], probs3


def test_injected_leak_on_copied_clean_module_is_red():
    tree = _real_tree()
    rel = "census_view.py"
    assert not [x for x in _scan(tree) if x.file == rel]  # clean module
    tree[rel] = tree[rel] + (
        "\n\ndef _leak(hass):\n"
        "    pc = hass.data['universal_room_automation']['person_coordinator']\n"
        "    return pc._is_room_occupied('x')\n")
    probs = E.compare(_scan(tree), A.ROWS, _listed(), A.LAYER_ALLOWLIST_TOTAL)
    assert any(p.startswith("unlisted ('R1', 'census_view.py', '_leak:_is_room_occupied')")
               for p in probs), probs



# Review C (ship 3a) guard caveat: census_view.py and arrival_edges.py were
# exempt from the member-only rules wholesale. They are now members for no
# rule (``E.MEMBER_MODULE_RULES``), so each leak below injected into either
# file is caught with its rule named.
_HELPER_LEAKS = {
    "R2": ("def _leak(hass):\n"
           "    pc = hass.data['universal_room_automation']['person_coordinator']\n"
           "    return pc.get_room_occupants('x')\n"),
    "R3": "def _leak(hass):\n    return hass.states.async_all('person')\n",
    "R4": ("def _leak(hass):\n"
           "    for c in hass.data['universal_room_automation'].values():\n"
           "        if hasattr(c, 'camera_input_stream_dead'):\n            return c\n"),
    "R7": ("def _leak(hass):\n"
           "    pc = hass.data['universal_room_automation']['person_coordinator']\n"
           "    pc.__dict__.update({})\n"),
}


@pytest.mark.parametrize("rule", sorted(_HELPER_LEAKS))
@pytest.mark.parametrize("rel", ["census_view.py", "arrival_edges.py"])
def test_helper_module_leak_is_caught(rel, rule):
    tree = _real_tree()
    assert not [x for x in _scan(tree) if x.file == rel]  # clean module
    tree[rel] = tree[rel] + "\n\n" + _HELPER_LEAKS[rule]
    got = {x.rule for x in _scan(tree) if x.file == rel}
    assert rule in got, (rel, rule, got)


# ------------------------------------------------ reverted 3a sites (red)
REVERTS = {
    "p1_geofence": ("domain_coordinators/presence.py",
                    "                _layer_signals.dispatch_person_arriving(\n"
                    "                    self.hass,\n"
                    "                    _layer_signals.PersonArrivingPayload(\n"
                    "                        person_entity=entity_id, source=\"geofence\",\n"
                    "                    ),\n"
                    "                )",
                    "                async_dispatcher_send(\n"
                    "                    self.hass,\n"
                    "                    SIGNAL_PERSON_ARRIVING,\n"
                    "                    {\"person_entity\": entity_id, \"source\": \"geofence\"},\n"
                    "                )"),
    "p1_camera": ("domain_coordinators/presence.py",
                  "        _layer_signals.dispatch_person_arriving(\n"
                  "            self.hass,\n"
                  "            _layer_signals.PersonArrivingPayload(\n"
                  "                person_entity=sighting.person_entity,",
                  "        async_dispatcher_send(self.hass, SIGNAL_PERSON_ARRIVING, {})\n"
                  "        (lambda **k: None)(\n"
                  "            hass=self.hass,\n"
                  "            payload=dict(\n"
                  "                person_entity=sighting.person_entity,"),
    "p1_ble": ("person_coordinator.py",
               "                                        _layer_signals.dispatch_person_arriving(",
               "                                        __import__('homeassistant.helpers.dispatcher')"
               ".helpers.dispatcher.async_dispatcher_send(self.hass, "
               "SIGNAL_PERSON_ARRIVING, {}) or (lambda *a: None)("),
    "p5": ("domain_coordinators/hvac.py",
           "            pc.set_pre_arrival_enabled(value)",
           "            pc._pre_arrival_enabled = value"),
    "s4": ("arrival_edges.py",
           "    reader = getattr(egress_tracker, \"door_entry_entities\", None)\n"
           "    ents = list(reader() or ()) if callable(reader) else []",
           "    ents = list(getattr(egress_tracker, \"_egress_entities\", None) or [])\n"
           "    nb = getattr(egress_tracker, \"_interior_neighbours_by_group\", None) or {}\n"
           "    for cams in nb.values():\n"
           "        ents.extend(cams or [])"),
    "s8": ("perimeter_alert.py",
           "                for n in tracker.door_neighbours_for_stem(cam_key):",
           "                group = tracker._door_group_for_stem(cam_key)\n"
           "                for n in (getattr(tracker, \"_interior_neighbours_by_group\", {}) or {}).get(group, []):"),
    "exit_backfill": ("camera_census.py",
                      "                        amend_crossing(\n"
                      "                            self.hass, None, {}, provenance=None,",
                      "                        __import__('x').async_dispatcher_send(\n"
                      "                            self.hass, SIGNAL_EGRESS_RECORD_AMENDED, None, provenance=None,"),
    "raw_residency_connect": ("crossing_vision.py",
                              "class CrossingVisionShadow",
                              "def _raw(hass, cb):\n"
                              "    async_dispatcher_connect(hass, \"ura_residency_event\", cb)\n\n\n"
                              "class CrossingVisionShadow"),
    "latch_key": ("person_sighting.py",
                  "        self._bridge_unsub = register_face_latch_callback(self.hass, self._bridge_cb)",
                  "        self.hass.data.setdefault(_c.DOMAIN, {}).setdefault(\"face_latch_callbacks\", [])"
                  ".append(self._bridge_cb)"),
    "sighting_private_write": ("person_sighting.py",
                               "            tracker.note_face(sighting.slug, when)  # ship 3a D4",
                               "            tracker._last_face_recognized = sighting.slug\n"
                               "            tracker._last_face_time = when"),
    "census_view_kwonly": ("sensor.py",
                           "house_census_view(self.hass, \"trust\")",
                           "house_census_view(self.hass, view)"),
    "d2_crossing_vision_raw_connect": ("crossing_vision.py",
                                       "            subscribe_person_edges(self.hass, self._on_residency_event, kinds=EDGE_KINDS)",
                                       "            async_dispatcher_connect(self.hass, \"ura_residency_event\", self._on_residency_event)"),
    "d4_plb_cls": ("binary_sensor.py",
                   "house_census_view(self.hass, cls=\"house_state\")",
                   "house_census_view(self.hass, \"trust\")"),
    "missing_source": ("domain_coordinators/presence.py",
                       "                        person_entity=entity_id, source=\"geofence\",",
                       "                        person_entity=entity_id,"),
    # VISION-INTERIOR-SIGHTINGS-1 §6.3 drills (injected leaks; IV_RULES pins
    # the rule each must trip).
    "iv_trust_reader": ("domain_coordinators/security.py",
                        "        \"\"\"Evaluate an entry event against census data.\"\"\"\n",
                        "        \"\"\"Evaluate an entry event against census data.\"\"\"\n"
                        "        _p = self.hass.data['d']['coordinator_manager'].coordinators['presence']\n"
                        "        _leak = _p.get_room_sightings()\n"),
    "iv_census_feed": ("domain_coordinators/presence.py",
                       "        v3.6.0.11: Schedules deferred retry when hysteresis blocks.\n"
                       "        \"\"\"\n",
                       "        v3.6.0.11: Schedules deferred retry when hysteresis blocks.\n"
                       "        \"\"\"\n"
                       "        _term = self._person_sightings.interior_census_tick()\n"),
    "iv_direct_store_write": ("interior_vision.py",
                              "class OnEdgeRing:",
                              "def _leak(producer, recs):\n"
                              "    producer._room_sightings[0] = recs\n\n\n"
                              "class OnEdgeRing:"),
    "iv_unnamed_on_sighting_signal": ("person_sighting.py",
                                      "        raise ValueError(f\"unknown unnamed kind {kind!r}\")",
                                      "        async_dispatcher_send(self.hass, SIGNAL_PERSON_SIGHTING, None)\n"
                                      "        raise ValueError(f\"unknown unnamed kind {kind!r}\")"),
    "iv_record_built_outside_owner": ("interior_vision.py",
                                      "class OnEdgeRing:",
                                      "def _leak(**f):\n    return RoomSighting(**f)\n\n\n"
                                      "class OnEdgeRing:"),
    # Ship 2 (§6.3, closure N7): an affect read injected into a copied NM
    # function (R16), and a describe request from a trust module (R15).
    "iv_affect_reader": ("domain_coordinators/notification_manager.py",
                         "        \"\"\"Send a text response back via the originating channel.\"\"\"\n",
                         "        \"\"\"Send a text response back via the originating channel.\"\"\"\n"
                         "        _leak = message.affect\n"),
    "iv_describe_from_trust_module": ("domain_coordinators/security.py",
                                      "        \"\"\"Evaluate an entry event against census data.\"\"\"\n",
                                      "        \"\"\"Evaluate an entry event against census data.\"\"\"\n"
                                      "        _p = self.hass.data['d']['coordinator_manager'].coordinators['presence']\n"
                                      "        _leak = _p.request_room_description('foyer', requester=None, reason='x')\n"),
    "iv_description_built_outside_owner": ("interior_vision.py",
                                           "class OnEdgeRing:",
                                           "def _leak(**f):\n    return RoomDescription(**f)\n\n\n"
                                           "class OnEdgeRing:"),
}

# The rule each interior-vision drill must trip (not only "some problem").
IV_RULES = {
    "iv_trust_reader": ("R15", "domain_coordinators/security.py",
                        "SanctionChecker.check_entry:get_room_sightings"),
    "iv_census_feed": ("R15", "domain_coordinators/presence.py",
                       "PresenceCoordinator._run_inference:interior_census_tick"),
    "iv_direct_store_write": ("R7", "interior_vision.py", "_leak:_room_sightings"),
    "iv_unnamed_on_sighting_signal": ("R6", "person_sighting.py",
                                      "PersonSightingProducer._emit_unnamed:ura_person_sighting"),
    "iv_record_built_outside_owner": ("R7", "interior_vision.py", "_leak:RoomSighting"),
    "iv_affect_reader": ("R16", "domain_coordinators/notification_manager.py",
                         "NotificationManager._send_reply:affect"),
    "iv_describe_from_trust_module": ("R15", "domain_coordinators/security.py",
                                      "SanctionChecker.check_entry:request_room_description"),
    "iv_description_built_outside_owner": ("R7", "interior_vision.py",
                                           "_leak:RoomDescription"),
}


@pytest.mark.parametrize("case", sorted(IV_RULES))
def test_iv_drill_trips_its_rule(case):
    """Each §6.3 interior drill is caught by the rule that owns it."""
    rel, new, old = REVERTS[case]
    tree = _real_tree()
    assert tree[rel].count(new) == 1, case
    tree[rel] = tree[rel].replace(new, old, 1)
    keys = {x.key for x in _scan(tree)}
    assert IV_RULES[case] in keys, (case, sorted(k for k in keys if k[1] == rel))


def test_iv_pinned_readers_clean_on_real_tree_and_pins_are_real():
    """No R15 hit on the real tree, and every non-reserved ship-1 pin names a
    real (module, qualname) that calls the pinned method (no dead pin)."""
    hits = _scan(_real_tree())
    assert [h for h in hits if h.rule == "R15"] == []
    import ast
    tree = _real_tree()
    for name in ("get_room_sightings", "get_last_path_records", "request_room_description"):
        for mod, q in E.PINNED_READERS[name]:
            if mod.startswith("<reserved"):
                continue
            calls = [
                qual for node, qual, _f in E.iter_scoped(ast.parse(tree[mod]))
                if isinstance(node, ast.Call) and E._call_name(node) == name
            ]
            assert any(E.pinned_ok(name, mod, c) for c in calls), (name, mod, q, calls)


@pytest.mark.parametrize("snippet, rule", [
    ("def f(p):\n    return getattr(p, 'get_room_sightings')()\n", "R15"),
    ("def f(p):\n    return p.get_last_path_records()\n", "R15"),
    ("def f(x):\n    return PathRecord('a', 'd', 0.0, None, None, ())\n", "R7"),
    ("def f(prod):\n    prod._path_records.append(1)\n    return prod._vision_counts\n", "R2"),
    # Ship 2 R16 (FORBIDDEN_ATTR_READS) forms and the new store.
    ("def f(d):\n    return d.affect\n", "R16"),
    ("def f(d):\n    return d['affect']\n", "R16"),
    ("def f(d):\n    return d.get('affect')\n", "R16"),
    ("def f(d):\n    return getattr(d, 'affect', None)\n", "R16"),
    ("from dataclasses import asdict\ndef f(desc):\n    return asdict(desc)\n", "R16"),
    ("def f(p):\n    return vars(p.get_room_description('x'))\n", "R16"),
    ("def f(prod):\n    return prod._room_descriptions\n", "R2"),
])
def test_iv_engine_shapes(snippet, rule):
    assert rule in _rules(snippet), _snippet_hits(snippet)


@pytest.mark.parametrize("snippet", [
    "def f(d):\n    return d['affects']\n",
    "def f(d):\n    d.affect = 1\n",
    "from dataclasses import asdict\ndef f(row):\n    return asdict(row)\n",
])
def test_r16_ignores_non_reads(snippet):
    assert "R16" not in _rules(snippet), _snippet_hits(snippet)


def test_r16_owner_modules_may_read_affect():
    """The owner and the reply formatter are the only readers (closure N7)."""
    src = "def f(d):\n    return d.affect\n"
    for rel in ("person_sighting.py", "interior_vision.py"):
        assert "R16" not in _rules(src, rel=rel), rel


@pytest.mark.parametrize("case", sorted(REVERTS))
def test_guard_red_on_reverted_site(case):
    """Undo one ship 3a fix in an in-memory copy of the real tree: the guard
    must report it (an unlisted hit, a stale pinned feeder, or a missing
    source)."""
    rel, new, old = REVERTS[case]
    tree = _real_tree()
    src = tree[rel]
    count = src.count(new)
    assert count >= 1, (case, "anchor not found")
    tree[rel] = src.replace(new, old, 1)
    probs = E.compare(_scan(tree), A.ROWS, _listed(), A.LAYER_ALLOWLIST_TOTAL)
    assert probs, case


# ------------------------------------------------ ship 3b evidence reads (§4.1)
@pytest.mark.parametrize("snippet, listed", [
    ("def f(hass):\n    c = hass.data['d']['census']\n    return c.interior_camera_entities()\n", True),
    ("def f(manager):\n    p = manager.coordinators['presence']\n    return p.zone_camera_entities()\n", True),
    ("def f(hass):\n    c = hass.data['d']['census']\n    return c.egress_identity_outcomes()\n", False),
])
def test_ship3b_evidence_reads_on_read_list(snippet, listed):
    """Contract §4.1 evidence row: a non-member may call
    ``PersonCensus.interior_camera_entities`` and
    ``PresenceCoordinator.zone_camera_entities`` (no R2 against the REAL
    tree's public methods); an unlisted public read on the same receiver is
    still R2 (control)."""
    sources = _real_tree()
    sources["probe.py"] = snippet
    rules = {x.rule for x in _scan(sources) if x.file == "probe.py"}
    assert ("R2" in rules) is (not listed), rules
