"""PERSON-BLE-WINS-OVER-STALE-GPS-1 — the two hvac.py §6b trust readers.

Drives the REAL `HVACCoordinator._apply_house_state_presets` on the shared
W1-B harness (via the CPR suite's `Rig`):

* D7 night-trust preset hold (`hvac.py` night-trust person check): a
  zone_persons member reading raw `home` keeps an empty `sleep` zone off
  `away`; the same raw `home` for a person whose GPS "home" was overruled by
  BLE does not.
* `main_row_home_persons` (display, activity-log `home_persons`): lists a
  raw-home person, omits an overruled one.

The overrule is produced by a REAL PersonTrackingCoordinator holding the
person in `_gps_home_overruled` with URA location `away` (the state a real
overrule tick leaves behind; the tick itself is covered in
test_person_gps_assistive.py).
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("homeassistant.helpers.storage")

_HERE = os.path.dirname(__file__)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import _w1b_harness as H  # noqa: E402
from test_hvac_cpr_batch_c import E1, E2, E3, T0, Z1, Z2, Z3, Rig  # noqa: E402

PERSON = "person.a"


@pytest.fixture(autouse=True, scope="module")
def _scoped():
    baseline = H.snapshot_shims()
    try:
        yield
    finally:
        H.restore_shims(baseline)


@pytest.fixture
def mods():
    return H.load_real()


@pytest.fixture
def expected_lingering_timers():
    return True


def _install_overruled_person_coordinator(hass, overruled: bool):
    """A real PersonTrackingCoordinator in hass.data, with person 'A'
    overruled (location away) or not."""
    import importlib
    pc_mod = importlib.import_module(
        "custom_components.universal_room_automation.person_coordinator")
    import homeassistant.helpers.frame as _frame
    entry = MagicMock()
    entry.data = {"tracked_persons": ["A"]}
    with patch.object(_frame, "report_usage", lambda *a, **k: None):
        pc = pc_mod.PersonTrackingCoordinator(hass, entry)
    pc.hass = hass
    pc.tracked_persons = ["A"]
    if overruled:
        pc._gps_home_overruled = frozenset({"A"})
        pc.data = {"A": {"location": "away"}}
    else:
        pc._gps_home_overruled = frozenset()
        pc.data = {"A": {"location": "home"}}
    hass.data[pc_mod.DOMAIN]["person_coordinator"] = pc
    return pc


def _sleep_rig(mods, monkeypatch):
    r = Rig(mods, monkeypatch, house="sleep")
    c = r.coord
    c._zone_intelligence_enabled = True
    c._boot_settle_done = True
    for zid in (Z1, Z2, Z3):
        c.zone_manager.zones[zid].preset_mode = "sleep"
    for e in (E1, E2, E3):
        r.view(e, preset="sleep")
    z = c.zone_manager.zones[Z1]
    z.last_occupied_time = T0 - timedelta(hours=3)
    z.zone_persons = [PERSON]
    r.hass.states.async_set(PERSON, "home", {})
    calls = []

    def _spy(zone):
        # 1st consult per zone = row-1 (retreat), 2nd = D7 (not retreat-ok)
        n = sum(1 for zid in calls if zid == zone.zone_id)
        calls.append(zone.zone_id)
        return (True, False)[min(n, 1)] if zone.zone_id == Z1 else False
    monkeypatch.setattr(c, "_zone_conditioning_retreat_ok", _spy)
    return r


@pytest.mark.asyncio
@pytest.mark.parametrize("overruled,expect_away", [(False, False), (True, True)])
async def test_hvac_night_trust_effective(mods, monkeypatch, overruled, expect_away):
    r = _sleep_rig(mods, monkeypatch)
    _install_overruled_person_coordinator(r.hass, overruled)
    assert r.hass.states.get(PERSON).state == "home"
    await r.coord._apply_house_state_presets()
    await H.drain(r.hass)
    assert bool(H.preset_writes(r.hass, E1, "away")) is expect_away


@pytest.mark.asyncio
@pytest.mark.parametrize("overruled,expect", [(False, [PERSON]), (True, [])])
async def test_hvac_main_row_home_persons_effective(mods, monkeypatch, overruled, expect):
    """Display row: the preset_change activity row's `home_persons`."""
    r = Rig(mods, monkeypatch, house="away")
    c = r.coord
    c._zone_intelligence_enabled = False
    c._boot_settle_done = True
    z = c.zone_manager.zones[Z1]
    z.zone_persons = [PERSON]
    r.hass.states.async_set(PERSON, "home", {})
    _install_overruled_person_coordinator(r.hass, overruled)
    await c._apply_house_state_presets()
    await H.drain(r.hass)
    rows = [row for row in r.hass.data[r.DOMAIN]["activity_logger"].actions("preset_change")
            if row.get("zone") == Z1]
    assert rows, "expected a preset_change activity row for zone_1"
    assert rows[0]["details"]["home_persons"] == expect
