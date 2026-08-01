"""Tests for the 2026-08-01 census fusion policy (divergence-aware confidence).

Cycle: `feature/census-fusion-policy`. Drives REAL production code
(``PersonCensus._cross_validate_platforms``, ``_cross_correlate_persons``,
``_is_divergence_downgrade_enabled``) per Bug Class #62 (test-authority via
production code, not hand-copied stubs).

Invariant (Reviewer D framing, from the planning doc):

    A lone unidentified count originating from ONE source, contradicted by a
    SECOND source that covers the same interior zone and reports zero, with
    ZERO corroboration (no face-recognized persons, no BLE persons, no
    tier-1 room occupancy anywhere in the zone), can NEVER alone flip house
    state to GUEST.

Tests (T1-T6) mirror the acceptance criteria in
``docs/planning/PLANNING_census_fusion_policy.md`` §D1.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import _provenance_harness  # noqa: F401 — bootstraps HA module stubs.
from _provenance_harness import make_hass

from custom_components.universal_room_automation import const as ura_const
from custom_components.universal_room_automation.camera_census import (
    PersonCensus,
)


# The guest-gate rank ordering as implemented in presence.py:4323.
# Kept literal here so a divergence between presence.py and this test surface
# is caught by the guest-bar assertion in T1.
_GUEST_CONFIDENCE_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}
_GUEST_REQUIRE_DEFAULT = "medium"


def _make_census(
    *,
    downgrade_enabled: bool = True,
) -> PersonCensus:
    """Build a PersonCensus wired to a stub integration entry.

    Only the fields the cycle's helpers read (``CONF_CENSUS_DIVERGENCE_DOWNGRADE``,
    ``CONF_CENSUS_CROSS_VALIDATION``) are seeded. No cameras — the tests
    drive ``_cross_validate_platforms`` and ``_cross_correlate_persons``
    directly with synthetic inputs matching the 2026-08-01 snapshot shape.
    """
    hass = make_hass()
    entry = MagicMock()
    entry.data = {ura_const.CONF_ENTRY_TYPE: ura_const.ENTRY_TYPE_INTEGRATION}
    entry.options = {
        ura_const.CONF_CENSUS_CROSS_VALIDATION: True,
        ura_const.CONF_CENSUS_DIVERGENCE_DOWNGRADE: downgrade_enabled,
    }
    hass.config_entries.async_entries.return_value = [entry]
    mgr = MagicMock()
    return PersonCensus(hass, mgr)  # type: ignore[arg-type]


def _correlate(
    census: PersonCensus,
    *,
    camera_total: int,
    agreement: str,
    face_ids: set[str] | None = None,
    ble_ids: set[str] | None = None,
    frigate_count: int = 0,
    unifi_count: int = 0,
) -> object:
    """Thin wrapper around the real _cross_correlate_persons for tests."""
    return census._cross_correlate_persons(
        face_ids=face_ids or set(),
        ble_ids=ble_ids or set(),
        camera_total=camera_total,
        zone="house",
        frigate_count=frigate_count,
        unifi_count=unifi_count,
        agreement=agreement,
        now=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# T1 — playroom 2026-08-01 replay: frigate=1, unifi=0, no corroboration.
# ---------------------------------------------------------------------------


def test_playroom_snapshot_replay_downgrades_and_blocks_guest_flip() -> None:
    """T1: the exact 2026-08-01 shape must produce (0, disagree) → LOW →
    below the guest-flip bar.

    Playroom snapshot: frigate_count=1, binary=0, face_ids=∅, ble_ids=∅,
    any_zone_occupied=False → merge returns (0, DISAGREE); downstream
    confidence LOW; presence's guest gate requires >= MEDIUM (see
    presence.py _confidence_at_least + _CONFIDENCE_RANK); LOW does not
    clear it, so a guest flip cannot occur on this signal alone.
    """
    census = _make_census(downgrade_enabled=True)

    count, agreement = census._cross_validate_platforms(
        1, 0, corroborated=False,
    )
    assert count == 0, "min-wins on uncorroborated divergent max"
    assert agreement == ura_const.CENSUS_AGREEMENT_DISAGREE

    zone = _correlate(
        census,
        camera_total=count,
        agreement=agreement,
        frigate_count=1,
        unifi_count=0,
    )
    # Downstream confidence: when the downgrade collapses camera_total to
    # zero AND there are no identified persons, _cross_correlate_persons
    # short-circuits to NONE (the zero-camera / zero-identified branch,
    # camera_census.py near l.1391) — a STRONGER suppression than the
    # bare DISAGREE→LOW mapping. Either NONE or LOW is acceptable; both
    # are below the MEDIUM guest-flip bar (the invariant that matters).
    assert zone.confidence in (
        ura_const.CENSUS_CONFIDENCE_NONE,
        ura_const.CENSUS_CONFIDENCE_LOW,
    )
    assert zone.source_agreement == ura_const.CENSUS_AGREEMENT_DISAGREE
    # Vendor columns preserved as-is for analytics (schema untouched).
    assert zone.frigate_count == 1
    assert zone.unifi_count == 0
    assert zone.unidentified_count == 0, "no unidentified body when count=0"

    # Guest-bar seam: the observed LOW confidence must NOT meet the default
    # MEDIUM guest-require bar. Mirrors presence._confidence_at_least().
    observed_rank = _GUEST_CONFIDENCE_RANK[zone.confidence]
    required_rank = _GUEST_CONFIDENCE_RANK[_GUEST_REQUIRE_DEFAULT]
    assert observed_rank < required_rank, (
        "LOW must be below the MEDIUM guest-flip bar; if this assertion "
        "flips, the divergence downgrade would no longer block guest mode"
    )


# ---------------------------------------------------------------------------
# T2 — agreement (both > 0) is preserved (max/CLOSE→BOTH semantics unchanged).
# ---------------------------------------------------------------------------


def test_agreement_both_gt_zero_unchanged() -> None:
    """T2: both sources > 0 → (frigate, BOTH), confidence HIGH — unchanged.

    Downgrade knob must NOT touch the agreement branch even when
    ``corroborated=False`` (which is legal here since both sources agree).
    """
    census = _make_census(downgrade_enabled=True)
    count, agreement = census._cross_validate_platforms(
        2, 1, corroborated=False,
    )
    assert count == 2, "frigate numeric wins when both > 0"
    assert agreement == ura_const.CENSUS_AGREEMENT_BOTH
    zone = _correlate(
        census,
        camera_total=count,
        agreement=agreement,
        frigate_count=2,
        unifi_count=1,
    )
    assert zone.confidence == ura_const.CENSUS_CONFIDENCE_HIGH


# ---------------------------------------------------------------------------
# T3 — single-source zone is not re-classified.
# ---------------------------------------------------------------------------


def test_single_source_agreement_maps_to_medium_and_is_untouched() -> None:
    """T3: single-source zones (only one platform available at the merge
    site) never enter _cross_validate_platforms — the caller stamps
    ``CENSUS_AGREEMENT_SINGLE`` directly. This test pins the downstream
    invariant that SINGLE maps to MEDIUM (the pre-cycle behavior on
    single-camera interiors and on the exterior census).
    """
    census = _make_census(downgrade_enabled=True)
    zone = _correlate(
        census,
        camera_total=1,
        agreement=ura_const.CENSUS_AGREEMENT_SINGLE,
        frigate_count=1,
        unifi_count=0,
    )
    assert zone.confidence == ura_const.CENSUS_CONFIDENCE_MEDIUM
    assert zone.source_agreement == ura_const.CENSUS_AGREEMENT_SINGLE


# ---------------------------------------------------------------------------
# T4 — divergence WITH corroboration is trusted (unchanged from today).
# ---------------------------------------------------------------------------


def test_corroborated_divergence_keeps_max_and_close() -> None:
    """T4: frigate=1, binary=0, but a BLE-tracked person is present →
    the divergence is CORROBORATED, so we keep the pre-cycle behavior:
    (max=1, CLOSE), which maps to MEDIUM confidence.
    """
    census = _make_census(downgrade_enabled=True)
    count, agreement = census._cross_validate_platforms(
        1, 0, corroborated=True,
    )
    assert count == 1, "corroborated divergence retains max-wins"
    assert agreement == ura_const.CENSUS_AGREEMENT_CLOSE
    zone = _correlate(
        census,
        camera_total=count,
        agreement=agreement,
        ble_ids={"ble_person_1"},
        frigate_count=1,
        unifi_count=0,
    )
    assert zone.confidence == ura_const.CENSUS_CONFIDENCE_MEDIUM


# ---------------------------------------------------------------------------
# T5 — kill switch False restores pre-cycle behavior byte-identically.
# ---------------------------------------------------------------------------


def test_kill_switch_false_restores_max_wins_close_on_playroom_shape() -> None:
    """T5: with ``CONF_CENSUS_DIVERGENCE_DOWNGRADE`` OFF, the exact T1
    inputs (frigate=1, binary=0, uncorroborated) produce the pre-cycle
    output byte-identically: (1, CLOSE), MEDIUM confidence.

    This is the fire-axe. If a live incident shows the downgrade over-firing,
    the operator toggles it OFF and the merge returns to max-wins.
    """
    census = _make_census(downgrade_enabled=False)
    count, agreement = census._cross_validate_platforms(
        1, 0, corroborated=False,
    )
    assert count == 1, "kill switch OFF → pre-cycle max-wins restored"
    assert agreement == ura_const.CENSUS_AGREEMENT_CLOSE
    zone = _correlate(
        census,
        camera_total=count,
        agreement=agreement,
        frigate_count=1,
        unifi_count=0,
    )
    assert zone.confidence == ura_const.CENSUS_CONFIDENCE_MEDIUM


# ---------------------------------------------------------------------------
# T6 — mutation-anchored: neutering the divergence branch turns T1 red.
# ---------------------------------------------------------------------------


def test_mutation_drill_structure_is_documented() -> None:
    """T6: mutation-anchor documentation for Reviewer C.

    Drill:
      1. Restore the divergence branch to pre-cycle behavior::
             return (frigate_count, CENSUS_AGREEMENT_CLOSE)
         (delete the `if not corroborated and self._is_divergence_downgrade_enabled():`
          block in ``_cross_validate_platforms`` at the ``f>0 AND b==0``
          site — and symmetric on ``f==0 AND b>0``).
      2. ``PYTHONDONTWRITEBYTECODE=1`` and clear ``__pycache__`` so the
         mutation is actually loaded (see feedback_mutation_pycache_staleness).
      3. Run ``pytest quality/tests/test_census_fusion_policy.py`` — the
         specific test that MUST turn red is
         ``test_playroom_snapshot_replay_downgrades_and_blocks_guest_flip``
         (T1). The kill-switch test (T5) must stay green (proves the
         mutation didn't accidentally break the OFF path).
      4. Restore the source. Re-run — all green.

    This test itself only pins the invariant that a mutation-verifiable
    site exists at the two divergence branches. The verifier RUNS the
    drill; this docstring is the drill spec.
    """
    # Structural anchor: the two branches the mutation targets exist and
    # accept the kwarg (via inspect, no source parsing).
    import inspect
    sig = inspect.signature(PersonCensus._cross_validate_platforms)
    assert "corroborated" in sig.parameters, (
        "cycle-signature invariant: _cross_validate_platforms must accept "
        "the `corroborated` kwarg used by the divergence branches"
    )
    assert sig.parameters["corroborated"].kind == inspect.Parameter.KEYWORD_ONLY
