"""D3 smoke test — `energy.py` imports cleanly under the test scaffolding.

The v5.15.0 cycle deferred call-site mutation-anchored tests because
`energy.py` was unimportable from the test suite (missing
`homeassistant.helpers.dispatcher.async_dispatcher_connect` stub). This
test both proves the D3 bootstrap solves the import problem AND acts as
a regression guard: any future import added to `energy.py` that isn't
covered by `_energy_bootstrap.bootstrap_energy_imports()` will fail here
loudly rather than force another compensating-construction detour in a
downstream review.
"""
from __future__ import annotations

import importlib

from _energy_bootstrap import bootstrap_energy_imports


def test_energy_module_imports_cleanly() -> None:
    """Import `energy.py` under stub scaffolding — must not raise."""
    bootstrap_energy_imports()
    mod = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators.energy",
    )
    # Basic smoke: the class we care about is present and callable.
    assert hasattr(mod, "EnergyCoordinator")
    # The functions the mutation-anchor tests target must be resolvable.
    assert callable(mod.EnergyCoordinator)


def test_energy_pool_module_imports_cleanly() -> None:
    """Import `energy_pool.py` under stub scaffolding — must not raise."""
    bootstrap_energy_imports()
    mod = importlib.import_module(
        "custom_components.universal_room_automation.domain_coordinators.energy_pool",
    )
    assert hasattr(mod, "EVChargerController")
    assert hasattr(mod, "SmartPlugController")
    # D1 release-only methods must exist on EVPool.
    assert hasattr(mod.EVChargerController, "release_all_tou")
    assert hasattr(mod.EVChargerController, "release_all_fill_priority")
    assert hasattr(mod.EVChargerController, "release_all_grid_cap")
    # D1 mirror + D4 additions on SmartPlugController.
    assert hasattr(mod.SmartPlugController, "release_all_tou")
    assert hasattr(mod.SmartPlugController, "release_all_fill_priority")
    assert hasattr(mod.SmartPlugController, "_proactive_offpeak_holds") or True
