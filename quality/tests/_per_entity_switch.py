"""Sleep-mask Rev 3.2 R3.2.2 — ONE way to flip ``ZONE_OCCUPANCY_PER_ENTITY_ENABLED``.

Production reads the switch as a module ATTRIBUTE at call time
(``_ura_const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED``), never by name import, so
patching the ``const`` module object reaches presence.py,
occupancy_substrate.py and __init__.py at once.

* ``per_entity_off`` fixture — patches the switch False on EVERY loaded
  const module that carries it (the canonical package and any private test
  alias such as ``ura_sleepmask_pkg.const``), restored by monkeypatch.
* ``--per-entity-off`` (or ``URA_PER_ENTITY_OFF=1``) — the switch-off run:
  every test runs under ``per_entity_off``; tests marked
  ``per_entity_on_only`` (they assert Rev-3 behaviour by design) are
  skipped. Tests marked ``per_entity_off_only`` request the fixture
  themselves, so they run switched-off in BOTH modes.

Never patch the name on presence / occupancy_substrate / __init__ modules;
``test_zone_tracker_per_entity.py::test_zone_per_entity_switch_read_by_attribute``
lints both production and tests.
"""
from __future__ import annotations

import os
import sys

import pytest

SWITCH = "ZONE_OCCUPANCY_PER_ENTITY_ENABLED"
ENV = "URA_PER_ENTITY_OFF"


def _const_modules():
    out = []
    for name, mod in list(sys.modules.items()):
        if mod is None:
            continue
        if not (name == "const" or name.endswith(".const")):
            continue
        try:
            if hasattr(mod, SWITCH):
                out.append(mod)
        except Exception:  # noqa: BLE001 — exotic stub
            continue
    return out


def pytest_addoption(parser):
    parser.addoption(
        "--per-entity-off",
        action="store_true",
        default=False,
        help="Run every test with ZONE_OCCUPANCY_PER_ENTITY_ENABLED patched "
             "False (skips per_entity_on_only tests).",
    )


def _switch_off_mode(config) -> bool:
    return bool(config.getoption("--per-entity-off")) or (
        os.environ.get(ENV, "").strip() in ("1", "true", "yes", "on")
    )


@pytest.fixture
def per_entity_off(monkeypatch):
    mods = _const_modules()
    assert mods, "no const module carrying the switch is loaded"
    for mod in mods:
        monkeypatch.setattr(mod, SWITCH, False)
    yield mods


@pytest.fixture(autouse=True)
def _per_entity_switch_mode(request):
    off_only = request.node.get_closest_marker("per_entity_off_only")
    on_only = request.node.get_closest_marker("per_entity_on_only")
    if _switch_off_mode(request.config):
        if on_only is not None:
            pytest.skip("per_entity_on_only: asserts Rev-3 behaviour (switch on)")
        request.getfixturevalue("per_entity_off")
    elif off_only is not None:
        request.getfixturevalue("per_entity_off")
    yield
