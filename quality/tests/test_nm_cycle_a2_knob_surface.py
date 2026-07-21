"""NM Cycle A-2 — knob-surface promotion tests.

Two tiers, matching the pattern of `test_nm_cycle_a_preserved_signals.py`
and `test_baec_config_flow_round_trip.py`:

  * Source-anchored regression: reads files, asserts wiring is in place.
    Removing a load-bearing wire (e.g. `invalidate_knob_cache()` in the CM
    listener branch) flunks a specific test — mutation-anchored per plan.

  * Behavioral: drives the `_nm_cycle_a` helper directly with a mock hass
    + config entry, and drives the OptionsFlow via the `_load_config_flow`
    harness inherited from `test_cycle_b_config_flow._load_config_flow`.

`_nm_cycle_a` is import-safe: it imports from `..const` — but the parent
package `__init__.py` pulls in `homeassistant.config_entries`, which is
absent in the CI baseline. So we import the module from source rather
than through the package tree, using a lightweight `importlib.util`
loader (identical trick to `_load_config_flow`).
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CC = REPO_ROOT / "custom_components" / "universal_room_automation"

# Reuse the HA-mock harness that already stubs the package for OptionsFlow.
_cbcf = importlib.import_module("test_cycle_b_config_flow")
UniversalRoomAutomationOptionsFlow = _cbcf.UniversalRoomAutomationOptionsFlow
_make_options_flow = _cbcf._make_options_flow
_FakeHass = _cbcf._FakeHass
_FakeConfigEntry = _cbcf._FakeConfigEntry


# ---------------------------------------------------------------------------
# _nm_cycle_a loaded from source (bypasses package __init__ which needs HA)
# ---------------------------------------------------------------------------


def _load_nm_cycle_a():
    """Load `domain_coordinators._nm_cycle_a` without triggering
    package-level HA imports.

    Reuses `_cbcf._build_ha_modules()` to stub `homeassistant.core` so
    the helper's `from homeassistant.core import HomeAssistant` resolves.
    Loads const + _nm_cycle_a from source under a fake package name.

    C-HIGH-1 (2026-07-20 fix-up): SNAPSHOT-AND-RESTORE sys.modules for the
    `homeassistant.*` stub install. Previously the stubs were pushed via
    `sys.modules.setdefault(...)` and NEVER restored — that leaked a
    MagicMock `homeassistant.util.dt.utcnow` into `test_safety_coordinator.py`
    (which uses `sys.modules.setdefault`, so its own `datetime.utcnow`
    binding was silently skipped), breaking three safety tests when both
    modules ran in the same pytest invocation. The loaded `_nm_cycle_a`
    module holds its `HomeAssistant` reference in its globals; no runtime
    sys.modules lookup, so removal after load is safe.
    """
    pkg_name = "_nm_cycle_a_test_pkg"
    if f"{pkg_name}._nm" in sys.modules:
        return sys.modules[f"{pkg_name}._nm"]

    ha_modules = _cbcf._build_ha_modules()
    saved: dict[str, ModuleType | None] = {
        name: sys.modules.get(name) for name in ha_modules
    }
    try:
        for name, mod in ha_modules.items():
            sys.modules[name] = mod

        pkg = ModuleType(pkg_name)
        pkg.__path__ = [str(CC)]
        sys.modules[pkg_name] = pkg

        const_spec = importlib.util.spec_from_file_location(
            f"{pkg_name}.const",
            CC / "const.py",
        )
        const_mod = importlib.util.module_from_spec(const_spec)
        sys.modules[f"{pkg_name}.const"] = const_mod
        const_spec.loader.exec_module(const_mod)  # type: ignore[union-attr]

        src = (CC / "domain_coordinators" / "_nm_cycle_a.py").read_text(encoding="utf-8")
        src = src.replace("from ..const import", f"from {pkg_name}.const import")
        mod_name = f"{pkg_name}._nm"
        mod = ModuleType(mod_name)
        mod.__file__ = str(CC / "domain_coordinators" / "_nm_cycle_a.py")
        exec(compile(src, mod.__file__, "exec"), mod.__dict__)
        sys.modules[mod_name] = mod
        return mod
    finally:
        # Restore ONLY the homeassistant.* keys — keep our fake test-package
        # (`_nm_cycle_a_test_pkg.*`) loaded so callers can use the returned
        # module without re-executing this loader.
        for name, prev in saved.items():
            if prev is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prev


_nm = _load_nm_cycle_a()
# Re-export const alias for convenience in tests.
_const = sys.modules["_nm_cycle_a_test_pkg.const"]


class _StubHAContext:
    """Re-inject the HA stubs + a stub URA package so relative `from .const`
    imports inside OptionsFlow step methods resolve at call time.

    `_cbcf._load_config_flow` restores sys.modules after loading — but the
    step methods do their own `from .const import ...` at call time, so we
    have to put stubs back in place while the step runs.
    """
    def __enter__(self):
        self._saved = {}
        ha_modules = _cbcf._build_ha_modules()
        for name, mod in ha_modules.items():
            self._saved[name] = sys.modules.get(name)
            sys.modules[name] = mod
        # Stub the URA package pointing const → our already-loaded const.
        pkg_name = "custom_components.universal_room_automation"
        self._saved["custom_components"] = sys.modules.get("custom_components")
        self._saved[pkg_name] = sys.modules.get(pkg_name)
        self._saved[f"{pkg_name}.const"] = sys.modules.get(f"{pkg_name}.const")
        if "custom_components" not in sys.modules:
            cc = ModuleType("custom_components")
            cc.__path__ = [str(REPO_ROOT / "custom_components")]
            sys.modules["custom_components"] = cc
        pkg = ModuleType(pkg_name)
        pkg.__path__ = [str(CC)]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg
        sys.modules[f"{pkg_name}.const"] = _const
        pkg.const = _const
        return self

    def __exit__(self, *exc):
        for name, mod in self._saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        return False


def _make_hass_with_cm(cm_options: dict | None = None):
    entry = SimpleNamespace(
        data={_const.CONF_ENTRY_TYPE: _const.ENTRY_TYPE_COORDINATOR_MANAGER},
        options=dict(cm_options or {}),
    )
    hass = MagicMock()
    hass.config_entries.async_entries = lambda domain: [entry]
    return hass, entry


@pytest.fixture(autouse=True)
def _flush_cache():
    _nm.invalidate_knob_cache()
    yield
    _nm.invalidate_knob_cache()


# ---------------------------------------------------------------------------
# D1 — const surface
# ---------------------------------------------------------------------------


def test_all_a2_conf_keys_and_defaults_exist_in_const():
    pairs = [
        ("CONF_TRIPPED_BREAKER_ZERO_WINDOW_S", "DEFAULT_TRIPPED_BREAKER_ZERO_WINDOW_S"),
        ("CONF_TRIPPED_BREAKER_ROUTE_NM", "DEFAULT_TRIPPED_BREAKER_ROUTE_NM"),
        ("CONF_LOCK_UNAVAILABLE_DEDUP_S", "DEFAULT_LOCK_UNAVAILABLE_DEDUP_S"),
        ("CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT", "DEFAULT_HUMIDITY_NORMAL_LOG_ONLY_PCT"),
        ("CONF_HUMIDITY_NORMAL_MEDIUM_PCT", "DEFAULT_HUMIDITY_NORMAL_MEDIUM_PCT"),
        ("CONF_HUMIDITY_NORMAL_HIGH_PCT", "DEFAULT_HUMIDITY_NORMAL_HIGH_PCT"),
        ("CONF_HUMIDITY_SWING_DELTA_PCT", "DEFAULT_HUMIDITY_SWING_DELTA_PCT"),
        ("CONF_HUMIDITY_SWING_MIN_ABS_PCT", "DEFAULT_HUMIDITY_SWING_MIN_ABS_PCT"),
        ("CONF_CO2_LOG_ONLY_CEILING_PPM", "DEFAULT_CO2_LOG_ONLY_CEILING_PPM"),
        ("CONF_TVOC_ABSOLUTE_HIGH_PPB", "DEFAULT_TVOC_ABSOLUTE_HIGH_PPB"),
        ("CONF_TVOC_SUSTAINED_S", "DEFAULT_TVOC_SUSTAINED_S"),
        ("CONF_SAFETY_DISCOVERY_BLOCKLIST", "DEFAULT_SAFETY_DISCOVERY_BLOCKLIST"),
        ("CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS",
         "DEFAULT_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS"),
    ]
    for conf_name, default_name in pairs:
        assert hasattr(_const, conf_name), f"missing const {conf_name}"
        assert hasattr(_const, default_name), f"missing const {default_name}"


def test_default_path_byte_identical_to_shipped_constants():
    """With no options set, `nm_cycle_a_knob` returns exactly the DEFAULT_*.

    Cycle-A-2 invariant: behavior with no options set must be byte-identical
    to v5.24.0. Drives every A-2 knob through the helper.
    """
    hass, _entry = _make_hass_with_cm()
    knob_pairs = [
        (_const.CONF_TRIPPED_BREAKER_ZERO_WINDOW_S, _const.DEFAULT_TRIPPED_BREAKER_ZERO_WINDOW_S),
        (_const.CONF_TRIPPED_BREAKER_ROUTE_NM, _const.DEFAULT_TRIPPED_BREAKER_ROUTE_NM),
        (_const.CONF_LOCK_UNAVAILABLE_DEDUP_S, _const.DEFAULT_LOCK_UNAVAILABLE_DEDUP_S),
        (_const.CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT, _const.DEFAULT_HUMIDITY_NORMAL_LOG_ONLY_PCT),
        (_const.CONF_HUMIDITY_NORMAL_MEDIUM_PCT, _const.DEFAULT_HUMIDITY_NORMAL_MEDIUM_PCT),
        (_const.CONF_HUMIDITY_NORMAL_HIGH_PCT, _const.DEFAULT_HUMIDITY_NORMAL_HIGH_PCT),
        (_const.CONF_HUMIDITY_SWING_DELTA_PCT, _const.DEFAULT_HUMIDITY_SWING_DELTA_PCT),
        (_const.CONF_HUMIDITY_SWING_MIN_ABS_PCT, _const.DEFAULT_HUMIDITY_SWING_MIN_ABS_PCT),
        (_const.CONF_CO2_LOG_ONLY_CEILING_PPM, _const.DEFAULT_CO2_LOG_ONLY_CEILING_PPM),
        (_const.CONF_TVOC_ABSOLUTE_HIGH_PPB, _const.DEFAULT_TVOC_ABSOLUTE_HIGH_PPB),
        (_const.CONF_TVOC_SUSTAINED_S, _const.DEFAULT_TVOC_SUSTAINED_S),
        (_const.CONF_SAFETY_DISCOVERY_BLOCKLIST, _const.DEFAULT_SAFETY_DISCOVERY_BLOCKLIST),
        (_const.CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS,
         _const.DEFAULT_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS),
    ]
    # Fixture self-check: guard against the tautological-fixture bug class —
    # if all defaults collapsed to a single falsy value the loop would trivially
    # pass. Assert at least one non-falsy default is present.
    assert any(v not in (0, False, (), []) for _k, v in knob_pairs)
    for conf_key, default in knob_pairs:
        _nm.invalidate_knob_cache()
        got = _nm.nm_cycle_a_knob(hass, conf_key, default)
        assert got == default, f"{conf_key}: {got!r} != {default!r}"


# ---------------------------------------------------------------------------
# D2 — reload suppression membership + cache invalidation
# ---------------------------------------------------------------------------


def test_all_a2_keys_in_reload_suppress_and_no_live_attr_source():
    """Every A-2 conf-key name literal appears in both allowlist sets in
    __init__.py's source. Reading source (rather than importing) sidesteps
    the HA-less test env; the invariant is still exact-match.
    """
    src = (CC / "__init__.py").read_text(encoding="utf-8")
    # Identify the two set literals and slice each.
    no_live_start = src.find("_NO_LIVE_ATTR_KEYS: frozenset[str] = frozenset({")
    assert no_live_start != -1
    no_live_end = src.find("})", no_live_start)
    no_live_block = src[no_live_start:no_live_end]

    suppress_start = src.find("OPTIONS_RELOAD_SUPPRESS_KEYS: frozenset[str] = frozenset({")
    assert suppress_start != -1
    suppress_end = src.find("})", suppress_start)
    suppress_block = src[suppress_start:suppress_end]

    # Both sets splat `*_NM_A2_KEYS`; that's the load-bearing wire.
    assert "*_NM_A2_KEYS" in no_live_block, (
        "_NO_LIVE_ATTR_KEYS must include *_NM_A2_KEYS — otherwise the "
        "apply_in_place path leaves NM Cycle A-2 keys un-applied and the "
        "snapshot never advances"
    )
    assert "*_NM_A2_KEYS" in suppress_block, (
        "OPTIONS_RELOAD_SUPPRESS_KEYS must include *_NM_A2_KEYS — otherwise "
        "editing any NM knob triggers a full CM reload"
    )

    # And the _NM_A2_KEYS declaration itself must list all 13 imports.
    keys_start = src.find("_NM_A2_KEYS: frozenset[str] = frozenset({")
    assert keys_start != -1
    keys_end = src.find("})", keys_start)
    keys_block = src[keys_start:keys_end]
    for name in [
        "_CONF_TRIPPED_BREAKER_ZERO_WINDOW_S",
        "_CONF_TRIPPED_BREAKER_ROUTE_NM",
        "_CONF_LOCK_UNAVAILABLE_DEDUP_S",
        "_CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT",
        "_CONF_HUMIDITY_NORMAL_MEDIUM_PCT",
        "_CONF_HUMIDITY_NORMAL_HIGH_PCT",
        "_CONF_HUMIDITY_SWING_DELTA_PCT",
        "_CONF_HUMIDITY_SWING_MIN_ABS_PCT",
        "_CONF_CO2_LOG_ONLY_CEILING_PPM",
        "_CONF_TVOC_ABSOLUTE_HIGH_PPB",
        "_CONF_TVOC_SUSTAINED_S",
        "_CONF_SAFETY_DISCOVERY_BLOCKLIST",
        "_CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS",
    ]:
        assert name in keys_block, f"_NM_A2_KEYS missing {name}"


def test_cache_invalidation_flushes_stored_value():
    """Read → mutate options WITHOUT flush → cached stale value persists →
    flush → next read hits the new value.
    """
    hass, entry = _make_hass_with_cm({_const.CONF_HUMIDITY_NORMAL_MEDIUM_PCT: 80})
    v1 = _nm.nm_cycle_a_knob(
        hass,
        _const.CONF_HUMIDITY_NORMAL_MEDIUM_PCT,
        _const.DEFAULT_HUMIDITY_NORMAL_MEDIUM_PCT,
    )
    assert v1 == 80
    # Mutate options WITHOUT invalidation — cached value must persist.
    entry.options[_const.CONF_HUMIDITY_NORMAL_MEDIUM_PCT] = 70
    v_stale = _nm.nm_cycle_a_knob(
        hass,
        _const.CONF_HUMIDITY_NORMAL_MEDIUM_PCT,
        _const.DEFAULT_HUMIDITY_NORMAL_MEDIUM_PCT,
    )
    assert v_stale == 80, "cache must persist without explicit flush"
    # Fixture self-check.
    assert entry.options[_const.CONF_HUMIDITY_NORMAL_MEDIUM_PCT] == 70
    _nm.invalidate_knob_cache()
    v2 = _nm.nm_cycle_a_knob(
        hass,
        _const.CONF_HUMIDITY_NORMAL_MEDIUM_PCT,
        _const.DEFAULT_HUMIDITY_NORMAL_MEDIUM_PCT,
    )
    assert v2 == 70, "post-invalidate call must re-read entry.options"


def test_listener_flushes_knob_cache_source():
    """Mutation-anchored: the CM branch of _async_update_listener MUST
    invoke `invalidate_knob_cache` BEFORE the subset check. Remove the
    call site (or move it after the subset check) → this test fails.
    """
    src = (CC / "__init__.py").read_text(encoding="utf-8")
    # Scope to the update-listener function (there are earlier occurrences
    # of the same string in _async_setup_entry helpers).
    listener_idx = src.find("async def _async_update_listener")
    assert listener_idx != -1
    listener_src = src[listener_idx:]
    idx = listener_src.find('if entry_type == ENTRY_TYPE_COORDINATOR_MANAGER:')
    assert idx != -1
    tail = listener_src[idx: idx + 3000]
    flush_pos = tail.find("invalidate_knob_cache()")
    subset_pos = tail.find("OPTIONS_RELOAD_SUPPRESS_KEYS")
    assert flush_pos != -1, (
        "NM Cycle A-2 B-LOW-1: `invalidate_knob_cache()` missing from CM "
        "branch of _async_update_listener — knob cache would go stale on "
        "options edits"
    )
    assert flush_pos < subset_pos, (
        "invalidate_knob_cache() must run BEFORE the reload-suppress subset "
        "check so the cache is fresh whether or not we apply-in-place"
    )


# ---------------------------------------------------------------------------
# D3 — optimizer allowlist L4 normalization
# ---------------------------------------------------------------------------


def test_optimizer_allowlist_empty_by_default_tuple_default():
    assert _const.DEFAULT_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS == ()


# C-HIGH-2 fix-up (2026-07-20): behavioral test drives the REAL
# production path `_nm.high_finding_allowlisted` — no hand-copied
# normalization. Mutation `strip .lower() / strip getattr(dim,"value")`
# on the helper flunks the case + Enum-value assertions below.


class _EnumLikeDim:
    """Stand-in for `OptimizationDimension.COMFORT`.

    ``.value`` holds the canonical lowercased string; ``__str__`` returns
    the qualified enum repr to force the read-side to unwrap ``.value``
    (bare `str(dim)` would produce the wrong stringification).
    """
    def __init__(self, val):
        self.value = val
    def __str__(self):
        return f"OptimizationDimension.{self.value.upper()}"


class _FindingStub:
    def __init__(self, severity, dimension):
        self.severity = severity
        self.dimension = dimension


def test_high_finding_allowlisted_normalizes_case_and_enum_value():
    """C-HIGH-2 (behavioral): drives `_nm.high_finding_allowlisted` end-to-end.

    Mutation ``strip .lower()`` on either side → uppercase persisted
    allowlist vs lowercased Enum-.value diverges → helper returns False →
    the first assertion below flunks.

    Mutation ``remove getattr(dim, "value", dim)`` → ``str(_EnumLikeDim)`` is
    ``"OptimizationDimension.COMFORT"`` (via ``__str__``), not ``"comfort"``
    → the second assertion below flunks.
    """
    # (a) Uppercase persisted allowlist + lowercased-Enum-.value dim → matches.
    hass, _e = _make_hass_with_cm(
        {_const.CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS: ["COMFORT"]},
    )
    _nm.invalidate_knob_cache()
    assert _nm.high_finding_allowlisted(
        hass, _FindingStub("high", _EnumLikeDim("comfort"))
    ) is True, (
        "case-normalization broken: uppercase persisted allowlist entry must "
        "match lowercased Enum-.value dimension"
    )
    # (b) Lowercase allowlist + Enum-like dim whose __str__ != .value → matches.
    hass2, _e2 = _make_hass_with_cm(
        {_const.CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS: ["comfort"]},
    )
    _nm.invalidate_knob_cache()
    assert _nm.high_finding_allowlisted(
        hass2, _FindingStub("high", _EnumLikeDim("comfort"))
    ) is True, (
        ".value unwrap broken: str(_EnumLikeDim) == "
        "'OptimizationDimension.COMFORT' would not match allowlist entry "
        "'comfort' without getattr(dim, 'value', dim)"
    )
    # (c) Non-allowlisted dimension → False (locks the negative branch).
    _nm.invalidate_knob_cache()
    assert _nm.high_finding_allowlisted(
        hass2, _FindingStub("high", _EnumLikeDim("safety"))
    ) is False
    # (d) None dimension → False.
    _nm.invalidate_knob_cache()
    assert _nm.high_finding_allowlisted(
        hass2, _FindingStub("high", None)
    ) is False


def test_should_defer_high_to_digest_both_branches():
    """C-HIGH-3 (behavioral): the defer helper covers BOTH gate branches.

    * Non-allowlisted HIGH finding → defer (helper returns True).
    * Allowlisted HIGH finding    → PAGE (helper returns False).
    * CRITICAL finding             → NEVER defer (severity gate).

    Mutation ``if False and ...`` (bypass) on the caller is caught by the
    source-anchored consumer wiring test below (asserts the caller invokes
    `should_defer_high_to_digest` and `return`s on True).
    """
    hass, _e = _make_hass_with_cm(
        {_const.CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS: ["comfort"]},
    )
    _nm.invalidate_knob_cache()
    # Non-allowlisted HIGH → defer.
    assert _nm.should_defer_high_to_digest(
        hass, _FindingStub("high", "security_posture")
    ) is True
    # Allowlisted HIGH → page (do NOT defer).
    _nm.invalidate_knob_cache()
    assert _nm.should_defer_high_to_digest(
        hass, _FindingStub("high", "comfort")
    ) is False
    # CRITICAL — never defer even if not allowlisted.
    _nm.invalidate_knob_cache()
    assert _nm.should_defer_high_to_digest(
        hass, _FindingStub("critical", "security_posture")
    ) is False


def test_optimizer_consumer_wired_to_should_defer_helper():
    """Mutation-anchored: `_notify_if_severe` MUST invoke
    `should_defer_high_to_digest(...)` and `return` on truthy.

    Mutation `if False and should_defer_high_to_digest(...)` — the string
    " and " inside the `if` disqualifies the assertion below (we require the
    call to be the sole predicate of an `if ...:` line). Removing the
    `return` after the log line also flunks (asserts `return` sits
    inside the branch).
    """
    src = (CC / "domain_coordinators" / "optimization.py").read_text(encoding="utf-8")
    idx = src.find("async def _notify_if_severe")
    assert idx != -1
    body = src[idx: idx + 3000]
    # Import present.
    assert "from ._nm_cycle_a import should_defer_high_to_digest" in body
    # Gate is exactly `if should_defer_high_to_digest(self.hass, finding):`
    # (no trailing conjunction that would bypass the helper's return value).
    assert "if should_defer_high_to_digest(self.hass, finding):" in body, (
        "gate must be a bare `if should_defer_high_to_digest(...):` — any "
        "extra conjunction (`and`/`or`) would let a mutation bypass the helper"
    )
    # `return` follows the log inside the branch.
    gate_start = body.find("if should_defer_high_to_digest(self.hass, finding):")
    branch = body[gate_start: gate_start + 500]
    assert "return" in branch, "defer branch must `return`"
    # The deprecated bare-frozenset import must NOT reappear.
    assert "from ..const import OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS" not in body


# ---------------------------------------------------------------------------
# D1 (behavioral) — OptionsFlow round-trip via the HA-mock harness
# ---------------------------------------------------------------------------


def test_volume_step_defaults_wired_via_const_source():
    """Source-anchored: the step method resolves each field's default via
    `self._get_current(CONF_*, DEFAULT_*)` — never inlined literals.

    Behavioral form-render was attempted here but the schema build in the
    full-suite context depends on which module load holds
    `UniversalRoomAutomationOptionsFlow` (multiple sibling test harnesses
    each stash their own copy). Source-anchoring is the deterministic
    equivalent: if any default drifts to a literal, this test flunks.
    """
    src = (CC / "config_flow.py").read_text(encoding="utf-8")
    idx = src.find("async def async_step_coordinator_notifications_volume")
    body = src[idx: idx + 20000]
    conf_defaults = [
        ("CONF_TRIPPED_BREAKER_ZERO_WINDOW_S", "DEFAULT_TRIPPED_BREAKER_ZERO_WINDOW_S"),
        ("CONF_TRIPPED_BREAKER_ROUTE_NM", "DEFAULT_TRIPPED_BREAKER_ROUTE_NM"),
        ("CONF_LOCK_UNAVAILABLE_DEDUP_S", "DEFAULT_LOCK_UNAVAILABLE_DEDUP_S"),
        ("CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT", "DEFAULT_HUMIDITY_NORMAL_LOG_ONLY_PCT"),
        ("CONF_HUMIDITY_NORMAL_MEDIUM_PCT", "DEFAULT_HUMIDITY_NORMAL_MEDIUM_PCT"),
        ("CONF_HUMIDITY_NORMAL_HIGH_PCT", "DEFAULT_HUMIDITY_NORMAL_HIGH_PCT"),
        ("CONF_HUMIDITY_SWING_DELTA_PCT", "DEFAULT_HUMIDITY_SWING_DELTA_PCT"),
        ("CONF_HUMIDITY_SWING_MIN_ABS_PCT", "DEFAULT_HUMIDITY_SWING_MIN_ABS_PCT"),
        ("CONF_CO2_LOG_ONLY_CEILING_PPM", "DEFAULT_CO2_LOG_ONLY_CEILING_PPM"),
        ("CONF_TVOC_ABSOLUTE_HIGH_PPB", "DEFAULT_TVOC_ABSOLUTE_HIGH_PPB"),
        ("CONF_TVOC_SUSTAINED_S", "DEFAULT_TVOC_SUSTAINED_S"),
        ("CONF_SAFETY_DISCOVERY_BLOCKLIST", "DEFAULT_SAFETY_DISCOVERY_BLOCKLIST"),
        ("CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS",
         "DEFAULT_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS"),
    ]
    for conf, default in conf_defaults:
        assert conf in body, f"volume step missing CONF import for {conf}"
        assert default in body, f"volume step missing DEFAULT for {conf}"
        # Pattern: default=self._get_current(CONF_X, DEFAULT_X) or similar
        assert f"self._get_current(\n                    {conf}" in body or \
               f"self._get_current({conf}" in body, (
            f"{conf} default must resolve via self._get_current(...) "
            "so options-first, const-fallback semantics are preserved"
        )


@pytest.mark.asyncio
async def test_volume_step_roundtrip_persists_and_normalizes_allowlist():
    """Submit → persisted options carry every field; allowlist lowercased."""
    flow = _make_options_flow(
        data={_const.CONF_ENTRY_TYPE: _const.ENTRY_TYPE_COORDINATOR_MANAGER},
        options={},
    )
    user_input = {
        _const.CONF_HUMIDITY_NORMAL_MEDIUM_PCT: 80,
        _const.CONF_TRIPPED_BREAKER_ROUTE_NM: True,
        _const.CONF_LOCK_UNAVAILABLE_DEDUP_S: 3600,
        _const.CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS: ["Comfort", "SAFETY"],
        _const.CONF_SAFETY_DISCOVERY_BLOCKLIST: ["sensor.foo", "sensor.bar"],
    }
    with _StubHAContext():
        result = await flow.async_step_coordinator_notifications_volume(
            user_input=user_input,
        )
    assert result["type"] == "create_entry"
    saved = result["data"]
    assert saved[_const.CONF_HUMIDITY_NORMAL_MEDIUM_PCT] == 80
    assert saved[_const.CONF_TRIPPED_BREAKER_ROUTE_NM] is True
    assert saved[_const.CONF_LOCK_UNAVAILABLE_DEDUP_S] == 3600
    assert saved[_const.CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS] == ["comfort", "safety"]
    assert saved[_const.CONF_SAFETY_DISCOVERY_BLOCKLIST] == ["sensor.foo", "sensor.bar"]


@pytest.mark.asyncio
async def test_volume_step_rejects_inverted_humidity_ladder():
    """A2 fix-up (2026-07-20): save-time validation blocks a non-monotonic
    humidity ladder (low > medium OR medium > high). Form re-renders with
    an `errors["base"]` code — NOT persisted.
    """
    flow = _make_options_flow(
        data={_const.CONF_ENTRY_TYPE: _const.ENTRY_TYPE_COORDINATOR_MANAGER},
        options={},
    )
    # Inverted: medium (90) > high (80).
    user_input = {
        _const.CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT: 70,
        _const.CONF_HUMIDITY_NORMAL_MEDIUM_PCT: 90,
        _const.CONF_HUMIDITY_NORMAL_HIGH_PCT: 80,
    }
    with _StubHAContext():
        result = await flow.async_step_coordinator_notifications_volume(
            user_input=user_input,
        )
    assert result["type"] == "form", (
        "inverted ladder must re-render the form, not persist"
    )
    assert result.get("errors"), "errors dict must be populated"
    assert result["errors"].get("base") == "nm_a4_humidity_ladder_not_monotonic"


@pytest.mark.asyncio
async def test_volume_step_open_and_save_untouched_persists_no_defaults():
    """C-MED-1 fix-up (2026-07-20): submitting all fields at DEFAULT_*
    (i.e. the shape of `async_show_form` re-rendered with no user edits)
    MUST NOT persist any of the 13 A-2 keys — future const retunes need
    to reach deployments.

    Mutation: skip the DEFAULT drop → this test flunks because the
    resulting `saved` dict gains every A-2 key.
    """
    flow = _make_options_flow(
        data={_const.CONF_ENTRY_TYPE: _const.ENTRY_TYPE_COORDINATOR_MANAGER},
        options={},
    )
    # Simulate "open form + save without touching" — every field submitted
    # equals its DEFAULT_*.
    default_input = {
        _const.CONF_TRIPPED_BREAKER_ZERO_WINDOW_S: float(_const.DEFAULT_TRIPPED_BREAKER_ZERO_WINDOW_S),
        _const.CONF_TRIPPED_BREAKER_ROUTE_NM: _const.DEFAULT_TRIPPED_BREAKER_ROUTE_NM,
        _const.CONF_LOCK_UNAVAILABLE_DEDUP_S: float(_const.DEFAULT_LOCK_UNAVAILABLE_DEDUP_S),
        _const.CONF_HUMIDITY_NORMAL_LOG_ONLY_PCT: float(_const.DEFAULT_HUMIDITY_NORMAL_LOG_ONLY_PCT),
        _const.CONF_HUMIDITY_NORMAL_MEDIUM_PCT: float(_const.DEFAULT_HUMIDITY_NORMAL_MEDIUM_PCT),
        _const.CONF_HUMIDITY_NORMAL_HIGH_PCT: float(_const.DEFAULT_HUMIDITY_NORMAL_HIGH_PCT),
        _const.CONF_HUMIDITY_SWING_DELTA_PCT: float(_const.DEFAULT_HUMIDITY_SWING_DELTA_PCT),
        _const.CONF_HUMIDITY_SWING_MIN_ABS_PCT: float(_const.DEFAULT_HUMIDITY_SWING_MIN_ABS_PCT),
        _const.CONF_CO2_LOG_ONLY_CEILING_PPM: float(_const.DEFAULT_CO2_LOG_ONLY_CEILING_PPM),
        _const.CONF_TVOC_ABSOLUTE_HIGH_PPB: float(_const.DEFAULT_TVOC_ABSOLUTE_HIGH_PPB),
        _const.CONF_TVOC_SUSTAINED_S: float(_const.DEFAULT_TVOC_SUSTAINED_S),
        _const.CONF_SAFETY_DISCOVERY_BLOCKLIST: list(_const.DEFAULT_SAFETY_DISCOVERY_BLOCKLIST),
        _const.CONF_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS:
            list(_const.DEFAULT_OPTIMIZER_NM_HIGH_ALLOWLIST_DIMENSIONS),
    }
    with _StubHAContext():
        result = await flow.async_step_coordinator_notifications_volume(
            user_input=default_input,
        )
    assert result["type"] == "create_entry"
    saved = result["data"]
    a2_keys = set(default_input.keys())
    persisted_a2 = a2_keys & saved.keys()
    assert not persisted_a2, (
        "no A-2 keys should be persisted when every submitted value equals "
        f"its DEFAULT_*; got: {sorted(persisted_a2)}"
    )


@pytest.mark.asyncio
async def test_volume_step_reset_to_default_removes_previously_persisted_key():
    """C-MED-1 fix-up: a key that WAS persisted, then re-submitted at its
    DEFAULT_*, MUST be REMOVED from options (not kept at the default value).
    """
    # Pre-seed options with a non-default humidity medium.
    flow = _make_options_flow(
        data={_const.CONF_ENTRY_TYPE: _const.ENTRY_TYPE_COORDINATOR_MANAGER},
        options={_const.CONF_HUMIDITY_NORMAL_MEDIUM_PCT: 80},
    )
    # Now user re-submits medium = default (85) — expect key removed.
    user_input = {
        _const.CONF_HUMIDITY_NORMAL_MEDIUM_PCT:
            float(_const.DEFAULT_HUMIDITY_NORMAL_MEDIUM_PCT),
    }
    with _StubHAContext():
        result = await flow.async_step_coordinator_notifications_volume(
            user_input=user_input,
        )
    assert result["type"] == "create_entry"
    saved = result["data"]
    assert _const.CONF_HUMIDITY_NORMAL_MEDIUM_PCT not in saved, (
        "reset-to-default MUST remove the previously-persisted key"
    )


@pytest.mark.asyncio
async def test_menu_lists_notification_volume_option():
    """The CM options menu MUST expose `coordinator_notifications_volume`."""
    flow = _make_options_flow(
        data={_const.CONF_ENTRY_TYPE: _const.ENTRY_TYPE_COORDINATOR_MANAGER},
        options={},
    )
    result = await flow.async_step_init()
    assert result["type"] == "menu"
    assert "coordinator_notifications_volume" in result["menu_options"]
