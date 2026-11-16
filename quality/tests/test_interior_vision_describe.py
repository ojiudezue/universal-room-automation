"""VISION-INTERIOR-SIGHTINGS-1 ship 2 (plan §9.D3, §8, §8b, §9.D7): describe
on demand, plus the per-still dewarp for a 360-lens camera.

REAL hass + REAL PresenceCoordinator / PersonSightingProducer /
InteriorVisionSampler / PersonCensus over the live-house registry fixture
(``_sighting_rig`` via the ship-1 ``rig`` fixture). The model is a REAL
``llmvision.image_analyzer`` service registered on the test hass that records
every call (and, for staged stills, opens the files while the call runs).
Every request goes through the production entry
``PresenceCoordinator.request_room_description`` (the pinned delegate) or the
producer method it calls; background calls are awaited with
``async_block_till_done(wait_background_tasks=True)``, never swallowed.
Oracles are hand-written values. Stills are synthetic (never family footage).
"""
from __future__ import annotations

import io
import json
import os
from types import SimpleNamespace

import numpy as np
import pytest
import pytest_asyncio
from PIL import Image

import _iv_dewarp_fixture as DF
import _sighting_rig as R
from test_interior_vision_records import (  # noqa: F401 — fixture reuse
    FAM_F, FAM_KEY, FAM_P, MAS_F, MAS_P, _mod, _set, hass, mods, rig,
)

PROTECT_FAM_DEV = "c580a1b3bb405a01b84de5a9239a0f57"
LENS = "sensor.family_room_lens_type"
OP = "person.op"
_DEFAULT_PAYLOAD = {
    "people": 1,
    "activities": [{"what": "reading a book", "where_in_room": "on the sofa"}],
    "context": "A quiet evening room.",
    "confidence": 0.8,
    "affect": [{"mood": "calm", "energy": "low"}],
}


def _c(rig):
    return rig.m.const if hasattr(rig, "m") else _mod("const")


async def _done(rig):
    await rig.hass.async_block_till_done(wait_background_tasks=True)


class _DB:
    def __init__(self):
        self.rows = []

    async def log_memory_episode(self, **kw):
        self.rows.append(kw)
        return len(self.rows)


@pytest_asyncio.fixture
async def drig(rig, monkeypatch, tmp_path):
    hass = rig.hass
    monkeypatch.setattr(hass.config, "config_dir", str(tmp_path))
    rig.tmp = tmp_path
    rig.calls = []
    rig.responses = []
    from homeassistant.core import SupportsResponse

    async def _svc(call):
        data = dict(call.data)
        files = [f for f in str(data.get("image_file") or "").split("\n") if f]
        sizes = []
        for f in files:
            with Image.open(f) as im:
                sizes.append(im.size)
        rig.calls.append({"data": data, "files": files, "sizes": sizes})
        payload = rig.responses.pop(0) if rig.responses else _DEFAULT_PAYLOAD
        if isinstance(payload, Exception):
            raise payload
        return {"response_text": json.dumps(payload)}

    hass.services.async_register("llmvision", "image_analyzer", _svc,
                                 supports_response=SupportsResponse.ONLY)
    rig.db = _DB()
    hass.data[R.DOMAIN]["database"] = rig.db
    rig.fetches = []
    # HA's camera component needs PyTurboJPEG, which the test venv lacks (HA
    # core ships it). Scoped stand-in for the one function the sampler calls,
    # same signature as homeassistant.components.camera.async_get_image;
    # monkeypatch restores sys.modules and the package attribute.
    import sys
    import types

    import homeassistant.components as ha_components

    cam_mod = types.ModuleType("homeassistant.components.camera")
    monkeypatch.setitem(sys.modules, "homeassistant.components.camera", cam_mod)
    monkeypatch.setattr(ha_components, "camera", cam_mod, raising=False)

    buf = io.BytesIO()
    Image.fromarray(DF.synthetic_fisheye(512)).save(buf, format="JPEG", quality=92)
    rig.still_jpeg = buf.getvalue()

    async def _get_image(hass_, entity_id, timeout=10, width=None, height=None):
        rig.fetches.append(entity_id)
        return SimpleNamespace(content_type="image/jpeg", content=rig.still_jpeg)

    cam_mod.async_get_image = _get_image
    _set(rig, {FAM_F: 1, FAM_P: 1, MAS_F: 0, MAS_P: 0},
         {FAM_F: "on", FAM_P: "on", MAS_F: "off", MAS_P: "off",
          "camera.family_room": "idle", "camera.master_hallway": "idle"})
    rig.producer.interior_tick()
    rig.replies = []
    yield rig


def _ask(rig, target="family room", *, affect=False, requester=OP):
    async def _reply(text):
        rig.replies.append(text)

    return rig.presence.request_room_description(
        target, requester=requester, reason="test", include_affect=affect, reply=_reply)


def _add_lens(rig, state="360", *, platform="unifiprotect", translation_key="lens_type",
              device=PROTECT_FAM_DEV, eid=LENS):
    ent = SimpleNamespace(entity_id=eid, platform=platform, unique_id="F4E2C67BF1DF_lens_type",
                          device_id=device, disabled_by=None, domain="sensor", area_id=None,
                          config_entry_id=None, translation_key=translation_key)
    rig.er.entities[eid] = ent
    rig.hass.states.async_set(eid, state)
    rig.producer._interior_sig = None


# ------------------------------------------------------------- end to end
@pytest.mark.asyncio
async def test_describe_end_to_end_one_call_record_row_reply(drig):
    """`describe family room`: one llmvision call on the group's Frigate
    still (registry `image_entity`, no URA-held frame), privacy flags off,
    one RoomDescription, one `interior_description` row, the reply to the
    requester only, no affect in the reply."""
    assert _ask(drig) == ""
    await _done(drig)
    assert len(drig.calls) == 1
    d = drig.calls[0]["data"]
    assert d["image_entity"] == ["camera.family_room"]
    assert "image_file" not in d
    assert (d["store_in_timeline"], d["use_memory"], d["expose_images"]) == (False, False, False)
    assert d["model"] == "gpt-6-luna" and d["max_tokens"] == 4000 and d["target_width"] == 768
    rec = drig.presence.get_room_description("Family Room")
    assert rec is not None
    assert (rec.room, rec.group_key, rec.people) == ("Family Room", FAM_KEY, 1)
    assert rec.activities == (("reading a book", "on the sofa"),)
    assert (rec.requested_by, rec.views, rec.dewarped) == (OP, 1, False)
    assert len(drig.db.rows) == 1
    row = drig.db.rows[0]
    assert row["episode_type"] == "interior_description"
    assert row["attrs"]["room"] == "Family Room" and row["attrs"]["people"] == 1
    assert drig.replies == [
        "Family Room: 1 person. reading a book (on the sofa). A quiet evening room."]
    assert drig.fetches == []


@pytest.mark.asyncio
async def test_describe_affect_recorded_when_on(drig):
    """Affect ON (knob True, operator_affect requester): the schema asks for
    it, the record and its row carry it, and only then may the reply."""
    assert _ask(drig, affect=True) == ""
    await _done(drig)
    d = drig.calls[0]["data"]
    assert "affect" in json.loads(d["structure"])["properties"]
    assert "mood and energy" in d["message"]
    rec = drig.presence.get_room_description("Family Room")
    assert rec.affect == (("calm", "low"),)
    assert drig.db.rows[0]["attrs"]["affect"] == [{"mood": "calm", "energy": "low"}]
    assert drig.replies[0].endswith("Mood: calm/low.")


@pytest.mark.asyncio
async def test_describe_reply_excludes_affect(drig):
    """Affect is recorded whoever asks (knob on), but a requester without
    `operator_affect` gets a reply with no affect value (closure N7)."""
    assert _ask(drig, affect=False) == ""
    await _done(drig)
    assert "affect" in json.loads(drig.calls[0]["data"]["structure"])["properties"]
    rec = drig.presence.get_room_description("Family Room")
    assert rec.affect == (("calm", "low"),)
    assert drig.db.rows[0]["attrs"]["affect"] == [{"mood": "calm", "energy": "low"}]
    assert "calm" not in drig.replies[0] and "Mood" not in drig.replies[0]


@pytest.mark.asyncio
async def test_describe_affect_absent_when_knob_off(drig, monkeypatch):
    """INTERIOR_DESCRIBE_AFFECT_ENABLED False: not requested and not stored,
    even when the caller asked and the model volunteers it."""
    monkeypatch.setattr(_c(drig), "INTERIOR_DESCRIBE_AFFECT_ENABLED", False)
    assert _ask(drig, affect=True) == ""
    await _done(drig)
    assert "affect" not in json.loads(drig.calls[0]["data"]["structure"])["properties"]
    assert drig.presence.get_room_description("Family Room").affect == ()
    assert "Mood" not in drig.replies[0]


@pytest.mark.asyncio
async def test_describe_scrubs_resident_names(drig):
    """INV-IV-NO-NAME: a model text naming residents (display name, slug,
    first name, any case) reaches no field, row or reply; counted."""
    drig.responses.append({
        "people": 2,
        "activities": [{"what": "Ezinne is cooking", "where_in_room": "near oji_udezue"}],
        "context": "Oji Udezue and JAYA talk.", "confidence": 0.9,
        "affect": [{"mood": "happy ziri", "energy": "high"}],
    })
    assert _ask(drig, affect=True) == ""
    await _done(drig)
    rec = drig.presence.get_room_description("Family Room")
    text = json.dumps([rec.activities, rec.context, rec.affect, drig.replies,
                       drig.db.rows[0]["attrs"]]).lower()
    for name in ("ezinne", "oji", "udezue", "jaya", "ziri"):
        assert name not in text, name
    assert rec.context == "a person and a person talk."
    assert rec.names_scrubbed == 5
    diag = drig.presence.get_layer_diagnostics()["interior_vision"]["vision"]
    assert diag["counters"]["description_name_scrubbed"] == 5


def test_describe_schema_no_names_prompt():
    """The prompt forbids names and asks to count each person once across
    dewarped views; the schema is the §9.D3 one."""
    iv = _mod("interior_vision")
    p1 = iv.describe_prompt("Foyer", 1, False)
    assert "Never name anyone" in p1 and "count each person once" not in p1
    p2 = iv.describe_prompt("Foyer", 2, True)
    assert "count each person once" in p2 and "mood and energy" in p2
    s = json.loads(iv.describe_structure(False))
    assert s["required"] == ["people", "activities", "context", "confidence"]


# ----------------------------------------------------------- refusals
@pytest.mark.asyncio
async def test_describe_room_without_camera_no_call(drig):
    """A URA room with no covered camera ("Garage A") answers at once, no
    call, no fetch."""
    assert _ask(drig, "garage a") == "No camera in Garage A."
    await _done(drig)
    assert drig.calls == [] and drig.fetches == []


@pytest.mark.asyncio
async def test_describe_bedroom_camera_never_called(drig, monkeypatch):
    """INV-IV-SCOPE: the same camera in a bedroom-typed room is never a
    describe target."""
    for e in drig.hass.config_entries.async_entries(R.DOMAIN):
        if (e.data or {}).get(_c(drig).CONF_ROOM_NAME) == "Family Room":
            e.data[_c(drig).CONF_ROOM_TYPE] = "bedroom"
    drig.producer._interior_sig = None
    assert _ask(drig) == "No camera in Family Room."
    await _done(drig)
    assert drig.calls == []


@pytest.mark.asyncio
async def test_describe_unknown_target_no_call(drig):
    assert _ask(drig, "the moon") == "I don't know a room or person called 'the moon'."
    await _done(drig)
    assert drig.calls == []


@pytest.mark.asyncio
async def test_describe_switch_off_no_call(drig):
    drig.hass.data[R.DOMAIN][_c(drig).INTERIOR_VISION_SWITCH_HASS_KEY] = False
    assert _ask(drig) == "Interior vision is off."
    await _done(drig)
    assert drig.calls == [] and drig.fetches == []


@pytest.mark.asyncio
async def test_describe_kill_no_call(drig, monkeypatch):
    monkeypatch.setattr(_c(drig), "LLMVISION_ENRICHMENT_KILL", True)
    assert _ask(drig) == "Interior vision is off."
    await _done(drig)
    assert drig.calls == []


@pytest.mark.asyncio
async def test_describe_counts_against_caps(drig):
    """Daily call cap 1: the first request calls, the second is refused at
    once (the call is reserved before any await). Cost cap 0: no call."""
    c = _c(drig)
    drig.hass.data[R.DOMAIN][c.INTERIOR_VISION_CAP_HASS_KEY] = 1
    assert _ask(drig) == ""
    assert _ask(drig, "master hallway") == "Interior vision limit reached today."
    await _done(drig)
    assert len(drig.calls) == 1
    drig.hass.data[R.DOMAIN][c.INTERIOR_VISION_CAP_HASS_KEY] = 60
    drig.hass.data[R.DOMAIN][c.INTERIOR_VISION_COST_HASS_KEY] = 0.0
    assert _ask(drig) == "Interior vision limit reached today."
    await _done(drig)
    assert len(drig.calls) == 1


@pytest.mark.asyncio
async def test_describe_non_live_still_source_no_call(drig):
    """Closure N1: the Frigate (still) member held while the Protect member
    is LIVE reading 1 -> no call, skip `still_source_not_live`; the record
    still carries the Protect reading."""
    drig.views[FAM_F] = "held"
    drig.producer.interior_tick()
    rec = [r for r in drig.producer.get_room_sightings() if r.room == "Family Room"][0]
    assert rec.bodies == 1
    assert _ask(drig) == "The Family Room camera is not available right now."
    await _done(drig)
    assert drig.calls == []
    diag = drig.presence.get_layer_diagnostics()["interior_vision"]["vision"]
    assert diag["skips_by_reason"]["still_source_not_live"] == 1


@pytest.mark.asyncio
async def test_describe_unavailable_still_camera_no_call(drig):
    drig.hass.states.async_set("camera.family_room", "unavailable")
    assert _ask(drig) == "The Family Room camera is not available right now."
    await _done(drig)
    assert drig.calls == []


# --------------------------------------------------------------- person
@pytest.mark.asyncio
async def test_describe_person_ble_placement(drig):
    """`describe ezinne`: BLE ACTIVE in the family room at confidence >= the
    notification bar -> that room is described, header names her."""
    pc_cls = _mod("person_coordinator").PersonTrackingCoordinator
    import types
    drig.pc.get_person_location = types.MethodType(pc_cls.get_person_location, drig.pc)
    drig.pc.get_person_confidence = types.MethodType(pc_cls.get_person_confidence, drig.pc)
    drig.pc.tracked_persons = ["Ezinne"]
    drig.pc.data = {"Ezinne": {"location": "family_room", "confidence": 0.9,
                               "tracking_status": "active"}}
    assert _ask(drig, "Ezinne") == ""
    await _done(drig)
    assert len(drig.calls) == 1
    assert drig.replies[0].startswith("Ezinne is in Family Room. Family Room: 1 person.")
    # Below the notification bar (0.75): not placed by BLE, no face -> refused.
    drig.pc.data["Ezinne"]["confidence"] = 0.74
    assert _ask(drig, "ezinne") == "Can't place Ezinne right now."


@pytest.mark.asyncio
async def test_describe_person_face_fallback(drig):
    """BLE cannot place her; her newest fresh named interior face sighting
    can: "last seen in <room> <n> min ago"."""
    ps = drig.m.sighting if hasattr(drig, "m") else _mod("person_sighting")
    now = drig.producer._now()
    s = SimpleNamespace(slug="ezinne", sighting_source=ps.SIGHTING_SOURCE_INTERIOR,
                        room="Family Room", ts=now - 125.0)
    drig.producer._last_sightings["person.ezinne"] = s
    assert _ask(drig, "ezinne") == ""
    await _done(drig)
    assert drig.replies[0].startswith("Ezinne was last seen in Family Room 2 min ago.")
    s.ts = now - 301.0   # older than INTERIOR_ROOM_FACE_FRESH_S (300)
    assert _ask(drig, "ezinne") == "Can't place Ezinne right now."


# ---------------------------------------------------------------- dewarp
@pytest.mark.asyncio
async def test_describe_dewarps_360_lens(drig):
    """The group's Protect device carries a registry lens sensor reading
    "360": the still is fetched, cut into the configured flat views
    (768 px each), sent as staged files in ONE call with no entity, and
    every staged file is gone after the call."""
    _add_lens(drig, "360")
    assert _ask(drig) == ""
    await _done(drig)
    assert drig.fetches == ["camera.family_room"]
    d = drig.calls[0]["data"]
    assert "image_entity" not in d
    assert drig.calls[0]["sizes"] == [(768, 768), (768, 768)]
    assert "count each person once" in d["message"]
    for f in drig.calls[0]["files"]:
        assert not os.path.exists(f)
    stage = drig.tmp / "universal_room_automation" / "interior_stage"
    assert list(stage.iterdir()) == []
    rec = drig.presence.get_room_description("Family Room")
    assert (rec.views, rec.dewarped) == (2, True)


@pytest.mark.asyncio
async def test_describe_wide_lens_sends_raw_still(drig):
    """Lens "wide": no fetch, no file, the registry still entity."""
    _add_lens(drig, "wide")
    assert _ask(drig) == ""
    await _done(drig)
    assert drig.fetches == []
    assert drig.calls[0]["data"]["image_entity"] == ["camera.family_room"]
    assert drig.calls[0]["files"] == []


@pytest.mark.asyncio
async def test_lens_unavailable_keeps_last_reading(drig):
    _add_lens(drig, "360")
    assert _ask(drig) == ""
    await _done(drig)
    drig.hass.states.async_set(LENS, "unavailable")
    assert _ask(drig) == ""
    await _done(drig)
    assert len(drig.calls) == 2
    assert drig.calls[1]["files"] and "image_entity" not in drig.calls[1]["data"]


@pytest.mark.asyncio
async def test_lens_never_read_and_unavailable_sends_raw(drig):
    _add_lens(drig, "unavailable")
    assert _ask(drig) == ""
    await _done(drig)
    assert drig.fetches == [] and drig.calls[0]["files"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("platform, tkey", [("esphome", "lens_type"),
                                            ("unifiprotect", "lens_mode")])
async def test_lens_by_registry_not_name(drig, platform, tkey):
    """A sensor NAMED `..._lens_type` reading "360" that is not the Protect
    lens sensor by registry (other platform, other translation key) is never
    used: raw still."""
    _add_lens(drig, "360", platform=platform, translation_key=tkey)
    assert _ask(drig) == ""
    await _done(drig)
    assert drig.fetches == [] and drig.calls[0]["data"]["image_entity"] == ["camera.family_room"]


@pytest.mark.asyncio
async def test_dewarp_failure_falls_back_to_raw(drig):
    _add_lens(drig, "360")
    drig.still_jpeg = b"not a jpeg"
    assert _ask(drig) == ""
    await _done(drig)
    assert drig.calls[0]["data"]["image_entity"] == ["camera.family_room"]
    diag = drig.presence.get_layer_diagnostics()["interior_vision"]["vision"]
    assert diag["counters"]["dewarp_failed"] == 1


@pytest.mark.asyncio
async def test_dewarp_disabled_sends_raw(drig, monkeypatch):
    monkeypatch.setattr(_c(drig), "INTERIOR_DEWARP_ENABLED", False)
    _add_lens(drig, "360")
    assert _ask(drig) == ""
    await _done(drig)
    assert drig.fetches == [] and drig.calls[0]["files"] == []


# ------------------------------------------------- lifecycle and wires
@pytest.mark.asyncio
async def test_describe_task_cancelled_on_teardown(drig):
    """A call in flight at teardown is cancelled: no record, no reply, and
    no staged still left behind."""
    import asyncio
    gate = asyncio.Event()
    from homeassistant.core import SupportsResponse

    async def _slow(call):
        await gate.wait()
        return {"response_text": json.dumps(_DEFAULT_PAYLOAD)}

    drig.hass.services.async_register("llmvision", "image_analyzer", _slow,
                                      supports_response=SupportsResponse.ONLY)
    _add_lens(drig, "360")
    assert _ask(drig) == ""
    for _ in range(20):
        await asyncio.sleep(0)
    sampler = drig.producer._iv_sampler
    assert len(sampler.tasks) == 1
    drig.producer.async_teardown()
    await _done(drig)
    assert sampler.tasks == set()
    assert drig.presence.get_room_description("Family Room") is None
    assert drig.replies == []
    stage = drig.tmp / "universal_room_automation" / "interior_stage"
    assert not stage.exists() or list(stage.iterdir()) == []


@pytest.mark.asyncio
async def test_setup_sweep_deletes_leftover_stills(drig):
    stage = drig.tmp / "universal_room_automation" / "interior_stage"
    stage.mkdir(parents=True)
    (stage / "iv_1_0.jpg").write_bytes(b"x")
    (stage / "other.txt").write_bytes(b"keep")
    await drig.producer._iv_sampler.async_sweep_stage()
    assert sorted(p.name for p in stage.iterdir()) == ["other.txt"]
    assert drig.producer._iv_sampler.counters["frames_deleted"] == 1


@pytest.mark.asyncio
async def test_frames_left_pages_when_delete_fails(drig, monkeypatch):
    """INV-IV-NO-STORE trip-wire: a staged still that cannot be deleted
    pages `interior_frames_left` once (HIGH)."""
    iv = _mod("interior_vision")
    pages = []
    drig.producer._iv_sampler._fire = lambda *a: pages.append(a)
    monkeypatch.setattr(iv, "_remove_files", lambda paths: list(paths))
    _add_lens(drig, "360")
    assert _ask(drig) == ""
    await _done(drig)
    assert [p[0] for p in pages] == ["interior_frames_left"]
    assert pages[0][3] == "HIGH"
    for f in drig.calls[0]["files"]:   # clean up what the failure left
        os.remove(f)


@pytest.mark.asyncio
async def test_zero_calls_tripwire_pages_once(drig):
    """`interior_vision_zero_calls` (HIGH): 5 accepted-but-uncalled requests
    (still source down) in the window and no call -> one page."""
    pages = []
    drig.producer._iv_sampler._fire = lambda *a: pages.append(a)
    drig.hass.states.async_set("camera.family_room", "unavailable")
    for _ in range(4):
        _ask(drig)
    assert pages == []
    _ask(drig)
    _ask(drig)
    assert [p[0] for p in pages] == ["interior_vision_zero_calls"]
    assert pages[0][3] == "HIGH"


@pytest.mark.asyncio
async def test_errors_tripwire_pages(drig):
    """`interior_vision_errors` (MEDIUM): 2 of 4 calls fail (rate 0.5 >
    0.25) -> one page."""
    pages = []
    drig.producer._iv_sampler._fire = lambda *a: pages.append(a)
    drig.responses += [_DEFAULT_PAYLOAD, RuntimeError("boom"), _DEFAULT_PAYLOAD,
                       RuntimeError("boom")]
    for _ in range(4):
        _ask(drig)
        await _done(drig)
    assert [p[0] for p in pages] == ["interior_vision_errors"]
    assert pages[0][3] == "MEDIUM"
    assert drig.replies[1] == "Couldn't describe Family Room right now."


@pytest.mark.asyncio
async def test_describe_never_feeds_census(drig):
    """INV-SEEN-NOT-COUNTED: descriptions change no census input. The
    census result object, its counts and the awareness view are identical
    before and after a description of a room with people."""
    census = drig.census
    before = census.last_result
    view_before = drig.presence.get_house_census("awareness")
    assert _ask(drig) == ""
    await _done(drig)
    assert drig.presence.get_room_description("Family Room").people == 1
    assert census.last_result is before
    assert drig.presence.get_house_census("awareness") == view_before


@pytest.mark.asyncio
async def test_setup_interior_sweeps_stage(drig):
    """Wire-in anchor: the producer's own setup (`_setup_interior`, run by
    `async_setup`) schedules the stage sweep, so a still left by a restart
    mid-call is gone once setup's tasks finish."""
    stage = drig.tmp / "universal_room_automation" / "interior_stage"
    stage.mkdir(parents=True)
    (stage / "iv_9_0.jpg").write_bytes(b"x")
    drig.producer._teardown_interior()
    drig.producer._setup_interior()
    await _done(drig)
    assert list(stage.iterdir()) == []
    drig.producer._teardown_interior()


@pytest.mark.asyncio
async def test_zero_calls_silent_when_calls_happen(drig):
    """Six requests that all reach the model never page
    `interior_vision_zero_calls` (the wire needs zero calls)."""
    pages = []
    drig.producer._iv_sampler._fire = lambda *a: pages.append(a)
    for _ in range(6):
        assert _ask(drig) == ""
        await _done(drig)
    assert len(drig.calls) == 6 and pages == []
