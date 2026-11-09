"""FACE-SOURCE-REGISTRY-DISCOVERY-1 (v5.107.1) — registry-first Frigate face
sources, the `_N` person-sensor skip fix, the device-derived engine tag, the
face-name alias field and the token-only last_camera map.

Drives PRODUCTION code (`CameraResolver`, `PersonCensus`,
`PresenceCoordinator._get_face_for_camera` / `_find_person_entity_from_face`,
`EgressDirectionTracker._resolve_egress_face_identity`) over a registry
fixture EXTRACTED from the live HA registry by
`scripts/probe_face_source_registry.py --emit-fixture`
(`fixtures/face_source_registry_2026_11.json`), never typed by hand.

Oracles are independent of the code under test:
  - the INV-1 oracle is the kill-switch-OFF (pre-cycle) path, and the
    fixture's own `sensor.<stem>_last_recognized_face[_2]` names;
  - S7 oracles are hand-computed literals (count, count-1).
"""

from __future__ import annotations

import copy
import json
import logging
import pathlib
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

import _provenance_harness  # noqa: F401 — HA stubs (setdefault-safe)
from _provenance_harness import make_hass

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation import camera_census as _cc_mod
from custom_components.universal_room_automation.camera_census import (
    CameraInfo,
    FaceLeg,
    PersonCensus,
)
from custom_components.universal_room_automation.camera_resolver import (
    CameraResolver,
    FACE_USABLE,
    FACE_ABSENT,
)

UTC = timezone.utc
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "face_source_registry_2026_11.json"


class _TzUtil:
    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def as_local(dt: datetime) -> datetime:
        return dt

    UTC = timezone.utc


@pytest.fixture(autouse=True)
def _scoped_dt_util(monkeypatch):
    monkeypatch.setattr(_cc_mod, "dt_util", _TzUtil(), raising=True)
    yield


def _set_flag(monkeypatch, name: str, value) -> None:
    """Flip a rung-1 flag on EVERY live copy of const: the one camera_census
    bound at import (`_cc_mod._ura_const`), this file's import, and the
    current sys.modules entry (read lazily by camera_resolver). Sibling
    files re-import const, so patching one copy is order-dependent."""
    import sys as _sys
    seen = set()
    for mod in (PersonCensus._resolve_face_legs.__globals__.get("_ura_const"),
                getattr(_cc_mod, "_ura_const", None), ura_const,
                _sys.modules.get("custom_components.universal_room_automation.const")):
        if mod is not None and id(mod) not in seen:
            seen.add(id(mod))
            monkeypatch.setattr(mod, name, value, raising=False)


@pytest.fixture
def discovery_off(monkeypatch):
    _set_flag(monkeypatch, "FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED", False)


@pytest.fixture
def skipfix_off(monkeypatch):
    _set_flag(monkeypatch, "FACE_SOURCE_INCLUDE_DISAMBIGUATED_PERSON_SENSORS", False)


# ---------------------------------------------------------------------------
# Registry fakes built from the extracted fixture.
# ---------------------------------------------------------------------------


class _Ent:
    def __init__(self, d: dict) -> None:
        self.entity_id = d["entity_id"]
        self.platform = d.get("platform")
        self.unique_id = d.get("unique_id")
        self.device_id = d.get("device_id")
        self.disabled_by = d.get("disabled_by")
        self.domain = self.entity_id.split(".", 1)[0]
        self.area_id = None


class _ER:
    def __init__(self, ents: list[_Ent]) -> None:
        self.entities = {e.entity_id: e for e in ents}

    def async_get(self, eid: str):
        return self.entities.get(eid)


class _Dev:
    def __init__(self, d: dict) -> None:
        self.id = d["id"]
        self.name = d.get("name")
        self.identifiers = {tuple(x) for x in (d.get("identifiers") or [])}
        self.connections = set()
        self.via_device_id = d.get("via_device_id")


class _DR:
    def __init__(self, devs: list[_Dev]) -> None:
        self.devices = {d.id: d for d in devs}

    def async_get(self, did: str):
        return self.devices.get(did)


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def _registries(fx: Optional[dict] = None):
    fx = fx or _load_fixture()
    return _ER([_Ent(e) for e in fx["entities"]]), _DR([_Dev(d) for d in fx["devices"]])


def _face_entities(fx: dict) -> list[dict]:
    return [e for e in fx["entities"]
            if e["platform"] == "frigate" and e["entity_id"].startswith("sensor.")
            and (e["unique_id"] or "").split(":")[1] == "sensor_recognized_face"]


def _face_base(eid: str) -> str:
    name = eid.split(".", 1)[1]
    for suf in ("_last_recognized_face_2", "_last_recognized_face"):
        if name.endswith(suf):
            return name[: -len(suf)]
    raise AssertionError(eid)


def _person_sensor_for_device(fx: dict, did: str) -> str:
    hits = [e for e in fx["entities"]
            if e["platform"] == "frigate" and e["device_id"] == did
            and e["entity_id"].startswith("binary_sensor.")
            and (e["unique_id"] or "").split(":")[1] == "occupancy_sensor"
            and (e["unique_id"] or "").endswith("_person")]
    hits.sort(key=lambda e: "_package_" in e["unique_id"])
    if not hits:
        raise AssertionError(did)
    return hits[0]["entity_id"]


class _Mgr:
    def __init__(self, resolver, cameras: Optional[dict[str, CameraInfo]] = None) -> None:
        self._resolver = resolver
        self._camera_by_entity = dict(cameras or {})

    def _get_resolver(self):
        return self._resolver

    def get_platform_for_camera(self, entity_id):
        info = self._camera_by_entity.get(entity_id)
        return info.platform if info else None

    def get_all_frigate_cameras(self):
        return [c for c in self._camera_by_entity.values()
                if c.platform == ura_const.CAMERA_PLATFORM_FRIGATE]

    def resolve_configured_cameras(self, ids):
        return [self._camera_by_entity[i] for i in ids if i in self._camera_by_entity]


def _state(value, last_changed=None, attributes=None):
    st = MagicMock()
    st.state = value
    st.last_changed = last_changed
    st.attributes = attributes or {}
    return st


def _census(states: dict, *, er_=None, dr_=None, cameras=None, aliases=None,
            known_guests=("Ojini",), tracked=("person.oji_udezue", "person.jaya",
                                              "person.ziri", "person.ezinne"),
            monkeypatch=None, resolver: Any = "build"):
    hass = make_hass()
    hass.states.get = lambda eid: states.get(eid)
    entry = MagicMock()
    entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        "tracked_persons": list(tracked),
        ura_const.CONF_KNOWN_FACE_GUESTS: list(known_guests),
        ura_const.CONF_ENHANCED_CENSUS: True,
        ura_const.CONF_EGRESS_IDENTITY_FAILSAFE_STRICT: False,
        ura_const.CONF_CAMERA_PERSON_ENTITIES: list((cameras or {}).keys()),
    }
    if aliases is not None:
        entry.options[ura_const.CONF_FACE_NAME_ALIASES] = list(aliases)
    hass.config_entries.async_entries.return_value = [entry]
    if er_ is None:
        er_, dr_ = _registries()
    if resolver == "build":
        resolver = CameraResolver(er_, dr_)
    if monkeypatch is not None:
        monkeypatch.setattr(_cc_mod.er, "async_get", lambda _h: er_)
    census = PersonCensus(hass, _Mgr(resolver, cameras))  # type: ignore[arg-type]
    return census, hass, resolver


def _all_faces_named(fx, name="Jaya", ts=None):
    ts = ts or datetime.now(UTC)
    return {e["entity_id"]: _state(name, ts) for e in _face_entities(fx)}


def _legs_tuple(legs):
    return [(l.entity_id, l.engine, l.device_id, l.base_stem, l.canonical_slug,
             l.last_changed, l.confidence) for l in legs]


# ---------------------------------------------------------------------------
# D2 — registry-first index
# ---------------------------------------------------------------------------


def test_registry_equals_pattern_on_live_fixture(monkeypatch):
    """INV-1 over the live fixture: every face stem resolves to the same
    face entity_id (S1) and the same FaceLeg fields except engine (S2) with
    discovery ON vs OFF; and the S1 lookup's missing-counter delta matches."""
    fx = _load_fixture()
    states = _all_faces_named(fx)
    stems = sorted({_face_base(e["entity_id"]) for e in _face_entities(fx)})
    assert len(stems) == 29
    # plus stems a caller can pass that are NOT face stems (Protect / `_2`
    # camera names / Frigate identifiers) — discovery must not widen them.
    extra = ["garage_a_2", "foyer", "upstairs_hall_high_resolution_channel", "nope"]
    census, _, resolver = _census(states, monkeypatch=monkeypatch)
    on: dict = {}
    for s in stems + extra:
        before = census._face_lookup_missing_count
        on[s] = (census._resolve_face_entity_id(s),
                 census._face_lookup_missing_count - before,
                 [x[:2] + x[3:] for x in _legs_tuple(census._resolve_face_legs(s))])
    assert census._face_source_registry_hits > 0
    _set_flag(monkeypatch, "FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED", False)
    for s in stems + extra:
        before = census._face_lookup_missing_count
        off_eid = census._resolve_face_entity_id(s)
        off_delta = census._face_lookup_missing_count - before
        off_legs = [x[:2] + x[3:] for x in _legs_tuple(census._resolve_face_legs(s))]
        # engine excluded (INV-2 declared exception): index 1 dropped below
        assert on[s][0] == off_eid, s
        assert on[s][1] == off_delta, s
        assert [l[:1] + l[2:] for l in on[s][2]] == [l[:1] + l[2:] for l in off_legs], s
    # Independent oracle: each face stem's S1 result is the fixture's own
    # face sensor (sensor.<stem>_last_recognized_face[_2]).
    ids = {e["entity_id"] for e in _face_entities(fx)}
    for s in stems:
        assert on[s][0] in ids and _face_base(on[s][0]) == s


def test_d10_5_known_identity_legs_equal_under_discovery(monkeypatch):
    """INV-1 for the perimeter D10.5 consumer: `_known_identity_for` reads
    `canonical_slug` / `last_changed` / `confidence` from `_resolve_face_legs`
    — identical ON vs OFF on a dual-role door camera stem."""
    fx = _load_fixture()
    states = _all_faces_named(fx, "Oji")
    census, _, _ = _census(states, monkeypatch=monkeypatch)
    on = [(l.canonical_slug, l.last_changed, l.confidence)
          for l in census._resolve_face_legs("doorbell_lite")]
    _set_flag(monkeypatch, "FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED", False)
    off = [(l.canonical_slug, l.last_changed, l.confidence)
           for l in census._resolve_face_legs("doorbell_lite")]
    assert on == off and on and on[0][0] == "oji_udezue"


def _rename(fx, old, new):
    fx = copy.deepcopy(fx)
    for e in fx["entities"]:
        if e["entity_id"] == old:
            e["entity_id"] = new
    return fx


def test_renamed_face_sensor_resolves_by_registry(monkeypatch):
    fx = _rename(_load_fixture(), "sensor.doorbell_lite_last_recognized_face_2",
                 "sensor.front_bell_face_name")
    er_, dr_ = _registries(fx)
    states = {"sensor.front_bell_face_name": _state("Oji", datetime.now(UTC))}
    census, _, _ = _census(states, er_=er_, dr_=dr_, monkeypatch=monkeypatch)
    assert census._resolve_face_entity_id("doorbell_lite") == "sensor.front_bell_face_name"
    assert census._face_source_registry_hits == 1
    assert census._face_source_pattern_fallbacks == 0
    legs = census._resolve_face_legs("doorbell_lite")
    assert [l.entity_id for l in legs] == ["sensor.front_bell_face_name"]


def test_empty_index_falls_back_to_pattern(monkeypatch):
    """Discriminates a broken index from a rename: index forced empty ->
    the renamed id is NOT found (None) and the FALLBACK counter moves."""
    fx = _rename(_load_fixture(), "sensor.doorbell_lite_last_recognized_face_2",
                 "sensor.front_bell_face_name")
    er_, dr_ = _registries(fx)
    states = {"sensor.front_bell_face_name": _state("Oji", datetime.now(UTC))}
    census, _, resolver = _census(states, er_=er_, dr_=dr_, monkeypatch=monkeypatch)
    resolver._frigate_face_entities_by_device = {}
    assert census._resolve_face_entity_id("doorbell_lite") is None
    assert census._face_source_registry_hits == 0
    assert census._face_source_pattern_fallbacks == 1
    assert census._face_source_pattern_fallback_stems == {"doorbell_lite"}


def test_global_face_never_indexed():
    """INV-3: a `sensor_global_face` row, even placed on a camera device and
    named like a face sensor, is never a face-name source."""
    fx = copy.deepcopy(_load_fixture())
    dev = _face_entities(fx)[0]["device_id"]
    fx["entities"].append({
        "entity_id": "sensor.lookalike_last_recognized_face",
        "platform": "frigate",
        "unique_id": "01KM239Z8ZQWQTN1D9CV5JRA7V:sensor_global_face:Oji",
        "device_id": dev, "disabled_by": None,
    })
    er_, dr_ = _registries(fx)
    r = CameraResolver(er_, dr_)
    indexed = {e for lst in r._frigate_face_entities_by_device.values() for e in lst}
    assert "sensor.lookalike_last_recognized_face" not in indexed
    gf = [e["entity_id"] for e in fx["entities"]
          if (e["unique_id"] or "").split(":")[1:2] == ["sensor_global_face"]]
    assert len(gf) == 7 and not (set(gf) & indexed)
    assert len(indexed) == 29


@pytest.mark.parametrize("platform,entity_id", [
    ("unifiprotect", "sensor.intruder_face_name"),      # wrong platform
    ("frigate", "binary_sensor.intruder_face_name"),    # wrong domain
])
def test_index_predicate_requires_frigate_sensor(platform, entity_id):
    """INV-3 conjuncts, each on its own: the token alone is not enough."""
    fx = copy.deepcopy(_load_fixture())
    dev = _face_entities(fx)[0]["device_id"]
    fx["entities"].append({
        "entity_id": entity_id, "platform": platform,
        "unique_id": "X:sensor_recognized_face:intruder",
        "device_id": dev, "disabled_by": None,
    })
    r = CameraResolver(*_registries(fx))
    indexed = {e for lst in r._frigate_face_entities_by_device.values() for e in lst}
    assert entity_id not in indexed and len(indexed) == 29


def test_index_order_bare_before_disambiguated(monkeypatch):
    """D2 order = legacy bare-then-`_2`: a device carrying both names lists
    the bare one first, so S1 picks it when both have usable states."""
    fx = copy.deepcopy(_load_fixture())
    src = next(e for e in fx["entities"]
               if e["entity_id"] == "sensor.garage_a_last_recognized_face_2")
    bare = dict(src, entity_id="sensor.garage_a_last_recognized_face",
                unique_id=src["unique_id"] + "_dup")
    fx["entities"].append(bare)
    er_, dr_ = _registries(fx)
    now = datetime.now(UTC)
    states = {"sensor.garage_a_last_recognized_face": _state("Oji", now),
              "sensor.garage_a_last_recognized_face_2": _state("Jaya", now)}
    census, _, resolver = _census(states, er_=er_, dr_=dr_, monkeypatch=monkeypatch)
    assert resolver.face_name_entities_for_device(src["device_id"]) == [
        "sensor.garage_a_last_recognized_face", "sensor.garage_a_last_recognized_face_2"]
    assert census._resolve_face_entity_id("garage_a") == "sensor.garage_a_last_recognized_face"


def test_new_entry_prefix_same_index():
    fx = _load_fixture()
    base = CameraResolver(*_registries(fx))._frigate_face_entities_by_device
    fx2 = copy.deepcopy(fx)
    for e in fx2["entities"]:
        if e["platform"] == "frigate" and e["unique_id"] and ":" in e["unique_id"]:
            e["unique_id"] = "01NEWENTRYIDXXXXXXXXXXXXXX:" + e["unique_id"].split(":", 1)[1]
    again = CameraResolver(*_registries(fx2))._frigate_face_entities_by_device
    assert again == base and len(base) == 29


def test_latch_key_from_camera_entity_equals_legacy_key(monkeypatch):
    """S9: latch keys for all 29 Frigate cam names equal the pre-cycle keys;
    a renamed face sensor latches under the camera.* stem (`_N` stripped)."""
    fx = _load_fixture()
    census, _, resolver = _census({}, monkeypatch=monkeypatch)
    cams = sorted(resolver._frigate_stem_to_device_ids)
    on = {c: census._compute_face_latch_stems(resolver, c) for c in cams}
    _set_flag(monkeypatch, "FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED", False)
    off = {c: census._compute_face_latch_stems(resolver, c) for c in cams}
    face_cams = [c for c in cams if off[c]]
    assert len(face_cams) == 29
    assert on == off
    # rename: legacy finds nothing, registry latches under the camera stem
    _set_flag(monkeypatch, "FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED", True)
    fx2 = _rename(fx, "sensor.garage_a_last_recognized_face_2", "sensor.garage_face_x")
    er2, dr2 = _registries(fx2)
    census2, _, r2 = _census({}, er_=er2, dr_=dr2, monkeypatch=monkeypatch)
    assert census2._compute_face_latch_stems(r2, "garage_a") == ["garage_a"]
    _set_flag(monkeypatch, "FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED", False)
    assert census2._compute_face_latch_stems(r2, "garage_a") == []


def test_kill_switch_off_byte_identical(monkeypatch, discovery_off):
    """Switch OFF: a renamed face sensor is invisible (pre-cycle), the
    discovery counters never move, and engine is the suffix tag."""
    fx = _rename(_load_fixture(), "sensor.doorbell_lite_last_recognized_face_2",
                 "sensor.front_bell_face_name")
    er_, dr_ = _registries(fx)
    now = datetime.now(UTC)
    states = {"sensor.front_bell_face_name": _state("Oji", now),
              "sensor.garage_a_last_recognized_face_2": _state("Oji", now)}
    census, _, _ = _census(states, er_=er_, dr_=dr_, monkeypatch=monkeypatch)
    assert census._resolve_face_entity_id("doorbell_lite") is None
    legs = census._resolve_face_legs("garage_a")
    assert [l.engine for l in legs] == ["frigate2"]
    assert census._face_source_registry_hits == 0
    assert census._face_source_pattern_fallbacks == 0


def test_face_cap_by_token_for_renamed_sensor(monkeypatch):
    """S10: a renamed Frigate face sensor still sets face_cap USABLE via the
    unique_id token; with discovery OFF it does not (suffix only)."""
    fx = _rename(_load_fixture(), "sensor.doorbell_lite_last_recognized_face_2",
                 "sensor.front_bell_face_name")
    r = CameraResolver(*_registries(fx))
    did = _face_entities(fx)[0]["device_id"]
    for e in fx["entities"]:
        if e["entity_id"] == "sensor.front_bell_face_name":
            did = e["device_id"]
    cap_on = r._scan_device_entities(did, "frigate", stem_filter=None)[2]
    _set_flag(monkeypatch, "FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED", False)
    cap_off = r._scan_device_entities(did, "frigate", stem_filter=None)[2]
    assert cap_on == FACE_USABLE
    assert cap_off == FACE_ABSENT


# ---------------------------------------------------------------------------
# D3 — the `_N` person-sensor skip fix (S5-S8), INV-4
# ---------------------------------------------------------------------------


def _frigate_cam(fx, stem_prefix: str, area: str = "area_play"):
    """CameraInfo for the fixture's Frigate camera whose face base is
    `stem_prefix`, with its REAL person sensor id."""
    for e in _face_entities(fx):
        if _face_base(e["entity_id"]) == stem_prefix:
            bs = _person_sensor_for_device(fx, e["device_id"])
            pc = f"sensor.{stem_prefix}_person_count"
            return CameraInfo(entity_id=bs, platform=ura_const.CAMERA_PLATFORM_FRIGATE,
                              area_id=area, person_binary_sensor=bs,
                              person_count_sensor=pc), pc, e["entity_id"]
    raise AssertionError(stem_prefix)


def test_skip_fix_on_reads_device_face(monkeypatch):
    """S5 + S6 + counters: playroom's person sensor is `_person_occupancy_2`;
    ON -> its face is read via the device and listed as device-derived."""
    fx = _load_fixture()
    info, pc, face = _frigate_cam(fx, "playroom")
    assert info.entity_id == "binary_sensor.playroom_person_occupancy_2"
    now = datetime.now(UTC)
    states = {face: _state("Jaya", now), pc: _state("1")}
    census, _, _ = _census(states, cameras={info.entity_id: info}, monkeypatch=monkeypatch)
    assert census._get_face_recognized_persons() == {"Jaya"}
    assert census._get_face_recognized_persons_fresh(now) == {"Jaya"}
    assert census._face_source_device_derived_reads == 2
    assert census._face_source_device_derived_cameras == {info.entity_id}
    assert census._face_source_skipped_person_sensors == 0


def test_skip_fix_off_counts_skipped(monkeypatch, skipfix_off):
    fx = _load_fixture()
    info, pc, face = _frigate_cam(fx, "playroom")
    now = datetime.now(UTC)
    states = {face: _state("Jaya", now), pc: _state("1")}
    census, _, _ = _census(states, cameras={info.entity_id: info}, monkeypatch=monkeypatch)
    assert census._get_face_recognized_persons() == set()
    assert census._get_face_recognized_persons_fresh(now) == set()
    assert census._face_source_skipped_person_sensors == 2
    assert census._face_source_skipped_cameras == {info.entity_id}
    assert census._face_source_device_derived_reads == 0


def test_renamed_person_sensor_resolves_when_on_skipped_when_off(monkeypatch):
    fx = _rename(_load_fixture(), "binary_sensor.playroom_person_occupancy_2",
                 "binary_sensor.kids_room_motion_person")
    er_, dr_ = _registries(fx)
    info, pc, face = _frigate_cam(fx, "playroom")
    assert info.entity_id == "binary_sensor.kids_room_motion_person"
    now = datetime.now(UTC)
    states = {face: _state("Ziri", now), pc: _state("1")}
    census, _, _ = _census(states, er_=er_, dr_=dr_, cameras={info.entity_id: info},
                           monkeypatch=monkeypatch)
    assert census._get_face_recognized_persons() == {"Ziri"}
    _set_flag(monkeypatch, "FACE_SOURCE_INCLUDE_DISAMBIGUATED_PERSON_SENSORS", False)
    census._reset_face_source_counters()
    assert census._get_face_recognized_persons() == set()
    assert census._face_source_skipped_person_sensors == 1


@pytest.mark.parametrize("face_kind", ["fresh", "stale", "absent", "exception"])
def test_unrecognized_contribution_never_rises(monkeypatch, face_kind):
    """INV-4 at S7 (`_get_unrecognized_camera_count`): playroom
    (`_person_occupancy_2`), person_count 2. Hand oracles: OFF -> 2 always;
    ON -> 1 only for a fresh face, else 2. Never above OFF."""
    fx = _load_fixture()
    info, pc, face = _frigate_cam(fx, "playroom")
    now = datetime.now(UTC)
    states = {pc: _state("2")}
    if face_kind == "fresh":
        states[face] = _state("Jaya", now - timedelta(seconds=10))
    elif face_kind == "stale":
        states[face] = _state("Jaya", now - timedelta(seconds=7200))
    census, _, resolver = _census(states, cameras={info.entity_id: info}, monkeypatch=monkeypatch)
    if face_kind == "exception":
        def _boom(_eid):
            raise RuntimeError("device join broke")
        resolver.face_name_entities_for_entity = _boom
        states[face] = _state("Jaya", now - timedelta(seconds=10))
    census._get_unrecognized_camera_count()
    on = dict(census._last_area_raw_max_pre_cancel)
    _set_flag(monkeypatch, "FACE_SOURCE_INCLUDE_DISAMBIGUATED_PERSON_SENSORS", False)
    census._get_unrecognized_camera_count()
    off = dict(census._last_area_raw_max_pre_cancel)
    assert off == {"area_play": 2}
    expected_on = 1 if face_kind == "fresh" else 2
    assert on == {"area_play": expected_on}
    assert on["area_play"] <= off["area_play"]
    assert census._last_camera_total_pre_cancel == 2


def test_unrecognized_bare_camera_one_append_and_identical_under_flip(monkeypatch):
    """A bare `_person_occupancy` camera (family_room) is byte-identical
    under the flip; and the `_2` camera with no face sensor on its device
    appends exactly once (fail-CLOSED, no double count)."""
    fx = _load_fixture()
    bare, pc_b, face_b = _frigate_cam(fx, "family_room", area="area_fam")
    assert bare.entity_id.endswith("_person_occupancy")
    play, pc_p, face_p = _frigate_cam(fx, "playroom", area="area_play")
    now = datetime.now(UTC)
    states = {pc_b: _state("3"), face_b: _state("Oji", now), pc_p: _state("2")}
    cams = {bare.entity_id: bare, play.entity_id: play}
    census, _, resolver = _census(states, cameras=cams, monkeypatch=monkeypatch)
    # remove playroom's face sensor from its device: join yields nothing
    play_dev = resolver._er.async_get(play.entity_id).device_id
    resolver._frigate_face_entities_by_device.pop(play_dev)
    census._get_unrecognized_camera_count()
    on = dict(census._last_area_raw_max_pre_cancel)
    on_total = census._last_camera_total_pre_cancel
    _set_flag(monkeypatch, "FACE_SOURCE_INCLUDE_DISAMBIGUATED_PERSON_SENSORS", False)
    census._get_unrecognized_camera_count()
    assert on == dict(census._last_area_raw_max_pre_cancel) == {"area_fam": 2, "area_play": 2}
    assert on_total == census._last_camera_total_pre_cancel == 4


def test_bare_cameras_identical_under_flip(monkeypatch):
    """S5/S6 for the 12 bare cameras return exactly the legacy value."""
    fx = _load_fixture()
    now = datetime.now(UTC)
    cams, states = {}, {}
    for e in _face_entities(fx):
        bs = _person_sensor_for_device(fx, e["device_id"])
        if not bs.endswith("_person_occupancy"):
            continue
        cams[bs] = CameraInfo(entity_id=bs, platform=ura_const.CAMERA_PLATFORM_FRIGATE,
                              area_id=None, person_binary_sensor=bs)
        states[e["entity_id"]] = _state(_face_base(e["entity_id"]).title(), now)
    assert len(cams) == 12
    census, _, _ = _census(states, cameras=cams, monkeypatch=monkeypatch)
    on = (census._get_face_recognized_persons(), census._get_face_recognized_persons_fresh(now))
    _set_flag(monkeypatch, "FACE_SOURCE_INCLUDE_DISAMBIGUATED_PERSON_SENSORS", False)
    off = (census._get_face_recognized_persons(), census._get_face_recognized_persons_fresh(now))
    assert on == off and len(on[0]) == 12


def test_enhanced_overwrites_raw_face_union(monkeypatch):
    """With enhanced census on, the identified set comes from
    `_get_face_recognized_person_names` (last_camera map), which the skip-fix
    flag does not touch: flipping it leaves that set unchanged while the raw
    union S5 does change."""
    fx = _load_fixture()
    info, pc, face = _frigate_cam(fx, "garage_a", area="area_garage")
    now = datetime.now(UTC)
    states = {face: _state("Oji", now), pc: _state("1")}
    census, _, _ = _census(states, cameras={info.entity_id: info}, monkeypatch=monkeypatch)
    raw_on = census._get_face_recognized_persons()
    names_on = census._get_face_recognized_person_names(now)
    _set_flag(monkeypatch, "FACE_SOURCE_INCLUDE_DISAMBIGUATED_PERSON_SENSORS", False)
    raw_off = census._get_face_recognized_persons()
    names_off = census._get_face_recognized_person_names(now)
    assert raw_on == {"Oji"} and raw_off == set()
    assert names_on == names_off


def _presence_with_census(census, hass_states):
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )
    pc = object.__new__(PresenceCoordinator)
    hass = MagicMock()
    hass.states.get = lambda eid: hass_states.get(eid)
    hass.data = {ura_const.DOMAIN: {"census": census}}
    pc.hass = hass
    return pc


def test_presence_face_for_camera_reads_device_face(monkeypatch):
    """S8: `_get_face_for_camera` on a `_person_occupancy_2` camera returns
    the fresh face via the device join; OFF -> None (legacy)."""
    fx = _load_fixture()
    info, pc, face = _frigate_cam(fx, "doorbell_lite")
    now = datetime.now(UTC)
    states = {face: _state("Jaya", now - timedelta(seconds=5))}
    census, _, _ = _census(states, monkeypatch=monkeypatch)
    pres = _presence_with_census(census, states)
    _set_flag(monkeypatch, "FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED", True)
    assert pres._get_face_for_camera(info.entity_id) == "Jaya"
    _set_flag(monkeypatch, "FACE_SOURCE_INCLUDE_DISAMBIGUATED_PERSON_SENSORS", False)
    assert pres._get_face_for_camera(info.entity_id) is None


def test_presence_arrival_flag_default_off_keeps_legacy_skip(monkeypatch):
    """Shipped default: S8 does NOT widen camera_face arrivals onto `_N`
    person sensors (the door/garage cameras), because SIGNAL_PERSON_ARRIVING
    feeds the SC lock regime release / away-lock unlock. Census S5-S7 still
    read the same face (skip fix live there)."""
    fx = _load_fixture()
    info, pc, face = _frigate_cam(fx, "doorbell_lite")
    now = datetime.now(UTC)
    states = {face: _state("Jaya", now - timedelta(seconds=5)), pc: _state("1")}
    census, _, _ = _census(states, cameras={info.entity_id: info}, monkeypatch=monkeypatch)
    pres = _presence_with_census(census, states)
    assert pres._get_face_for_camera(info.entity_id) is None
    assert census._get_face_recognized_persons() == {"Jaya"}


def test_presence_bare_camera_unchanged(monkeypatch):
    fx = _load_fixture()
    info, pc, face = _frigate_cam(fx, "family_room")
    now = datetime.now(UTC)
    states = {face: _state("Ziri", now - timedelta(seconds=5))}
    census, _, _ = _census(states, monkeypatch=monkeypatch)
    pres = _presence_with_census(census, states)
    a = pres._get_face_for_camera(info.entity_id)
    _set_flag(monkeypatch, "FACE_SOURCE_INCLUDE_DISAMBIGUATED_PERSON_SENSORS", False)
    _set_flag(monkeypatch, "FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED", False)
    assert a == pres._get_face_for_camera(info.entity_id) == "Ziri"


# ---------------------------------------------------------------------------
# D4 — engine tag from the device (INV-2)
# ---------------------------------------------------------------------------


def _latch(census, stem, name, ts):
    census._frigate_face_latch[stem] = (name, ts)


def test_entity_and_latch_legs_dedup_same_engine(monkeypatch):
    fx = _load_fixture()
    now = datetime.now(UTC)
    face = "sensor.garage_a_last_recognized_face_2"
    states = {face: _state("Oji", now - timedelta(seconds=20))}
    census, _, _ = _census(states, monkeypatch=monkeypatch)
    _latch(census, "garage_a", "Oji", now - timedelta(seconds=5))
    legs = census._resolve_face_legs("garage_a")
    assert len(legs) == 1
    assert legs[0].engine == "frigate"
    assert legs[0].entity_id == face


def test_engine_tag_from_device_not_suffix(monkeypatch):
    """Bare and `_2` face sensors on the same install get the same family
    tag ("frigate") — the suffix no longer names an engine."""
    now = datetime.now(UTC)
    states = {"sensor.garage_a_last_recognized_face_2": _state("Oji", now),
              "sensor.kitchen_panel_last_recognized_face": _state("Jaya", now)}
    census, _, _ = _census(states, monkeypatch=monkeypatch)
    e1 = census._resolve_face_legs("garage_a")[0]
    e2 = census._resolve_face_legs("kitchen_panel")[0]
    assert (e1.engine, e2.engine) == ("frigate", "frigate")
    assert e1.device_id and e2.device_id and e1.device_id != e2.device_id


def test_engine_fallback_is_hint_not_unknown(monkeypatch):
    """Rev 2 pin (review 1 F-2): face entity's device ABSENT from the device
    registry -> entity leg engine is the hint "frigate", and entity leg +
    fresh latch on the same stem still give ONE leg."""
    fx = copy.deepcopy(_load_fixture())
    face = "sensor.garage_a_last_recognized_face_2"
    dev = next(e["device_id"] for e in fx["entities"] if e["entity_id"] == face)
    fx["devices"] = [d for d in fx["devices"] if d["id"] != dev]
    er_, dr_ = _registries(fx)
    now = datetime.now(UTC)
    states = {face: _state("Oji", now - timedelta(seconds=20))}
    census, _, resolver = _census(states, er_=er_, dr_=dr_, monkeypatch=monkeypatch)
    assert resolver.face_engine_tag(dev, "frigate") == "frigate"
    assert resolver.face_engine_tag(None, "frigate") == "frigate"
    _latch(census, "garage_a", "Oji", now - timedelta(seconds=5))
    legs = census._resolve_face_legs("garage_a")
    assert [l.engine for l in legs] == ["frigate"]


def test_synthetic_only_leg_engine_matches_entity_family(monkeypatch):
    """Latch with no live entity leg: the synthetic leg is tagged by the
    same helper ("frigate"), sentinel = the registry face sensor."""
    now = datetime.now(UTC)
    census, _, _ = _census({}, monkeypatch=monkeypatch)
    _latch(census, "garage_a", "Oji", now - timedelta(seconds=5))
    legs = census._resolve_face_legs("garage_a")
    assert [(l.engine, l.entity_id) for l in legs] == [
        ("frigate", "sensor.garage_a_last_recognized_face_2")]


def _tracker(census, hass, interior_stems=()):
    from custom_components.universal_room_automation.transit_validator import (
        EgressDirectionTracker,
    )
    hass.data = {ura_const.DOMAIN: {"census": census}}
    t = EgressDirectionTracker(hass)
    t._get_interior_cameras_near = lambda cam: [
        f"binary_sensor.{s}_person_occupancy" for s in interior_stems]
    return t


@pytest.mark.parametrize("discovery", [True, False])
def test_egress_confidence_unchanged_single_and_pair(monkeypatch, discovery):
    """Single named camera (+ its own fresh latch) -> 0.6; two cameras -> 0.9;
    identical with discovery ON and OFF."""
    _set_flag(monkeypatch, "FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED", discovery)
    now = datetime.now(UTC)
    states = {"sensor.garage_a_last_recognized_face_2": _state("Oji", now - timedelta(seconds=10))}
    census, hass, _ = _census(states, monkeypatch=monkeypatch)
    census._egress_identity_enabled_cache = None
    _latch(census, "garage_a", "Oji", now - timedelta(seconds=8))
    t = _tracker(census, hass)
    slug, idc, _ = t._resolve_egress_face_identity(
        "binary_sensor.garage_a_person_occupancy_2", now, "exit")
    assert (slug, idc) == ("oji_udezue", 0.6)
    states["sensor.kitchen_panel_last_recognized_face"] = _state("Oji", now - timedelta(seconds=15))
    t2 = _tracker(census, hass, interior_stems=["kitchen_panel"])
    slug, idc, _ = t2._resolve_egress_face_identity(
        "binary_sensor.garage_a_person_occupancy_2", now, "exit")
    assert (slug, idc) == ("oji_udezue", 0.9)


# ---------------------------------------------------------------------------
# D5 — face-name aliases
# ---------------------------------------------------------------------------


def test_alias_empty_is_noop(monkeypatch):
    census, _, _ = _census({}, aliases=[], monkeypatch=monkeypatch)
    assert census._canonical_person_slug("Oji") == "oji_udezue"
    assert census._canonical_person_slug("Ojini") == "guest:ojini"
    assert census._canonical_person_slug("Boss") == "boss"
    assert census.face_alias_person_slug("Oji") is None


def test_alias_maps_nickname(monkeypatch):
    census, _, _ = _census({}, aliases=["Ojini=oji_udezue", "Boss=person.oji_udezue",
                                        "Pal=Ojini"], monkeypatch=monkeypatch)
    assert census._canonical_person_slug("Ojini") == "oji_udezue"
    assert census._canonical_person_slug("Boss") == "oji_udezue"
    assert census._canonical_person_slug("Pal") == "guest:ojini"
    assert census.face_alias_person_slug("Boss") == "oji_udezue"
    assert census.face_alias_person_slug("Pal") is None


def test_alias_beats_ambiguous_head(monkeypatch):
    tracked = ("person.oji_udezue", "person.oji_other")
    census, _, _ = _census({}, tracked=tracked, aliases=[], monkeypatch=monkeypatch)
    assert census._canonical_person_slug("Oji") == ""  # fail-closed today
    census2, _, _ = _census({}, tracked=tracked, aliases=["Oji=oji_udezue"],
                            monkeypatch=monkeypatch)
    assert census2._canonical_person_slug("Oji") == "oji_udezue"


def test_alias_bad_target_ignored(monkeypatch, caplog):
    census, _, _ = _census({}, aliases=["Oji=nobody", "nonsense"], monkeypatch=monkeypatch)
    with caplog.at_level(logging.WARNING):
        assert census._canonical_person_slug("Oji") == "oji_udezue"
        assert census._canonical_person_slug("Oji") == "oji_udezue"
    warns = [r for r in caplog.records if "face_name_aliases" in r.getMessage()]
    assert len(warns) == 2  # one per bad entry, not per lookup


def test_presence_alias_maps_face_to_person(monkeypatch):
    """S8 person mapping: 'Oji' has no `person.oji`; the alias
    'Oji=oji_udezue' maps it to `person.oji_udezue`. Empty -> None."""
    states = {"person.oji_udezue": _state("home")}
    census, _, _ = _census({}, aliases=[], monkeypatch=monkeypatch)
    pres = _presence_with_census(census, states)
    assert pres._find_person_entity_from_face("Oji") is None
    census2, _, _ = _census({}, aliases=["Oji=oji_udezue"], monkeypatch=monkeypatch)
    pres2 = _presence_with_census(census2, states)
    assert pres2._find_person_entity_from_face("Oji") == "person.oji_udezue"
    assert pres2._find_person_entity_from_face("Jaya") is None


# ---------------------------------------------------------------------------
# D6 — last_camera map, token-only filter
# ---------------------------------------------------------------------------


def test_last_camera_map_same_on_live_fixture(monkeypatch):
    census, _, _ = _census({}, monkeypatch=monkeypatch)
    on = census._build_frigate_person_last_camera_map()
    _set_flag(monkeypatch, "FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED", False)
    off = census._build_frigate_person_last_camera_map()
    assert on == off and len(on) == 6


def test_last_camera_map_survives_rename(monkeypatch):
    fx = _load_fixture()
    gf = next(e["entity_id"] for e in fx["entities"]
              if (e["unique_id"] or "").split(":")[1:2] == ["sensor_global_face"]
              and (e["unique_id"] or "").endswith(":Jaya"))
    fx2 = _rename(fx, gf, "sensor.where_is_jaya")
    er_, dr_ = _registries(fx2)
    census, _, _ = _census({}, er_=er_, dr_=dr_, monkeypatch=monkeypatch)
    assert census._build_frigate_person_last_camera_map().get("jaya") == "sensor.where_is_jaya"
    _set_flag(monkeypatch, "FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED", False)
    assert "jaya" not in census._build_frigate_person_last_camera_map()


# ---------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------


def test_counters_reset_each_tick(monkeypatch):
    census, _, _ = _census({}, monkeypatch=monkeypatch)
    census._resolve_face_entity_id("doorbell_lite")
    census._device_derived_face_entity_id("binary_sensor.playroom_person_occupancy_2")
    assert census._face_source_registry_hits == 1
    assert census._face_source_device_derived_reads == 1
    census._reset_face_source_counters()
    assert (census._face_source_registry_hits, census._face_source_pattern_fallbacks,
            census._face_source_device_derived_reads,
            census._face_source_skipped_person_sensors) == (0, 0, 0, 0)
    assert census._face_source_device_derived_cameras == set()


def test_persons_in_house_unrecorded_attributes_exact():
    from custom_components.universal_room_automation import sensor as sensor_mod
    assert sensor_mod.URAPersonsInHouseSensor._unrecorded_attributes == frozenset({
        "face_dropped_ble_overrule_count",
        "face_source_registry_hits",
        "face_source_pattern_fallbacks",
        "face_source_pattern_fallback_stems",
        "face_source_device_derived_reads",
        "face_source_device_derived_cameras",
        "face_source_skipped_person_sensors",
        "face_source_skipped_cameras",
    })


def test_shipped_defaults():
    assert ura_const.FACE_SOURCE_REGISTRY_DISCOVERY_ENABLED is True
    assert ura_const.FACE_SOURCE_INCLUDE_DISAMBIGUATED_PERSON_SENSORS is True
    assert ura_const.FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED is False
    assert ura_const.DEFAULT_FACE_NAME_ALIASES == []


def test_census_tick_resets_face_source_counters(monkeypatch):
    """Wire-in anchor for the per-tick reset: drive the REAL
    `async_update_census`; counters seeded from a previous tick read 0 after
    a tick that does no face lookups."""
    import asyncio
    import homeassistant.helpers.dispatcher as _disp
    from custom_components.universal_room_automation.camera_census import (
        CensusZoneResult,
    )
    monkeypatch.setattr(_disp, "async_dispatcher_send", lambda *_a, **_k: None)
    census, _, _ = _census({}, monkeypatch=monkeypatch)

    def _zr(zone):
        return CensusZoneResult(
            zone=zone, identified_count=0, identified_persons=[],
            unidentified_count=0, total_persons=0, confidence="high",
            source_agreement="single_source", frigate_count=0, unifi_count=0,
        )

    async def _house(_ble, _now):
        return _zr("house")

    async def _prop(_now):
        return _zr("property")

    census._update_lock = asyncio.Lock()
    census._refresh_ble_crossing_listeners = lambda: None
    census._watchdog_stuck_cameras = lambda _now: None
    census._calculate_house_census = _house
    census._calculate_property_census = _prop
    census._is_enhanced_census_enabled = lambda: False
    census._refresh_camera_input_dark_latch = lambda: None
    census._compute_peak_age_seconds = lambda *_a: 0
    census._census_write_counter = 0
    census._last_result = None
    census._face_source_registry_hits = 7
    census._face_source_pattern_fallbacks = 3
    census._face_source_device_derived_reads = 5
    census._face_source_device_derived_cameras = {"binary_sensor.x_person_occupancy_2"}
    census._face_source_skipped_person_sensors = 2
    asyncio.run(census.async_update_census())
    assert census._face_source_registry_hits == 0
    assert census._face_source_pattern_fallbacks == 0
    assert census._face_source_device_derived_reads == 0
    assert census._face_source_device_derived_cameras == set()
    assert census._face_source_skipped_person_sensors == 0


def test_persons_in_house_sensor_publishes_face_source_attrs():
    """Wire-in anchor for the attribute publish on
    `sensor.universal_room_automation_persons_in_house`."""
    from types import SimpleNamespace
    from custom_components.universal_room_automation import sensor as sensor_mod
    from custom_components.universal_room_automation.camera_census import (
        CensusZoneResult, FullCensusResult,
    )
    t0 = datetime(2026, 11, 8, 20, 0, tzinfo=UTC)

    def _zr(zone):
        return CensusZoneResult(
            zone=zone, identified_count=0, identified_persons=[],
            unidentified_count=0, total_persons=0, confidence="high",
            source_agreement="single_source", frigate_count=0, unifi_count=0,
        )

    full = FullCensusResult(
        house=_zr("house"), property_exterior=_zr("property"), total_on_property=0,
        ble_persons=[], face_persons=[], persons_outside=0, timestamp=t0,
    )
    census = SimpleNamespace(
        last_result=full,
        get_pending_peak_info=lambda *_a: {},
        _face_lookup_missing_count=0,
        _face_dropped_ble_overrule_count=0,
        _face_source_registry_hits=11,
        _face_source_pattern_fallbacks=2,
        _face_source_pattern_fallback_stems={"zeta", "alpha"},
        _face_source_device_derived_reads=6,
        _face_source_device_derived_cameras={"binary_sensor.b_person_occupancy_2",
                                             "binary_sensor.a_person_occupancy_2"},
        _face_source_skipped_person_sensors=0,
        _face_source_skipped_cameras=set(),
    )
    hass = make_hass()
    hass.data = {ura_const.DOMAIN: {"census": census}}
    ent = object.__new__(sensor_mod.URAPersonsInHouseSensor)
    ent.hass = hass
    attrs = ent.extra_state_attributes
    assert attrs["face_source_registry_hits"] == 11
    assert attrs["face_source_pattern_fallbacks"] == 2
    assert attrs["face_source_pattern_fallback_stems"] == ["alpha", "zeta"]
    assert attrs["face_source_device_derived_reads"] == 6
    assert attrs["face_source_device_derived_cameras"] == [
        "binary_sensor.a_person_occupancy_2", "binary_sensor.b_person_occupancy_2"]
    assert attrs["face_source_skipped_person_sensors"] == 0
    assert attrs["face_source_skipped_cameras"] == []
