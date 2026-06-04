"""D4 — `check_zone_occupancy_confidence` docstring fidelity test.

Per AUDIT_presence_provenance.md Appendix A.6 #2, the helper is
independent of the OR split. D4 collapses to a docstring update; this
test asserts the docstring documents source-1's `_last_motion_time`
provenance and references the audit.
"""

from __future__ import annotations

import _provenance_harness  # noqa: F401

from custom_components.universal_room_automation.domain_coordinators.presence import (
    PresenceCoordinator,
)


def test_docstring_references_audit() -> None:
    doc = PresenceCoordinator.check_zone_occupancy_confidence.__doc__ or ""
    assert doc, "check_zone_occupancy_confidence has no docstring"
    lower = doc.lower()
    # Must call out _last_motion_time independence from the split.
    assert "_last_motion_time" in doc, doc
    # Must cite the audit doc / appendix.
    assert "audit" in lower
    assert "a.6" in lower or "appendix a" in lower or "audit_presence_provenance" in lower
    # Must mention that Source 1 / possible count is unchanged by D2.
    assert "possible" in lower
