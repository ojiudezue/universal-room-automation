"""VISION-INTERIOR-SIGHTINGS-1 ship 2 fix pass (reviews A, B, C of 0bc751d8).

Review C's HIGH gaps H1-H10 and MEDIUMs, and the A / B production fixes
(restart-durable budget, cancel-safe staging, torn-down refusal, durable row
without affect). Same REAL rig as ``test_interior_vision_describe.py`` (its
``drig`` fixture): real hass, real producer / sampler / census over the
live-house registry fixture, a real llmvision service registered on the
test hass. Oracles are literals; nothing here swallows an exception.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from types import SimpleNamespace

import pytest

import _sighting_rig as R
from test_interior_vision_describe import (  # noqa: F401 — fixture reuse
    LENS, OP, PROTECT_FAM_DEV, _DEFAULT_PAYLOAD, _add_lens, _ask, _c, _done, drig,
)
from test_interior_vision_records import FAM_F, MAS_F, _mod, hass, mods, rig  # noqa: F401


def _iv():
    return _mod("interior_vision")


def _sampler(rig):
    return rig.producer._iv_sampler


class _Clock:
    def __init__(self, t):
        self.t = float(t)

    def __call__(self):
        return self.t


def _respond_with(rig, result):
    """Replace the llmvision service: return ``result`` verbatim."""
    from homeassistant.core import SupportsResponse

    async def _svc(call):
        rig.calls.append({"data": dict(call.data), "files": [], "sizes": []})
        return result

    rig.hass.services.async_register("llmvision", "image_analyzer", _svc,
                                     supports_response=SupportsResponse.ONLY)


# ------------------------------------------------------------- H1 parse
def test_response_payload_shapes():
    """llmvision answers `response_format: json` with `structured_response`
    (a dict, or a JSON string); a REST call wraps it in `service_response`.
    `structured_response` wins over `response_text`."""
    iv = _iv()
    p = {"people": 2}
    assert iv.response_payload({"structured_response": p}) == p
    assert iv.response_payload({"structured_response": json.dumps(p)}) == p
    assert iv.response_payload({"service_response": {"structured_response": p}}) == p
    assert iv.response_payload({"service_response": {"response_text": json.dumps(p)}}) == p
    assert iv.response_payload({"structured_response": {"people": 3},
                                "response_text": json.dumps(p)}) == {"people": 3}
    assert iv.response_payload({"response_text": "not json"}) is None
    assert iv.response_payload("nope") is None


@pytest.mark.asyncio
async def test_structured_response_end_to_end(drig):
    _respond_with(drig, {"structured_response": dict(_DEFAULT_PAYLOAD, people=3)})
    assert _ask(drig) == ""
    await _done(drig)
    assert drig.presence.get_room_description("Family Room").people == 3


@pytest.mark.asyncio
async def test_unparsed_response_no_record_but_row_and_reply(drig):
    _respond_with(drig, {"response_text": "I cannot help with that."})
    assert _ask(drig) == ""
    await _done(drig)
    assert drig.presence.get_room_description("Family Room") is None
    assert drig.replies == ["Couldn't describe Family Room right now."]
    assert [r["attrs"]["outcome"] for r in drig.db.rows] == ["unparsed"]


# ---------------------------------------------------------- H2 / H3
@pytest.mark.asyncio
async def test_day_roll_resets_call_and_cost_counters(drig):
    """H2: cap 1 used, refused; after local midnight the counters reset and
    a call goes again."""
    # Two days on is a new local day whatever time zone a donor test left
    # on the dt module (suite-order robustness).
    s = _sampler(drig)
    clock = _Clock(time.time())
    s._now = clock
    drig.hass.data[R.DOMAIN][_c(drig).INTERIOR_VISION_CAP_HASS_KEY] = 1
    assert _ask(drig) == ""
    await _done(drig)
    assert (s.calls_today, round(s.cost_today, 4)) == (1, 0.0003)
    assert _ask(drig) == "Interior vision limit reached today."
    clock.t += 2 * 86400.0
    assert _ask(drig) == ""
    await _done(drig)
    assert len(drig.calls) == 2 and s.calls_today == 1


@pytest.mark.asyncio
async def test_cost_cap_refuses_before_call_cap(drig):
    """H3: cost accrues per call (0.0003 each); a cost cap of 0.0009 allows
    3 calls and refuses the 4th although the call cap is 60."""
    drig.hass.data[R.DOMAIN][_c(drig).INTERIOR_VISION_COST_HASS_KEY] = 0.0009
    for _ in range(3):
        assert _ask(drig) == ""
        await _done(drig)
    assert _ask(drig) == "Interior vision limit reached today."
    assert len(drig.calls) == 3
    assert drig.presence.get_layer_diagnostics()["interior_vision"]["vision"][
        "skips_by_reason"]["cost_cap_reached"] == 1


# ------------------------------------------- A-L2 / B-L2 rehydrate
@pytest.mark.asyncio
async def test_rehydrate_sets_today_counters_from_rows(drig):
    """A restart counts today's `interior_description` rows (every call
    outcome) over today's local-day bounds: 5 rows -> calls 5, cost
    5 x 0.0003; with cap 5 the next request is refused."""
    s = _sampler(drig)
    s.calls_today, s.cost_today = 0, 0.0
    drig.db.count_result = (5, True)
    await s.async_rehydrate(retry=False)
    assert (s.calls_today, round(s.cost_today, 4), s.rehydrate_state) == (5, 0.0015, "ok")
    etype, start, end, outcomes = drig.db.count_calls[-1]
    assert etype == "interior_description"
    assert set(outcomes) == {"ok", "error", "timeout", "unparsed"}
    assert start < end
    drig.hass.data[R.DOMAIN][_c(drig).INTERIOR_VISION_CAP_HASS_KEY] = 5
    assert _ask(drig) == "Interior vision limit reached today."
    assert drig.calls == []


@pytest.mark.asyncio
async def test_rehydrate_failure_holds_until_midnight_and_pages(drig):
    s = _sampler(drig)
    pages = []
    s._fire = lambda *a: pages.append(a)
    drig.db.count_result = RuntimeError("db down")
    await s.async_rehydrate(retry=False)
    assert s.rehydrate_state == "failed" and s.cap_hold is True
    assert [p[0] for p in pages] == ["interior_vision_cap_rehydrate_failed"]
    assert pages[0][3] == "LOW"
    assert _ask(drig) == "Interior vision is starting up; try again in a minute."
    s._now = _Clock(time.time() + 2 * 86400.0)
    assert _ask(drig) == ""
    await _done(drig)
    assert len(drig.calls) == 1


@pytest.mark.asyncio
async def test_hold_until_rehydrated(drig):
    """Until today's rows are counted, describe refuses (no call)."""
    s = _sampler(drig)
    s.cap_hold = True
    assert _ask(drig) == "Interior vision is starting up; try again in a minute."
    await _done(drig)
    assert drig.calls == []


@pytest.mark.asyncio
async def test_every_outcome_writes_a_counted_row(drig):
    """B-L2: an error call writes a row too (else a restart under-counts),
    with `ended_at` set; the description row carries no affect (B-L3)."""
    drig.responses += [RuntimeError("boom"), _DEFAULT_PAYLOAD]
    for _ in range(2):
        _ask(drig)
        await _done(drig)
    assert [r["attrs"]["outcome"] for r in drig.db.rows] == ["error", "ok"]
    for r in drig.db.rows:
        assert r["episode_type"] == "interior_description" and r["ended_at"]
        assert r["window_dedup"] is False and r["dedup_source_ref"] is False
        assert r["source_ref"].startswith("idesc:") and "affect" not in r["attrs"]
    assert drig.db.rows[1]["attrs"]["people"] == 1


# ------------------------------------------------------------ H4 person
def _two_people(drig, monkeypatch):
    import types
    pc_cls = _mod("person_coordinator").PersonTrackingCoordinator
    drig.pc.get_person_location = types.MethodType(pc_cls.get_person_location, drig.pc)
    drig.pc.get_person_confidence = types.MethodType(pc_cls.get_person_confidence, drig.pc)
    drig.pc.tracked_persons = ["Ezinne", "Jaya"]
    drig.pc.data = {
        "Ezinne": {"location": "family_room", "confidence": 0.9, "tracking_status": "active"},
        "Jaya": {"location": "master_hallway", "confidence": 0.9, "tracking_status": "active"},
    }


@pytest.mark.asyncio
async def test_describe_person_picks_that_persons_room(drig, monkeypatch):
    """H4: two tracked people in two rooms; `describe jaya` describes
    Jaya's room (Master Hallway), not the first tracked person's."""
    _two_people(drig, monkeypatch)
    assert _ask(drig, "jaya") == ""
    await _done(drig)
    assert drig.calls[0]["data"]["image_entity"] == ["camera.master_hallway"]
    assert drig.replies[0].startswith("Jaya is in Master Hallway.")


@pytest.mark.asyncio
async def test_describe_person_name_forms_and_ambiguous_first_name(drig, monkeypatch):
    """Display name and space forms match; a first name shared by two
    tracked people refuses (never guesses one)."""
    monkeypatch.setattr(drig.census, "tracked_person_slugs",
                        lambda: ["ezinne_a", "ezinne_b", "jaya"])
    assert _ask(drig, "ezinne") == ("I don't know a room or person called 'ezinne'. "
                                     "Rooms with a camera: Family Room, Master Hallway.")
    assert _ask(drig, "Ezinne A") == "Can't place Ezinne A right now."
    assert _ask(drig, "ezinne_b") == "Can't place Ezinne B right now."
    monkeypatch.setattr(drig.census, "tracked_person_slugs", lambda: ["ezinne_a", "jaya"])
    assert _ask(drig, "ezinne") == "Can't place Ezinne A right now."
    assert drig.calls == []


@pytest.mark.asyncio
async def test_face_fallback_newest_same_person_interior_only(drig):
    """The face fallback reads only this person's INTERIOR sightings and
    takes the newest: another person's newer sighting and a door camera
    sighting are ignored."""
    ps = _mod("person_sighting")
    now = drig.producer._now()

    def sig(slug, room, age, source=ps.SIGHTING_SOURCE_INTERIOR):
        return SimpleNamespace(slug=slug, sighting_source=source, room=room, ts=now - age,
                               census_would_veto=False, confidence=0.9)

    drig.producer._last_sightings.update({
        "a": sig("ezinne", "Master Hallway", 200.0),
        "b": sig("ezinne", "Family Room", 100.0),
        "c": sig("jaya", "Master Hallway", 10.0),
        "d": sig("ezinne", "Master Hallway", 5.0, source=ps.SIGHTING_SOURCE_EGRESS_ENTRY),
    })
    assert _ask(drig, "ezinne") == ""
    await _done(drig)
    assert drig.replies[0].startswith("Ezinne was last seen in Family Room 1 min ago.")


# ------------------------------------------------------------- H5 scrub
@pytest.mark.asyncio
async def test_producer_scrubs_first_and_short_names_not_substrings(drig, monkeypatch):
    """INV-IV-NO-NAME built by the PRODUCER's name list: a first name alone
    (Oji), a last name alone (Udezue), a 2-letter first name (Al, review
    A-L1), the slug, and the affect energy field are scrubbed; "Hannah"
    keeps its letters although "anna" is tracked."""
    monkeypatch.setattr(drig.census, "tracked_person_slugs",
                        lambda: ["oji_udezue", "al_smith", "anna"])
    drig.responses.append({
        "people": 2, "confidence": 0.9,
        "activities": [{"what": "Oji waves; Udezue nods", "where_in_room": "Al is near"}],
        "context": "Hannah sings to anna and al_smith.",
        "affect": [{"mood": "calm", "energy": "Oji is tired"}],
    })
    assert _ask(drig) == ""
    await _done(drig)
    rec = drig.presence.get_room_description("Family Room")
    assert rec.activities == (("a person waves; a person nods", "a person is near"),)
    assert rec.context == "Hannah sings to a person and a person."
    assert rec.affect == (("calm", "a person is tired"),)


# --------------------------------------------------------- H7 / H8 wiring
@pytest.mark.asyncio
async def test_producer_wires_its_clock_into_the_sampler(mods, hass):  # noqa: F811
    """H7: the sampler's clock is the producer's `now_fn`."""
    ps = mods.sighting
    prod = ps.PersonSightingProducer(hass, SimpleNamespace(), now_fn=lambda: 1234.5)
    assert prod._iv_sampler._now() == 1234.5


@pytest.mark.asyncio
async def test_sampler_trip_wire_reaches_nm_through_the_producer(drig, monkeypatch):
    """H7: a sampler page goes out through the producer's `fire_stuck_signal`
    path (not a no-op)."""
    ps = _mod("person_sighting")
    sent = []

    async def _fake(hass_, **kw):
        sent.append(kw)

    monkeypatch.setattr(ps, "fire_stuck_signal", _fake)
    drig.hass.states.async_set("camera.family_room", "unavailable")
    for _ in range(5):
        _ask(drig)
    await drig.hass.async_block_till_done()
    assert [k["kind"] for k in sent] == ["interior_vision_zero_calls"]
    assert sent[0]["severity"] == "HIGH"


@pytest.mark.asyncio
async def test_provider_id_reaches_the_service_call(drig, monkeypatch):
    """H8: the install's llmvision entry (crossing-vision provider rule)
    is sent as `provider`."""
    pid = _c(drig).CROSSING_VISION_PROVIDER_ID
    orig = drig.hass.config_entries.async_get_entry

    def _get(entry_id):
        if entry_id == pid:
            return SimpleNamespace(domain="llmvision", entry_id=pid)
        return orig(entry_id)

    monkeypatch.setattr(drig.hass.config_entries, "async_get_entry", _get)
    assert _ask(drig) == ""
    await _done(drig)
    assert drig.calls[0]["data"]["provider"] == pid


@pytest.mark.asyncio
async def test_call_arguments_are_the_knobs(drig, monkeypatch):
    """MEDIUM pass-through: model, max tokens, width, the call timeout and
    the json response format reach the adapter / service."""
    pe = _mod("perimeter_enrichment")
    seen = {}
    real = pe.analyze_crossing_images

    async def _spy(hass_, **kw):
        seen.update(kw)
        return await real(hass_, **kw)

    monkeypatch.setattr(pe, "analyze_crossing_images", _spy)
    monkeypatch.setattr(_c(drig), "INTERIOR_VISION_CALL_TIMEOUT_S", 17)
    assert _ask(drig) == ""
    await _done(drig)
    assert seen["timeout_s"] == 17.0 and seen["expose_images"] is False
    d = drig.calls[0]["data"]
    assert (d["model"], d["max_tokens"], d["target_width"], d["response_format"]) == (
        "gpt-6-luna", 4000, 768, "json")


@pytest.mark.asyncio
async def test_dewarp_arguments_are_the_knobs(drig, monkeypatch):
    """MEDIUM pass-through: still timeout, output size and per-device views
    reach the fetch and the remap."""
    import homeassistant.components as ha_components

    seen = {}
    cam = ha_components.camera
    real = cam.async_get_image

    async def _spy(hass_, eid, timeout=10, **kw):
        seen["timeout"] = timeout
        return await real(hass_, eid, timeout=timeout, **kw)

    cam.async_get_image = _spy
    c = _c(drig)
    monkeypatch.setattr(c, "INTERIOR_VISION_STILL_TIMEOUT_S", 7)
    monkeypatch.setattr(c, "INTERIOR_DEWARP_OUT_PX", 64)
    monkeypatch.setattr(c, "INTERIOR_DEWARP_VIEWS_BY_DEVICE",
                        {PROTECT_FAM_DEV: ((0.0, 0.0, 0.0),)})
    _add_lens(drig, "360")
    assert _ask(drig) == ""
    await _done(drig)
    assert seen["timeout"] == 7
    assert drig.calls[0]["sizes"] == [(64, 64)]
    assert all(os.path.basename(f).startswith("iv_") for f in drig.calls[0]["files"])


# ------------------------------------------------------------- H9 lens
@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["other_device", "disabled", "binary_sensor"])
async def test_lens_sensor_must_be_an_enabled_sensor_on_the_group(drig, kind):
    """H9: a 360 lens sensor of ANOTHER camera, a disabled one, or a
    non-sensor entity never drives a dewarp."""
    if kind == "other_device":
        _add_lens(drig, "360", device="ffffffffffffffffffffffffffffffff")
    else:
        _add_lens(drig, "360")
        ent = drig.er.entities[LENS]
        if kind == "disabled":
            ent.disabled_by = "user"
        else:
            ent.domain = "binary_sensor"
    assert _ask(drig) == ""
    await _done(drig)
    assert drig.fetches == [] and drig.calls[0]["files"] == []


@pytest.mark.asyncio
async def test_lens_by_unique_id_when_no_translation_key(drig):
    """H9: an older registry entry without a translation key is matched by
    the integration's own `<mac>_lens_type` unique id."""
    _add_lens(drig, "360", translation_key=None)
    assert _ask(drig) == ""
    await _done(drig)
    assert drig.fetches == ["camera.family_room"] and drig.calls[0]["files"]


# ------------------------------------------------------------ H10 lifecycle
@pytest.mark.asyncio
async def test_describe_after_teardown_refuses_and_resetup_works(drig):
    """H10 / B-L5: after teardown a request is refused at once (never ""),
    no call, no task; a re-setup revives the sampler."""
    s = _sampler(drig)
    drig.producer._teardown_interior()
    assert _ask(drig) == "Interior vision is not running."
    await _done(drig)
    assert drig.calls == [] and s.tasks == set()
    drig.producer._setup_interior()
    for task in list(s.tasks):
        task.cancel()
    await drig.hass.async_block_till_done()
    s.cap_hold = False
    assert _ask(drig) == ""
    await _done(drig)
    assert len(drig.calls) == 1 and s.tasks == set()
    drig.producer._teardown_interior()


@pytest.mark.asyncio
async def test_setup_tasks_are_tracked_and_cancelled(drig):
    """H10: the setup rehydrate is a tracked sampler task (cancelled by
    teardown); the sweep is a tracked producer task."""
    s = _sampler(drig)
    drig.db.count_result = RuntimeError("slow")   # forces the retry sleep
    drig.producer._teardown_interior()
    before = len(drig.db.count_calls)
    drig.producer._setup_interior()
    await asyncio.sleep(0)
    assert len(drig.db.count_calls) == before + 1   # the rehydrate ran
    pending = [t for t in s.tasks if not t.done()]
    assert len(pending) == 1
    sweeps = list(drig.producer._interior_tasks)
    drig.producer._teardown_interior()
    await drig.hass.async_block_till_done()
    assert pending[0].cancelled() and s.tasks == set()
    assert all(t.done() for t in sweeps)


# ------------------------------------------- A-L3 / B-L1 cancel during write
@pytest.mark.asyncio
async def test_cancel_during_stage_write_leaves_no_still(drig, monkeypatch):
    """Teardown while the dewarped views are being written in the executor:
    the write finishes, then every file of that call is deleted."""
    iv = _iv()
    real = iv._write_stage
    started = []

    def _slow(folder, prefix, jpegs):
        started.append(prefix)
        time.sleep(0.3)
        return real(folder, prefix, jpegs)

    monkeypatch.setattr(iv, "_write_stage", _slow)
    _add_lens(drig, "360")
    assert _ask(drig) == ""
    for _ in range(200):
        if started:
            break
        await asyncio.sleep(0.01)
    assert started
    drig.producer._teardown_interior()
    await _done(drig)
    await asyncio.sleep(0.5)
    await _done(drig)
    stage = drig.tmp / "universal_room_automation" / "interior_stage"
    assert not stage.exists() or list(stage.iterdir()) == []
    assert drig.calls == []


@pytest.mark.asyncio
async def test_two_dewarped_calls_use_distinct_files(drig):
    """A-L5: each call stages under its own unique prefix."""
    _add_lens(drig, "360")
    assert _ask(drig) == ""
    assert _ask(drig, "family room") == ""
    await _done(drig)
    a, b = drig.calls[0]["files"], drig.calls[1]["files"]
    assert a and b and not set(a) & set(b)


# ------------------------------------------------------- producer MEDIUMs
@pytest.mark.asyncio
async def test_get_room_description_max_age(drig):
    assert _ask(drig) == ""
    await _done(drig)
    rec = drig.producer.get_room_description("Family Room")
    assert rec.ts > 0
    drig.producer._now = lambda: rec.ts + 301.0
    assert drig.presence.get_room_description("Family Room", 300) is None
    assert drig.presence.get_room_description("Family Room", 302) is rec
    assert drig.presence.get_room_description("Family Room") is rec


@pytest.mark.asyncio
async def test_watchdog_discounted_still_member_is_not_live(drig, monkeypatch):
    """A census watchdog-discounted (stuck) Frigate member is not LIVE: no
    still call."""
    real = drig.census.area_evidence

    def _ev():
        ev = dict(real())
        ev["discounted"] = [FAM_F]
        return ev

    monkeypatch.setattr(drig.census, "area_evidence", _ev)
    assert _ask(drig) == "The Family Room camera is not available right now."


@pytest.mark.asyncio
async def test_no_row_after_teardown(drig):
    rec = SimpleNamespace(ts=1.0, people=1, activities=(), context="", confidence=None,
                          names_scrubbed=0)
    drig.producer._teardown_interior()
    drig.producer._log_description_row(rec, {"outcome": "ok", "group_key": "g"})
    await drig.hass.async_block_till_done()
    assert drig.db.rows == []


# ------------------------------------------------------- trip-wire MEDIUMs
@pytest.mark.asyncio
async def test_zero_calls_guards(drig, monkeypatch):
    """No page with the switch off or a cap at 0, none for requests older
    than the window, MIN 0 = off; a call re-arms the latch."""
    s = _sampler(drig)
    pages = []
    s._fire = lambda *a: pages.append(a[0])
    drig.hass.states.async_set("camera.family_room", "unavailable")
    data = drig.hass.data[R.DOMAIN]
    c = _c(drig)
    data[c.INTERIOR_VISION_SWITCH_HASS_KEY] = False
    for _ in range(6):
        _ask(drig)
    data[c.INTERIOR_VISION_SWITCH_HASS_KEY] = True
    data[c.INTERIOR_VISION_CAP_HASS_KEY] = 0
    s.check_tripwires(s._now())
    data[c.INTERIOR_VISION_CAP_HASS_KEY] = 60
    clock = _Clock(s._now() + 25 * 3600.0)
    s._now = clock
    s.check_tripwires(clock.t)
    assert pages == []
    monkeypatch.setattr(c, "INTERIOR_VISION_ZERO_MIN_TRIGGERS", 0)
    for _ in range(6):
        _ask(drig)
    assert pages == []
    monkeypatch.setattr(c, "INTERIOR_VISION_ZERO_MIN_TRIGGERS", 5)
    _ask(drig)
    assert pages == ["interior_vision_zero_calls"]


@pytest.mark.asyncio
async def test_errors_guards(drig, monkeypatch):
    """Fewer than 4 calls never page; rate max above 1 = off."""
    s = _sampler(drig)
    pages = []
    s._fire = lambda *a: pages.append(a[0])
    drig.responses += [RuntimeError("x")] * 3
    for _ in range(3):
        _ask(drig)
        await _done(drig)
    assert pages == []
    monkeypatch.setattr(_c(drig), "INTERIOR_VISION_ERROR_RATE_MAX", 2.0)
    drig.responses += [RuntimeError("x")]
    _ask(drig)
    await _done(drig)
    assert pages == []


@pytest.mark.asyncio
async def test_frames_left_knob_off_and_latch(drig, monkeypatch):
    iv = _iv()
    pages = []
    _sampler(drig)._fire = lambda *a: pages.append(a[0])
    monkeypatch.setattr(iv, "_remove_files", lambda paths: list(paths))
    _add_lens(drig, "360")
    monkeypatch.setattr(_c(drig), "INTERIOR_FRAMES_LEFT_CHECK_ENABLED", False)
    _ask(drig)
    await _done(drig)
    assert pages == []
    monkeypatch.setattr(_c(drig), "INTERIOR_FRAMES_LEFT_CHECK_ENABLED", True)
    for _ in range(2):
        _ask(drig)
        await _done(drig)
    assert pages == ["interior_frames_left"]
    stage = drig.tmp / "universal_room_automation" / "interior_stage"
    for f in stage.iterdir():
        os.remove(f)


def test_remove_helpers(tmp_path):
    iv = _iv()
    a = tmp_path / "iv_x_0.jpg"
    a.write_bytes(b"1")
    (tmp_path / "keep.jpg").write_bytes(b"1")
    assert iv._remove_files([str(a), str(tmp_path / "missing.jpg")]) == []
    (tmp_path / "iv_y_0.jpg").write_bytes(b"1")
    (tmp_path / "iv_y_1.jpg").write_bytes(b"1")
    (tmp_path / "iv_yz_0.jpg").write_bytes(b"1")
    assert iv._remove_prefix(str(tmp_path), "iv_y") == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["iv_yz_0.jpg", "keep.jpg"]
    assert iv._remove_prefix(str(tmp_path / "nope"), "iv_y") == []


# ---------------------------------------------------------------- LOWs
def test_parse_clamps():
    iv = _iv()
    f, _ = iv.parse_description({"people": -2, "activities": [{"what": "", "where_in_room": "x"},
                                                              {"what": "sits", "where_in_room": ""}],
                                 "context": "c", "confidence": 1.7}, [], False)
    assert (f["people"], f["activities"], f["confidence"], f["affect"]) == (0, (("sits", ""),), 1.0, ())
    f, _ = iv.parse_description({"people": True, "context": "c"}, [], False)
    assert f["people"] is None
    assert iv.parse_description({"foo": 1}, [], False) == (None, 0)
    s = json.loads(iv.describe_structure(True))
    assert s["required"][-1] == "affect"
    assert s["properties"]["confidence"] == {"type": "number", "minimum": 0, "maximum": 1}
    assert "activities and affect are empty" in iv.describe_prompt("X", 1, True)
