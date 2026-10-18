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


def _residue(probes) -> list[str]:
    bad = []
    for modname, attr, kind in probes:
        mod = sys.modules.get(modname)
        if kind == "ura":
            if mod is None:
                continue
            f = getattr(mod, "__file__", None) or ""
            if not f or not Path(f).resolve().is_relative_to(_REPO / "custom_components"):
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


def test_probe():
    """Only meaningful inside the subprocess launched below."""
    donor = os.environ.get(_ENV_KEY)
    if not donor:
        pytest.skip("probe runs only inside test_donor_leaves_no_residue")
    assert _residue(DONOR_PROBES[donor]) == []


def _run_pair(donor: str, root: Path = _REPO) -> subprocess.CompletedProcess:
    tests = root / "quality" / "tests"
    env = {**os.environ, _ENV_KEY: donor, "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(root / "quality")}
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(tests / donor),
         f"{tests / _HERE.name}::test_probe", "-q", "-p", "no:cacheprovider",
         "-rs", "--tb=short"],
        cwd=root, env=env, capture_output=True, text=True, timeout=300,
    )


@pytest.mark.parametrize("donor", sorted(DONOR_PROBES))
def test_donor_leaves_no_residue(donor):
    proc = _run_pair(donor)
    out = proc.stdout + proc.stderr
    # The probe must have RUN (not skipped) and passed, and the donor's own
    # tests must still pass (a fix may not weaken the donor).
    summary = [ln for ln in out.splitlines() if " in " in ln and ("passed" in ln or "failed" in ln)]
    assert summary, out[-3000:]
    assert proc.returncode == 0, out[-3000:]
    assert "failed" not in summary[-1] and "skipped" not in summary[-1], out[-3000:]


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
    # Un-scope the import block: restore nothing on exit.
    "test_hvac_fan_control.py": (
        "with _d7_import_scope() as _D7_INSTALLED:",
        "with _d7_import_scope(prefixes=()) as _D7_INSTALLED:",
    ),
}


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
