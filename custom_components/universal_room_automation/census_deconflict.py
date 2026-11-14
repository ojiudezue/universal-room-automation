"""Census deconfliction: the ONE dedup function (census deconfliction CD1).

Plan: docs/planning/PLANNING_census_deconfliction.md §3.3. Pure: no Home
Assistant import, no clock read. Called once per census evaluation by
``PersonCensus._apply_enhanced_house_census`` (INV-DEDUP / INV-SINGLE-WRITER:
nothing else calls it and nothing else writes the awareness fields).

Two views of F2 (who is in the house):

* Trust view (F2-T): the census's existing fields, passed through unchanged
  (byte-identical; every AWAY / house-state / security / lock / HVAC reader
  keeps reading it).
* Awareness view (F2-A): ``aware_guests``, ``aware_total``,
  ``aware_identified`` (= the trust identified union; no second identity
  path), ``count_provenance`` and ``aware_agreement``.

Terms in this build: ``guest_cam`` (the trust view's post-hold
``unidentified_count``; the camera estimate always exists) and ``guest_vis``
(the crossing ledger, ``max(0, L - R)``; None when unknown or unhealthy:
an unhealthy source is MISSING, never zero).

Falsifiable invariants:

* INV-P2-AWARE-DECONFLICT: while ``vision_leads`` is False,
  ``aware_guests == guest_cam`` for every input (cases A-D).
* INV-DEDUP (guest side): guest-side terms combine by max, never sum;
  residents are subtracted once, upstream (``R`` inside ``guest_vis``).
* INV-P2-IDENTITY / INV-NO-NAME: ``aware_identified`` is the trust union,
  copied; vision supplies counts, never names.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# count_provenance: which estimate produced aware_guests.
PROVENANCE_CAMERA = "camera"
PROVENANCE_VISION = "vision"
PROVENANCE_AGREE = "agree"

# aware_agreement values: the census vocabulary (const.CENSUS_AGREEMENT_*,
# const.py:2439-2442; equality pinned by test_agreement_values_match_const).
AGREEMENT_BOTH = "both_agree"
AGREEMENT_CLOSE = "close"
AGREEMENT_DISAGREE = "disagree"
AGREEMENT_SINGLE = "single_source"

# Deconfliction cases (plan §3.3, §15.7).
CASE_AGREE = "A"
CASE_VISION_HIGHER = "B"
CASE_CAMERA_HIGHER = "C"
CASE_ONE_MISSING = "D"


@dataclass(frozen=True)
class TrustFields:
    """The trust view's existing house fields (passed through unchanged)."""

    identified_count: int
    identified_persons: tuple[str, ...]
    unidentified_count: int
    total_persons: int


@dataclass(frozen=True)
class AwarenessFields:
    aware_guests: int
    aware_total: int
    aware_identified: tuple[str, ...]
    count_provenance: str
    aware_agreement: str
    case: str


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def guest_terms_max(terms: Mapping[str, Any]) -> int | None:
    """Dedup rule 3: guest-side terms combine by max, never sum. A missing
    (None) or malformed term drops out; all missing -> None."""
    present = [c for c in (_count(v) for v in terms.values()) if c is not None]
    return max(present) if present else None


def deconflict_house(
    trust: TrustFields,
    *,
    guest_vis: Any,
    vision_leads: bool,
    flag_min: int,
    extra_guest_terms: Mapping[str, Any] | None = None,
) -> tuple[TrustFields, AwarenessFields]:
    """Return ``(trust, awareness)``; ``trust`` is the object passed in.

    ``guest_vis`` None = case D (vision missing / unknown / unhealthy).
    ``extra_guest_terms``: later vision-side guest terms (none built yet;
    each enters only here, combined by max with the ledger term).
    """
    guest_cam = int(trust.unidentified_count)
    vis = guest_terms_max({"ledger": guest_vis, **dict(extra_guest_terms or {})})
    if vis is None:
        aware, prov, agr, case = guest_cam, PROVENANCE_CAMERA, AGREEMENT_SINGLE, CASE_ONE_MISSING
    else:
        diff = abs(vis - guest_cam)
        if diff == 0 or diff < int(flag_min):
            case, agr, prov = CASE_AGREE, AGREEMENT_BOTH, PROVENANCE_AGREE
        else:
            case = CASE_VISION_HIGHER if vis > guest_cam else CASE_CAMERA_HIGHER
            agr = AGREEMENT_CLOSE if diff <= int(flag_min) else AGREEMENT_DISAGREE
            prov = PROVENANCE_VISION if vision_leads else PROVENANCE_CAMERA
        # INV-P2-AWARE-DECONFLICT: vision moves the value only once it leads.
        aware = vis if vision_leads else guest_cam
    identified: Sequence[str] = tuple(trust.identified_persons)
    return trust, AwarenessFields(
        aware_guests=int(aware),
        aware_total=int(trust.identified_count) + int(aware),
        aware_identified=tuple(identified),
        count_provenance=prov,
        aware_agreement=agr,
        case=case,
    )
