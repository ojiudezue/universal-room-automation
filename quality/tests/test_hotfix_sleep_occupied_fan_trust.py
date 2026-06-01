"""Hotfix B — Sleep-state occupied fan trust (companion to v4.7.13).

Validates the two surfaces that produce fan turn_off decisions:

Path A — `hvac_fans.py::_evaluate_temp_fan`
  Adds a short-circuit between the manual-off cooldown (~line 322) and
  the occupancy gate (~line 332): while occupied during sleep, the
  temperature off-path is suppressed.

Path B — `automation.py::handle_temperature_based_fan_control`
  Adds a `sleep_occupied_hold` guard on the existing off-condition at
  ~line 1541 so the threshold off-path doesn't fire during sleep with
  occupant present. FAN_SLEEP_OFF policy still wins (returns at line
  1517 before this block).

Triggered by 2026-06-01 00:11 CDT incident: master bedroom PolyFan
turned off mid-sleep when Bryant Z1 preset oscillation pushed
target_high above current room temp, dragging delta to -1°F and
crossing the off-threshold at hvac_fans.py:387.

Source-grep style (matches the v4.7.x convention) — fast, no running
HA required. Runtime behavior covered by post-deploy live validation.
"""

import pytest


@pytest.fixture(scope="module")
def hvac_fans_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/hvac_fans.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def automation_src() -> str:
    with open(
        "custom_components/universal_room_automation/automation.py"
    ) as f:
        return f.read()


class TestPathA_HvacFans:
    """Sleep-state occupied fan trust block in _evaluate_temp_fan."""

    # The new block is the only place with this comment; use it as a
    # unique anchor since the predicate string is also matched by the
    # v3.18.1 sleep-cap line at ~line 240.
    _SLEEP_BLOCK_ANCHOR = "Sleep-state occupied fan trust"

    def test_sleep_occupied_short_circuit_block_exists(self, hvac_fans_src):
        """The block must reference house_state == 'sleep' AND occupied
        AND the bedroom-only room_type gate."""
        idx = hvac_fans_src.find(self._SLEEP_BLOCK_ANCHOR)
        assert idx > 0
        body = hvac_fans_src[idx: idx + 3000]
        assert "and occupied" in body
        assert "room_fan.room_type == ROOM_TYPE_BEDROOM" in body, (
            "v4.7.16.2: sleep+occupied trust must gate on ROOM_TYPE_BEDROOM "
            "to prevent spurious presence in common areas from holding fans on"
        )

    def test_sleep_occupied_block_returns_on_when_running(self, hvac_fans_src):
        """When the fan was already on, preserve the prior trigger + speed."""
        idx = hvac_fans_src.find(self._SLEEP_BLOCK_ANCHOR)
        assert idx > 0
        body = hvac_fans_src[idx: idx + 3000]
        assert "if room_fan.is_on:" in body
        assert "room_fan.speed_pct" in body
        # Reviewer A fix-up B-M2: distinct labels for hold vs activate.
        # Preserve prior trigger when present; fall back to the hold label
        # only when trigger is truly empty (post-reload window).
        assert "room_fan.trigger or \"sleep_occupied_hold\"" in body

    def test_sleep_occupied_block_activates_off_fan_at_low(self, hvac_fans_src):
        """When fan was off, activate at LOW with `sleep_occupied_activate`
        label (v3.18.1 sleep cap will enforce LOW anyway; being explicit
        makes the intent clear). Distinct from `sleep_occupied_hold`
        which is used only when preserving a running fan with no prior
        trigger — distinct labels for audit fidelity (Reviewer A B-M2)."""
        idx = hvac_fans_src.find(self._SLEEP_BLOCK_ANCHOR)
        body = hvac_fans_src[idx: idx + 3000]
        assert "FAN_SPEED_LOW_PCT" in body
        assert '"sleep_occupied_activate"' in body
        assert '"sleep_occupied_hold"' in body

    def test_sleep_occupied_runs_before_occupancy_gate(self, hvac_fans_src):
        """Placement: AFTER manual-off cooldown (preserves user override)
        and BEFORE the occupancy gate (so it short-circuits temperature
        evaluation entirely when sleep+occupied)."""
        cooldown_idx = hvac_fans_src.find(
            "manual_off_cooldown_until"
        )
        sleep_block_idx = hvac_fans_src.find(self._SLEEP_BLOCK_ANCHOR)
        occupancy_gate_idx = hvac_fans_src.find(
            "Occupancy gate: don't activate fans in unoccupied rooms"
        )
        assert 0 < cooldown_idx < sleep_block_idx < occupancy_gate_idx, (
            "sleep-occupied trust must be between manual cooldown and "
            "occupancy gate"
        )

    def test_sleep_occupied_block_clears_stale_vacancy_anchor(self, hvac_fans_src):
        """Reviewer B fix-up B-MED-1: the new sleep+occupied branch must
        clear `vacancy_detected_time` before returning.

        Without this, a prior unoccupied tick's anchor persists through
        the sleep+occupied window; on subsequent re-vacancy mid-night,
        the vacancy timer would compute `vacancy_seconds` from a stale
        timestamp and bypass DEFAULT_FAN_VACANCY_HOLD instantly — fan
        would turn off the moment occupancy drops instead of honoring
        the grace window.
        """
        idx = hvac_fans_src.find(self._SLEEP_BLOCK_ANCHOR)
        body = hvac_fans_src[idx: idx + 3000]
        assert 'room_fan.vacancy_detected_time = ""' in body, (
            "sleep+occupied short-circuit must clear vacancy_detected_time "
            "to prevent stale anchor (Reviewer B B-MED-1)"
        )

    def test_room_type_field_on_room_fan_state(self, hvac_fans_src):
        """RoomFanState must carry the per-room CONF_ROOM_TYPE so the
        sleep-trust predicate can gate on bedroom."""
        # Dataclass field declared with safe default
        assert "room_type: str = ROOM_TYPE_GENERIC" in hvac_fans_src
        # Threaded through discover_fans() at construction
        assert "room_type=merged.get(CONF_ROOM_TYPE, ROOM_TYPE_GENERIC)" in hvac_fans_src

    def test_room_type_constants_imported(self, hvac_fans_src):
        """ROOM_TYPE_BEDROOM + ROOM_TYPE_GENERIC + CONF_ROOM_TYPE imported
        from the canonical const surface (not hard-coded as bare strings)."""
        # Confirm import block contains the symbols (substring is sufficient —
        # the import is grouped under `from ..const import (...)`)
        for sym in ("CONF_ROOM_TYPE", "ROOM_TYPE_BEDROOM", "ROOM_TYPE_GENERIC"):
            assert sym in hvac_fans_src


class TestPathB_AutomationEngine:
    """Sleep-state occupied fan trust guard in handle_temperature_based_fan_control."""

    # Multi-line `sleep_occupied_hold = (...)` after bedroom-gate addition;
    # anchor on the assignment LHS instead of the full literal expression.
    _HOLD_ANCHOR = "sleep_occupied_hold"

    def test_sleep_occupied_hold_uses_sleep_occupied_and_bedroom(self, automation_src):
        """The guard reads is_sleep_mode_active() AND occupied AND
        room_type == ROOM_TYPE_BEDROOM."""
        idx = automation_src.find(f"{self._HOLD_ANCHOR} = (")
        # Fall back to single-line form if the predicate is ever inlined
        if idx < 0:
            idx = automation_src.find(f"{self._HOLD_ANCHOR} =")
        assert idx > 0
        body = automation_src[idx: idx + 400]
        assert "self.is_sleep_mode_active()" in body
        assert "and occupied" in body
        assert "and room_type == ROOM_TYPE_BEDROOM" in body, (
            "v4.7.16.2: Path B sleep_occupied_hold must gate on ROOM_TYPE_BEDROOM "
            "to prevent common-area fans from being held on mid-night"
        )

    def test_off_condition_gated_by_sleep_occupied_hold(self, automation_src):
        """The existing off-branch (temperature < threshold OR not occupied)
        must now be gated by `and not sleep_occupied_hold`."""
        assert (
            "if (temperature < effective_threshold or not occupied) "
            "and not sleep_occupied_hold:"
        ) in automation_src

    def test_fan_sleep_off_policy_still_wins(self, automation_src):
        """FAN_SLEEP_OFF policy returns early at line ~1517 BEFORE the new
        guard runs, so explicit user opt-out is preserved."""
        fan_sleep_off_idx = automation_src.find('policy == FAN_SLEEP_OFF')
        guard_idx = automation_src.find(f"{self._HOLD_ANCHOR} =")
        assert fan_sleep_off_idx > 0
        assert guard_idx > 0
        assert fan_sleep_off_idx < guard_idx, (
            "FAN_SLEEP_OFF early-return must precede sleep_occupied_hold "
            "guard so explicit user OFF policy still wins"
        )

    def test_room_type_constants_imported_in_automation(self, automation_src):
        """Path B reads CONF_ROOM_TYPE and compares to ROOM_TYPE_BEDROOM —
        symbols must be imported from the canonical const surface."""
        for sym in ("CONF_ROOM_TYPE", "ROOM_TYPE_BEDROOM", "ROOM_TYPE_GENERIC"):
            assert sym in automation_src


class TestOrthogonalPathsNotTouched:
    """Sanity: paths C (humidity) and D (pre-arrival defan) must NOT be
    affected by this hotfix. We verify by absence of the new identifier."""

    def test_humidity_fan_path_unchanged(self, automation_src):
        """handle_humidity_based_fan_control must NOT reference
        sleep_occupied_hold — humidity is a different concern."""
        # Find function boundary
        idx = automation_src.find("async def handle_humidity_based_fan_control")
        assert idx > 0
        # Read until next 'async def ' or class boundary (~3000 chars typical)
        next_def = automation_src.find("async def ", idx + 100)
        if next_def < 0:
            next_def = idx + 6000
        body = automation_src[idx: next_def]
        assert "sleep_occupied_hold" not in body

    def test_hvac_fans_humidity_fan_path_unchanged(self, hvac_fans_src):
        """_evaluate_humidity_fan must NOT reference sleep-occupied trust."""
        idx = hvac_fans_src.find("def _evaluate_humidity_fan")
        assert idx > 0
        next_def = hvac_fans_src.find("    def _", idx + 50)
        body = hvac_fans_src[idx: next_def]
        assert "sleep_occupied" not in body
