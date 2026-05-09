"""v4.5.8 — Lock down the signal-handler gating model.

The 4 coordinator-signal handlers (_on_house_state_changed,
_on_energy_constraint, _on_safety_hazard, _on_security_event) have an
intentional asymmetry vs. the per-room occupancy/lux trigger path:

  - house_state, energy_constraint  → AI toggle gates; master toggle does NOT
  - safety, security                → NEITHER toggle gates (Review fix F11)
  - occupancy/lux (per-room)        → BOTH toggles gate

This is documented in the "GATING MODEL FOR SIGNAL HANDLERS" comment
block in coordinator.py (added v4.5.8). The audit on 2026-05-09 flagged
the asymmetry as a possible bug — user confirmed it's intentional. To
prevent a future "consistency fix" from accidentally regressing the
matrix (especially the safety/security ungating, which has real user
safety implications), this test asserts the model in source.

Source-grep tests rather than runtime tests because the signal
handlers are deeply coupled to the coordinator and pull HA imports
that don't load cleanly in the test env. Same mirror pattern used
in v4.5.0.4 / v4.5.3 / v4.5.6 / v4.5.7.
"""

import pytest


# ---------------------------------------------------------------------------
# Source-contract tests — the gating must match the documented matrix
# ---------------------------------------------------------------------------

class TestGatingModel:
    """Lock down which toggles gate which signal handlers."""

    @pytest.fixture
    def coord_src(self):
        with open("custom_components/universal_room_automation/coordinator.py") as f:
            return f.read()

    def _extract_handler_body(self, src, fn_name):
        """Slice the handler function body out of source."""
        idx = src.find(f"def {fn_name}(self, payload)")
        assert idx > 0, f"{fn_name} must exist in coordinator.py"
        # Body extends until the next `@callback` or method definition
        next_callback = src.find("@callback", idx + 1)
        next_def = src.find("\n    def ", idx + 1)
        # Pick whichever comes first that's > 0
        candidates = [c for c in (next_callback, next_def) if c > 0]
        end = min(candidates) if candidates else len(src)
        return src[idx:end]

    def test_house_state_handler_gated_by_ai_toggle_only(self, coord_src):
        body = self._extract_handler_body(coord_src, "_on_house_state_changed")
        assert "_is_ai_automation_enabled()" in body, (
            "_on_house_state_changed must check AI automation toggle "
            "(documented in v4.5.8 gating model)"
        )
        assert "_is_automation_enabled()" not in body, (
            "_on_house_state_changed must NOT check the master automation "
            "toggle — system-level reactions fire regardless of per-room "
            "automation pause. See GATING MODEL comment block."
        )

    def test_energy_constraint_handler_gated_by_ai_toggle_only(self, coord_src):
        body = self._extract_handler_body(coord_src, "_on_energy_constraint")
        assert "_is_ai_automation_enabled()" in body
        assert "_is_automation_enabled()" not in body, (
            "_on_energy_constraint must NOT check master automation toggle"
        )

    def test_safety_handler_ungated(self, coord_src):
        """CRITICAL: safety must NEVER be gated by either toggle.

        Killing safety chained automation with a "pause automation" toggle
        is a real bug (smoke detector firing while user has paused
        automation for the night → notify + light-the-path automation
        must still run). Review fix F11 made this deliberate.
        """
        body = self._extract_handler_body(coord_src, "_on_safety_hazard")
        assert "_is_ai_automation_enabled()" not in body, (
            "_on_safety_hazard must NOT check AI automation toggle — "
            "Review fix F11. A future 'add the AI gate for consistency' "
            "PR is the exact regression this test guards against."
        )
        assert "_is_automation_enabled()" not in body, (
            "_on_safety_hazard must NOT check master automation toggle "
            "either — see Review fix F11."
        )

    def test_security_handler_ungated(self, coord_src):
        """CRITICAL: security must NEVER be gated by either toggle.

        Same rationale as safety — Review fix F11.
        """
        body = self._extract_handler_body(coord_src, "_on_security_event")
        assert "_is_ai_automation_enabled()" not in body, (
            "_on_security_event must NOT check AI automation toggle — "
            "Review fix F11."
        )
        assert "_is_automation_enabled()" not in body, (
            "_on_security_event must NOT check master automation toggle — "
            "Review fix F11."
        )


# ---------------------------------------------------------------------------
# Per-room occupancy/lux path stays double-gated (regression check)
# ---------------------------------------------------------------------------

class TestOccupancyLuxPathStaysDoubleGated:
    """The per-room occupancy/lux path in _async_update_data fires
    chained automations only when BOTH toggles are on. This is the
    asymmetric counterpart to the signal-handler gating above."""

    @pytest.fixture
    def coord_src(self):
        with open("custom_components/universal_room_automation/coordinator.py") as f:
            return f.read()

    def test_master_automation_gates_occupancy_path(self, coord_src):
        """The master automation switch wraps the occupancy/lux trigger
        detection in _async_update_data."""
        idx = coord_src.find("elif self._is_automation_enabled():")
        assert idx > 0, (
            "Per-room occupancy/lux path must check _is_automation_enabled() "
            "as a wrapping guard. If this disappears, occupancy triggers "
            "would fire even when master automation is paused."
        )

    def test_ai_toggle_gates_chained_dispatch(self, coord_src):
        """Inside the master-gated block, the dispatch to chained
        automations + AI rules also requires the AI toggle. Both must
        be on for the per-room path."""
        # Look for the inner gate: `if triggers_fired and self._is_ai_automation_enabled():`
        assert (
            "triggers_fired and self._is_ai_automation_enabled()" in coord_src
            or "self._is_ai_automation_enabled() and triggers_fired" in coord_src
        ), (
            "Per-room path must check _is_ai_automation_enabled() before "
            "firing chained automations. Both master + AI toggles required."
        )


# ---------------------------------------------------------------------------
# The GATING MODEL comment block must exist (so future readers find the
# explanation, not just the code)
# ---------------------------------------------------------------------------

class TestGatingModelDocumented:
    @pytest.fixture
    def coord_src(self):
        with open("custom_components/universal_room_automation/coordinator.py") as f:
            return f.read()

    def test_gating_model_comment_block_present(self, coord_src):
        assert "GATING MODEL FOR SIGNAL HANDLERS" in coord_src, (
            "v4.5.8 added a comment block above the signal handlers "
            "explaining the asymmetric gating. If it's gone, future "
            "engineers will mis-read the asymmetry as a bug (this exact "
            "thing happened during the v4.5.7 audit)."
        )

    def test_each_handler_has_gating_docstring(self, coord_src):
        """Each signal handler's docstring must explicitly say which
        toggle gates it (or that NEITHER does)."""
        # Use simple keyword check on each handler's docstring region
        for fn_name in (
            "_on_house_state_changed",
            "_on_energy_constraint",
            "_on_safety_hazard",
            "_on_security_event",
        ):
            idx = coord_src.find(f"def {fn_name}(self, payload)")
            assert idx > 0
            docstring_region = coord_src[idx:idx + 1500]
            assert "Gating:" in docstring_region, (
                f"{fn_name} docstring must declare its gating model "
                f"(start with 'Gating: ...')."
            )
