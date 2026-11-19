"""TEST-MUSIC-SYSMODULES-LEAK-1 regression guard.

test_music_following_coordinator.py builds private copies of the URA package,
const, domain_coordinators and five submodules in sys.modules at import time
and must restore sys.modules afterwards. Each private copy carries the marker
attribute ``__ura_music_private_copy__ = True``; this guard asserts, by module
identity rather than import-path spelling, that none is left in sys.modules.

Run ordering that exercises it:
    pytest -p no:randomly quality/tests/test_music_following_coordinator.py \
        quality/tests/test_music_following_sysmodules_no_leak.py
"""

import importlib
import sys

DC = "custom_components.universal_room_automation.domain_coordinators"
MARKER = "__ura_music_private_copy__"


def _is_private_copy(mod):
    # `is True`: MagicMock stubs in sys.modules answer any getattr truthily.
    try:
        return mod is not None and vars(mod).get(MARKER) is True
    except TypeError:  # objects without __dict__
        return False


def test_no_music_private_copies_left_in_sys_modules():
    leaked = sorted(k for k, m in list(sys.modules.items()) if _is_private_copy(m))
    assert leaked == [], f"music-following private copies leaked: {leaked}"


def test_base_severity_isinstance_on_non_private_base():
    base = importlib.import_module(f"{DC}.base")
    assert not _is_private_copy(base)
    assert isinstance(base.Severity.LOW, base.Severity)
