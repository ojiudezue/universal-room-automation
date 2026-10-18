"""TEST-HARNESS Wave 2 D7: donor-hygiene anchors.

A "donor" is a test file that leaves a stub / monkeypatch behind and turns a
LATER file's tests red. Each donor fixed in D7 gets one entry in
``DONOR_PROBES``: the exact symbols it used to clobber. The anchor runs, in a
fresh subprocess, ``pytest <donor> <this file>::test_probe`` — the probe runs
AFTER every donor test and asserts each listed symbol is the REAL one again.

Re-introducing the leak (e.g. reverting a donor's fixture-scoped install to an
import-time write) turns ``test_donor_leaves_no_residue[<donor>]`` red; see the
``_mutation_sandbox`` drills at the bottom.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from _mutation_sandbox import apply_mutation_in_sandbox

_HERE = Path(__file__).resolve()
_TESTS = _HERE.parent
_REPO = _TESTS.parent.parent
_ENV_KEY = "URA_D7_PROBE"
_REAL_OWNERS = ("homeassistant", "pytest_homeassistant_custom_component")

# donor file -> [(module, attr | None, kind)]
#   kind "ha"  : sys.modules[module] is the real homeassistant module and
#                attr (if given) is defined in a homeassistant.* module.
#   kind "ura" : sys.modules[module] (if present) is the real package from
#                custom_components/ (has a __file__ inside the repo) and attr
#                (if given) is defined in a custom_components.* module.
#   kind "ident": sys.modules[module] is still the SAME object it was when
#                this file was collected (after the donor's collection,
#                before the donor's tests ran) -- catches run-time
#                eviction / re-import of a real module.
DONOR_PROBES: dict[str, list[tuple[str, str | None, str]]] = {
    "test_chatter_detector.py": [
        ("homeassistant.helpers.entity_registry", "async_get", "ha"),
        ("homeassistant.core", "Event", "ha"),
        ("homeassistant.core", "HomeAssistant", "ha"),
        ("homeassistant.helpers.event", "async_track_state_change_event", "ha"),
        ("homeassistant.util.dt", "utcnow", "ha"),
    ],
    "test_identity_fusion_d2_d3_d4.py": [
        ("homeassistant.helpers.entity_registry", "async_get", "ha"),
        ("homeassistant.util.dt", "utcnow", "ha"),
    ],
    "test_appliance_coordinator_v1a.py": [
        ("homeassistant.helpers.entity_registry", "async_get", "ha"),
    ],
    "test_ac_ramp_master_option_persistence.py": [
        ("custom_components.universal_room_automation", None, "ura"),
        ("custom_components.universal_room_automation.domain_coordinators", None, "ura"),
    ],
    "test_bathroom_exhaust_occupancy_and_resend.py": [
        ("homeassistant.core", "callback", "ha"),
        ("homeassistant.core", "HomeAssistant", "ha"),
        ("homeassistant.helpers.entity_registry", "async_get", "ha"),
        ("homeassistant.helpers.event", "async_track_state_change_event", "ha"),
        ("homeassistant.util.dt", None, "ha"),
    ],
    "test_census_device_switches.py": [
        ("custom_components.universal_room_automation", None, "ura"),
        ("custom_components.universal_room_automation.domain_coordinators", None, "ura"),
        ("custom_components.universal_room_automation.transit_validator", None, "ura"),
    ],
    "test_onboarding_simplify_slice1.py": [
        ("homeassistant.helpers.entity_registry", "async_get", "ha"),
        ("homeassistant.helpers.device_registry", "async_get", "ha"),
    ],
    # Slice 2: same import-time shape as bathroom_exhaust_occupancy.
    "test_comfort_fan_away_veto_behavioral.py": [
        ("homeassistant.core", "callback", "ha"),
        ("homeassistant.core", "HomeAssistant", "ha"),
        ("homeassistant.helpers.entity_registry", "async_get", "ha"),
        ("homeassistant.helpers.event", "async_track_state_change_event", "ha"),
        ("homeassistant.util.dt", None, "ha"),
    ],
    "test_carrier_freshness.py": [
        ("homeassistant.core", "callback", "ha"),
        ("homeassistant.core", "HomeAssistant", "ha"),
        ("homeassistant.helpers.entity_registry", "async_get", "ha"),
        ("homeassistant.helpers.event", "async_track_state_change_event", "ha"),
        ("homeassistant.util.dt", None, "ha"),
    ],
    # Borrows onboarding's _install_registries (and now its restore fixture).
    "test_room_create_prefill_filter.py": [
        ("homeassistant.helpers.entity_registry", "async_get", "ha"),
        ("homeassistant.helpers.device_registry", "async_get", "ha"),
    ],
    "test_v5_17_1_part3_seams.py": [
        ("homeassistant.util.dt", "utcnow", "ha"),
        ("homeassistant.util.dt", "now", "ha"),
        ("homeassistant.util.dt", "parse_datetime", "ha"),
    ],
    "test_oc_pillar_a_handshake.py": [
        ("custom_components.universal_room_automation.domain_coordinators.presence", None, "ident"),
        ("custom_components.universal_room_automation.const", None, "ident"),
    ],
    "test_hvac_fan_control.py": [
        ("custom_components.universal_room_automation", None, "ura"),
        ("custom_components.universal_room_automation.const", None, "ura"),
        ("custom_components.universal_room_automation.domain_coordinators.signals", None, "ura"),
        # The residue the conftest PRODSTUBS rescue cannot heal (setdefault
        # keeps the stub's value): EnergyConstraint = MagicMock.
        ("custom_components.universal_room_automation.domain_coordinators.signals",
         "EnergyConstraint", "ura"),
    ],
}


# kind "ident" baseline, taken at collection time inside the probe run only.
_IDENT_AT_COLLECT: dict = {}
if os.environ.get(_ENV_KEY) in DONOR_PROBES:
    for _m, _a, _k in DONOR_PROBES[os.environ[_ENV_KEY]]:
        if _k == "ident":
            _IDENT_AT_COLLECT[_m] = importlib.import_module(_m)


def _residue(probes) -> list[str]:
    bad = []
    for modname, attr, kind in probes:
        mod = sys.modules.get(modname)
        if kind == "ident":
            if mod is not _IDENT_AT_COLLECT.get(modname):
                bad.append(f"sys.modules[{modname!r}] was replaced/evicted at run time")
            continue
        if kind == "ura":
            if mod is None:
                continue
            f = getattr(mod, "__file__", None) or ""
            # A types.ModuleType placeholder has no import spec — even after
            # the conftest PRODSTUBS rescue backfills __path__/__file__.
            spec = getattr(mod, "__spec__", None)
            if spec is None or not getattr(spec, "origin", None):
                bad.append(f"{modname} is a placeholder (no import spec)")
            elif not f or not Path(f).resolve().is_relative_to(_REPO / "custom_components"):
                bad.append(f"{modname} is a placeholder (__file__={f!r})")
            elif attr is not None:
                val = getattr(mod, attr, None)
                owner = getattr(val, "__module__", None)
                if not (isinstance(owner, str) and owner.startswith("custom_components.")):
                    bad.append(f"{modname}.{attr} is foreign: {val!r}")
            continue
        if mod is None:
            mod = importlib.import_module(modname)
        f = getattr(mod, "__file__", None) or ""
        if f"{os.sep}homeassistant{os.sep}" not in f:
            bad.append(f"sys.modules[{modname!r}] is not real HA (__file__={f!r})")
            continue
        if attr is None:
            continue
        val = getattr(mod, attr, None)
        owner = getattr(val, "__module__", None)
        # phcc legitimately patches some HA helpers (e.g. dt.utcnow).
        if not (isinstance(owner, str) and owner.startswith(_REAL_OWNERS)):
            bad.append(f"{modname}.{attr} is foreign: {val!r} (__module__={owner!r})")
    return bad


_PARENT_PREFIXES = ("custom_components", "homeassistant")


def _parent_attr_residue(prefixes=_PARENT_PREFIXES) -> list[str]:
    """Submodule attributes on a package that disagree with sys.modules.

    The import system binds ``pkg.child`` as an attribute of ``pkg``. A scope
    that pops ``pkg.child`` from sys.modules but leaves the attribute behind
    gives ``from pkg import child`` a DIFFERENT object than
    ``sys.modules['pkg.child']`` (review s1 B-LOW / A-LOW-1)."""
    bad = []
    for name, mod in list(sys.modules.items()):
        if mod is None or not any(name == p or name.startswith(p + ".") for p in prefixes):
            continue
        try:
            items = list(vars(mod).items())
        except TypeError:
            continue
        for attr, val in items:
            if not isinstance(val, types.ModuleType):
                continue
            child = f"{name}.{attr}"
            if getattr(val, "__name__", None) != child:
                continue
            if sys.modules.get(child) is not val:
                bad.append(f"{child}: parent attribute is a stale module object")
    return bad


def test_probe():
    """Only meaningful inside the subprocess launched below."""
    donor = os.environ.get(_ENV_KEY)
    if not donor:
        pytest.skip("probe runs only inside test_donor_leaves_no_residue")
    assert _residue(DONOR_PROBES[donor]) == []
    assert _parent_attr_residue() == []


def _run_pair(donor: str, root: Path = _REPO) -> subprocess.CompletedProcess:
    tests = root / "quality" / "tests"
    env = {**os.environ, _ENV_KEY: donor, "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(root / "quality")}
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(tests / donor),
         f"{tests / _HERE.name}::test_probe", "-q", "-p", "no:cacheprovider",
         "-rA", "--tb=short"],
        cwd=root, env=env, capture_output=True, text=True, timeout=300,
    )


@pytest.mark.parametrize("donor", sorted(DONOR_PROBES))
def test_donor_leaves_no_residue(donor):
    proc = _run_pair(donor)
    out = proc.stdout + proc.stderr
    # The probe must have RUN (not skipped) and passed, and the donor's own
    # tests must still pass (a fix may not weaken the donor).
    # The probe must have RUN (not skipped) and PASSED. The donor's own
    # pass/fail is that file's business (some donors carry pre-existing,
    # order-independent failures — e.g. census_device_switches' 6, slice 2).
    assert f"PASSED quality/tests/{_HERE.name}::test_probe" in out, out[-3000:]


# donor file -> victim node ids that fail when the donor runs first (found
# with collect_order_matrix.py --find-donors / --victim). Anchor: the pair
# run in that order must be green.
DONOR_VICTIMS: dict[str, list[str]] = {
    "test_perimeter_alert_nm_routing.py": [
        "test_exterior_cycle2.py::test_vehicle_in_flight_guard_dedups_fused_edges",
    ],
    # Run-time donor: pops `...domain_coordinators.presence` from sys.modules,
    # so a later `from ... import presence` yields a NEW module object. Fixed
    # victim-side (v4715 now patches the coordinator's own globals).
    # Collection-time donor; reproduced pre-fix: exactly the 9 suite names.
    "test_bathroom_exhaust_occupancy_and_resend.py": [
        "test_dp_drain_target_value_stamp.py::test_debounce_first_none_tick_holds_pause",
        "test_evse_drain_precedence_session_b2b_i.py::test_force_charge_preempts_dp_pause_release",
        "test_evse_drain_precedence_session_b2b_ii.py::test_must_start_by_arm_skipped_when_fire_at_in_past",
        "test_evse_drain_precedence_session_b2c2_fixup.py::test_transition_entry_pauses_actual_configured_evse_id",
    ],
    # Slice 2: second collection-time donor of the same 9 (bisected against
    # the full default-order prefix after bathroom_exhaust was scoped).
    "test_comfort_fan_away_veto_behavioral.py": [
        "test_dp_drain_target_value_stamp.py::test_debounce_first_none_tick_holds_pause",
        "test_evse_drain_precedence_session_b2b_i.py::test_force_charge_preempts_dp_pause_release",
        "test_evse_drain_precedence_session_b2b_ii.py::test_must_start_by_arm_skipped_when_fire_at_in_past",
        "test_evse_drain_precedence_session_b2c2_fixup.py::test_transition_entry_pauses_only_charging_evse_ids_multi_evse",
    ],
    # Reproduced pre-fix: 15 weather_manager + 4 dpm_drift_guard + 1 v5110.
    "test_identity_fusion_d2_d3_d4.py": [
        "test_v47x_weather_manager.py::TestApparentFallback::test_apparent_fallback_to_raw",
        "test_v4_7_18_dpm_drift_guard.py::TestCounterRestartResilience::test_restore_rehydrates_counter",
        "test_v5110_optimizer_hardening.py::TestD9WriteVolumeTripwire::test_rolling_window_evicts_old_timestamps",
    ],
    # Reproduced pre-fix: signals.EnergyConstraint left as MagicMock.
    "test_hvac_fan_control.py": [
        "test_v47x_weather_manager.py::TestEnergyConstraintApparentField::test_apparent_field_defaults_to_none",
    ],
    # Collect-time donor: binds an AWARE dt_util.utcnow at import, after the
    # NM files' own import-time naive write. Fixed victim-side (per-test pin).
    "test_v5_17_1_part3_seams.py": [
        "test_nm_cycle_c2_fixup.py::test_router_mute_exception_extras_promoted",
        "test_nm_cycle_c_routing_matrix.py::TestC4MuteShortcut::test_mute_expiry_auto_clears",
        "test_nm_image_delivery.py::TestD2ForceImmediateOverride::test_force_immediate_respects_silence_until",
    ],
    # Run-time donor (UNFIXED, slice 2): leaves entity_registry.async_get on a
    # registry whose lookups return None. Victims fixed victim-side (pin).
    "test_onboarding_simplify_slice1.py": [
        "test_envoy_auto_derive.py::TestValidateEnvoyConfig::test_full_pass",
        "test_ec_solar_entity_override.py::test_ec_solar_override_validation_resolves_override",
    ],
    "test_oc_pillar_a_handshake.py": [
        "test_v4715_universalize_veto.py::TestD3InferenceOrchestration::test_guest_exit_fires_after_sustained_quiet",
    ],
}


def _pair_ids():
    return [(d, v) for d, vs in sorted(DONOR_VICTIMS.items()) for v in vs]


@pytest.mark.parametrize("donor,victim", _pair_ids())
def test_victim_green_after_donor(donor, victim):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(_REPO / "quality")}
    # Run the victim's WHOLE file (some leaks only bite after the victim
    # file's own earlier tests have run) and require the named node PASSED.
    vfile = victim.split("::", 1)[0]
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(_TESTS / donor), str(_TESTS / vfile),
         "-q", "-p", "no:cacheprovider", "--tb=short", "-rA"],
        cwd=_REPO, env=env, capture_output=True, text=True, timeout=300,
    )
    out = proc.stdout + proc.stderr
    assert f"PASSED quality/tests/{victim}" in out, out[-3000:]


# ---------------------------------------------------------------------------
# Mutation drills: re-introduce each donor's leak in a sandbox copy -> the
# matching anchor must go RED. (source_mutation: excluded from default run.)
# ---------------------------------------------------------------------------

_DRILLS = {
    # Revert the module-scoped, undone install to a never-undone one.
    "test_chatter_detector.py": ("    yield\n    mp.undo()\n", "    yield\n"),
    # Disable the restoring fixture.
    "test_identity_fusion_d2_d3_d4.py": (
        "@pytest.fixture(autouse=True)\ndef _scope_real_ha_patches",
        "def _scope_real_ha_patches",
    ),
    "test_appliance_coordinator_v1a.py": (
        "@pytest.fixture(autouse=True)\ndef _d7_restore_entity_registry_async_get",
        "def _d7_restore_entity_registry_async_get",
    ),
    "test_ac_ramp_master_option_persistence.py": (
        "with _d7_import_scope(attrs=True) as _D7_INSTALLED:",
        "with _d7_import_scope(prefixes=()) as _D7_INSTALLED:",
    ),
    "test_census_device_switches.py": (
        "with _d7_import_scope() as _D7_INSTALLED:",
        "with _d7_import_scope(prefixes=()) as _D7_INSTALLED:",
    ),
    "test_comfort_fan_away_veto_behavioral.py": (
        "with _d7_import_scope(attrs=True) as _D7_INSTALLED:",
        "with _d7_import_scope(prefixes=()) as _D7_INSTALLED:",
    ),
    "test_carrier_freshness.py": (
        "with _d7_import_scope(attrs=True) as _D7_INSTALLED:",
        "with _d7_import_scope(prefixes=()) as _D7_INSTALLED:",
    ),
    "test_onboarding_simplify_slice1.py": (
        "@pytest.fixture(autouse=True)\ndef _d7_restore_registries",
        "def _d7_restore_registries",
    ),
    # The borrowed fixture is bound into the file's namespace: unbind it.
    "test_room_create_prefill_filter.py": (
        "_d7_restore_registries = _slice1._d7_restore_registries\n",
        "",
    ),
    "test_v5_17_1_part3_seams.py": (
        "@pytest.fixture(autouse=True)\ndef _d7_tz_aware_dt",
        "def _d7_tz_aware_dt",
    ),
    "test_oc_pillar_a_handshake.py": (
        "    with _d7_import_scope(prefixes=(\"custom_components\",), attrs=True):",
        "    with _d7_import_scope(prefixes=()):",
    ),
    # Un-scope the import block: restore nothing on exit.
    "test_hvac_fan_control.py": (
        "with _d7_import_scope() as _D7_INSTALLED:",
        "with _d7_import_scope(prefixes=()) as _D7_INSTALLED:",
    ),
}


# Drills whose anchor is a donor->victim pair (the reviewer-C shape:
# neuter the donor fix -> the victim goes red).
_PAIR_DRILLS = {
    "test_comfort_fan_away_veto_behavioral.py": (
        "with _d7_import_scope(attrs=True) as _D7_INSTALLED:",
        "with _d7_import_scope(prefixes=()) as _D7_INSTALLED:",
    ),
    "test_perimeter_alert_nm_routing.py": ("    yield\n    _scheduled.clear()\n", "    yield\n"),
    "test_bathroom_exhaust_occupancy_and_resend.py": (
        "with _d7_import_scope(attrs=True) as _D7_INSTALLED:",
        "with _d7_import_scope(prefixes=()) as _D7_INSTALLED:",
    ),
    "test_identity_fusion_d2_d3_d4.py": (
        "@pytest.fixture(autouse=True)\ndef _scope_real_ha_patches",
        "def _scope_real_ha_patches",
    ),
    "test_hvac_fan_control.py": (
        "with _d7_import_scope() as _D7_INSTALLED:",
        "with _d7_import_scope(prefixes=()) as _D7_INSTALLED:",
    ),
}


@pytest.mark.source_mutation
@pytest.mark.parametrize("donor", sorted(_PAIR_DRILLS))
def test_drill_donor_fix_neutered_victim_goes_red(donor):
    swap_from, swap_to = _PAIR_DRILLS[donor]
    victim = DONOR_VICTIMS[donor][0]
    apply_mutation_in_sandbox(
        _TESTS / donor,
        swap_from=swap_from,
        swap_to=swap_to,
        anchor_test_file=_HERE,
        anchor_test_name=f"test_victim_green_after_donor[{donor}-{victim}]",
        expect="KILLED",
        timeout=600,
    )


@pytest.mark.source_mutation
@pytest.mark.parametrize("donor", sorted(_DRILLS))
def test_drill_donor_leak_reintroduced_goes_red(donor):
    swap_from, swap_to = _DRILLS[donor]
    apply_mutation_in_sandbox(
        _TESTS / donor,
        swap_from=swap_from,
        swap_to=swap_to,
        anchor_test_file=_HERE,
        anchor_test_name=f"test_donor_leaves_no_residue[{donor}]",
        expect="KILLED",
        timeout=600,
    )


# ---------------------------------------------------------------------------
# Beneficiary fixes: files that passed only because a donor's leak happened
# to suit them (exposed once the donor was scoped). Drill: undo the fix in a
# sandbox copy -> the file's own anchor goes RED when run alone.
# ---------------------------------------------------------------------------

_SELF_DRILLS = {
    "test_safeword_window.py": (
        "remaining = nm._perimeter_silence_until - _now()",
        "remaining = nm._perimeter_silence_until - datetime.utcnow()",
        "test_duke_45m_parses",
    ),
}


@pytest.mark.source_mutation
@pytest.mark.parametrize("target", sorted(_SELF_DRILLS))
def test_drill_beneficiary_fix_reverted_goes_red(target):
    swap_from, swap_to, anchor = _SELF_DRILLS[target]
    apply_mutation_in_sandbox(
        _TESTS / target,
        swap_from=swap_from,
        swap_to=swap_to,
        anchor_test_file=_TESTS / target,
        anchor_test_name=anchor,
        expect="KILLED",
        timeout=600,
    )


# Victim-side fixes anchored by a donor->victim pair: revert the victim's fix
# in a sandbox copy -> the pair goes RED.
_V4715_FIX = (
    'with _patch.dict(PresenceCoordinator._run_inference.__globals__, '
    '{"dt_util": _mock_dt}):'
)
_V4715_REVERT = (
    "from custom_components.universal_room_automation.domain_coordinators "
    "import presence as _pm\n        with _patch.object(_pm, 'dt_util', _mock_dt):"
)
def _unpin_nm_clock(src: str) -> str:
    return src.replace(
        "@pytest.fixture(autouse=True)\ndef _d7_naive_nm_clock",
        "def _d7_naive_nm_clock",
    )


_VICTIM_SIDE_DRILLS = {
    "test_v4715_universalize_veto.py": (
        lambda src: src.replace(_V4715_FIX, _V4715_REVERT),
        "test_oc_pillar_a_handshake.py",
    ),
    "test_envoy_auto_derive.py": (
        lambda src: src.replace(
            "    @pytest.fixture(autouse=True)\n    def _d7_truthy_entity_registry",
            "    def _d7_truthy_entity_registry",
        ),
        "test_onboarding_simplify_slice1.py",
    ),
    "test_ec_solar_entity_override.py": (
        lambda src: src.replace("    _state_only_registry()\n    hass = MagicMock()",
                                "    hass = MagicMock()"),
        "test_onboarding_simplify_slice1.py",
    ),
    "test_nm_cycle_c2_fixup.py": (_unpin_nm_clock, "test_v5_17_1_part3_seams.py"),
    "test_nm_cycle_c_routing_matrix.py": (_unpin_nm_clock, "test_v5_17_1_part3_seams.py"),
    "test_nm_image_delivery.py": (_unpin_nm_clock, "test_v5_17_1_part3_seams.py"),
}


@pytest.mark.source_mutation
@pytest.mark.parametrize("target", sorted(_VICTIM_SIDE_DRILLS))
def test_drill_victim_fix_reverted_pair_goes_red(target):
    mutator, donor = _VICTIM_SIDE_DRILLS[target]
    victim = next(v for v in DONOR_VICTIMS[donor] if v.startswith(target))
    apply_mutation_in_sandbox(
        _TESTS / target,
        mutator=mutator,
        anchor_test_file=_HERE,
        anchor_test_name=f"test_victim_green_after_donor[{donor}-{victim}]",
        expect="KILLED",
        timeout=600,
    )


# ---------------------------------------------------------------------------
# import_scope unit anchors (slice 2: review s1 B-LOW / A-LOW-1 / A-LOW-2).
# A throwaway on-disk package stands in for a real one that outlives the
# scope; nothing under custom_components / homeassistant is touched.
# ---------------------------------------------------------------------------


@pytest.fixture
def _d7_tmp_pkg(tmp_path, monkeypatch):
    name = f"d7pkg_{os.getpid()}_{id(tmp_path)}"
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("TABLE = {'a': 1}\n")
    (pkg / "child.py").write_text("X = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    parent = importlib.import_module(name)
    yield name, parent
    for k in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
        del sys.modules[k]


def test_import_scope_removes_parent_attr_of_popped_child(_d7_tmp_pkg):
    from _d7_isolation import import_scope

    name, parent = _d7_tmp_pkg
    with import_scope(prefixes=(name,)):
        importlib.import_module(f"{name}.child")
        assert getattr(parent, "child", None) is sys.modules[f"{name}.child"]
    assert f"{name}.child" not in sys.modules
    assert "child" not in vars(parent)
    assert _parent_attr_residue(prefixes=(name,)) == []


def test_import_scope_restores_parent_attr_of_replaced_child(_d7_tmp_pkg):
    from _d7_isolation import import_scope

    name, parent = _d7_tmp_pkg
    real = importlib.import_module(f"{name}.child")
    with import_scope(prefixes=(name,)):
        stub = types.ModuleType(f"{name}.child")
        sys.modules[f"{name}.child"] = stub
        parent.child = stub
    assert sys.modules[f"{name}.child"] is real
    assert parent.child is real


def test_parent_attr_residue_detects_stale_child(_d7_tmp_pkg):
    name, _parent = _d7_tmp_pkg
    importlib.import_module(f"{name}.child")
    del sys.modules[f"{name}.child"]
    assert _parent_attr_residue(prefixes=(name,)) == [
        f"{name}.child: parent attribute is a stale module object"
    ]


def test_import_scope_guard_flags_in_place_mutation(_d7_tmp_pkg):
    from _d7_isolation import import_scope

    name, parent = _d7_tmp_pkg
    with pytest.raises(RuntimeError, match=rf"{name}\.TABLE"):
        with import_scope(prefixes=(name,), guard=True):
            parent.TABLE["b"] = 2
    # Reported, not undone (the documented limit).
    assert parent.TABLE == {"a": 1, "b": 2}
    # guard off (the default): silent, as documented.
    with import_scope(prefixes=(name,)):
        parent.TABLE["c"] = 3


_ISOLATION = _TESTS / "_d7_isolation.py"


@pytest.mark.source_mutation
def test_drill_parent_attr_restore_neutered_goes_red():
    apply_mutation_in_sandbox(
        _ISOLATION,
        swap_from="        _restore_parent_attrs(before, after)\n",
        swap_to="",
        anchor_test_file=_HERE,
        anchor_test_name="test_import_scope_removes_parent_attr_of_popped_child",
        expect="KILLED",
        timeout=600,
    )


@pytest.mark.source_mutation
def test_drill_guard_neutered_goes_red():
    apply_mutation_in_sandbox(
        _ISOLATION,
        swap_from="        if mutated:\n",
        swap_to="        if False:\n",
        anchor_test_file=_HERE,
        anchor_test_name="test_import_scope_guard_flags_in_place_mutation",
        expect="KILLED",
        timeout=600,
    )


# ---------------------------------------------------------------------------
# Multi-donor sets (slice 2): the victim fails only when ALL the listed files
# precede it (delta-debugged minimal set, default order). Anchor: run the set
# then the victim's whole file; the named node must PASS.
# ---------------------------------------------------------------------------

MULTI_DONOR_VICTIMS: dict[tuple[str, ...], list[str]] = {
    # ddmin over the 75-file default-order prefix -> these 4. Pre-fix: the
    # 10 identity_fusion suite failures (fresh-BLE / face legs judged
    # stale against a foreign clock). Fixed donor: test_carrier_freshness.
    (
        "test_bathroom_exhaust_occupancy_and_resend.py",
        "test_carrier_freshness.py",
        "test_census_ble_cancel_unrecognized.py",
        "test_census_device_switches.py",
    ): [
        "test_identity_fusion_d2_d3_d4.py::test_d2_ble_only_attaches_with_ble_provenance",
        "test_identity_fusion_d2_d3_d4.py::test_rev5_single_use_removes_arriving_legs_on_attach",
    ],
}


def _multi_ids():
    return [(d, v) for d, vs in MULTI_DONOR_VICTIMS.items() for v in vs]


def _run_set_then_victim(donors, victim) -> str:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(_REPO / "quality")}
    vfile = victim.split("::", 1)[0]
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *[str(_TESTS / d) for d in donors],
         str(_TESTS / vfile), "-q", "-p", "no:cacheprovider", "--tb=short", "-rA"],
        cwd=_REPO, env=env, capture_output=True, text=True, timeout=300,
    )
    return proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "donors,victim", _multi_ids(),
    ids=[f"{len(d)}donors-{v}" for d, v in _multi_ids()],
)
def test_victim_green_after_donor_set(donors, victim):
    out = _run_set_then_victim(donors, victim)
    assert f"PASSED quality/tests/{victim}" in out, out[-3000:]


_MULTI_DRILLS = {
    "test_carrier_freshness.py": (
        "with _d7_import_scope(attrs=True) as _D7_INSTALLED:",
        "with _d7_import_scope(prefixes=()) as _D7_INSTALLED:",
    ),
}


@pytest.mark.source_mutation
@pytest.mark.parametrize("donor", sorted(_MULTI_DRILLS))
def test_drill_multi_donor_fix_neutered_victim_goes_red(donor):
    swap_from, swap_to = _MULTI_DRILLS[donor]
    donors, victims = next(
        (d, v) for d, v in MULTI_DONOR_VICTIMS.items() if donor in d
    )
    apply_mutation_in_sandbox(
        _TESTS / donor,
        swap_from=swap_from,
        swap_to=swap_to,
        anchor_test_file=_HERE,
        anchor_test_name=f"test_victim_green_after_donor_set[{len(donors)}donors-{victims[0]}]",
        expect="KILLED",
        timeout=600,
    )
