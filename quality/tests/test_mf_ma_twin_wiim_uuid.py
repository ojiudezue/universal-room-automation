"""MF-MA-TWIN-WIIM-UUID-1: music following picks the WiiM MA twin that plays.

Registry fixtures are COPIED from the live HA registry (read-only,
``core.device_registry`` / ``core.entity_registry``, 2026-11-15, the same rows
AUDIT_step8_b0_ours_attr_2026_11_15.md addendum names):

* ``media_player.kitchen_3`` (wiim) device identifier
  ``('wiim', 'FF98F09C822B13991AA5F49F')``, MAC ``c0:f5:35:2f:c1:22``;
  ``kitchen_5`` (music_assistant) ``('music_assistant', 'upc0f5352fc122')``
  (unavailable all week); ``kitchen_7`` ``('music_assistant',
  'wiim_uuid:FF98F09C-822B-1399-1AA5-F49FFF98F09C')`` (the one that plays).
* ``media_player.study_a_3`` ``('wiim', 'FF98F3597D200A82DAB81047')``, MAC
  ``c0:f5:35:8b:ec:04``; ``study_a_5`` ``upc0f5358bec04``; ``study_a_7``
  ``wiim_uuid:FF98F359-7D20-0A82-DAB8-1047FF98F359``.
* ``media_player.master_bathroom_3`` ``('wiim', 'FF98F3590FD4B749D97C61D6')``,
  MAC ``54:78:c9:2f:ba:8e``; ``_5`` ``up5478c92fba8e``; ``_7``
  ``wiim_uuid:FF98F359-0FD4-B749-D97C-61D6FF98F359`` (used as a bonus speaker).

The rule (audit addendum): the MA identifier starts ``wiim_uuid:`` and
``sval[10:].replace('-', '').upper()`` starts with the native device's ``wiim``
identifier.
"""
from __future__ import annotations

import pytest

from test_music_following_repair import (  # noqa: F401
    GP, _speaker_device, hass, mods, move, rig, set_area,
)

KITCHEN_W = "FF98F09C822B13991AA5F49F"
KITCHEN_7 = "wiim_uuid:FF98F09C-822B-1399-1AA5-F49FFF98F09C"
STUDY_W = "FF98F3597D200A82DAB81047"
STUDY_7 = "wiim_uuid:FF98F359-7D20-0A82-DAB8-1047FF98F359"
MBATH_W = "FF98F3590FD4B749D97C61D6"
MBATH_7 = "wiim_uuid:FF98F359-0FD4-B749-D97C-61D6FF98F359"


def _set_native_wiim_id(rig, native_eid, wiim_id):
    ent = rig.er.async_get(native_eid)
    rig.dr.async_update_device(ent.device_id, new_identifiers={("wiim", wiim_id)})


def _add_live_twin(rig, speaker, native_eid, wiim_id, twin_obj, twin_ident, dead_eid=None):
    """Give the native its live wiim identifier, add the playing _7 MA twin
    on its own MA device (as live), and make the _5 twin read unavailable."""
    _set_native_wiim_id(rig, native_eid, wiim_id)
    _speaker_device(rig, "music_assistant", twin_obj, area=None,
                    ident=("music_assistant", twin_ident))
    sp = rig.world.speakers[speaker]
    eid = f"media_player.{twin_obj}"
    sp.entities.append(eid)
    rig.world.by_entity[eid] = sp
    rig.world.features[eid] = GP
    if dead_eid:
        sp.entities.remove(dead_eid)
        rig.hass.states.async_set(dead_eid, "unavailable", {})
    rig.world.push(sp)


def _live_kitchen_and_study(rig):
    _add_live_twin(rig, "kitchen", "media_player.kitchen_3", KITCHEN_W, "kitchen_7",
                   KITCHEN_7, dead_eid="media_player.kitchen_5")
    _add_live_twin(rig, "study_a", "media_player.study_a_3", STUDY_W, "study_a_7",
                   STUDY_7, dead_eid="media_player.study_a_5")


@pytest.mark.asyncio
async def test_wiim_uuid_twin_is_a_candidate_and_live_first(rig):
    _live_kitchen_and_study(rig)
    cands = rig.mf._ma_candidates("media_player.study_a_3")
    assert cands == [("media_player.study_a_7", "wiim_uuid_match"),
                     ("media_player.study_a_5", "mac_in_ma_id")]


@pytest.mark.asyncio
async def test_wiim_uuid_rule_needs_the_native_wiim_identifier(rig):
    """A wiim_uuid MA device whose UUID does not start with this device's
    wiim identifier is not a candidate (no other rule matches it)."""
    _live_kitchen_and_study(rig)
    names = [c[0] for c in rig.mf._ma_candidates("media_player.kitchen_3")]
    assert "media_player.kitchen_7" in names
    assert "media_player.study_a_7" not in names


@pytest.mark.asyncio
async def test_wiim_room_transfer_resolves_to_the_playing_7_twin(rig):
    """The live shape: kitchen_7 plays, both _5 twins are unavailable. Before
    the fix _resolve_path saw only the dead _5 twins (ma_source_not_playing,
    native join). Now the MA path moves the queue between the _7 twins."""
    _live_kitchen_and_study(rig)
    rig.world.play("kitchen")
    set_area(rig, "Study A")
    assert await move(rig, "Kitchen", "Study A") in ("success", "success_nudged")
    tq = rig.world.services("music_assistant", "transfer_queue")
    assert [c[2] for c in tq] == [{"entity_id": ["media_player.study_a_7"],
                                   "source_player": "media_player.kitchen_7",
                                   "auto_play": True}]
    assert rig.world.state("study_a") == "playing"


@pytest.mark.asyncio
async def test_resolve_path_target_prefers_the_live_twin_across_kinds(rig):
    """Source is an MA player itself (is_ma), so no target twin has the same
    kind and the FIRST target candidate is used: it must be the live _7, not
    the unavailable _5."""
    _live_kitchen_and_study(rig)
    rig.world.play("master")
    set_area(rig, "Study A")
    await move(rig, "Master Bedroom", "Study A")
    tq = rig.world.services("music_assistant", "transfer_queue")
    assert tq and tq[0][2]["entity_id"] == ["media_player.study_a_7"]


@pytest.mark.asyncio
async def test_bonus_candidate_is_the_live_7_twin(rig):
    """A second WiiM in the target area (live master-bath registry shape)
    joins as its live _7 MA twin, never the dead _5."""
    _live_kitchen_and_study(rig)
    _speaker_device(rig, "wiim", "master_bathroom_3", area="study_a",
                    mac="54:78:c9:2f:ba:8e", ident=("wiim", MBATH_W))
    _speaker_device(rig, "music_assistant", "master_bathroom_5", area=None,
                    ident=("music_assistant", "up5478c92fba8e"))
    _speaker_device(rig, "music_assistant", "master_bathroom_7", area=None,
                    ident=("music_assistant", MBATH_7))
    rig.world.speaker("mbath", "media_player.master_bathroom_3", "media_player.master_bathroom_7")
    rig.hass.states.async_set("media_player.master_bathroom_5", "unavailable", {})
    rig.world.play("kitchen")
    set_area(rig, "Study A")
    await move(rig, "Kitchen", "Study A")
    joins = [c[2] for c in rig.world.services("media_player", "join")]
    assert {"entity_id": ["media_player.study_a_7"],
            "group_members": ["media_player.master_bathroom_7"]} in joins


@pytest.mark.asyncio
async def test_existing_mac_twin_still_matches_without_wiim_identifier(rig):
    """Rig speakers with no live wiim identifier keep the mac_in_ma_id match
    (the pre-fix behaviour)."""
    assert rig.mf._ma_candidates("media_player.kitchen_3") == [
        ("media_player.kitchen_5", "mac_in_ma_id")]
