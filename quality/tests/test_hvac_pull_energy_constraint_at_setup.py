"""HVAC-PRECOOL-NO-CONSTRAINT-POST-BOOT-1: producer-owned pull at HVAC setup.

Root cause covered:
    EC is registered before HVAC (__init__.py); CoordinatorManager sets up
    coordinators sequentially so EC's boot decision cycle fires
    SIGNAL_ENERGY_CONSTRAINT BEFORE HVAC subscribes. async_dispatcher_send is
    fire-and-forget (no replay) and the change-gate then suppresses re-emits
    of a stable `normal` — so HVAC's `_energy_constraint` sat at None until
    the first mode change (evening coast), disarming Path A pre-cool.

Fix:
    EnergyCoordinator exposes `current_energy_constraint()` (backed by a
    private `_build_energy_constraint()` shared with the dispatch site so the
    payload cannot drift). HVAC's async_setup pulls this right after the
    SIGNAL_ENERGY_CONSTRAINT subscribe and feeds it into
    `_handle_energy_constraint`.

Tests:
    - boot_ordering: extract HVAC's pull block, exec it against a mock self
      + a mock energy coordinator that returns a `normal` seed constraint.
      Assert `_handle_energy_constraint(seed)` was called (mutation anchor:
      remove the pull → this test fails).
    - payload_shape: `current_energy_constraint()` must return the SAME
      EnergyConstraint shape the dispatch site emits (both routed through
      `_build_energy_constraint`), verified by source-anchor: dispatch site
      no longer constructs `EnergyConstraint(...)` inline, and both callers
      go through the private builder.
    - guard: with no energy coordinator on `hass.data`, the pull block runs
      without raising and does NOT call `_handle_energy_constraint`.
"""

from __future__ import annotations

import os
import re
from unittest.mock import MagicMock


_HERE = os.path.dirname(__file__)
_HVAC_PY = os.path.join(
    _HERE, "..", "..", "custom_components", "universal_room_automation",
    "domain_coordinators", "hvac.py",
)
_ENERGY_PY = os.path.join(
    _HERE, "..", "..", "custom_components", "universal_room_automation",
    "domain_coordinators", "energy.py",
)


def _extract_pull_block() -> str:
    """Pull out the setup-time energy-constraint pull block from hvac.py."""
    with open(_HVAC_PY, "r") as fh:
        src = fh.read()
    marker = "HVAC-PRECOOL-NO-CONSTRAINT-POST-BOOT-1: producer-owned pull."
    idx = src.index(marker)
    # Start at the `try:` line that follows the comment block.
    try_idx = src.index("        try:", idx)
    end_idx = src.index("        # v3.17.0 D3: Subscribe to person arriving", try_idx)
    block = src[try_idx:end_idx]
    dedented = "\n".join(
        line[8:] if len(line) >= 8 else line for line in block.splitlines()
    ) + "\n"
    return dedented


_PULL_SRC = _extract_pull_block()


def _run_pull(mock_self, mock_hass_data):
    """Exec the extracted pull block with `self` and `_LOGGER` bound."""
    import logging
    mock_self.hass = MagicMock()
    mock_self.hass.data = mock_hass_data
    exec_globals = {
        "self": mock_self,
        "_LOGGER": logging.getLogger("test.hvac_pull_energy_constraint"),
    }
    exec(compile(_PULL_SRC, "<hvac_setup_pull_block>", "exec"), exec_globals)


class TestBootOrdering:
    def test_pull_seeds_energy_constraint_from_energy_coordinator(self):
        """Load-bearing: HVAC pulls current constraint and applies it.

        MUTATION ANCHOR: delete the pull block from hvac.py.async_setup →
        this assertion fails because `_handle_energy_constraint` is never
        invoked at setup time.
        """
        seed = MagicMock()
        seed.mode = "normal"
        seed.setpoint_offset = 0.0
        seed.reason = "normal conditions"

        energy = MagicMock()
        energy.current_energy_constraint.return_value = seed

        cm = MagicMock()
        cm.coordinators = {"energy": energy}
        hass_data = {"universal_room_automation": {"coordinator_manager": cm}}

        mock_self = MagicMock()
        _run_pull(mock_self, hass_data)

        energy.current_energy_constraint.assert_called_once()
        mock_self._handle_energy_constraint.assert_called_once_with(seed)


class TestGuards:
    def test_no_coordinator_manager_is_safe_noop(self):
        mock_self = MagicMock()
        _run_pull(mock_self, {})
        mock_self._handle_energy_constraint.assert_not_called()

    def test_no_energy_coordinator_is_safe_noop(self):
        cm = MagicMock()
        cm.coordinators = {}
        hass_data = {"universal_room_automation": {"coordinator_manager": cm}}
        mock_self = MagicMock()
        _run_pull(mock_self, hass_data)
        mock_self._handle_energy_constraint.assert_not_called()

    def test_current_energy_constraint_returning_none_is_safe(self):
        energy = MagicMock()
        energy.current_energy_constraint.return_value = None
        cm = MagicMock()
        cm.coordinators = {"energy": energy}
        hass_data = {"universal_room_automation": {"coordinator_manager": cm}}
        mock_self = MagicMock()
        _run_pull(mock_self, hass_data)
        mock_self._handle_energy_constraint.assert_not_called()

    def test_helper_exception_does_not_crash_setup(self):
        energy = MagicMock()
        energy.current_energy_constraint.side_effect = RuntimeError("boom")
        cm = MagicMock()
        cm.coordinators = {"energy": energy}
        hass_data = {"universal_room_automation": {"coordinator_manager": cm}}
        mock_self = MagicMock()
        # Should NOT raise — guarded by try/except in the pull block.
        _run_pull(mock_self, hass_data)
        mock_self._handle_energy_constraint.assert_not_called()


class TestPayloadShapeSingleBuilder:
    """The dispatch site and the pull helper MUST route through the same
    private builder so the EnergyConstraint payload cannot drift."""

    def test_energy_source_has_build_energy_constraint(self):
        with open(_ENERGY_PY, "r") as fh:
            src = fh.read()
        assert "def _build_energy_constraint(self)" in src
        assert "def current_energy_constraint(self)" in src

    def test_dispatch_site_no_longer_inlines_energyconstraint_construction(self):
        """The old inline `EnergyConstraint(...)` construction inside
        `_update_hvac_constraint` is gone; both callers use the builder.
        """
        with open(_ENERGY_PY, "r") as fh:
            src = fh.read()
        start = src.index("    def _update_hvac_constraint(")
        end = src.index("\n    def _build_energy_constraint(", start)
        body = src[start:end]
        # No inline construction inside the dispatch method anymore.
        assert "EnergyConstraint(" not in body, (
            "Dispatch site must call self._build_energy_constraint(), not "
            "construct EnergyConstraint inline (payload drift risk)."
        )
        # And the dispatch site calls the builder.
        assert "self._build_energy_constraint()" in body

    def test_current_energy_constraint_calls_builder(self):
        with open(_ENERGY_PY, "r") as fh:
            src = fh.read()
        m = re.search(
            r"def current_energy_constraint\(self\).*?(?=\n    def )",
            src, re.DOTALL,
        )
        assert m, "current_energy_constraint not found"
        assert "self._build_energy_constraint()" in m.group(0)
