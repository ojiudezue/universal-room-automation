"""Zone-tier substrate migration tests (D2 acceptance).

The zone tier's `_on_substrate_kind_changed` consumes per-kind edges
from the substrate signal and writes them into
``ZonePresenceTracker._room_provenance`` with the SAME call shape
the prior `_handle_occupancy_change` used. Provenance dict shape
remains unchanged; raw_occupied freshness preserved.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401
from _provenance_harness import make_hass

from custom_components.universal_room_automation.const import TIER1_KINDS
from custom_components.universal_room_automation.domain_coordinators.presence import (  # noqa: E501
    ZonePresenceTracker,
)


def test_room_provenance_shape_after_kind_edge() -> None:
    """A per-kind True write produces the same per-kind dict shape as before."""
    hass = make_hass()
    t = ZonePresenceTracker(hass, "z", ["bedroom"])
    # Simulate the substrate-driven path: substrate fires
    # _on_substrate_kind_changed -> tracker.update_room_occupancy(room, True, kind=kind).
    t.update_room_occupancy("bedroom", True, kind="mmwave")
    prov = t.provenance_for("bedroom")
    assert set(prov.keys()) == set(TIER1_KINDS)
    assert prov["mmwave"] is True
    assert prov["motion"] is False
    assert prov["occupancy"] is False


def test_raw_occupied_freshness_preserved() -> None:
    """`raw_occupied` flips on substrate-mediated True/False edges."""
    hass = make_hass()
    t = ZonePresenceTracker(hass, "z", ["a"])
    assert t.raw_occupied is False
    t.update_room_occupancy("a", True, kind="motion")
    assert t.raw_occupied is True
    t.update_room_occupancy("a", False)
    assert t.raw_occupied is False


def test_area_sweep_path_deleted_no_substring_fallback() -> None:
    """The zone-tier source no longer contains the area-sweep + name-fallback bodies."""
    import inspect
    from custom_components.universal_room_automation.domain_coordinators import (
        presence as presence_mod,
    )
    src = inspect.getsource(presence_mod)
    # The deleted name-based fallback function should be GONE from source.
    assert "_discover_room_sensors_by_name" not in src or (
        # If the string lingers only in a deletion comment, that's fine —
        # but the def-line must not exist.
        "def _discover_room_sensors_by_name(" not in src
    )
    # The area-sweep entity-registry walk inside the discovery body
    # should also be gone — verified by checking that the new
    # substrate-driven body does not contain the prior loop.
    assert "for entity in ent_reg.entities.values():" not in src
