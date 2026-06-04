"""D1 audit harness — provenance-split cycle.

Verifies:
  * docs/planning/AUDIT_presence_provenance.md exists + carries the
    GREEN verdict line and the helper-spec block.
  * `_audit_provenance_invariants` exists at module level in
    `domain_coordinators/presence.py` and returns the expected shape.
"""

from __future__ import annotations

import os

import _provenance_harness  # noqa: F401 — side-effect: HA mocks
from _provenance_harness import make_hass

from custom_components.universal_room_automation.domain_coordinators.presence import (
    ZonePresenceTracker,
    _audit_provenance_invariants,
)


REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)


def test_audit_doc_exists() -> None:
    """The audit gate doc must exist and carry the verdict + helper spec."""
    path = os.path.join(
        REPO_ROOT, "docs", "planning", "AUDIT_presence_provenance.md",
    )
    assert os.path.isfile(path), f"audit doc missing: {path}"
    body = open(path, encoding="utf-8").read()
    # Verdict line — accept either GREEN phrasing variant from spec.
    assert "GREEN" in body, "audit doc missing GREEN verdict"
    assert "Appendix A" in body, "audit doc missing Appendix A reference"
    assert "_audit_provenance_invariants" in body, (
        "audit doc missing helper spec block"
    )


def test_invariants_helper_is_module_level() -> None:
    """Helper must be a module-level function — greppable + diagnostic."""
    assert callable(_audit_provenance_invariants)
    # First argument should accept a tracker.
    hass = make_hass()
    tracker = ZonePresenceTracker(hass, "test_zone", ["roomA"])
    result = _audit_provenance_invariants(tracker)
    assert isinstance(result, list)
    assert result == []


def test_invariants_helper_flags_dict_shape_violation() -> None:
    """If _room_provenance is mutated to an invalid type the helper flags."""
    hass = make_hass()
    tracker = ZonePresenceTracker(hass, "test_zone", ["roomA"])
    tracker._room_provenance["roomA"] = "not a dict"  # type: ignore[assignment]
    violations = _audit_provenance_invariants(tracker)
    assert any("not a dict" in v for v in violations), violations


def test_invariants_helper_flags_unknown_kind() -> None:
    hass = make_hass()
    tracker = ZonePresenceTracker(hass, "test_zone", ["roomA"])
    tracker._room_provenance["roomA"] = {"infrared": True}  # bogus kind
    violations = _audit_provenance_invariants(tracker)
    assert any("unknown kind" in v for v in violations), violations
