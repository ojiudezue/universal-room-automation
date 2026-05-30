"""v4.7.9 — Hygiene Bundle.

Three concern groups bundled (Tier 2-DB cycle):

  D1 (Group A) — per-zone Force AC Reset button.
    - New `_AC_RAMP_BUTTON_SPECS["force_ac_reset"]` entry (parameterizes
      the existing `_ACRampButton` class — no new class).
    - New `OverrideArrester.force_ac_reset` method bridging into
      `_perform_hard_reset_escalation(zone, kwh_rate_now=0.0)`.
    - A3 guard inside escalation cleanly no-ops when `_ac_reset_enabled`
      is False (helper text says "Requires AC Reset switch ON").
    - Strings + translations for `entity.button.hvac_force_ac_reset`.

  D2 (Group B) — SIGNAL_DPM_SKIP_REASONS_UPDATED.
    - New `Final` constant in `signals.py`.
    - Edge-detection in `energy.py:_async_evaluate_dynamic_presets`
      against `_dynamic_preset_skip_reasons_prev` (init `{}` in
      `__init__`); fires only when reasons dict changes between ticks.
    - Third dispatcher subscription on
      `DynamicPresetOverridesAppliedSensor.async_added_to_hass`, tracked
      via `async_on_remove` (Bug Class #38).

  D3 (Group C) — DPM zone-skip taxonomy coverage tests for all 6 reasons.
    - Live MCP probe at build start was attempted; HA endpoint
      authentication was unavailable from the build agent shell, so
      Group C ships as tests-only per planning §4 fallback. All 6 reason
      types are exercised below.

Source-grep style (matches project convention, fast, no running HA) plus
small behavioral mirrors for `force_ac_reset` and the edge-detection
state machine — same shape as
`test_v477_ac_nudge_decouple_and_dpm_cleanup.py`.
"""

from __future__ import annotations

import ast
import json
import os
import re
from unittest.mock import MagicMock

import pytest


# ============================================================================
# Source fixtures (module-scoped, read once)
# ============================================================================

ROOT = "custom_components/universal_room_automation"
BUTTON_PY = os.path.join(ROOT, "button.py")
SENSOR_PY = os.path.join(ROOT, "sensor.py")
SIGNALS_PY = os.path.join(ROOT, "domain_coordinators", "signals.py")
ENERGY_PY = os.path.join(ROOT, "domain_coordinators", "energy.py")
HVAC_OVERRIDE_PY = os.path.join(ROOT, "domain_coordinators", "hvac_override.py")
DYN_PRESET_PY = os.path.join(ROOT, "domain_coordinators", "dynamic_preset.py")
STRINGS_JSON = os.path.join(ROOT, "strings.json")
EN_JSON = os.path.join(ROOT, "translations", "en.json")


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


@pytest.fixture(scope="module")
def button_src() -> str:
    return _read(BUTTON_PY)


@pytest.fixture(scope="module")
def sensor_src() -> str:
    return _read(SENSOR_PY)


@pytest.fixture(scope="module")
def signals_src() -> str:
    return _read(SIGNALS_PY)


@pytest.fixture(scope="module")
def energy_src() -> str:
    return _read(ENERGY_PY)


@pytest.fixture(scope="module")
def override_src() -> str:
    return _read(HVAC_OVERRIDE_PY)


@pytest.fixture(scope="module")
def dyn_preset_src() -> str:
    return _read(DYN_PRESET_PY)


# ============================================================================
# D1 Group A — `force_ac_reset` button SPEC + arrester method presence
# ============================================================================


class TestD1ForceAcResetButtonSpec:
    """Group A: a new entry in `_AC_RAMP_BUTTON_SPECS` keyed `force_ac_reset`
    that parameterizes the existing `_ACRampButton` class. NO new button class.
    """

    def test_spec_key_present(self, button_src):
        assert '"force_ac_reset"' in button_src, (
            "D1: _AC_RAMP_BUTTON_SPECS must include a 'force_ac_reset' key"
        )

    def test_spec_label(self, button_src):
        # Locate the spec dict slice for force_ac_reset.
        idx = button_src.find('"force_ac_reset":')
        assert idx > 0
        block = button_src[idx:idx + 400]
        assert '"label": "Force AC Reset"' in block

    def test_spec_method_name(self, button_src):
        idx = button_src.find('"force_ac_reset":')
        block = button_src[idx:idx + 400]
        assert '"method": "force_ac_reset"' in block, (
            "D1: spec must route to OverrideArrester.force_ac_reset"
        )

    def test_spec_category_none(self, button_src):
        idx = button_src.find('"force_ac_reset":')
        block = button_src[idx:idx + 400]
        assert '"category": None' in block, (
            "D1: Force AC Reset is a primary user-facing action; "
            "category must be None (mirrors force_nudge)"
        )

    def test_spec_action_offset_4(self, button_src):
        idx = button_src.find('"force_ac_reset":')
        block = button_src[idx:idx + 400]
        assert '"action_offset": 4' in block, (
            "D1: action_offset must be 4 -> zone-1 prefix 24, sits after "
            "force_nudge (offset 0 -> 20) and cancel_nudge (offset 2 -> 22)"
        )

    def test_spec_cluster_controls(self, button_src):
        idx = button_src.find('"force_ac_reset":')
        block = button_src[idx:idx + 400]
        assert '"cluster": "controls"' in block

    def test_no_new_button_class(self, button_src):
        # Reuse-only: no `class _ForceAcResetButton` or similar.
        for forbidden in ("class _ForceAcResetButton", "class ForceAcResetButton"):
            assert forbidden not in button_src, (
                "D1: must NOT introduce a new button class; parameterize "
                "_ACRampButton via _AC_RAMP_BUTTON_SPECS instead"
            )


class TestD1ForceAcResetButtonRegistration:
    """Group A: the per-zone loop in async_setup_entry must register the
    new action alongside the existing three actions."""

    def test_force_ac_reset_call_present(self, button_src):
        # Search for the make-call referencing the new action literal.
        assert re.search(
            r'_make_ac_ramp_button\(\s*hass,\s*entry,\s*zone_spec,\s*"force_ac_reset",\s*zone_index,?\s*\)',
            button_src,
        ), (
            "D1: per-zone loop must include _make_ac_ramp_button(..., "
            "'force_ac_reset', zone_index)"
        )

    def test_registration_order_after_cancel_before_clear(self, button_src):
        # The registration block sits AFTER cancel_nudge and BEFORE
        # clear_lockout in the per-zone loop. This is the Controls-cluster
        # ordering: force_nudge -> cancel_nudge -> force_ac_reset (new) ->
        # clear_lockout (Config cluster, fixed prefix 95).
        cancel_idx = button_src.find('"cancel_nudge", zone_index')
        force_reset_idx = button_src.find('"force_ac_reset", zone_index')
        clear_idx = button_src.find('"clear_lockout", zone_index')
        assert 0 < cancel_idx < force_reset_idx < clear_idx, (
            "D1: registration order must be cancel_nudge -> force_ac_reset "
            "-> clear_lockout in the per-zone loop"
        )

    def test_unique_id_format_via_existing_class(self, button_src):
        # The existing _ACRampButton class composes unique_id as
        # f"{DOMAIN}_hvac_ac_ramp_{action}_{zone_id}". The action literal
        # "force_ac_reset" plugs in, producing
        # f"{DOMAIN}_hvac_ac_ramp_force_ac_reset_{zone_id}" — exactly the
        # planning spec.
        assert 'f"{DOMAIN}_hvac_ac_ramp_{action}_{zone_id}"' in button_src, (
            "D1: existing _ACRampButton unique_id format must be unchanged "
            "(planning spec relies on it to produce "
            "f'{DOMAIN}_hvac_ac_ramp_force_ac_reset_{zone_id}')"
        )


class TestD1ForceAcResetArresterMethod:
    """Group A: OverrideArrester.force_ac_reset bridges into
    _perform_hard_reset_escalation. Signature is FIXED: no `triggered_by`."""

    def test_method_defined(self, override_src):
        assert "async def force_ac_reset(" in override_src, (
            "D1: OverrideArrester must define async force_ac_reset"
        )

    def test_method_signature_takes_one_string(self, override_src):
        # Match the def line — accept either `zone_id_or_entity: str` or a
        # close variant. Critical bit: there's exactly one positional
        # parameter besides self.
        m = re.search(
            r"async def force_ac_reset\(\s*self,\s*(\w+)\s*:\s*str\s*\)",
            override_src,
        )
        assert m, (
            "D1: force_ac_reset must take (self, <id>: str). "
            "Found signature did not match."
        )

    def test_master_switch_gate(self, override_src):
        # Locate the method body.
        idx = override_src.find("async def force_ac_reset(")
        body = override_src[idx:idx + 2000]
        assert "_ramp_master_enabled" in body, (
            "D1: master switch (kill-switch contract) must be checked"
        )
        assert "force_ac_reset blocked: master switch is OFF" in body, (
            "D1: master-off log message must mirror force_nudge precedent"
        )

    def _force_ac_reset_body(self, override_src: str) -> str:
        # Slice from `async def force_ac_reset(` to the next top-level
        # `async def`/`def` at 4-space indent (end of method). Wide enough
        # to span long docstrings.
        idx = override_src.find("async def force_ac_reset(")
        assert idx > 0
        # Find the next method def at the same indent (4 spaces).
        m = re.search(r"\n    (async def|def) \w+\(", override_src[idx + 1:])
        if m is None:
            return override_src[idx:]
        return override_src[idx:idx + 1 + m.start()]

    def test_resolves_zone_via_existing_helper(self, override_src):
        body = self._force_ac_reset_body(override_src)
        assert "self._resolve_zone(" in body, (
            "D1: must use _resolve_zone to bridge climate_entity -> ZoneState"
        )

    def test_routes_to_perform_hard_reset_escalation(self, override_src):
        body = self._force_ac_reset_body(override_src)
        assert "_perform_hard_reset_escalation" in body, (
            "D1: must delegate to _perform_hard_reset_escalation"
        )

    def test_passes_zero_kwh_rate(self, override_src):
        # Per plan §D1 spec: manual press isn't reacting to a reading;
        # kwh_rate_now=0.0 is the explicit choice.
        body = self._force_ac_reset_body(override_src)
        assert re.search(
            r"_perform_hard_reset_escalation\(\s*zone\s*,\s*0\.0\s*\)",
            body,
        ), (
            "D1: must call _perform_hard_reset_escalation(zone, 0.0) — "
            "kwh_rate_now=0.0 for manual press (not reacting to a reading)"
        )

    def test_no_triggered_by_parameter_added(self, override_src):
        # Plan §D1 out-of-scope decision: do NOT change
        # _perform_hard_reset_escalation signature.
        # Match across the multi-line signature (typed params).
        m = re.search(
            r"async def _perform_hard_reset_escalation\((.*?)\)\s*->",
            override_src,
            re.DOTALL,
        )
        assert m is not None, (
            "method _perform_hard_reset_escalation must exist with a "
            "return annotation"
        )
        sig = m.group(1)
        assert "triggered_by" not in sig, (
            "D1: planning §D1 explicitly says do NOT add triggered_by "
            "to _perform_hard_reset_escalation"
        )


class TestD1StringsAndTranslations:
    """Group A: helper text per planning §D1 must be present in
    strings.json AND translations/en.json under entity.button.hvac_force_ac_reset.
    """

    EXPECTED_DESCRIPTION = (
        "Manually trigger a hard AC reset for this zone. "
        "Requires AC Reset switch ON. Subject to daily cap and "
        "minimum interval gates. Use when soft-nudge auto-detection is "
        "disabled and you want to manually clear a stuck AC cycle."
    )

    def test_strings_button_section_present(self):
        strings = json.loads(_read(STRINGS_JSON))
        button_section = strings.get("entity", {}).get("button", {})
        assert "hvac_force_ac_reset" in button_section, (
            "D1: strings.json must include entity.button.hvac_force_ac_reset"
        )

    def test_strings_name_and_description(self):
        strings = json.loads(_read(STRINGS_JSON))
        entry = strings["entity"]["button"]["hvac_force_ac_reset"]
        assert entry["name"] == "Force AC Reset"
        assert entry["description"] == self.EXPECTED_DESCRIPTION

    def test_translations_mirror_strings(self):
        en = json.loads(_read(EN_JSON))
        assert (
            "hvac_force_ac_reset"
            in en.get("entity", {}).get("button", {})
        ), "D1: translations/en.json must mirror strings.json"
        entry = en["entity"]["button"]["hvac_force_ac_reset"]
        assert entry["name"] == "Force AC Reset"
        assert entry["description"] == self.EXPECTED_DESCRIPTION


# ============================================================================
# D1 Group A — Behavioral mirror tests for force_ac_reset gates
# ============================================================================


class _MockZone:
    """Stand-in for ZoneState — only the attrs force_ac_reset / escalation
    actually read."""

    def __init__(self, zone_id="zone_1", zone_name="Test Zone",
                 climate_entity="climate.test_zone"):
        self.zone_id = zone_id
        self.zone_name = zone_name
        self.climate_entity = climate_entity
        self.ramp_state = "IDLE"  # AC_RAMP_STATE_IDLE
        self.ac_reset_count_today = 0
        self.nudge_kwh_rate_before = None


class _ForceAcResetMirror:
    """Mirror of OverrideArrester.force_ac_reset gate logic.

    Mirrors the structure documented in the production method docstring:
      Gate 1: master switch (kill-switch contract).
      Gate 2: _resolve_zone (returns None -> no-op, no exception).
      Gate 3: A3 guard inside _perform_hard_reset_escalation (mocked here).
    """

    def __init__(
        self,
        *,
        master_enabled: bool = True,
        ac_reset_enabled: bool = True,
        zones: dict | None = None,
    ):
        self._ramp_master_enabled = master_enabled
        self._ac_reset_enabled = ac_reset_enabled
        self._zones = zones or {}
        # Captures for assertions.
        self.escalation_calls: list[tuple] = []
        self.master_block_logged = False
        self.zone_missing_logged = False
        self.a3_skipped_logged = False

    def _resolve_zone(self, key):
        return self._zones.get(key)

    async def _perform_hard_reset_escalation(self, zone, kwh_rate_now):
        """Mirror of the real method's A3 guard (production L1549-1556)."""
        self.escalation_calls.append((zone.zone_id, kwh_rate_now))
        if not self._ac_reset_enabled:
            zone.ramp_state = "IDLE"  # AC_RAMP_STATE_IDLE
            self.a3_skipped_logged = True
            return
        # Real method continues into DB writes + actuation — out of scope
        # for this mirror, which only verifies the bridge contract.

    async def force_ac_reset(self, key):
        if not self._ramp_master_enabled:
            self.master_block_logged = True
            return
        zone = self._resolve_zone(key)
        if zone is None:
            self.zone_missing_logged = True
            return
        await self._perform_hard_reset_escalation(zone, 0.0)


class TestD1ForceAcResetBehavior:
    """Behavioral mirror tests for the gate sequence."""

    @pytest.mark.asyncio
    async def test_master_off_blocks_without_escalation(self):
        zone = _MockZone()
        mirror = _ForceAcResetMirror(
            master_enabled=False, zones={"climate.test_zone": zone},
        )
        await mirror.force_ac_reset("climate.test_zone")
        assert mirror.master_block_logged is True
        assert mirror.escalation_calls == []

    @pytest.mark.asyncio
    async def test_unknown_zone_no_op_no_exception(self):
        mirror = _ForceAcResetMirror(zones={})
        await mirror.force_ac_reset("climate.does_not_exist")
        assert mirror.zone_missing_logged is True
        assert mirror.escalation_calls == []

    @pytest.mark.asyncio
    async def test_happy_path_routes_to_escalation_with_zero_kwh(self):
        zone = _MockZone()
        mirror = _ForceAcResetMirror(
            ac_reset_enabled=True, zones={"climate.test_zone": zone},
        )
        await mirror.force_ac_reset("climate.test_zone")
        # Exactly one escalation call with kwh_rate_now == 0.0
        assert mirror.escalation_calls == [(zone.zone_id, 0.0)]
        assert mirror.a3_skipped_logged is False

    @pytest.mark.asyncio
    async def test_a3_guard_no_op_when_reset_disabled(self):
        # Group A planning: "A3 guard handles _ac_reset_enabled=False
        # cleanly — no-op when AC Reset off."
        zone = _MockZone()
        mirror = _ForceAcResetMirror(
            ac_reset_enabled=False, zones={"climate.test_zone": zone},
        )
        await mirror.force_ac_reset("climate.test_zone")
        # Escalation IS entered (master+resolve gates passed) but the
        # internal A3 guard short-circuits without DB writes.
        assert len(mirror.escalation_calls) == 1
        assert mirror.a3_skipped_logged is True
        assert zone.ramp_state == "IDLE"

    @pytest.mark.asyncio
    async def test_resolve_zone_accepts_climate_entity(self):
        # Existing _resolve_zone (production L1649-1667) accepts either
        # zone_id OR climate_entity. The button passes climate_entity.
        zone = _MockZone(zone_id="zone_3", climate_entity="climate.living_room")
        mirror = _ForceAcResetMirror(
            zones={"climate.living_room": zone, "zone_3": zone},
        )
        # Press path: climate entity key.
        await mirror.force_ac_reset("climate.living_room")
        assert len(mirror.escalation_calls) == 1


class TestD1ForceAcResetAH1NudgeCleanup:
    """A-H1 fix-up regression: force_ac_reset must cancel in-flight nudge
    timers + clear nudge in-flight state BEFORE entering escalation.

    Without this, a still-active soft-nudge's restore/eval timer fires on
    top of the reset's off->wait->restore cycle (race: nudge restore
    writes a setpoint while the reset's off-state is in flight).

    The test is split between (a) a source-grep guard for the cleanup
    code being present and ordered BEFORE the escalation call, and (b) a
    behavioral mirror that asserts the cleanup ordering against a fake
    that tracks timer cancels + escalation calls.
    """

    def test_force_ac_reset_cancels_nudge_timers_before_escalation(
        self, override_src
    ):
        # Source-grep: the cleanup MUST appear inside the force_ac_reset
        # method body BEFORE the `_perform_hard_reset_escalation` call.
        # Otherwise an in-flight nudge restore timer can fire mid-reset.
        # Find the method body via the docstring anchor (most stable
        # delimiter — the canonical "(v4.7.9 D1 button)" marker).
        anchor = "User-triggered hard AC reset (v4.7.9 D1 button)"
        assert anchor in override_src
        start = override_src.index(anchor)
        # Method body ends at the next "    async def " sibling.
        end_marker = "\n    async def "
        end = override_src.index(end_marker, start)
        body = override_src[start:end]
        # Required cleanup statements (mirror of cancel_nudge L1680-1686).
        assert "self._nudge_restore_timers.pop(" in body, (
            "A-H1: force_ac_reset must pop the in-flight restore timer "
            "before escalation"
        )
        assert "self._nudge_eval_timers.pop(" in body, (
            "A-H1: force_ac_reset must pop the in-flight eval timer "
            "before escalation"
        )
        assert "self._nudge_in_flight.discard(" in body, (
            "A-H1: force_ac_reset must discard the zone from "
            "_nudge_in_flight before escalation"
        )
        assert "clear_ac_in_flight_nudge(" in body, (
            "A-H1: force_ac_reset must clear the persisted nudge row "
            "before escalation"
        )
        # Ordering: cleanup MUST precede the escalation call.
        cleanup_idx = body.index("self._nudge_in_flight.discard(")
        escalation_idx = body.index("_perform_hard_reset_escalation(")
        assert cleanup_idx < escalation_idx, (
            "A-H1: nudge-state cleanup must execute BEFORE the "
            "escalation call, not after"
        )

    @pytest.mark.asyncio
    async def test_behavioral_cleanup_before_escalation(self):
        # Behavioral mirror — assert that a fake force_ac_reset clears
        # nudge in-flight state BEFORE the escalation is invoked. This
        # exercises the exact ordering A-H1 demands.

        class _CleanupOrderMirror:
            def __init__(self, zone, in_flight_nudge_present=True):
                self._zone = zone
                self._nudge_restore_timers = {}
                self._nudge_eval_timers = {}
                self._nudge_in_flight = set()
                self._db_cleared = False
                self._escalation_state_at_call = None
                self.restore_cancel_called = False
                self.eval_cancel_called = False
                if in_flight_nudge_present:
                    self._nudge_in_flight.add(zone.zone_id)
                    # Fake timer handles — closures capture flags so we
                    # can prove the cancel callable was invoked.
                    def _cancel_restore():
                        self.restore_cancel_called = True
                    def _cancel_eval():
                        self.eval_cancel_called = True
                    self._nudge_restore_timers[zone.zone_id] = _cancel_restore
                    self._nudge_eval_timers[zone.zone_id] = _cancel_eval

            def _resolve_zone(self, key):
                return self._zone

            async def _perform_hard_reset_escalation(self, zone, kwh_rate):
                # Capture nudge state AT THE MOMENT escalation runs.
                self._escalation_state_at_call = {
                    "in_flight": zone.zone_id in self._nudge_in_flight,
                    "restore_timer": zone.zone_id in self._nudge_restore_timers,
                    "eval_timer": zone.zone_id in self._nudge_eval_timers,
                    "db_cleared": self._db_cleared,
                }

            async def force_ac_reset(self, key):
                # Mirror of production cleanup-then-escalate ordering.
                zone = self._resolve_zone(key)
                if zone is None:
                    return
                zone_id = zone.zone_id
                cancel_restore = self._nudge_restore_timers.pop(zone_id, None)
                if cancel_restore:
                    cancel_restore()
                cancel_eval = self._nudge_eval_timers.pop(zone_id, None)
                if cancel_eval:
                    cancel_eval()
                self._nudge_in_flight.discard(zone_id)
                self._db_cleared = True
                await self._perform_hard_reset_escalation(zone, 0.0)

        zone = _MockZone()
        mirror = _CleanupOrderMirror(zone, in_flight_nudge_present=True)
        # Sanity — nudge is in-flight pre-press.
        assert zone.zone_id in mirror._nudge_in_flight
        assert zone.zone_id in mirror._nudge_restore_timers
        assert zone.zone_id in mirror._nudge_eval_timers

        await mirror.force_ac_reset(zone.zone_id)

        # Both cancel callables were invoked.
        assert mirror.restore_cancel_called is True
        assert mirror.eval_cancel_called is True
        # Escalation observed nudge state ALREADY cleared.
        assert mirror._escalation_state_at_call is not None
        snap = mirror._escalation_state_at_call
        assert snap["in_flight"] is False, (
            "A-H1: _nudge_in_flight must be empty when escalation runs"
        )
        assert snap["restore_timer"] is False, (
            "A-H1: restore timer dict must be empty when escalation runs"
        )
        assert snap["eval_timer"] is False, (
            "A-H1: eval timer dict must be empty when escalation runs"
        )
        assert snap["db_cleared"] is True, (
            "A-H1: persisted in-flight nudge row must be cleared before "
            "escalation runs"
        )


class TestAM1TranslationKeyOnForceAcResetButton:
    """A-M1 / C-M1 fix-up: _ACRampButton must set _attr_translation_key for
    the force_ac_reset variant so the existing strings.json/en.json entry
    surfaces in the HA frontend."""

    def test_translation_key_set_for_force_ac_reset(self, button_src):
        # Source-grep: the assignment must reference the strings.json
        # key literally so the helper text is reachable.
        assert '_attr_translation_key = "hvac_force_ac_reset"' in button_src, (
            "A-M1/C-M1: _ACRampButton must set _attr_translation_key = "
            "'hvac_force_ac_reset' for the force_ac_reset variant"
        )

    def test_translation_key_matches_strings_json(self, button_src):
        # Round-trip check: the key in code must match the key in
        # strings.json (and translations/en.json). Drift here is the
        # bug C-M1 was originally flagging.
        import json
        import os
        base = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation",
        )
        with open(os.path.join(base, "strings.json")) as f:
            strings = json.load(f)
        with open(os.path.join(base, "translations", "en.json")) as f:
            en = json.load(f)
        assert "hvac_force_ac_reset" in strings["entity"]["button"]
        assert "hvac_force_ac_reset" in en["entity"]["button"]
        # And the source uses the same key.
        assert '"hvac_force_ac_reset"' in button_src


# ============================================================================
# D2 Group B — SIGNAL_DPM_SKIP_REASONS_UPDATED constant + edge detection
# ============================================================================


class TestD2SignalConstantDefined:
    """Group B: the new signal must be a module-level Final constant in
    signals.py with the planned literal value."""

    def test_constant_name_present(self, signals_src):
        assert "SIGNAL_DPM_SKIP_REASONS_UPDATED" in signals_src

    def test_constant_value(self, signals_src):
        # Expect: SIGNAL_DPM_SKIP_REASONS_UPDATED: Final = "ura_dpm_skip_reasons_updated"
        m = re.search(
            r'SIGNAL_DPM_SKIP_REASONS_UPDATED\s*:\s*Final\s*=\s*"([^"]+)"',
            signals_src,
        )
        assert m, "D2: constant must be typed as Final and assigned a string"
        assert m.group(1) == "ura_dpm_skip_reasons_updated", (
            "D2: literal value must match planning §6"
        )

    def test_module_level_definition(self, signals_src):
        # AST-walk: constant must be at module top level (not inside a class
        # or function).
        tree = ast.parse(signals_src)
        found = False
        for node in tree.body:
            # Plain assignment OR AnnAssign at module scope.
            if isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and (
                    node.target.id == "SIGNAL_DPM_SKIP_REASONS_UPDATED"
                ):
                    found = True
                    break
        assert found, (
            "D2: SIGNAL_DPM_SKIP_REASONS_UPDATED must be a module-level "
            "AnnAssign (Final-typed)"
        )


class TestD2EnergyEdgeDetection:
    """Group B: energy.py must:
      - init `_dynamic_preset_skip_reasons_prev` to `{}` in __init__.
      - after the existing overrides _changed block, edge-detect on the
        new prev attr and fire SIGNAL_DPM_SKIP_REASONS_UPDATED only when
        the reasons dict actually changed.
    """

    def test_prev_attr_initialized(self, energy_src):
        assert (
            "self._dynamic_preset_skip_reasons_prev: dict[str, str] = {}"
            in energy_src
        ), (
            "D2: __init__ must init _dynamic_preset_skip_reasons_prev to {}"
        )

    def test_edge_detection_uses_prev_snapshot(self, energy_src):
        assert (
            "self._dynamic_preset_skip_reasons_prev != updated_skip_reasons"
            in energy_src
        ), (
            "D2: edge detection must compare prev snapshot against "
            "updated_skip_reasons"
        )

    def test_signal_imported_and_dispatched(self, energy_src):
        assert "from .signals import SIGNAL_DPM_SKIP_REASONS_UPDATED" in energy_src
        assert (
            "async_dispatcher_send(self.hass, SIGNAL_DPM_SKIP_REASONS_UPDATED)"
            in energy_src
        )

    def test_snapshot_after_compare_for_next_tick(self, energy_src):
        # The snapshot of the new state must be taken AFTER comparison,
        # not before, so the next tick's compare is correct. Use
        # dict() copy to break aliasing with _dynamic_preset_skip_reasons.
        assert (
            "self._dynamic_preset_skip_reasons_prev = dict(updated_skip_reasons)"
            in energy_src
        ), (
            "D2: snapshot copy must use dict(updated_skip_reasons) AFTER "
            "the comparison (avoid aliasing the live attr)"
        )


# ============================================================================
# D2 Group B — Edge-detection state-machine behavioral tests
# ============================================================================


class _SkipReasonEdgeDetector:
    """Mirror of the four (overrides_changed × reasons_changed) cases.

    Encapsulates the production edge-detection logic so the behavior can be
    exercised against a tick sequence without spinning up EnergyCoordinator.
    """

    def __init__(self):
        self._overrides = {}
        self._reasons = {}
        self._reasons_prev = {}
        self.fires: list[str] = []  # ordered list of signal labels fired

    def tick(self, new_overrides: dict, new_reasons: dict) -> None:
        prev_overrides = self._overrides
        # Production edge detection — overrides side.
        _changed = set(new_overrides.keys()) != set(prev_overrides.keys())
        if not _changed:
            for zid, new_ovs in new_overrides.items():
                old_ovs = prev_overrides.get(zid, [])
                if new_ovs != old_ovs:
                    _changed = True
                    break
        self._overrides = new_overrides
        self._reasons = new_reasons
        if _changed:
            self.fires.append("SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED")

        # Production edge detection — reasons side (compare-then-snapshot).
        _reasons_changed = self._reasons_prev != new_reasons
        self._reasons_prev = dict(new_reasons)
        if _reasons_changed:
            self.fires.append("SIGNAL_DPM_SKIP_REASONS_UPDATED")


class TestD2EdgeDetectionBehavior:
    """Walks the four combinations of (overrides_changed × reasons_changed)."""

    def test_first_tick_empty_no_spurious_fire(self):
        # First tick with both dicts empty: no signals.
        det = _SkipReasonEdgeDetector()
        det.tick({}, {})
        assert det.fires == []

    def test_first_tick_with_reason_fires_once(self):
        # First tick with a non-empty reasons dict: legit first-real-state.
        det = _SkipReasonEdgeDetector()
        det.tick({}, {"zone_1": "dwell_pending"})
        # overrides dict didn't change (still empty); reasons did.
        assert det.fires == ["SIGNAL_DPM_SKIP_REASONS_UPDATED"]

    def test_reason_only_change_fires_only_reasons_signal(self):
        det = _SkipReasonEdgeDetector()
        det.tick({}, {"zone_1": "dwell_pending"})
        det.fires.clear()
        # Reason transitions on the same zone; overrides still empty.
        det.tick({}, {"zone_1": "unknown_bucket"})
        assert det.fires == ["SIGNAL_DPM_SKIP_REASONS_UPDATED"]

    def test_no_change_no_fire(self):
        det = _SkipReasonEdgeDetector()
        det.tick({}, {"zone_1": "dwell_pending"})
        det.fires.clear()
        det.tick({}, {"zone_1": "dwell_pending"})
        assert det.fires == []

    def test_overrides_only_change_fires_only_overrides_signal(self):
        det = _SkipReasonEdgeDetector()
        det.tick({}, {})
        det.fires.clear()
        det.tick({"zone_1": ["some_override_obj"]}, {})
        assert det.fires == ["SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED"]

    def test_both_change_both_signals_fire(self):
        det = _SkipReasonEdgeDetector()
        det.tick({}, {"zone_1": "dwell_pending"})
        det.fires.clear()
        # Overrides dict gains a key AND a different zone gains a reason.
        det.tick(
            {"zone_2": ["ov"]},
            {"zone_1": "dwell_pending", "zone_3": "unknown_bucket"},
        )
        assert "SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED" in det.fires
        assert "SIGNAL_DPM_SKIP_REASONS_UPDATED" in det.fires


# ============================================================================
# D2 Group B — Sensor subscription wiring
# ============================================================================


class TestD2SensorSubscription:
    """Group B: DynamicPresetOverridesAppliedSensor.async_added_to_hass must
    add a third subscription to SIGNAL_DPM_SKIP_REASONS_UPDATED with tracked
    unsub via async_on_remove (Bug Class #38)."""

    def _sensor_method_body(self, sensor_src: str) -> str:
        # Slice the class body for DynamicPresetOverridesAppliedSensor up to
        # the next top-level `class ` definition.
        idx = sensor_src.find("class DynamicPresetOverridesAppliedSensor(")
        assert idx > 0
        # Search for end-of-class — next "class " at column 0.
        end = sensor_src.find("\nclass ", idx + 1)
        return sensor_src[idx:end if end > 0 else len(sensor_src)]

    def test_signal_imported_in_method(self, sensor_src):
        body = self._sensor_method_body(sensor_src)
        assert "SIGNAL_DPM_SKIP_REASONS_UPDATED" in body, (
            "D2: sensor must import SIGNAL_DPM_SKIP_REASONS_UPDATED"
        )

    def test_three_subscriptions_present(self, sensor_src):
        body = self._sensor_method_body(sensor_src)
        # Count the three signals appearing in async_dispatcher_connect calls.
        connect_calls = re.findall(
            r"async_dispatcher_connect\(\s*self\.hass,\s*([A-Z_]+),",
            body,
        )
        assert "SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED" in connect_calls
        assert "SIGNAL_DYNAMIC_PRESET_TRANSITIONED" in connect_calls
        assert "SIGNAL_DPM_SKIP_REASONS_UPDATED" in connect_calls, (
            "D2: must subscribe to SIGNAL_DPM_SKIP_REASONS_UPDATED"
        )
        # Exactly three (not more, not fewer) — keeps the scope tight.
        assert len(connect_calls) == 3, (
            f"D2: expected exactly 3 dispatcher subscriptions, got "
            f"{len(connect_calls)}: {connect_calls}"
        )

    def test_unsub_tracked_via_async_on_remove(self, sensor_src):
        body = self._sensor_method_body(sensor_src)
        # All three subscriptions must be wrapped in async_on_remove.
        # Count async_on_remove(async_dispatcher_connect(...)) occurrences.
        wrapped = re.findall(
            r"async_on_remove\(\s*async_dispatcher_connect\(",
            body,
        )
        assert len(wrapped) == 3, (
            f"D2: all three dispatcher subscriptions must be wrapped in "
            f"async_on_remove (Bug Class #38). Found {len(wrapped)}."
        )

    def test_on_signal_is_callback_decorated(self, sensor_src):
        body = self._sensor_method_body(sensor_src)
        # The `_on_signal` handler must be @callback-decorated (Bug #42).
        idx = body.find("def _on_signal(")
        assert idx > 0
        preceding = body[max(0, idx - 80):idx]
        assert "@callback" in preceding, (
            "D2: _on_signal must be @callback-decorated (Bug Class #42 — "
            "no lambda + async_create_task)"
        )

    def test_handler_is_bound_method_not_lambda(self, sensor_src):
        body = self._sensor_method_body(sensor_src)
        # The connect calls reference `self._on_signal` (bound method),
        # not a lambda. Searching for "lambda" in the subscription
        # context would also fail this test if introduced.
        connect_lines = re.findall(
            r"async_dispatcher_connect\([^)]+\)",
            body,
        )
        for line in connect_lines:
            assert "lambda" not in line, (
                "D2: dispatcher subscription must not use lambda (Bug #42)"
            )
            assert "self._on_signal" in line, (
                "D2: subscription must reference bound method self._on_signal"
            )


# ============================================================================
# D3 Group C — All 6 skip-reason taxonomy values exercised
# ============================================================================


class TestD3SkipReasonTaxonomyCoverage:
    """Group C: tests cover ALL 6 reason types regardless of which (if any)
    targeted production fix landed. This protects against regression on the
    v4.7.7 B2 taxonomy AND establishes a fixture base for v4.7.11+ fixes."""

    # Reasons documented in dynamic_preset.evaluate_with_reason +
    # _build_overrides_with_reason + energy.py:_async_evaluate_dynamic_presets.
    EXPECTED_REASONS = {
        "gate_disabled",
        "no_forecast_delta",
        "dwell_pending",
        "unknown_bucket",
        "home_range_not_configured",
        "canonical_label_mismatch",
        "evaluation_failed",
    }

    def test_all_reason_strings_present_in_production_sources(
        self, dyn_preset_src, energy_src,
    ):
        # The 5 "evaluate" reasons live in dynamic_preset.py.
        in_dpm = {
            "gate_disabled",
            "no_forecast_delta",
            "dwell_pending",
            "unknown_bucket",
            "home_range_not_configured",
        }
        for reason in in_dpm:
            assert f'"{reason}"' in dyn_preset_src, (
                f"D3: reason literal '{reason}' missing from dynamic_preset.py"
            )
        # The 2 caller-side reasons live in energy.py.
        for reason in ("canonical_label_mismatch", "evaluation_failed"):
            assert f'"{reason}"' in energy_src, (
                f"D3: reason literal '{reason}' missing from energy.py"
            )

    def test_gate_disabled_return_path(self, dyn_preset_src):
        # Source-grep: when CONF_ZONE_DYNAMIC_PRESET_ENABLED is False the
        # method returns `[], "gate_disabled"`.
        assert (
            'return [], "gate_disabled"' in dyn_preset_src
        ), "D3: gate_disabled return path missing"

    def test_no_forecast_delta_return_path(self, dyn_preset_src):
        assert (
            'return [], "no_forecast_delta"' in dyn_preset_src
        ), "D3: no_forecast_delta return path missing"

    def test_dwell_pending_return_path(self, dyn_preset_src):
        # dwell_pending is returned when an active transition is gated by
        # the dwell timer AND no build-path reason applies.
        assert 'return overrides, "dwell_pending"' in dyn_preset_src, (
            "D3: dwell_pending return path missing"
        )

    def test_unknown_bucket_return_path(self, dyn_preset_src):
        assert (
            'return [], "unknown_bucket"' in dyn_preset_src
        ), "D3: unknown_bucket return path missing"

    def test_home_range_not_configured_return_path(self, dyn_preset_src):
        assert (
            'return [], "home_range_not_configured"' in dyn_preset_src
        ), "D3: home_range_not_configured return path missing"

    def test_canonical_label_mismatch_return_path(self, energy_src):
        # Lives in energy.py, surfaced when zone_name contains " + " but
        # no constituent part matches a real zm_zones key AND zone_id
        # fallback also returns empty data (v4.7.7 A-M1 fix-up).
        assert '"canonical_label_mismatch"' in energy_src, (
            "D3: canonical_label_mismatch literal missing from energy.py"
        )

    def test_evaluation_failed_return_path(self, energy_src):
        # Surfaced when the evaluate_with_reason call itself raises.
        assert (
            'updated_skip_reasons[zone_id] = "evaluation_failed"' in energy_src
        ), "D3: evaluation_failed assignment missing from energy.py"


# ============================================================================
# D3 Group C — Behavioral mirror of the easy reasons (no PresetManager needed)
# ============================================================================


class _MockDpmEvaluator:
    """Mirror of `evaluate_with_reason` covering the 2 caller-side gates
    that don't require PresetManager / bucket math.

    Gate 1: zone_data.get(CONF_ZONE_DYNAMIC_PRESET_ENABLED, False) -> gate_disabled
    Gate 2: delta is None -> no_forecast_delta

    Sufficient for behavioral verification of the early-return shape;
    the deeper gates (unknown_bucket / home_range_not_configured /
    dwell_pending) are exercised via source-grep above, which is the
    project test convention for code paths requiring full PresetManager
    + Zone Manager setup.
    """

    CONF_DPM_ENABLED = "dpm_enabled"  # alias for CONF_ZONE_DYNAMIC_PRESET_ENABLED

    def evaluate_with_reason(self, zone_data: dict, delta: float | None):
        if not zone_data.get(self.CONF_DPM_ENABLED, False):
            return [], "gate_disabled"
        if delta is None:
            return [], "no_forecast_delta"
        # Stand-in success path (not the focus of this test class).
        return ["FAKE_OVERRIDE"], None


class TestD3BehavioralEasyReasons:
    def test_gate_disabled_when_zone_opted_out(self):
        ev = _MockDpmEvaluator()
        overrides, reason = ev.evaluate_with_reason({"dpm_enabled": False}, 5.0)
        assert overrides == []
        assert reason == "gate_disabled"

    def test_no_forecast_delta_when_wpm_missing(self):
        ev = _MockDpmEvaluator()
        overrides, reason = ev.evaluate_with_reason({"dpm_enabled": True}, None)
        assert overrides == []
        assert reason == "no_forecast_delta"

    def test_happy_path_returns_overrides_and_no_reason(self):
        ev = _MockDpmEvaluator()
        overrides, reason = ev.evaluate_with_reason({"dpm_enabled": True}, 5.0)
        assert overrides == ["FAKE_OVERRIDE"]
        assert reason is None


# ============================================================================
# Parallel-merge audit guardrails — fail fast if v4.7.9 edits stray outside
# the planned line ranges in sensor.py / signals.py.
# ============================================================================


class TestParallelMergeAuditGuardrails:
    """Hygiene's edits to sensor.py + signals.py must be append-only or
    line-localized per planning §8 to keep merge-risk with Egress trivial."""

    def test_sensor_edit_localized_to_dpm_sensor_method(self, sensor_src):
        # The only sensor.py edit is the third dispatcher subscription
        # inside DynamicPresetOverridesAppliedSensor.async_added_to_hass.
        # Confirm the marker is present AND that no other v4.7.9 marker
        # leaked elsewhere in the file (cross-cycle hygiene).
        marker_count = sensor_src.count("v4.7.9 D2")
        # Acceptable count: 3 markers (method docstring + import comment +
        # third subscription comment). The number is intentionally tight
        # to catch stray edits introduced by future agents.
        assert marker_count == 3, (
            f"Parallel-merge audit: expected exactly 3 'v4.7.9 D2' markers "
            f"in sensor.py (one method docstring + one import comment + one "
            f"subscription comment), found {marker_count}. Stray edit?"
        )

    def test_signals_addition_is_append_only(self, signals_src):
        # The new constant must appear AFTER the existing v4.7.1 Cycle B
        # block — append-only, no insertion between unrelated regions.
        idx_v471 = signals_src.find("SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED")
        idx_v479 = signals_src.find("SIGNAL_DPM_SKIP_REASONS_UPDATED")
        assert idx_v471 > 0 and idx_v479 > idx_v471, (
            "Parallel-merge audit: SIGNAL_DPM_SKIP_REASONS_UPDATED must be "
            "appended AFTER SIGNAL_DYNAMIC_PRESET_OVERRIDES_UPDATED (Phase A "
            "merge order assumes append-only signals.py edits)"
        )
