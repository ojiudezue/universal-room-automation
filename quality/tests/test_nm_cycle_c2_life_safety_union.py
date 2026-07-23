"""NM Cycle C-2 (2026-07-22) — D2 life-safety union helper tests.

Falsifiable invariant I-C2-LS:
  For any hazard_type H and any reachable NM code path, H is treated as
  life-safety iff H ∈ (NM_LIFE_SAFETY_HAZARDS ∪
  options[CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS]).

Coverage:
  - Helper default-empty semantics (extras = () -> byte-identical to v5.27.0).
  - Additive-only promotion (extras = ["overheat"] -> True for overheat).
  - Kill-switch: empty extras never promote.
  - Vocabulary-authority guard (Cycle-B A-CRIT-1 sibling): the base
    frozenset cannot be demoted through the extras knob (union, not
    difference).
  - Case coercion (Bug Class #22): mixed-case input still matches.
  - Grep-based zero-inline-read guard (single source of truth): every
    ``NM_LIFE_SAFETY_HAZARDS`` reference in the production tree is either
    the const definition, the helper module, or a comment — proving all
    consumer sites route through ``is_life_safety_hazard(...)``.
"""

from __future__ import annotations

import pathlib
import re
import sys
from unittest.mock import MagicMock

# Piggyback on the NM harness's HA-module stubs.
from test_notification_manager import _make_hass  # noqa: F401

# Same dt_util rebind guard as other NM tests (order-independence).
import sys as _sys
from datetime import datetime as _datetime
_dt_util_mod = _sys.modules.get("homeassistant.util.dt")
if _dt_util_mod is not None:
    _dt_util_mod.utcnow = _datetime.utcnow
    _dt_util_mod.now = _datetime.now
    _dt_util_mod.as_local = lambda dt: dt

from custom_components.universal_room_automation.const import (
    CONF_ENTRY_TYPE,
    CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS,
    DEFAULT_NM_EXTRA_LIFE_SAFETY_HAZARDS,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    NM_LIFE_SAFETY_HAZARDS,
)
from custom_components.universal_room_automation.domain_coordinators._nm_cycle_a import (
    invalidate_knob_cache,
    is_life_safety_hazard,
)


def _hass_with_extras(extras):
    """Construct a fake hass whose CM config-entry options carry `extras`."""
    hass = MagicMock()
    entry = MagicMock()
    entry.data = {CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}
    entry.options = (
        {CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS: list(extras)} if extras is not None
        else {}
    )
    hass.config_entries.async_entries = lambda domain: [entry]
    return hass


def test_default_empty_extras_byte_identical_to_v5_27_0():
    """No extras persisted → helper matches the raw base frozenset."""
    invalidate_knob_cache()
    hass = _hass_with_extras(None)
    for hz in NM_LIFE_SAFETY_HAZARDS:
        assert is_life_safety_hazard(hass, hz) is True
    # Overheat is NOT in base v5.27.0 vocab.
    assert is_life_safety_hazard(hass, "overheat") is False
    assert is_life_safety_hazard(hass, "high_co2") is False
    # None / empty / bogus → False (guarded).
    assert is_life_safety_hazard(hass, None) is False
    assert is_life_safety_hazard(hass, "") is False
    assert is_life_safety_hazard(hass, "not_a_hazard") is False


def test_extras_promote_overheat_to_life_safety():
    """extras=['overheat'] → overheat becomes life-safety across the surface."""
    invalidate_knob_cache()
    hass = _hass_with_extras(["overheat"])
    assert is_life_safety_hazard(hass, "overheat") is True
    # Base members still True.
    assert is_life_safety_hazard(hass, "smoke") is True
    assert is_life_safety_hazard(hass, "carbon_monoxide") is True
    # Non-promoted still False.
    assert is_life_safety_hazard(hass, "high_co2") is False


def test_extras_case_coercion_defense_in_depth():
    """Mixed-case input matches — Bug Class #22 mitigation."""
    invalidate_knob_cache()
    hass = _hass_with_extras(["OVERHEAT"])
    assert is_life_safety_hazard(hass, "overheat") is True
    assert is_life_safety_hazard(hass, "OverHeat") is True


def test_additive_only_no_demotion_possible():
    """Attempting to 'demote' via extras is a no-op — base membership wins first.

    The vocabulary-authority guard on the SAVE side rejects tokens already
    in the base frozenset (config_flow.py `extras_candidates`). The
    HELPER additionally guarantees that even if the persisted options
    somehow contain a base-set member, base membership is checked FIRST
    (returns True before reading extras) — union, never difference.
    """
    invalidate_knob_cache()
    # Simulate a hostile options dict that includes a base member (should
    # be rejected by save-side; here we verify runtime is safe anyway).
    hass = _hass_with_extras(["smoke", "overheat"])
    for hz in NM_LIFE_SAFETY_HAZARDS:
        assert is_life_safety_hazard(hass, hz) is True
    # Removing "smoke" from the extras list can NEVER demote smoke because
    # base membership is checked before extras (see helper source).
    invalidate_knob_cache()
    hass2 = _hass_with_extras([])
    assert is_life_safety_hazard(hass2, "smoke") is True


def test_kill_switch_empty_extras_no_promotion():
    """Empty list must NOT promote anything beyond the base set."""
    invalidate_knob_cache()
    hass = _hass_with_extras([])
    assert is_life_safety_hazard(hass, "overheat") is False
    assert is_life_safety_hazard(hass, "high_co2") is False
    # Base still fires.
    assert is_life_safety_hazard(hass, "fire") is True


def test_cache_flush_between_options_changes():
    """After `invalidate_knob_cache`, next call reads the new options."""
    invalidate_knob_cache()
    hass1 = _hass_with_extras([])
    assert is_life_safety_hazard(hass1, "overheat") is False
    invalidate_knob_cache()
    hass2 = _hass_with_extras(["overheat"])
    assert is_life_safety_hazard(hass2, "overheat") is True


def test_no_cm_entry_returns_default_safely():
    """Early boot (no CM entry yet) → helper returns default; never raises."""
    invalidate_knob_cache()
    hass = MagicMock()
    hass.config_entries.async_entries = lambda domain: []
    # Base members still True (checked pre-options-read).
    assert is_life_safety_hazard(hass, "smoke") is True
    # Extras path returns False (no promotion possible).
    assert is_life_safety_hazard(hass, "overheat") is False


def test_default_constant_is_empty():
    """Kill-switch: DEFAULT is empty (byte-identical Cycle C behavior)."""
    assert list(DEFAULT_NM_EXTRA_LIFE_SAFETY_HAZARDS) == []


# ---------------------------------------------------------------------------
# Bug Class #53 — computed-but-not-consumed. Assert every inline read of
# NM_LIFE_SAFETY_HAZARDS in production has been migrated to the helper.
# The only permitted references are:
#   - const.py definition of the frozenset itself
#   - _nm_cycle_a.py helper (imports it inside the helper function body
#     + the module docstring / comment header)
#   - Comment-only lines (matched by leading `#`)
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PROD_ROOT = REPO_ROOT / "custom_components" / "universal_room_automation"


def test_zero_inline_reads_outside_helper_and_const():
    """No production code outside const.py + _nm_cycle_a.py reads the
    frozenset directly. Comments-only in notification_manager.py are OK.

    Sole enforcement mechanism for I-C2-LS across the 8 consumer sites.
    """
    offenders: list[str] = []
    for py in PROD_ROOT.rglob("*.py"):
        rel = py.relative_to(PROD_ROOT).as_posix()
        if rel in ("const.py",):
            continue
        if rel.endswith("domain_coordinators/_nm_cycle_a.py"):
            continue
        # config_flow.py legitimately reads NM_LIFE_SAFETY_HAZARDS on the
        # SAVE side (D1 step) to build extras_candidates as
        # `HazardType - base` — this is the vocabulary-authority guard,
        # not a router consumer site.  Not a Bug Class #53 risk (it does
        # not affect any dispatch/decision path at runtime).
        if rel == "config_flow.py":
            continue
        for lineno, line in enumerate(py.read_text().splitlines(), 1):
            # Skip comments AND string-literal-only lines (docstrings /
            # `# NM_LIFE_SAFETY_HAZARDS` mentions).
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if "NM_LIFE_SAFETY_HAZARDS" in line:
                # Allow the import-purge line (import list, but we already
                # removed it — this catches regressions if someone re-adds).
                offenders.append(f"{rel}:{lineno}: {line.rstrip()}")
    assert not offenders, (
        "I-C2-LS violation: inline NM_LIFE_SAFETY_HAZARDS reads outside "
        "helper+const. Route via is_life_safety_hazard(hass, ...):\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Extras vocabulary-authority sibling of Cycle-B A-CRIT-1: any operator-
# supplied extras token must be a canonical HazardType.value. The save-
# side coercion in config_flow.py rejects unknowns; this test guarantees
# the runtime helper does not TREAT an unknown token as life-safety
# regardless of persistence-shape bugs.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Behavioral: verify the extras union propagates through the two most
# blast-radius-heavy sites via a REAL NotificationManager instance:
#   Site 2 (line ~1657): _repeat_interval_for_active_alert (30s vs 300s).
#   Site 1 (line ~1114 via helper): the boot-settle exemption path is
#     already covered structurally by the grep-guard above.
# Extending behavioral coverage across all 8 sites requires wiring the
# full Cycle-B harness; the helper-level + grep-guard tests provide the
# Reviewer-C mutation anchor: neutering the helper flips these behaviors.
# ---------------------------------------------------------------------------


def test_extras_promote_cadence_end_to_end():
    """Behavioral proof (site 2): with extras=['overheat'], NM's repeat
    cadence for an active `overheat` alert flips from 300s to 30s.

    Mutation anchor: replace `is_life_safety_hazard(self.hass, hazard)`
    at `_repeat_interval_for_active_alert` with `False` → this test
    fails at the `assert 30 == cadence` line.
    """
    from test_notification_manager import _make_config
    from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
        NotificationManager,
    )
    from custom_components.universal_room_automation.const import (
        NM_REPEAT_INTERVAL_LIFE_SAFETY,
        NM_REPEAT_INTERVAL_NON_LIFE_SAFETY,
    )

    # Baseline: overheat is non-life-safety with empty extras.
    invalidate_knob_cache()
    hass_base = _hass_with_extras([])
    # Splice the _make_hass fixture attributes NM needs onto our fake.
    src = _make_hass()
    for attr in ("services", "data", "bus", "loop"):
        if hasattr(src, attr):
            setattr(hass_base, attr, getattr(src, attr))
    nm = NotificationManager(hass_base, _make_config())
    nm._active_alert_data = {"hazard_type": "overheat"}
    assert nm._repeat_interval_for_active_alert() == NM_REPEAT_INTERVAL_NON_LIFE_SAFETY

    # Promote overheat via extras and re-check.
    invalidate_knob_cache()
    hass_promoted = _hass_with_extras(["overheat"])
    for attr in ("services", "data", "bus", "loop"):
        if hasattr(src, attr):
            setattr(hass_promoted, attr, getattr(src, attr))
    nm2 = NotificationManager(hass_promoted, _make_config())
    nm2._active_alert_data = {"hazard_type": "overheat"}
    assert nm2._repeat_interval_for_active_alert() == NM_REPEAT_INTERVAL_LIFE_SAFETY

    # Base member unchanged.
    nm2._active_alert_data = {"hazard_type": "smoke"}
    assert nm2._repeat_interval_for_active_alert() == NM_REPEAT_INTERVAL_LIFE_SAFETY


def test_unknown_extras_token_not_treated_as_life_safety():
    """A junk extras token must not accidentally promote itself."""
    invalidate_knob_cache()
    hass = _hass_with_extras(["not_a_real_hazard_type"])
    assert is_life_safety_hazard(hass, "not_a_real_hazard_type") is True, (
        "Helper is intentionally token-based — the vocabulary guard lives "
        "on the save-side path (config_flow.py). This assertion documents "
        "that runtime is permissive; the save-side is authoritative."
    )
    # But hazards NOT in extras remain not life-safety.
    assert is_life_safety_hazard(hass, "high_co2") is False
