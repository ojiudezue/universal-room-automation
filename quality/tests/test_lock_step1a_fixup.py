"""HOUSE-STATE step 1a review fix-up, lock regime side: C-2 (the boot-window
argument of the shared really-away rule at the arriving-signal call sites)
and D LOW-2 (a restored VACATION lock read in an awake house pages instead
of staying silent). Real LockRegimeController through the lockout harness;
times are hardcoded literals."""

from __future__ import annotations

from datetime import datetime

import pytest

from _lockout_harness import TZ, settle
from test_sc_away_lock import BED, EZ as AEZ, MemStore, _owned_payload
from test_sc_away_lock import KIOSK as AKIOSK, OJI as AOJI
from test_sc_away_lock import make_rig as make_away_rig
from test_lock_release_arriving import BOOT_GAP, install_nm, snap
from test_sc_garage_lockout import EZ, LOCK_A, LOCK_B, OJI, DictStore, make_rig


@pytest.mark.asyncio
async def test_away_lock_arriving_signal_in_boot_window_releases():
    """C-2: restart with an owned away lock, both listed persons restored
    not_home. At +20 s Ezinne makes a LIVE not_home -> named-zone edge (her
    ledger is now real, 'work' since +20 s). At +60 s an arriving signal for
    her: outside a boot window she was away only 40 s (< 15 min), so only the
    boot-window exception of the shared rule releases."""
    rig = await make_away_rig(store=MemStore(_owned_payload()), past_boot=False,
                              bed="locked",
                              persons={AOJI: "not_home", AEZ: "not_home",
                                       AKIOSK: "unknown"})
    assert rig.regime.away_lock_owned == {BED}
    await rig.w.advance(20)
    await rig.person(AEZ, "work")
    await rig.w.advance(40)
    assert rig.unlocks() == []
    rig.regime.on_person_arriving({"person_entity": AEZ, "source": "geofence"})
    await settle()
    assert rig.unlocks() == [BED]


@pytest.mark.asyncio
async def test_restored_vacation_lock_in_awake_house_pages():
    """D LOW-2: a vacation engage from an awake house leaves saw-empty False.
    A restart that reads the house home_day with a resident home and the
    lockouts still locked: no release (INV-LOCK), and the boot gap page fires
    instead of a silent stay."""
    store = DictStore()
    rig1 = await make_rig(house="home_day", store=store)
    await rig1.edge("vacation")
    assert store.data["garage_reason"] == "vacation"
    assert store.data["garage_episode_saw_empty"] is False
    rig2 = await make_rig(start=datetime(2026, 11, 9, 12, 0, tzinfo=TZ),
                          house="home_day", lockouts="locked", past_boot=False,
                          persons={EZ: "home", OJI: "not_home"},
                          store=DictStore(dict(store.data)))
    nm = install_nm(rig2)
    assert rig2.regime.reason == "vacation"
    assert snap(rig2)["lock_regime_episode_saw_empty"] is True
    await rig2.w.advance(121)
    assert rig2.unlocks() == []
    assert rig2.regime.last_action["decision"] == "house_edge_ignored"
    assert sorted(p["location"] for p in nm.of(BOOT_GAP)) == [
        f"garage_lockout:still_locked:{LOCK_A}",
        f"garage_lockout:still_locked:{LOCK_B}"]
