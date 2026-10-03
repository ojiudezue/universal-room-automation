"""Lighting helpers for URA room automation.

Slice A of ROOM-LIGHTING-SETUP-REDESIGN-1 (v5.103.28). Additive-only:
no behaviour change. Exposes ``effective_entry_set`` / ``effective_exit_set``
so the entry/exit lighting derivations live behind a single named
helper that later slices (D1 sun fallback, D2 hold, D3 room-light
switch, D4 house-state) all consume through one seam instead of
re-deriving the set inline at each writer.

See ``docs/planning/PLANNING_room_dialog_cleanup_and_lighting_roles.md``.
"""

from .darkness import is_dark_fallback
from .resolver import effective_entry_set, effective_exit_set

__all__ = ["effective_entry_set", "effective_exit_set", "is_dark_fallback"]
