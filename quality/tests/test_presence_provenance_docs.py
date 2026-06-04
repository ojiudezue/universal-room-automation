"""D6 — Docs updates (PRESENCE_COORDINATOR.md + TECH_DEBT.md).

Asserts the two doc updates the cycle commits to:
  * `docs/Coordinator/PRESENCE_COORDINATOR.md` §5 INPUTS contains a
    Tier-1 provenance subsection naming the kind vocabulary.
  * `docs/TECH_DEBT.md` Presence entry shows "Resolved (audit GREEN)"
    with a back-pointer to the audit doc.
"""

from __future__ import annotations

import os


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_presence_coordinator_doc_has_tier1_provenance_section() -> None:
    path = os.path.join(
        REPO_ROOT, "docs", "Coordinator", "PRESENCE_COORDINATOR.md",
    )
    assert os.path.isfile(path), f"missing: {path}"
    body = open(path, encoding="utf-8").read()
    assert "Tier-1 provenance" in body, "missing Tier-1 provenance subsection"
    # Vocabulary must appear.
    assert "motion" in body
    assert "mmwave" in body
    assert "occupancy" in body
    # Back-pointer to the audit doc.
    assert "AUDIT_presence_provenance" in body


def test_tech_debt_marks_tier1_or_resolved() -> None:
    path = os.path.join(REPO_ROOT, "docs", "TECH_DEBT.md")
    assert os.path.isfile(path), f"missing: {path}"
    body = open(path, encoding="utf-8").read()
    lower = body.lower()
    # Either "resolved" or "audit green" marker — accept both phrasings.
    assert "tier 1" in lower or "tier-1" in lower
    assert "audit green" in lower or "resolved" in lower
    assert "AUDIT_presence_provenance" in body
