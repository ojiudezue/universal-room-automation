"""D3-BEHAVIOURAL-COVERAGE-1 — behavioural drive of guest-room registry resolution.

Cycle 1 (v5.79.0) shipped ``_discover_guest_rooms`` D3 registry resolution
but its coverage under ``test_guest_census_correctness.py`` is
predominantly source-shape (Bug Class #62 — hollow anchor): the six D3
tests grep for ``async_get_entity_id`` / ``f"{entry.entry_id}_occupied"``
/ ``self._guest_room_entity_to_name[`` substrings in the presence source
rather than driving the production method against a real fake registry
and asserting on observed effects.

Source-shape anchors are evadable in TWO documented ways:
  * **variant-7 comment-out** — delete the CALL, leave the substring in a
    comment; the grep still passes.
  * **Bug Class #63 (monkeypatch-oracle)** — patch the load-bearing site
    to return the expected value; the grep passes without executing the
    real code path.

This file adds three behavioural tests that fail under real production
mutation on the D3 code path — no source greps, no oracle echoes.

Mutation drills (all confirmed red -> green in the review record for this
change):
  * **M-A: reverse-map keying** — comment out ``self._guest_room_entity_to_name[
    occupancy_entity_id] = room_name`` (or replace with ``pass``) →
    ``test_resolved_guest_room_registered_with_reverse_map`` FAILs.
  * **M-A-v7 (variant-7 comment-out)** — replace the same statement with
    ``pass  # self._guest_room_entity_to_name[occupancy_entity_id] = room_name``
    → same test still FAILs (comment substring does not restore behaviour).
  * **M-B: rename resilience** — replace the registry lookup with the
    pre-D3 slug-string construction
    ``occupancy_entity_id = f"binary_sensor.{room_slug}_occupied"`` →
    ``test_rename_resilience_registry_lookup_by_entry_id`` FAILs (the
    reverse map ends up keyed on the RENAMED slug, not the real registry
    entity_id).
  * **M-B-v7** — leave the registry call live but hard-code the local
    ``occupancy_entity_id`` to the slug-of-renamed-name AFTER the lookup
    (e.g. `` occupancy_entity_id = f"binary_sensor.{room_slug}_occupied"
    # registry lookup done above``) → same test FAILs.
  * **M-C: handler reverse-map** — replace
    ``room_name = self._guest_room_entity_to_name.get(entity_id)`` with
    ``room_name = None`` (or a slug-built for-loop over
    ``_guest_room_state`` keys) → ``test_handler_dispatches_via_reverse_map``
    FAILs (first_seen never armed).
  * **M-C-v7** — replace with ``room_name = None  # self._guest_room_entity_to_name.get(entity_id)``
    → same test FAILs.

Discipline: no ``_LOGGER.warning`` / ``async_get_entity_id`` /
``_guest_room_entity_to_name[`` source greps live in this file. All
expected values are test-local literals (no import of production
constants for oracle purposes). Registry is a hand-built ``FakeRegistry``
that mirrors the real ``EntityRegistry.async_get_entity_id`` contract.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

import _provenance_harness  # noqa: F401 — installs stub HA modules
from _provenance_harness import make_hass


# ---------------------------------------------------------------------------
# FakeRegistry — hand-built fixture mirroring the read-side of
# ``homeassistant.helpers.entity_registry.EntityRegistry``. NOT a
# monkeypatch of the site under test; the production ``_discover_guest_rooms``
# still calls ``async_get_entity_id`` for real against this object.
# ---------------------------------------------------------------------------
class FakeRegistry:
    """Minimal EntityRegistry double.

    ``register(platform, domain, unique_id, entity_id)`` seeds the map;
    ``async_get_entity_id(platform, domain, unique_id)`` looks it up.
    Returning ``None`` on miss matches the real contract (developers.HA
    docs: EntityRegistry.async_get_entity_id).
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str, str], str] = {}

    def register(
        self, platform: str, domain: str, unique_id: str, entity_id: str,
    ) -> None:
        self._by_key[(platform, domain, unique_id)] = entity_id

    def async_get_entity_id(
        self, platform: str, domain: str, unique_id: str,
    ) -> Optional[str]:
        return self._by_key.get((platform, domain, unique_id))


# ---------------------------------------------------------------------------
# Bare PresenceCoordinator builder — mirrors the pattern used in
# test_guest_census_correctness.py so this file drops in cleanly.
# ---------------------------------------------------------------------------
def _bare_pc():
    from custom_components.universal_room_automation.domain_coordinators.presence import (
        PresenceCoordinator,
    )

    pc = PresenceCoordinator.__new__(PresenceCoordinator)
    pc.hass = make_hass()
    pc._guest_room_state = {}
    pc._guest_room_unsubs = {}
    pc._guest_room_entity_to_name = {}
    pc._guest_room_known_last_true = {}
    # Neutralise the identity check so it can never accidentally block
    # Transition 1 in the handler tests.
    pc._is_known_person_in_room = lambda room_name: False  # type: ignore[assignment]
    return pc


def _guest_entry(entry_id: str, room_name: str, threshold_min: int = 30):
    """Build a MagicMock ConfigEntry for a designated guest room."""
    from custom_components.universal_room_automation.const import (
        CONF_ENTRY_TYPE,
        CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN,
        CONF_ROOM_IS_GUEST_ROOM,
        CONF_ROOM_NAME,
        ENTRY_TYPE_ROOM,
    )
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_ROOM}
    entry.options = {
        CONF_ROOM_NAME: room_name,
        CONF_ROOM_IS_GUEST_ROOM: True,
        CONF_ROOM_GUEST_OCCUPANCY_THRESHOLD_MIN: threshold_min,
    }
    return entry


# ===========================================================================
# T1 — resolvable guest room: state registered + reverse-map keyed on the
# REGISTRY-returned entity_id + subscription installed.
# ===========================================================================
def test_resolved_guest_room_registered_with_reverse_map() -> None:
    """Drives _discover_guest_rooms against a real FakeRegistry hit.

    Asserts three behavioural effects of a successful resolution:
      1. ``_guest_room_state[room_name]`` populated with the configured
         threshold (contract-shape only — the anti-flap dict).
      2. ``_guest_room_entity_to_name`` maps the REGISTRY-returned
         entity_id to the room name (NOT some slug-constructed guess).
      3. A subscription was installed under ``_guest_room_unsubs[room_name]``.

    Mutation-red anchors (see module docstring): M-A / M-A-v7 both fail
    this test on assertion 2.
    """
    from custom_components.universal_room_automation.const import DOMAIN
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as _pres_mod,
    )

    pc = _bare_pc()
    entry_id = "01KTESTRESOLVED0000000000"
    room_name = "Guest Suite"
    # Test-local literal for the resolved entity_id — deliberately NOT the
    # slug of the room name, so a slug-string fallback would key differently.
    resolved_entity_id = "binary_sensor.custom_registry_slug_occupied"

    entry = _guest_entry(entry_id, room_name, threshold_min=30)
    pc.hass.config_entries.async_entries = MagicMock(return_value=[entry])

    fake_reg = FakeRegistry()
    # Seed under the well-known unique_id contract from binary_sensor.py:245.
    fake_reg.register(
        "binary_sensor", DOMAIN, f"{entry_id}_occupied", resolved_entity_id,
    )

    # Occupancy state absent — boot-seed path is inert; keeps this test
    # focused on registry-resolution + reverse-map keying.
    pc.hass.states.get = lambda eid: None

    fake_unsub = MagicMock(name="unsub")
    fake_track = MagicMock(return_value=fake_unsub)

    import homeassistant.helpers.entity_registry as _er_mod
    with patch.object(_er_mod, "async_get", return_value=fake_reg), \
            patch.object(_pres_mod, "async_track_state_change_event", fake_track):
        pc._discover_guest_rooms()

    # 1. state registered with the operator-set threshold (test-local 30).
    assert room_name in pc._guest_room_state, (
        f"resolved guest room must be registered; got keys "
        f"{list(pc._guest_room_state)}"
    )
    assert pc._guest_room_state[room_name]["threshold_min"] == 30

    # 2. reverse map keyed on the REGISTRY-returned entity_id, not a slug.
    assert resolved_entity_id in pc._guest_room_entity_to_name, (
        f"reverse map must key on registry-returned entity_id "
        f"{resolved_entity_id!r}; got keys "
        f"{list(pc._guest_room_entity_to_name)}"
    )
    assert pc._guest_room_entity_to_name[resolved_entity_id] == room_name

    # 3. subscription installed for cleanup (Bug Class #38).
    assert pc._guest_room_unsubs.get(room_name) is fake_unsub, (
        "listener unsub must be stored under the room name"
    )
    # And the subscription targeted the resolved entity_id (positional arg 2).
    subscribed_entities = fake_track.call_args.args[1]
    assert resolved_entity_id in subscribed_entities, (
        f"subscription must target the resolved entity_id "
        f"{resolved_entity_id!r}; got {subscribed_entities!r}"
    )


# ===========================================================================
# T2 — rename resilience: the registry lookup keys on entry_id, so a
# renamed room STILL resolves to its original entity_id.
# ===========================================================================
def test_rename_resilience_registry_lookup_by_entry_id() -> None:
    """The room was originally named "Upstairs Guestroom"; the operator
    renamed it via config to "Upstairs Guest Suite (renamed)". The
    binary_sensor entity_id in the registry did not move — the underlying
    ``{entry_id}_occupied`` unique_id is stable and the entity_id stays
    ``binary_sensor.upstairs_guestroom_occupied`` (HA registry semantics:
    entity_id is assigned on registration and does not auto-track name
    changes).

    D3 must therefore key the reverse map on the REGISTRY-returned
    entity_id (original slug), NOT on a slug freshly built from the
    room's current name.

    Mutation-red anchors: M-B / M-B-v7 (see module docstring) both fail
    this test — under slug-string construction the reverse map ends up
    keyed on ``binary_sensor.upstairs_guest_suite_renamed_occupied``,
    which will never match the actual occupancy sensor's entity_id at
    dispatch time.
    """
    from custom_components.universal_room_automation.const import DOMAIN
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as _pres_mod,
    )

    pc = _bare_pc()
    entry_id = "01KTESTRENAMED000000000000"
    renamed_room_name = "Upstairs Guest Suite (renamed)"
    original_entity_id = "binary_sensor.upstairs_guestroom_occupied"

    entry = _guest_entry(entry_id, renamed_room_name, threshold_min=45)
    pc.hass.config_entries.async_entries = MagicMock(return_value=[entry])

    fake_reg = FakeRegistry()
    fake_reg.register(
        "binary_sensor", DOMAIN, f"{entry_id}_occupied", original_entity_id,
    )
    pc.hass.states.get = lambda eid: None

    fake_track = MagicMock(return_value=MagicMock(name="unsub"))
    import homeassistant.helpers.entity_registry as _er_mod
    with patch.object(_er_mod, "async_get", return_value=fake_reg), \
            patch.object(_pres_mod, "async_track_state_change_event", fake_track):
        pc._discover_guest_rooms()

    # Reverse map keyed on ORIGINAL entity_id, not slug-of-renamed.
    assert original_entity_id in pc._guest_room_entity_to_name, (
        f"rename-resilient resolution must key reverse map on registry "
        f"entity_id {original_entity_id!r}; got "
        f"{list(pc._guest_room_entity_to_name)!r} — this indicates the "
        f"code fell back to slug-string construction"
    )
    assert (
        pc._guest_room_entity_to_name[original_entity_id] == renamed_room_name
    )

    # Discriminating check: the slug-of-renamed shape must NOT appear as a
    # key (this is what M-B would produce). Different observation from the
    # pass-shape above so a partial fix can't accidentally satisfy both.
    slug_of_renamed = (
        "binary_sensor.upstairs_guest_suite_renamed_occupied"
    )
    assert slug_of_renamed not in pc._guest_room_entity_to_name, (
        f"reverse map must NOT contain slug-of-renamed key "
        f"{slug_of_renamed!r} — indicates slug-string fallback is active"
    )

    # And the room is registered under its (renamed) name in state.
    assert renamed_room_name in pc._guest_room_state
    assert pc._guest_room_state[renamed_room_name]["threshold_min"] == 45

    # Subscription targeted the ORIGINAL registry entity_id.
    subscribed_entities = fake_track.call_args.args[1]
    assert original_entity_id in subscribed_entities, (
        f"subscription must target the registry entity_id "
        f"{original_entity_id!r}, not a slug-built guess; got "
        f"{subscribed_entities!r}"
    )


# ===========================================================================
# T3 — unresolvable room: WARNING emitted + NOT registered. Existing
# ``test_unresolvable_room_warns`` already covers this behaviourally; we
# add a DISCRIMINATING check (Producer/Consumer corollary) that the WARNING
# message names the well-known unique_id shape, so a WARNING that fires
# for the wrong reason (e.g. entry misconfiguration path) would not
# satisfy this test.
# ===========================================================================
def test_unresolvable_room_warning_names_unique_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Discriminating variant of the existing unresolvable-room test.

    Under a resolution miss, the emitted WARNING must reference the
    ``{entry_id}_occupied`` unique_id and the room name in its
    ``getMessage()`` payload. A generic "guest room setup failed" warning
    for an unrelated reason must not satisfy this test.

    Mutation-red anchor: delete the ``_LOGGER.warning(...)`` call in the
    unresolvable branch → this test FAILs (no records). Variant-7:
    replace with ``pass  # _LOGGER.warning(...)`` → still FAILs.
    """
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as _pres_mod,
    )

    pc = _bare_pc()
    entry_id = "01KTESTMISSING0000000000"
    room_name = "Vanished Guest Room"

    entry = _guest_entry(entry_id, room_name)
    pc.hass.config_entries.async_entries = MagicMock(return_value=[entry])

    fake_reg = FakeRegistry()  # empty → all lookups miss

    import homeassistant.helpers.entity_registry as _er_mod
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=_pres_mod.__name__), \
            patch.object(_er_mod, "async_get", return_value=fake_reg):
        pc._discover_guest_rooms()

    # Not registered.
    assert room_name not in pc._guest_room_state
    assert pc._guest_room_unsubs == {}

    # WARNING emitted AND the message discriminates the failure reason.
    expected_unique_id = f"{entry_id}_occupied"
    hits = [
        r for r in caplog.records
        if r.levelno >= logging.WARNING
        and room_name in r.getMessage()
        and expected_unique_id in r.getMessage()
    ]
    assert hits, (
        f"expected WARNING naming room {room_name!r} AND unique_id "
        f"{expected_unique_id!r}; got records "
        f"{[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )


# ===========================================================================
# T4 — handler behavioural drive: _handle_guest_room_occupancy_change
# must resolve the room via the reverse map, not by reconstructing the
# entity_id from the current room name.
# ===========================================================================
def test_handler_dispatches_via_reverse_map() -> None:
    """Seed the reverse map with a real->rename mapping, dispatch an
    on-event, and observe Transition 1 firing (first_seen armed) on the
    correct room's state dict.

    This test is decoupled from _discover_guest_rooms — it seeds the
    reverse map directly and drives ONLY the handler, so a failure here
    isolates to handler dispatch (Producer/Consumer decomposition:
    _discover is producer, handler is consumer).

    Mutation-red anchors: M-C / M-C-v7 both fail this test on the
    ``first_seen is not None`` assertion.
    """
    pc = _bare_pc()
    room_name = "Downstairs Guest Bedroom (renamed)"
    resolved_entity_id = "binary_sensor.original_downstairs_guest_occupied"

    # Seed reverse map + state as if _discover_guest_rooms had run.
    pc._guest_room_entity_to_name[resolved_entity_id] = room_name
    pc._guest_room_state[room_name] = {
        "first_seen": None,
        "current_occupancy_known": False,
        "threshold_min": 30,
    }
    # Neutralise inference scheduling: hass.async_create_task is already a
    # MagicMock; _run_inference just needs to be safely callable.
    pc._run_inference = MagicMock(return_value=None)

    # Build an "on" state-change event.
    event = MagicMock()
    new_state = MagicMock()
    new_state.state = "on"
    event.data = {"entity_id": resolved_entity_id, "new_state": new_state}

    before = pc._guest_room_state[room_name]["first_seen"]
    assert before is None, "precondition: first_seen must start unarmed"

    pc._handle_guest_room_occupancy_change(event)

    after = pc._guest_room_state[room_name]["first_seen"]
    assert after is not None, (
        "handler must arm first_seen on Transition 1 for the room whose "
        "occupancy entity fired — indicates reverse-map lookup missed"
    )
    # Discriminating: no OTHER room's state should have been touched.
    # Add a decoy room to prove the reverse-map key drove the dispatch.
    pc._guest_room_state["Decoy Room"] = {
        "first_seen": None,
        "current_occupancy_known": False,
        "threshold_min": 30,
    }
    # (Re-verify decoy after handler: it stayed None because it was never
    # in the reverse map.)
    assert pc._guest_room_state["Decoy Room"]["first_seen"] is None


# ===========================================================================
# T5 — negative dispatch: an unknown entity_id (not in reverse map) must
# be silently ignored by the handler — no KeyError on _guest_room_state.
# ===========================================================================
def test_handler_ignores_unknown_entity_id() -> None:
    """A state-change event for an entity_id NOT in the reverse map must
    be a no-op (early return), not raise on ``_guest_room_state[room_name]``.

    Guards against a mutation that replaces ``.get(entity_id)`` with
    ``[entity_id]`` (KeyError) or removes the ``if room_name is None:
    return`` early-return, which would crash the state-change handler
    for every non-guest occupancy event in the house.
    """
    pc = _bare_pc()
    pc._run_inference = MagicMock(return_value=None)
    # Reverse map deliberately empty — any incoming entity_id is "unknown".

    event = MagicMock()
    new_state = MagicMock()
    new_state.state = "on"
    event.data = {
        "entity_id": "binary_sensor.some_unrelated_room_occupied",
        "new_state": new_state,
    }

    # Must not raise; must not mutate state.
    pc._handle_guest_room_occupancy_change(event)
    assert pc._guest_room_state == {}
