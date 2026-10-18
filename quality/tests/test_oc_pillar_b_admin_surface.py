"""Tests for OC Pillar B (Phase 5) — observability + admin surface.

Covers:
  - D2/D6 confirm-guard state machine on `OptimizerAutonomyLevelSelect`
    (pending → confirm, pending → cancel, de-escalate-immediate,
    kill-strips-pending, restart-restore).
  - D3 translation-key resolution — every key referenced by
    `async_step_coordinator_optimization` resolves in `translations/en.json`
    and `strings.json`.
  - D4 button entities — Confirm, Cancel, Reset, Run Cycle Now.
  - D5 status sensor split (last_cycle_ vs window_ findings) + new attrs.

Bug-class guardrails honored: drives PRODUCTION code paths (Bug Class #44),
no hand-copied DDL, the URA stub-eviction autouse fixture from the sibling
test file is mirrored here so each test re-imports the real package.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import types
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

# Make the repo root importable as for sibling test files.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Reuse the same `homeassistant.*` mock module set as
# `test_optimization_coordinator.py` — importing that module installs the
# stubs into sys.modules. Importing it for its side-effects keeps the two
# files in sync; no test names collide because we don't re-export anything.
import quality.tests.test_optimization_coordinator as _opt_test  # noqa: F401  (side-effect import)


# ---------------------------------------------------------------------------
# Mock entry / hass plumbing (mirrors test_optimization_coordinator helpers
# but copied here so this file is self-contained and resilient to refactor).
# ---------------------------------------------------------------------------


class _MockEntry:
    def __init__(self, entry_id="cm", entry_type="coordinator_manager",
                 data=None, options=None):
        self.entry_id = entry_id
        self.data = {"entry_type": entry_type, **(data or {})}
        self.options = dict(options or {})


class _MockConfigEntries:
    def __init__(self, entries):
        self._entries = entries
        self.updates: list[dict] = []

    def async_entries(self, _domain):
        return list(self._entries)

    def async_update_entry(self, entry, options=None, **_):
        if options is not None:
            entry.options = dict(options)
            self.updates.append(dict(options))


class _MockHass:
    def __init__(self, entries=None):
        self.data = {"universal_room_automation": {}}
        self.config_entries = _MockConfigEntries(entries or [])
        self.states = MagicMock()
        self.bus = MagicMock()
        self.services = MagicMock()

    def async_create_task(self, coro):
        try:
            coro.close()
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _evict_ura_stubs():
    """Drop URA stubs so each test re-imports the real package.

    Mirrors the sibling test file's fixture; required because some
    tests in the broader suite install fake `custom_components.*`
    modules in sys.modules.
    """
    for modname in list(sys.modules):
        if (
            modname == "custom_components.universal_room_automation"
            or modname.startswith(
                "custom_components.universal_room_automation."
            )
        ):
            del sys.modules[modname]
    cc_dir = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__), "..", "..", "custom_components",
        )
    )
    cc = sys.modules.get("custom_components")
    if cc is None:
        cc = types.ModuleType("custom_components")
        cc.__path__ = [cc_dir]
        sys.modules["custom_components"] = cc
    else:
        existing_path = list(getattr(cc, "__path__", []) or [])
        if cc_dir not in existing_path:
            existing_path.append(cc_dir)
            cc.__path__ = existing_path
    yield


def _ensure_no_op_async_added(klass_path: str, klass_name: str) -> None:
    """Patch in an async no-op `async_added_to_hass` for a mocked base class.

    Tests import production entity classes whose `super().async_added_to_hass()`
    call resolves to the stub base classes installed in sys.modules. The stubs
    don't carry that method; without this shim the production code raises
    AttributeError during the await.
    """
    base_cls = sys.modules[klass_path].__dict__.get(klass_name)
    if base_cls is None:
        return
    if not hasattr(base_cls, "async_added_to_hass"):
        async def _noop(self):
            return None
        base_cls.async_added_to_hass = _noop
    if not hasattr(base_cls, "async_will_remove_from_hass"):
        async def _noop2(self):
            return None
        base_cls.async_will_remove_from_hass = _noop2


# ---------------------------------------------------------------------------
# D2 / D6 — Autonomy select confirm-guard
# ---------------------------------------------------------------------------


def _make_select(options=None, data=None):
    from custom_components.universal_room_automation.select import (
        OptimizerAutonomyLevelSelect,
    )
    entry = _MockEntry(options=options, data=data)
    hass = _MockHass(entries=[entry])
    sel = OptimizerAutonomyLevelSelect(hass, entry)
    # `async_write_ha_state` is a HA-runtime concern; stub it for unit tests.
    sel.async_write_ha_state = MagicMock()
    return sel, hass, entry


@pytest.mark.asyncio
async def test_autonomy_select_pending_escalation():
    """L1 (shadow) → L2 (reversible_device) STAGES as pending, not commit."""
    sel, hass, entry = _make_select(options={"optimizer_autonomy_level": "shadow"})
    await sel.async_select_option("reversible_device")
    # Pending key written; real key untouched.
    assert entry.options["optimizer_pending_autonomy_level"] == "reversible_device"
    assert entry.options["optimizer_autonomy_level"] == "shadow"
    # Entity state reflects the pending target via the prefixed token.
    assert sel.current_option == "pending_reversible_device"


@pytest.mark.asyncio
async def test_autonomy_select_l0_to_l4_also_stages_pending():
    """Larger upward jumps also stage rather than commit."""
    sel, hass, entry = _make_select(options={"optimizer_autonomy_level": "advisory"})
    await sel.async_select_option("immediate_config")
    assert entry.options["optimizer_pending_autonomy_level"] == "immediate_config"
    assert entry.options["optimizer_autonomy_level"] == "advisory"
    assert sel.current_option == "pending_immediate_config"


@pytest.mark.asyncio
async def test_autonomy_select_deescalate_commits_immediately():
    """ANY → lower rank commits without confirm; pending is cleared."""
    sel, hass, entry = _make_select(options={
        "optimizer_autonomy_level": "propose_config",
        "optimizer_pending_autonomy_level": "immediate_config",
    })
    await sel.async_select_option("shadow")
    assert entry.options["optimizer_autonomy_level"] == "shadow"
    # Stale pending stripped.
    assert "optimizer_pending_autonomy_level" not in entry.options
    assert sel.current_option == "shadow"


@pytest.mark.asyncio
async def test_autonomy_select_pending_token_maps_through_to_underlying_level():
    """Pillar B fix-up A-M5: selecting `pending_<level>` maps to `<level>`.

    Was a silent no-op (UI-artifact-only). New behavior: routes through
    so the dropdown is not "stuck" carrying a useless option. From
    shadow (committed) selecting `pending_propose_config` is equivalent
    to selecting `propose_config`, which (rank >= L2) stages as pending.
    """
    sel, hass, entry = _make_select(options={"optimizer_autonomy_level": "shadow"})
    await sel.async_select_option("pending_propose_config")
    # Mapped through → propose_config is L3, stages as pending.
    assert entry.options["optimizer_pending_autonomy_level"] == "propose_config"
    assert entry.options.get("optimizer_autonomy_level") == "shadow"
    assert sel.current_option == "pending_propose_config"


@pytest.mark.asyncio
async def test_autonomy_select_advisory_to_shadow_commits_immediately():
    """Pillar B fix-up A-M4: advisory ↔ shadow moves commit IMMEDIATELY.

    Both rungs are no-actuation; the confirm-guard threshold is L2
    (reversible_device). Upward jumps that stay below L2 don't need
    the dual-press ceremony.
    """
    sel, hass, entry = _make_select(options={"optimizer_autonomy_level": "advisory"})
    await sel.async_select_option("shadow")
    assert entry.options["optimizer_autonomy_level"] == "shadow"
    assert "optimizer_pending_autonomy_level" not in entry.options
    assert sel.current_option == "shadow"


def test_autonomy_select_restores_pending_on_construction():
    """Restart restore: pending key in options re-creates the pending state."""
    sel, hass, entry = _make_select(options={
        "optimizer_autonomy_level": "shadow",
        "optimizer_pending_autonomy_level": "propose_config",
    })
    assert sel.current_option == "pending_propose_config"


def test_autonomy_select_extra_state_attributes_split():
    """extra_state_attributes exposes committed + pending separately."""
    sel, hass, entry = _make_select(options={
        "optimizer_autonomy_level": "shadow",
        "optimizer_pending_autonomy_level": "reversible_device",
    })
    attrs = sel.extra_state_attributes
    assert attrs["committed_level"] == "shadow"
    assert attrs["pending_level"] == "reversible_device"


# ---------------------------------------------------------------------------
# D4 — Buttons (Confirm / Cancel / Reset / Run Cycle Now)
# ---------------------------------------------------------------------------


def _make_button(klass_name, options=None):
    """Construct one of the four Pillar B buttons against a mock hass+entry."""
    mod = importlib.import_module(
        "custom_components.universal_room_automation.button",
    )
    klass = getattr(mod, klass_name)
    entry = _MockEntry(options=options)
    hass = _MockHass(entries=[entry])
    btn = klass(hass, entry)
    return btn, hass, entry


@pytest.mark.asyncio
async def test_confirm_button_commits_pending():
    """ConfirmEscalation: pending → real, pending stripped, one update event."""
    btn, hass, entry = _make_button(
        "OptimizerConfirmEscalationButton",
        options={
            "optimizer_autonomy_level": "shadow",
            "optimizer_pending_autonomy_level": "propose_config",
        },
    )
    assert btn.available is True
    await btn.async_press()
    assert entry.options["optimizer_autonomy_level"] == "propose_config"
    assert "optimizer_pending_autonomy_level" not in entry.options
    # One single `async_update_entry` call (atomic commit).
    assert len(hass.config_entries.updates) == 1


@pytest.mark.asyncio
async def test_confirm_button_unavailable_without_pending():
    """Confirm button is unavailable when no pending key exists."""
    btn, hass, entry = _make_button(
        "OptimizerConfirmEscalationButton",
        options={"optimizer_autonomy_level": "shadow"},
    )
    assert btn.available is False
    await btn.async_press()  # no-op
    assert len(hass.config_entries.updates) == 0


@pytest.mark.asyncio
async def test_cancel_button_clears_pending():
    """CancelEscalation strips pending without touching the real key."""
    btn, hass, entry = _make_button(
        "OptimizerCancelEscalationButton",
        options={
            "optimizer_autonomy_level": "shadow",
            "optimizer_pending_autonomy_level": "immediate_config",
        },
    )
    assert btn.available is True
    await btn.async_press()
    assert "optimizer_pending_autonomy_level" not in entry.options
    assert entry.options["optimizer_autonomy_level"] == "shadow"


@pytest.mark.asyncio
async def test_reset_button_preserves_kill_switch():
    """Reset strips all optimizer_* keys EXCEPT optimizer_kill_switch."""
    btn, hass, entry = _make_button(
        "OptimizerResetSettingsButton",
        options={
            "optimizer_autonomy_level": "propose_config",
            "optimizer_kill_switch": True,  # engaged — must survive Reset
            "optimizer_confidence_gate": 0.95,
            "optimizer_rate_cap_per_hour": 50,
            "optimizer_pending_autonomy_level": "immediate_config",
            "optimizer_safety_deny_entities": ["lock.front"],
            "unrelated_key": "stays",
        },
    )
    await btn.async_press()
    # Kill switch preserved (the safety contract).
    assert entry.options["optimizer_kill_switch"] is True
    # Other optimizer_* keys stripped.
    for key in (
        "optimizer_autonomy_level",
        "optimizer_confidence_gate",
        "optimizer_rate_cap_per_hour",
        "optimizer_pending_autonomy_level",
        "optimizer_safety_deny_entities",
    ):
        assert key not in entry.options
    # Unrelated keys preserved.
    assert entry.options["unrelated_key"] == "stays"


class _FakeOptimizerCoord:
    """Spec'd fake coordinator exposing ONLY the methods the button is
    allowed to call. Mock-masking lesson: a bare MagicMock would happily
    accept any attribute name (including the now-removed
    ``async_request_refresh``) and silently pass the test. Restricting
    the surface forces the test to fail if the button ever calls a
    nonexistent method.
    """

    def __init__(self):
        self.run_cycle_calls = 0

    async def run_cycle(self):
        self.run_cycle_calls += 1
        return []


@pytest.mark.asyncio
async def test_run_cycle_button_debounces():
    """RunCycleNow debounces to one press per 30s."""
    btn, hass, entry = _make_button(
        "OptimizerRunCycleNowButton",
        options={"optimizer_kill_switch": False},
    )
    # Plumb a SPEC'D fake optimization coordinator that ONLY exposes
    # ``run_cycle``. If the button regresses to calling
    # ``async_request_refresh`` (or any other nonexistent method) the
    # test fails with AttributeError instead of silently passing on a
    # MagicMock's auto-vivified attribute.
    fake_coord = _FakeOptimizerCoord()
    cm = MagicMock()
    cm.coordinators = {"optimization": fake_coord}
    hass.data["universal_room_automation"]["coordinator_manager"] = cm

    # First press fires.
    await btn.async_press()
    assert fake_coord.run_cycle_calls == 1
    # Second press within 30s is debounced.
    await btn.async_press()
    assert fake_coord.run_cycle_calls == 1


@pytest.mark.asyncio
async def test_run_cycle_button_unavailable_with_kill_switch_engaged():
    """RunCycleNow disabled while kill switch is ON."""
    btn, hass, entry = _make_button(
        "OptimizerRunCycleNowButton",
        options={"optimizer_kill_switch": True},
    )
    fake_coord = _FakeOptimizerCoord()
    cm = MagicMock()
    cm.coordinators = {"optimization": fake_coord}
    hass.data["universal_room_automation"]["coordinator_manager"] = cm
    assert btn.available is False


# ---------------------------------------------------------------------------
# D6 — Kill switch strips pending escalation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kill_switch_engage_strips_pending_autonomy():
    """Engaging the kill switch clears `optimizer_pending_autonomy_level`."""
    _ensure_no_op_async_added(
        "homeassistant.helpers.restore_state", "RestoreEntity",
    )
    _ensure_no_op_async_added(
        "homeassistant.components.switch", "SwitchEntity",
    )
    from custom_components.universal_room_automation.switch import (
        OptimizerKillSwitch,
    )
    entry = _MockEntry(options={
        "optimizer_autonomy_level": "shadow",
        "optimizer_pending_autonomy_level": "propose_config",
        "optimizer_kill_switch": False,
    })
    hass = _MockHass(entries=[entry])
    sw = OptimizerKillSwitch(hass, entry)
    sw.async_write_ha_state = MagicMock()
    await sw.async_turn_on()
    # Kill switch persisted ON.
    assert entry.options["optimizer_kill_switch"] is True
    # Pending escalation stripped.
    assert "optimizer_pending_autonomy_level" not in entry.options


# ---------------------------------------------------------------------------
# D3 — Translations: every key referenced by `async_step_coordinator_optimization`
# resolves in BOTH translations/en.json and strings.json.
# ---------------------------------------------------------------------------


def _load_translation(path_segments: tuple[str, ...]) -> dict:
    """Walk a dotted-path through a JSON file. Returns {} if missing."""
    here = os.path.dirname(__file__)
    root = os.path.abspath(os.path.join(here, "..", ".."))
    fp = os.path.join(
        root, "custom_components", "universal_room_automation",
        *path_segments,
    )
    with open(fp, "r", encoding="utf-8") as f:
        return json.load(f)


_OPTIMIZER_STEP_DATA_KEYS = (
    "optimizer_autonomy_level",
    "optimizer_kill_switch",
    "optimizer_confidence_gate",
    "optimizer_rate_cap_per_hour",
    "optimizer_quiet_hours_source",
    "optimizer_safety_deny_entities",
    "optimizer_llm_task_entity",
    "optimizer_llm_triage_entity",
    "optimizer_llm_system_prompt",
    "optimizer_llm_max_invocations_per_24h",
)

_OPTIMIZER_STEP_SECTIONS = (
    "optimizer_guards",
    "optimizer_llm",
)


def _check_optimizer_step(payload: dict, source_label: str) -> None:
    """Validate the coordinator_optimization step has every required key."""
    step = (
        payload.get("options", {})
        .get("step", {})
        .get("coordinator_optimization")
    )
    assert step is not None, (
        f"{source_label}: options.step.coordinator_optimization missing"
    )
    assert step.get("title"), f"{source_label}: missing title"
    assert step.get("description"), f"{source_label}: missing description"
    data = step.get("data", {})
    desc = step.get("data_description", {})
    for key in _OPTIMIZER_STEP_DATA_KEYS:
        assert key in data, (
            f"{source_label}: data.{key} missing"
        )
        assert key in desc, (
            f"{source_label}: data_description.{key} missing"
        )
    sections = step.get("sections", {})
    for sec in _OPTIMIZER_STEP_SECTIONS:
        assert sec in sections, (
            f"{source_label}: sections.{sec} missing"
        )
    # Pillar B fix-up A-H3: each section MUST carry the nested
    # `{name, data, data_description}` shape per HA config-flow section
    # translations (top-level flat duplicates are kept belt-and-braces
    # since extra keys are ignored by HA, but the nested shape is what
    # the section header / inline labels resolve from).
    guards_sec = sections.get("optimizer_guards")
    assert isinstance(guards_sec, dict), (
        f"{source_label}: sections.optimizer_guards must be nested object"
    )
    assert "name" in guards_sec, (
        f"{source_label}: sections.optimizer_guards.name missing"
    )
    for key in (
        "optimizer_confidence_gate",
        "optimizer_rate_cap_per_hour",
        "optimizer_quiet_hours_source",
        "optimizer_safety_deny_entities",
    ):
        assert key in guards_sec.get("data", {}), (
            f"{source_label}: sections.optimizer_guards.data.{key} missing"
        )
        assert key in guards_sec.get("data_description", {}), (
            f"{source_label}: sections.optimizer_guards.data_description.{key} missing"
        )
    llm_sec = sections.get("optimizer_llm")
    assert isinstance(llm_sec, dict), (
        f"{source_label}: sections.optimizer_llm must be nested object"
    )
    assert "name" in llm_sec, (
        f"{source_label}: sections.optimizer_llm.name missing"
    )
    for key in (
        "optimizer_llm_task_entity",
        "optimizer_llm_triage_entity",
        "optimizer_llm_system_prompt",
        "optimizer_llm_max_invocations_per_24h",
    ):
        assert key in llm_sec.get("data", {}), (
            f"{source_label}: sections.optimizer_llm.data.{key} missing"
        )
        assert key in llm_sec.get("data_description", {}), (
            f"{source_label}: sections.optimizer_llm.data_description.{key} missing"
        )


def test_translations_en_json_has_optimizer_step():
    """All ~14 optimizer step keys (+2 sections) resolve in en.json."""
    payload = _load_translation(("translations", "en.json"))
    _check_optimizer_step(payload, "translations/en.json")


def test_strings_json_has_optimizer_step():
    """Same set of keys resolves in strings.json (the canonical source)."""
    payload = _load_translation(("strings.json",))
    _check_optimizer_step(payload, "strings.json")


def test_translations_have_optimizer_autonomy_select_state_labels():
    """Every level (6 real + 6 pending) has a state label."""
    payload = _load_translation(("translations", "en.json"))
    states = (
        payload.get("entity", {})
        .get("select", {})
        .get("optimizer_autonomy_level", {})
        .get("state", {})
    )
    for level in (
        "advisory", "shadow", "reversible_device",
        "propose_config", "immediate_config", "unbounded",
    ):
        assert level in states, f"missing state label for {level}"
        assert f"pending_{level}" in states, (
            f"missing state label for pending_{level}"
        )


def test_translations_have_optimizer_button_names():
    """All four Pillar B button entities have translated names."""
    payload = _load_translation(("translations", "en.json"))
    btns = payload.get("entity", {}).get("button", {})
    for key in (
        "optimizer_confirm_escalation",
        "optimizer_cancel_escalation",
        "optimizer_reset_settings",
        "optimizer_run_cycle_now",
    ):
        assert key in btns, f"button.{key} missing translation"
        assert "name" in btns[key]


# ---------------------------------------------------------------------------
# D5 — Status sensor split + new attrs
# ---------------------------------------------------------------------------


class _FakeFinding:
    def __init__(self, *, timestamp, level, target_id, dimension, severity,
                 description, applied_outcome=None, proposed_action=None,
                 applied_action_id=None, observed_effect=None):
        self.timestamp = timestamp
        self.level = level
        self.target_id = target_id
        self.dimension = dimension
        self.severity = severity
        self.description = description
        self.applied_outcome = applied_outcome
        self.proposed_action = proposed_action
        self.applied_action_id = applied_action_id
        self.observed_effect = observed_effect


def _make_status_sensor(coord):
    """Construct the OptimizerStatusSensor against a fake coordinator."""
    _ensure_no_op_async_added(
        "homeassistant.components.sensor", "SensorEntity",
    )
    from custom_components.universal_room_automation.sensor import (
        OptimizerStatusSensor,
    )
    entry = _MockEntry()
    hass = _MockHass(entries=[entry])
    cm = MagicMock()
    cm.coordinators = {"optimization": coord}
    hass.data["universal_room_automation"]["coordinator_manager"] = cm
    sensor = OptimizerStatusSensor(hass, entry)
    return sensor, hass


def _fake_coord(*, last_findings=None, last_evaluation_iso=None,
                open_findings_count=0, house_score=100.0,
                rate_window=0, quiet=False,
                effective_level="shadow", autonomy_level="shadow",
                cm_options=None, llm_invocations=0):
    coord = MagicMock()
    coord._last_findings = list(last_findings or [])
    coord._last_evaluation_iso = last_evaluation_iso
    coord._open_findings_count = open_findings_count
    coord._house_score = house_score
    coord._rate_cap_window_count = MagicMock(return_value=rate_window)
    coord._is_quiet_hours_active = MagicMock(return_value=quiet)
    coord.effective_level = effective_level
    coord.status = "healthy"
    options = {"optimizer_autonomy_level": autonomy_level}
    if cm_options:
        options.update(cm_options)
    coord._read_cm_config = MagicMock(return_value=options)
    # LLM tier shim.
    if llm_invocations:
        tier = MagicMock()
        tier._premium_invocations = [object() for _ in range(llm_invocations)]
        coord._llm_tier = tier
    else:
        coord._llm_tier = None
    return coord


def test_status_sensor_last_cycle_vs_window():
    """last_cycle_findings_count derives from latest cycle; window stays separate."""
    f1 = _FakeFinding(
        timestamp=datetime.utcnow().isoformat(), level="room",
        target_id="r1", dimension="comfort", severity="medium",
        description="d1",
    )
    f2 = _FakeFinding(
        timestamp=datetime.utcnow().isoformat(), level="room",
        target_id="r2", dimension="comfort", severity="medium",
        description="d2",
    )
    coord = _fake_coord(
        last_findings=[f1, f2],
        open_findings_count=7,   # window is bigger than this cycle's
        house_score=72.0,
        last_evaluation_iso=datetime.utcnow().isoformat(),
    )
    sensor, _ = _make_status_sensor(coord)
    attrs = sensor.extra_state_attributes
    assert attrs["last_cycle_findings_count"] == 2
    assert attrs["window_findings_count"] == 7
    assert attrs["window_house_score"] == 72.0
    # Back-compat alias still present.
    assert attrs["house_score"] == 72.0


def test_status_sensor_next_cycle_eta_non_negative():
    """next_cycle_eta_seconds is computed from last evaluation; never negative."""
    coord = _fake_coord(
        last_findings=[],
        last_evaluation_iso=datetime.utcnow().isoformat(),
    )
    sensor, _ = _make_status_sensor(coord)
    attrs = sensor.extra_state_attributes
    assert attrs["next_cycle_eta_seconds"] is not None
    assert attrs["next_cycle_eta_seconds"] >= 0
    # 5 min cycle → eta should be at most ~300.
    assert attrs["next_cycle_eta_seconds"] <= 300


def test_status_sensor_last_action_empty_at_l1():
    """At L1 (shadow) the last_action attribute is `{}` even with findings."""
    f1 = _FakeFinding(
        timestamp=datetime.utcnow().isoformat(), level="room",
        target_id="r1", dimension="comfort", severity="medium",
        description="d1",
        # In Shadow mode the chokepoint sets applied_outcome="shadow".
        applied_outcome="shadow",
    )
    coord = _fake_coord(
        last_findings=[f1],
        last_evaluation_iso=datetime.utcnow().isoformat(),
        effective_level="shadow",
        autonomy_level="shadow",
    )
    sensor, _ = _make_status_sensor(coord)
    attrs = sensor.extra_state_attributes
    assert attrs["last_action"] == {}


def test_status_sensor_last_action_populated_on_applied():
    """When a finding is 'applied', last_action reflects its target + action."""
    f1 = _FakeFinding(
        timestamp="2026-06-10T12:00:00",
        level="room", target_id="kitchen", dimension="comfort",
        severity="medium", description="cool down",
        applied_outcome="applied",
        applied_action_id="abc-123",
        proposed_action={
            "target_entity": "climate.kitchen", "service": "set_temperature",
        },
    )
    coord = _fake_coord(
        last_findings=[f1],
        last_evaluation_iso=datetime.utcnow().isoformat(),
        autonomy_level="reversible_device",
        effective_level="reversible_device",
    )
    sensor, _ = _make_status_sensor(coord)
    attrs = sensor.extra_state_attributes
    assert attrs["last_action"]["target_entity"] == "climate.kitchen"
    assert attrs["last_action"]["action_id"] == "abc-123"


def test_status_sensor_exposes_pending_autonomy():
    """pending_autonomy_level surfaces on the status sensor for dashboards."""
    coord = _fake_coord(
        last_findings=[],
        last_evaluation_iso=datetime.utcnow().isoformat(),
        cm_options={"optimizer_pending_autonomy_level": "reversible_device"},
    )
    sensor, _ = _make_status_sensor(coord)
    attrs = sensor.extra_state_attributes
    assert attrs["pending_autonomy_level"] == "reversible_device"


def test_status_sensor_llm_invocations_today():
    """llm_invocations_today reads the Phase-2 tier's premium counter."""
    coord = _fake_coord(
        last_findings=[],
        last_evaluation_iso=datetime.utcnow().isoformat(),
        llm_invocations=5,
    )
    sensor, _ = _make_status_sensor(coord)
    assert sensor.extra_state_attributes["llm_invocations_today"] == 5
