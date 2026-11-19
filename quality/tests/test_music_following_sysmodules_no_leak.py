"""TEST-MUSIC-SYSMODULES-LEAK-1 regression guard.

test_music_following_coordinator.py exec's its own copies of the
domain_coordinators submodules (signals, house_state, base, manager,
music_following) into sys.modules at import time. It must restore sys.modules
afterwards; otherwise files collected after it resolve
``...domain_coordinators.base`` to that private copy and class-identity checks
(``isinstance(x, base.Severity)``) against a normally imported class break.

The private copies are recognisable by their spec origin: they are loaded from
``quality/tests/../../custom_components/...`` (an unnormalised path), whereas a
normal import resolves a normalised package path. The conftest collect hook
repairs the parent package stubs, so the submodules are the reliable signal.

Run ordering that exercises it:
    pytest -p no:randomly quality/tests/test_music_following_coordinator.py \
        quality/tests/test_music_following_sysmodules_no_leak.py
"""

import importlib
import os
import sys

DC = "custom_components.universal_room_automation.domain_coordinators"
SUBMODS = ("signals", "house_state", "base", "manager", "music_following")


def test_no_private_submodule_copies_left_in_sys_modules():
    leaked = []
    for name in SUBMODS:
        mod = sys.modules.get(f"{DC}.{name}")
        if mod is None:
            continue
        origin = getattr(getattr(mod, "__spec__", None), "origin", None) or ""
        if origin != os.path.normpath(origin):
            leaked.append((name, origin))
    assert leaked == [], f"music-following stub copies leaked: {leaked}"


def test_base_severity_identity_after_music_file():
    base = importlib.import_module(f"{DC}.base")
    origin = base.__spec__.origin
    assert origin == os.path.normpath(origin), origin
    assert sys.modules[f"{DC}.base"] is base
    assert isinstance(base.Severity.LOW, base.Severity)
