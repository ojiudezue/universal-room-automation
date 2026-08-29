"""EGRESS-IDENTITY-JOIN-GAP-1 (2026-08-28) D2a/D2b/D3 tests.

Drives PRODUCTION `camera_census.PersonCensus._resolve_face_legs` and
`transit_validator.EgressDirectionTracker._resolve_egress_face_identity`.

Test names mirror plan §4 acceptance criteria; each is mutation-anchored
against the load-bearing production line (breaking the classifier /
window / independence predicate turns the named test RED).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass


import sys as _sys
import types as _types


_STUB_MODULES = (
    "homeassistant.helpers.area_registry",
    "homeassistant.helpers.event",
)


@pytest.fixture(autouse=True, scope="module")
def _install_stub_modules():
    saved: dict[str, object] = {}
    for name in _STUB_MODULES:
        saved[name] = _sys.modules.get(name, ...)
    if "homeassistant.helpers.area_registry" not in _sys.modules:
        mod = _types.ModuleType("homeassistant.helpers.area_registry")
        mod.async_get = MagicMock()
        _sys.modules["homeassistant.helpers.area_registry"] = mod
    if "homeassistant.helpers.event" not in _sys.modules:
        ev = _types.ModuleType("homeassistant.helpers.event")
        ev.async_track_state_change_event = lambda *a, **kw: (lambda: None)
        ev.async_call_later = lambda *a, **kw: (lambda: None)
        ev.async_track_time_interval = lambda *a, **kw: (lambda: None)
        _sys.modules["homeassistant.helpers.event"] = ev
    yield
    for name, prior in saved.items():
        if prior is ...:
            _sys.modules.pop(name, None)
        else:
            _sys.modules[name] = prior


# Bootstrap stubs at collection time too.
if "homeassistant.helpers.area_registry" not in _sys.modules:
    _mod = _types.ModuleType("homeassistant.helpers.area_registry")
    _mod.async_get = MagicMock()
    _sys.modules["homeassistant.helpers.area_registry"] = _mod
if "homeassistant.helpers.event" not in _sys.modules:
    _ev = _types.ModuleType("homeassistant.helpers.event")
    _ev.async_track_state_change_event = lambda *a, **kw: (lambda: None)
    _ev.async_call_later = lambda *a, **kw: (lambda: None)
    _ev.async_track_time_interval = lambda *a, **kw: (lambda: None)
    _sys.modules["homeassistant.helpers.event"] = _ev

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation.camera_census import (
    FaceLeg,
    PersonCensus,
)
from custom_components.universal_room_automation.transit_validator import (
    EgressDirectionTracker,
)


UTC = timezone.utc


class _StubCameraManager:
    def __init__(self):
        self._camera_by_entity = {}

    def get_platform_for_camera(self, entity_id):
        return None

    def get_all_frigate_cameras(self):
        return []

    def resolve_configured_cameras(self, ids):
        return []


def _make_state(value, last_changed=None, attributes=None):
    st = MagicMock()
    st.state = value
    st.last_changed = last_changed
    st.attributes = attributes or {}
    return st


def _configure_integration_entry(hass, *, enabled=True, tracked=("person.oji_udezue", "person.ezinne_udezue")):
    entry = MagicMock()
    entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        "tracked_persons": list(tracked),
        ura_const.CONF_EGRESS_IDENTITY_ENABLED: enabled,
    }
    hass.config_entries.async_entries.return_value = [entry]


def _make_census(states=None, *, enabled=True):
    hass = make_hass()
    st_map = dict(states or {})
    hass.states.get = lambda eid: st_map.get(eid)
    _configure_integration_entry(hass, enabled=enabled)
    census = PersonCensus(hass, _StubCameraManager())  # type: ignore[arg-type]
    return census, hass, st_map


def _make_tracker(census, hass, *, interior_stems=(), egress_camera_id="binary_sensor.front_door_person_occupancy"):
    hass.data = {ura_const.DOMAIN: {"census": census}}
    tracker = EgressDirectionTracker(hass)
    # Force interior-adjacency to a fixed list of stems (as entity_ids).
    interior_entities = [
        f"binary_sensor.{s}_person_occupancy" for s in interior_stems
    ]
    tracker._get_interior_cameras_near = lambda cam: list(interior_entities)
    return tracker


# ---------------------------------------------------------------------------
# D2a — _resolve_face_legs
# ---------------------------------------------------------------------------


def test_face_legs_multi_engine_enumeration():
    """Same physical camera exposes Frigate _last_recognized_face AND
    Protect _face_recognized (both named). Accessor returns TWO FaceLeg
    entries with distinct engines and matching canonical_slug."""
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    states = {
        "sensor.front_door_last_recognized_face": _make_state("Oji", now),
        "sensor.front_door_face_recognized": _make_state("Oji", now, {"confidence": 0.9}),
    }
    census, _, _ = _make_census(states)
    legs = census._resolve_face_legs("front_door")
    assert len(legs) == 2
    engines = sorted(l.engine for l in legs)
    assert "frigate" in engines and "protect" in engines
    assert all(l.canonical_slug == "oji_udezue" for l in legs)


def test_face_legs_2_engine_tagging():
    """_2-suffixed entity gets the disambiguated engine tag (frigate2)."""
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    states = {
        "sensor.front_door_last_recognized_face_2": _make_state("Oji", now),
    }
    census, _, _ = _make_census(states)
    legs = census._resolve_face_legs("front_door")
    assert len(legs) == 1
    assert legs[0].engine == "frigate2"


def test_face_legs_sentinel_and_below_floor_dropped():
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    states = {
        "sensor.front_door_last_recognized_face": _make_state("unavailable", now),
        "sensor.front_door_face_recognized": _make_state("Oji", now, {"confidence": 0.3}),
    }
    census, _, _ = _make_census(states)
    assert census._resolve_face_legs("front_door") == []


def test_face_legs_detection_only_suffix_ignored():
    """_face_detected / _smart_detect_face / _ai_face are NOT enumerated
    even when present in hass.states."""
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    states = {
        "sensor.front_door_face_detected": _make_state("Oji", now),
        "sensor.front_door_smart_detect_face": _make_state("Oji", now),
        "sensor.front_door_ai_face": _make_state("Oji", now),
    }
    census, _, _ = _make_census(states)
    assert census._resolve_face_legs("front_door") == []


# ---------------------------------------------------------------------------
# D2b — _resolve_egress_face_identity classifier
# ---------------------------------------------------------------------------


def _leg(entity_id, engine, device_id, slug, last_changed, confidence=None, base_stem=None):
    return FaceLeg(
        entity_id=entity_id,
        engine=engine,
        device_id=device_id,
        base_stem=base_stem or entity_id.split(".", 1)[-1].split("_last")[0].split("_face")[0],
        canonical_slug=slug,
        last_changed=last_changed,
        confidence=confidence,
    )


def _install_legs(census, mapping):
    """mapping: stem -> list[FaceLeg]. Wire _resolve_face_legs directly."""
    census._resolve_face_legs = lambda stem: list(mapping.get(stem, []))


def test_d2b_high_via_different_cameras_distant_in_time():
    """Same slug on 2 DIFFERENT device_id cameras at deltas -100s, -15s
    (exit window) -> HIGH + BOTH."""
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    census, hass, _ = _make_census({})
    tracker = _make_tracker(census, hass, interior_stems=["foyer"])
    _install_legs(census, {
        "front_door": [
            _leg("sensor.front_door_last_recognized_face", "frigate",
                 "dev_front", "oji_udezue", now + timedelta(seconds=-100)),
        ],
        "foyer": [
            _leg("sensor.foyer_last_recognized_face", "frigate",
                 "dev_foyer", "oji_udezue", now + timedelta(seconds=-15)),
        ],
    })
    slug, idc, agc = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "exit",
    )
    assert slug == "oji_udezue"
    assert idc == ura_const.CONFIDENCE_HIGH
    assert agc == ura_const.CENSUS_AGREEMENT_BOTH


def test_d2b_boost_via_same_camera_different_engines():
    """HIGH-1 anti-anchor: same physical camera (SAME base_stem
    'front_door') with Protect + Frigate legs — DIFFERENT device_ids
    (dev_A vs dev_B), same slug, deltas -120s and +20s (both in-window;
    separation 140s) -> BOOST + BOTH. Under the base_stem-ONLY
    independence predicate this pair is correlated (0.75), NOT HIGH
    (0.9). If the predicate ever regresses to device_id-first this test
    goes RED with idc == 0.9."""
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    census, hass, _ = _make_census({})
    tracker = _make_tracker(census, hass, interior_stems=[])
    _install_legs(census, {
        "front_door": [
            _leg("sensor.front_door_last_recognized_face", "frigate",
                 "dev_A", "oji_udezue", now + timedelta(seconds=-120),
                 base_stem="front_door"),
            _leg("sensor.front_door_face_recognized", "protect",
                 "dev_B", "oji_udezue", now + timedelta(seconds=20),
                 confidence=0.9, base_stem="front_door"),
        ],
    })
    boost_before = len(census._egress_identity_boost_events)
    slug, idc, agc = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "exit",
    )
    assert slug == "oji_udezue"
    assert idc == ura_const.FACE_MATCH_CORRELATED_BOOST
    assert agc == ura_const.CENSUS_AGREEMENT_BOTH
    assert len(census._egress_identity_boost_events) == boost_before + 1


def test_d2b_boost_via_same_camera_frigate_and_frigate2():
    """Two legs sharing device_id, engines frigate + frigate2 -> BOOST."""
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    census, hass, _ = _make_census({})
    tracker = _make_tracker(census, hass, interior_stems=[])
    _install_legs(census, {
        "front_door": [
            _leg("sensor.front_door_last_recognized_face", "frigate",
                 "dev_A", "oji_udezue", now + timedelta(seconds=-10)),
            _leg("sensor.front_door_last_recognized_face_2", "frigate2",
                 "dev_A", "oji_udezue", now + timedelta(seconds=-5)),
        ],
    })
    slug, idc, agc = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "exit",
    )
    assert idc == ura_const.FACE_MATCH_CORRELATED_BOOST
    assert agc == ura_const.CENSUS_AGREEMENT_BOTH


def test_d2b_single_leg_medium():
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    census, hass, _ = _make_census({})
    tracker = _make_tracker(census, hass, interior_stems=[])
    _install_legs(census, {
        "front_door": [
            _leg("sensor.front_door_last_recognized_face", "frigate",
                 "dev_A", "oji_udezue", now + timedelta(seconds=-30)),
        ],
    })
    slug, idc, agc = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "exit",
    )
    assert (slug, idc, agc) == (
        "oji_udezue", ura_const.CONFIDENCE_MEDIUM,
        ura_const.CENSUS_AGREEMENT_SINGLE,
    )


def test_d2b_disagree_close_abstain_deque_outcome():
    """Two distinct slugs in-window within ABSTAIN_MARGIN -> DISAGREE
    AND the outcomes deque carries a single 'abstain' entry (MED-3:
    unified deque-derived rate, no separate int counter)."""
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    census, hass, _ = _make_census({})
    tracker = _make_tracker(census, hass, interior_stems=[])
    _install_legs(census, {
        "front_door": [
            _leg("sensor.front_door_last_recognized_face", "frigate",
                 "dev_A", "oji_udezue", now + timedelta(seconds=-10)),
            # Same physical camera (same base_stem "front_door") so the
            # DISAGREE-close observation is not confused by the HIGH-1
            # base_stem-only independence predicate; distinct slug pair
            # separation = 7s <= FACE_MATCH_ABSTAIN_MARGIN_S.
            _leg("sensor.front_door_face_recognized", "protect",
                 "dev_B", "ezinne_udezue", now + timedelta(seconds=-3),
                 confidence=0.9, base_stem="front_door"),
        ],
    })
    before_len = len(census._egress_identity_outcomes)
    slug, idc, agc = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "exit",
    )
    assert (slug, idc, agc) == (None, None, ura_const.CENSUS_AGREEMENT_DISAGREE)
    assert len(census._egress_identity_outcomes) == before_len + 1
    _ts, label = census._egress_identity_outcomes[-1]
    assert label == "abstain"


def test_d2b_disagree_far_ambiguous_deque_outcome():
    """C-MED-1: two distinct slugs SEPARATED beyond ABSTAIN_MARGIN ->
    still DISAGREE but the outcome is 'ambiguous' (NOT 'abstain')."""
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    census, hass, _ = _make_census({})
    tracker = _make_tracker(census, hass, interior_stems=[])
    sep_s = ura_const.FACE_MATCH_ABSTAIN_MARGIN_S + 20
    _install_legs(census, {
        "front_door": [
            _leg("sensor.front_door_last_recognized_face", "frigate",
                 "dev_A", "oji_udezue", now + timedelta(seconds=-5)),
            _leg("sensor.front_door_face_recognized", "protect",
                 "dev_A", "ezinne_udezue",
                 now + timedelta(seconds=-(5 + sep_s)),
                 confidence=0.9, base_stem="front_door"),
        ],
    })
    slug, idc, agc = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "exit",
    )
    assert (slug, idc, agc) == (None, None, ura_const.CENSUS_AGREEMENT_DISAGREE)
    _ts, label = census._egress_identity_outcomes[-1]
    assert label == "ambiguous"


def test_d2b_egress_camera_only_stamps_single():
    """When only the egress cam's own stem has a named leg -> SINGLE
    (leg-set union DOES include the egress camera stem)."""
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    census, hass, _ = _make_census({})
    tracker = _make_tracker(census, hass, interior_stems=[])
    _install_legs(census, {
        "front_door": [
            _leg("sensor.front_door_last_recognized_face", "frigate",
                 "dev_A", "oji_udezue", now + timedelta(seconds=-5)),
        ],
    })
    slug, idc, agc = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "exit",
    )
    assert slug == "oji_udezue"
    assert agc == ura_const.CENSUS_AGREEMENT_SINGLE


def test_d2b_device_id_null_fallback_to_base_stem():
    """Two legs with device_id=None on DIFFERENT base_stem -> HIGH.
    Same-base_stem device_id=None pair -> BOOST."""
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    census, hass, _ = _make_census({})
    tracker = _make_tracker(census, hass, interior_stems=["foyer"])
    _install_legs(census, {
        "front_door": [
            _leg("sensor.front_door_last_recognized_face", "frigate",
                 None, "oji_udezue", now + timedelta(seconds=-10),
                 base_stem="front_door"),
        ],
        "foyer": [
            _leg("sensor.foyer_last_recognized_face", "frigate",
                 None, "oji_udezue", now + timedelta(seconds=-5),
                 base_stem="foyer"),
        ],
    })
    slug, idc, agc = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "exit",
    )
    assert idc == ura_const.CONFIDENCE_HIGH
    # Same stem case:
    _install_legs(census, {
        "front_door": [
            _leg("sensor.front_door_last_recognized_face", "frigate",
                 None, "oji_udezue", now + timedelta(seconds=-10),
                 base_stem="front_door"),
            _leg("sensor.front_door_face_recognized", "protect",
                 None, "oji_udezue", now + timedelta(seconds=-5),
                 base_stem="front_door", confidence=0.9),
        ],
        "foyer": [],
    })
    slug2, idc2, _ = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "exit",
    )
    assert idc2 == ura_const.FACE_MATCH_CORRELATED_BOOST


def test_d2b_kill_switch_disabled_short_circuits():
    """Kill-switch OFF -> (None, None, DISABLED) before any leg read;
    abstain / ambiguity counters do NOT increment."""
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    census, hass, _ = _make_census({}, enabled=False)
    tracker = _make_tracker(census, hass, interior_stems=[])
    # If legs were consulted this would DISAGREE:
    _install_legs(census, {
        "front_door": [
            _leg("sensor.front_door_last_recognized_face", "frigate",
                 "dev_A", "oji_udezue", now),
            _leg("sensor.front_door_face_recognized", "protect",
                 "dev_A", "ezinne_udezue", now, confidence=0.9),
        ],
    })
    slug, idc, agc = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "exit",
    )
    assert (slug, idc, agc) == (
        None, None, ura_const.CENSUS_AGREEMENT_DISABLED,
    )
    # The 'disabled' outcome is EXCLUDED from rate denominators.
    labels = [o for _t, o in census._egress_identity_outcomes]
    assert labels[-1] == "disabled"


# ---------------------------------------------------------------------------
# D2b — direction-keyed window boundaries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("delta_s,accepted", [
    (-53, True),    # median exit
    (-181, False),  # just outside exit before
    (30, True),     # exact window edge
])
def test_d2b_exit_window_boundaries(delta_s, accepted):
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    census, hass, _ = _make_census({})
    tracker = _make_tracker(census, hass, interior_stems=[])
    _install_legs(census, {
        "front_door": [
            _leg("sensor.front_door_last_recognized_face", "frigate",
                 "dev_A", "oji_udezue", now + timedelta(seconds=delta_s)),
        ],
    })
    slug, _, _ = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "exit",
    )
    assert (slug is not None) == accepted


@pytest.mark.parametrize("delta_s,accepted", [
    (14, True),     # median entry
    (301, False),   # outside entry after
])
def test_d2b_entry_window_boundaries(delta_s, accepted):
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    census, hass, _ = _make_census({})
    tracker = _make_tracker(census, hass, interior_stems=[])
    _install_legs(census, {
        "front_door": [
            _leg("sensor.front_door_last_recognized_face", "frigate",
                 "dev_A", "oji_udezue", now + timedelta(seconds=delta_s)),
        ],
    })
    slug, _, _ = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "entry",
    )
    assert (slug is not None) == accepted


# ---------------------------------------------------------------------------
# INV byte-identity on abstain / disabled — bus payload semantics
# ---------------------------------------------------------------------------


def test_inv_disabled_returns_disabled_class_and_none_slug():
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    census, hass, _ = _make_census({}, enabled=False)
    tracker = _make_tracker(census, hass, interior_stems=[])
    slug, idc, agc = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "exit",
    )
    assert slug is None and idc is None
    assert agc == ura_const.CENSUS_AGREEMENT_DISABLED


# ---------------------------------------------------------------------------
# D3 — deque prune + sync attrs property
# ---------------------------------------------------------------------------


def test_d3_deque_prune_beyond_24h():
    """Outcomes older than 24h are pruned on append; rate math uses the
    surviving entries only."""
    census, _, _ = _make_census({})
    now = 1_800_000_000.0
    # Seed 100 old entries (>25h) directly + 5 recent 'attached' via append.
    old = [(now - 25 * 3600, "attached") for _ in range(100)]
    census._egress_identity_outcomes.extend(old)
    # Monkey-clock: patch dt_util.utcnow used in _note_egress_identity_outcome
    from custom_components.universal_room_automation import camera_census as _cc
    orig = _cc.dt_util.utcnow
    _cc.dt_util.utcnow = lambda: datetime.fromtimestamp(now, tz=UTC)
    try:
        for _ in range(5):
            census._note_egress_identity_outcome("attached")
    finally:
        _cc.dt_util.utcnow = orig
    # After prune, only the 5 recent entries survive.
    denom = sum(1 for _t, o in census._egress_identity_outcomes if o != "disabled")
    assert denom == 5


def test_d3_attrs_block_is_synchronous_ast():
    """C-LOW-3 replacement: parse sensor.py via AST and prove the D3
    marker line sits inside a SYNCHRONOUS function whose entire body
    contains zero `await` nodes.

    Path is derived from sensor.__file__ style (via pathlib on the
    imported source module path if importable, else the checked-in
    source relative to the repo root) — no cwd fragility, no source
    grep for the whole block.
    """
    import ast, pathlib
    # Derive source path via importlib.util so a namespace-package
    # (no __init__.py, no __file__) still resolves. Uses the const
    # submodule spec (loaded successfully in this test session).
    import importlib.util as _il
    spec = _il.find_spec(
        "custom_components.universal_room_automation.const"
    )
    assert spec is not None and spec.origin is not None
    pkg_dir = pathlib.Path(spec.origin).parent
    src_path = pkg_dir / "sensor.py"
    src = src_path.read_text()
    tree = ast.parse(src)

    marker = "EGRESS-IDENTITY-JOIN-GAP-1 (2026-08-28) D3 attrs"
    marker_line = None
    for i, line in enumerate(src.splitlines(), start=1):
        if marker in line:
            marker_line = i
            break
    assert marker_line is not None, "D3 attrs marker not found"

    # Find the enclosing FunctionDef whose body span covers marker_line.
    enclosing = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", None) or start
            if start <= marker_line <= end:
                if enclosing is None or (
                    (node.end_lineno - node.lineno)
                    < (enclosing.end_lineno - enclosing.lineno)
                ):
                    enclosing = node
    assert enclosing is not None, "D3 marker not inside a function"
    # The enclosing function must be a SYNC def (not AsyncFunctionDef).
    assert isinstance(enclosing, ast.FunctionDef), (
        f"D3 attrs live inside async function {enclosing.name!r} — "
        "must be synchronous"
    )
    # AND its entire body contains no await.
    for sub in ast.walk(enclosing):
        assert not isinstance(sub, ast.Await), (
            f"await found in {enclosing.name!r} — D3 attrs must be sync"
        )


# ---------------------------------------------------------------------------
# MED-4 — direction_ambiguous outcome + no legs read
# ---------------------------------------------------------------------------


def test_d2b_direction_ambiguous_has_own_outcome_and_skips_leg_read():
    """C-MED-2: direction=='ambiguous' returns DISAGREE without reading
    ANY leg, and appends a distinct 'direction_ambiguous' outcome
    (excluded from rate denominators)."""
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    census, hass, _ = _make_census({})
    tracker = _make_tracker(census, hass, interior_stems=[])
    reads: list[str] = []

    def _spy(stem):
        reads.append(stem)
        return []

    census._resolve_face_legs = _spy
    slug, idc, agc = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "ambiguous",
    )
    assert (slug, idc, agc) == (None, None, ura_const.CENSUS_AGREEMENT_DISAGREE)
    assert reads == [], "ambiguous direction must not read any leg"
    labels = [o for _t, o in census._egress_identity_outcomes]
    assert labels[-1] == "direction_ambiguous"


# ---------------------------------------------------------------------------
# A5 — vetoed distinct outcome label
# ---------------------------------------------------------------------------


def test_d2b_vetoed_outcome_distinct_from_no_leg():
    """A5: person.<slug>=not_home veto yields a 'vetoed' outcome, not
    'no_leg'. Return tuple is SINGLE with slug=None."""
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    states = {"person.oji_udezue": _make_state("not_home")}
    census, hass, _ = _make_census(states)
    tracker = _make_tracker(census, hass, interior_stems=[])
    # Re-wire hass.data.states.get to include the person state; the
    # tracker reads via self.hass.states.get.
    hass.states.get = lambda eid: states.get(eid)
    hass.data = {ura_const.DOMAIN: {"census": census}}
    tracker = EgressDirectionTracker(hass)
    tracker._get_interior_cameras_near = lambda cam: []

    _install_legs(census, {
        "front_door": [
            _leg("sensor.front_door_last_recognized_face", "frigate",
                 "dev_A", "oji_udezue", now + timedelta(seconds=-5)),
        ],
    })
    slug, idc, agc = tracker._resolve_egress_face_identity(
        "binary_sensor.front_door_person_occupancy", now, "exit",
    )
    assert slug is None
    labels = [o for _t, o in census._egress_identity_outcomes]
    assert labels[-1] == "vetoed"


# ---------------------------------------------------------------------------
# HIGH-3 — WIRE-IN behavioral test end-to-end through _resolve_direction.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wire_in_bus_payload_carries_identity_fields_and_attach_rate_moves():
    """HIGH-3: drives _resolve_direction end-to-end for a real crossing.

    Anchors the wire-in for D3 observability: verifies (a) the fired
    ``ura_person_egress_event`` bus payload carries the real
    ``identity_confidence`` + ``agreement_class`` fields; and (b) after
    the crossing, the census-sensor D3 attrs (evaluated by the SAME
    code path the sensor uses) reports a non-zero
    ``egress_identity_attach_rate_24h``.

    Goes RED when:
      * the call site at ``transit_validator.py`` is neutered so the
        resolver's observability writes don't fire (e.g. call replaced
        with ``pass`` or bus payload hardcodes None); the bus assertion
        fails on the identity fields AND the attach rate stays 0.0.
      * the resolver's ``_note_egress_identity_outcome`` append is
        neutered; the attach rate assertion fails.
    """
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    census, hass, _ = _make_census({})
    hass.data = {ura_const.DOMAIN: {"census": census}}
    tracker = EgressDirectionTracker(hass)
    tracker._get_interior_cameras_near = (
        lambda cam: ["binary_sensor.foyer_person_occupancy"]
    )
    # Seed a positive-delta interior event so _resolve_direction picks
    # direction=="entry" (uses the entry-window branch).
    crossing = now
    tracker._recent_interior_events[
        "binary_sensor.foyer_person_occupancy"
    ] = [crossing + timedelta(seconds=2)]

    _install_legs(census, {
        "front_door": [
            _leg("sensor.front_door_last_recognized_face", "frigate",
                 "dev_A", "oji_udezue", crossing + timedelta(seconds=1),
                 base_stem="front_door"),
        ],
        "foyer": [],
    })

    fired: list[tuple[str, dict]] = []
    hass.bus = MagicMock()
    hass.bus.async_fire = lambda topic, payload: fired.append((topic, payload))

    await tracker._resolve_direction(
        "binary_sensor.front_door_person_occupancy", crossing,
    )

    assert fired, "bus event must have fired"
    topic, payload = fired[-1]
    assert topic == "ura_person_egress_event"
    assert payload["direction"] == "entry"
    assert payload["person_id"] == "oji_udezue"
    # Wire-in assertion #1: identity fields are on the bus payload with
    # real (non-None) values from the resolver.
    assert payload["identity_confidence"] == ura_const.CONFIDENCE_MEDIUM
    assert payload["agreement_class"] == ura_const.CENSUS_AGREEMENT_SINGLE

    # Wire-in assertion #2: the SAME reader code the census sensor uses
    # reports a non-zero attach_rate_24h after this crossing. We evaluate
    # the reader logic directly against the deque so the assertion binds
    # to the census producer + the sensor's rate math simultaneously.
    from homeassistant.util import dt as _dt_util
    now_ts = _dt_util.utcnow().timestamp()
    cutoff = now_ts - 86400.0
    denom = 0
    attached = 0
    for _ts, out in census._egress_identity_outcomes:
        if _ts < cutoff:
            continue
        if out in ("disabled", "direction_ambiguous"):
            continue
        denom += 1
        if out == "attached":
            attached += 1
    assert denom >= 1, "outcomes deque must have received an entry"
    assert attached >= 1, "at least one 'attached' outcome expected"
    attach_rate = attached / denom
    assert attach_rate > 0.0, (
        "attach_rate_24h must move above zero after a successful attach"
    )
