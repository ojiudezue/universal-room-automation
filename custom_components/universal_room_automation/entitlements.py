"""Coordinator entitlement hook (CM-COORDINATORS-ADD-ONE-BY-ONE-1 D4).

Design-only hook point: every coordinator is allowed today. A future
cycle can decide per coordinator (e.g. paid modules). No license server,
no token, no network call here.

Called from exactly two places:
  - the CM options flow "Add a coordinator" step (before routing to the
    coordinator's settings step), and
  - coordinator_gate.coordinator_should_run (so a hand-edited option
    cannot run a coordinator that is not allowed).
"""
from __future__ import annotations


def can_use_coordinator(coordinator_id: str) -> tuple[bool, str | None]:
    """Return (allowed, reason). Always allowed today."""
    return True, None
