"""EC reserve false "write reverted" fix-up D1 — remembered witness confirmation.

Plan: docs/planning/PLANNING_ec_reserve_false_revert_fixup.md (rev 2). Tier 3.

Drives the REAL `WriteVerifier._sweep_surface` (and the enclosing
`reversion_sweep` for the wire-in) through the shared governor harness: REAL
`BatteryStrategy` + REAL `WriteVerifier`; only the HA state machine, service
bus, NM and the DB are faked. Asserts on the `write_reverted` /
`reserve_cloud_oracle_stale` anomaly rows and on the NM calls, never on
`rec.status` alone. Oracles are the plan's acceptance facts (the 10-24 /
10-30 timelines), hardcoded literals, never re-derived from the code.

Falsifiable invariants (plan §2):
  INV-F1 (no false REVERTED after a witnessed landing while the Envoy is
          unavailable and the cloud still reads V):
          test_witnessed_then_envoy_drop_no_page,
          test_restart_seeded_ledger_rewitness_then_drop_no_page,
          test_cloud_blip_and_attribute_update_still_qualify,
          test_non_numeric_local_counts_as_unavailable.
  INV-F2 (real reversions still page):
          (a) test_contrary_local_clears_memory, test_contrary_while_stale_clears_memory
          (b) test_cloud_moved_after_command_pages,
              test_cloud_moved_while_local_live_then_drop_pages
          (c) test_revert_hidden_by_unchanged_cloud_detected_on_envoy_return
          (d) test_never_landed_still_pages
          (e) test_restart_during_outage_pages
  INV-F3 (kill switch byte-identical): test_kill_switch_byte_identical.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from test_ec_reserve_oracle_phase2 import (  # noqa: F401 — fixtures
    LOCAL_EID,
    SURFACE,
    _registry,
    anomalies,
    clock,
    reg,
    set_cloud,
    setk,
    sh,
)
from _reserve_governor_harness import RESERVE_WRITE_EID, _st

from custom_components.universal_room_automation.domain_coordinators import (
    energy_write_verify as ewv,
)

# 10-30 replay (plan §5 D1): command 21:00:38, local confirms 21:00:46,
# native drop 23:06. The harness clock starts at 21:00:00 (t0).
T_CMD_S = 38
T_LOCAL_S = 46
T_POST_WINDOW_S = 21 * 60  # 21:21, past the 900 s verify window
T_DROP_S = 2 * 3600 + 6 * 60  # 23:06


def _ledger(c, s, clock, value, at_s):
    s._last_reserve_level = value
    s._last_reserve_level_at = c.t0 + timedelta(seconds=at_s)


async def sweep(c, s, clock, at_s, *, local="keep", cloud=None, soc=None):
    """One real reserve sweep at t0+at_s with fresh strategy intent (desire ==
    commanded, stamped now, so the stale-desire / desire-retire branches do
    not stand the record down)."""
    clock.t = c.t0 + timedelta(seconds=at_s)
    if local != "keep":
        c.local_value = local
    if soc is not None:
        c.soc_value = soc
    from test_ec_reserve_oracle_phase2 import refresh
    refresh(c, clock)
    if cloud is not None:
        set_cloud(c, clock, cloud)
    s._last_reserve_level_desired = s._last_reserve_level
    s._desired_stamped_at = clock.t
    await c._write_verifier._sweep_surface(s, SURFACE)


def _reverted(c):
    return anomalies(c, "write_reverted")


def _reverted_nm(c):
    return [n for n in c.nm
            if n.get("title") == "Envoy write reverted: reserve_soc"]


def _stale(c):
    return anomalies(c, "reserve_cloud_oracle_stale")


async def _witnessed(sh, clock, *, cmd=20, cloud=10, soc=60):
    """The 10-30 shape up to the drop: command, local confirms inside the
    window, one post-window sweep with the local still live."""
    c, s = sh(soc=soc, cloud=cloud, local=None)
    _ledger(c, s, clock, cmd, T_CMD_S)
    await sweep(c, s, clock, T_LOCAL_S, local=cmd)
    await sweep(c, s, clock, T_POST_WINDOW_S)
    assert _reverted(c) == [] and _reverted_nm(c) == []
    return c, s


# ===========================================================================
# INV-F1
# ===========================================================================
@pytest.mark.asyncio
async def test_witnessed_then_envoy_drop_no_page(sh, clock):
    """10-30 replay: C=20, local 20 at 21:00:46, cloud 10 → at 23:06 local
    unavailable → reserve_cloud_oracle_stale, no write_reverted, no NM."""
    c, s = await _witnessed(sh, clock)
    wv = c._write_verifier
    mem = wv._reserve_witness_confirm
    assert mem.value == 20.0
    assert mem.cloud_at_first == 10.0
    assert mem.first_at == c.t0 + timedelta(seconds=46)
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert _reverted(c) == []
    assert _reverted_nm(c) == []
    assert c.nm == []
    assert len(_stale(c)) == 1
    assert wv._records[SURFACE].status == ewv.STATUS_CLOUD_STALE
    # Display attrs (ISO strings) — first/last stamps.
    attrs = wv.get_status_attrs()
    assert attrs["reserve_witness_confirm"] == 20.0
    assert attrs["reserve_witness_confirm_first_at"] == (
        c.t0 + timedelta(seconds=46)).isoformat()
    assert attrs["reserve_witness_confirm_last_at"] == (
        c.t0 + timedelta(seconds=T_POST_WINDOW_S)).isoformat()
    assert attrs["reserve_witness_cloud_at_first"] == 10.0


@pytest.mark.asyncio
async def test_witnessed_drop_via_reversion_sweep_wire_in(sh, clock):
    """Wire-in anchor through the enclosing `reversion_sweep`."""
    c, s = await _witnessed(sh, clock)
    clock.t = c.t0 + timedelta(seconds=T_DROP_S)
    c.local_value = None
    from test_ec_reserve_oracle_phase2 import refresh
    refresh(c, clock)
    s._desired_stamped_at = clock.t
    await c._write_verifier.reversion_sweep()
    assert _reverted(c) == [] and _reverted_nm(c) == []
    assert c._write_verifier._records[SURFACE].status == ewv.STATUS_CLOUD_STALE


@pytest.mark.asyncio
async def test_non_numeric_local_counts_as_unavailable(sh, clock):
    c, s = await _witnessed(sh, clock)
    clock.t = c.t0 + timedelta(seconds=T_DROP_S)
    s._desired_stamped_at = clock.t
    _st(c.hass, LOCAL_EID, "abc", unit="%", lu=clock.t)
    await c._write_verifier._sweep_surface(s, SURFACE)
    assert _reverted(c) == [] and c.nm == []


@pytest.mark.asyncio
async def test_cloud_blip_and_attribute_update_still_qualify(sh, clock):
    c, s = await _witnessed(sh, clock)
    # Cloud unavailable at a sweep → inconclusive read, returns silently.
    await sweep(c, s, clock, T_DROP_S, local=None, cloud="unavailable")
    assert _reverted(c) == [] and c.nm == []
    # Back to the same 10 → still qualifies.
    await sweep(c, s, clock, T_DROP_S + 300, cloud=10)
    assert _reverted(c) == [] and c.nm == []
    # Attribute-only update, value 10 → still qualifies.
    clock.t = c.t0 + timedelta(seconds=T_DROP_S + 600)
    _st(c.hass, RESERVE_WRITE_EID, "10", unit="%", lu=clock.t)
    c.hass._states[RESERVE_WRITE_EID].attributes["friendly_name"] = "x"
    s._desired_stamped_at = clock.t
    await c._write_verifier._sweep_surface(s, SURFACE)
    assert _reverted(c) == [] and c.nm == []


# ===========================================================================
# INV-F2
# ===========================================================================
@pytest.mark.asyncio
async def test_never_landed_still_pages(sh, clock):
    """10-24 shape: local 11 the whole time against C=15, the cloud write
    APPLIED (landed-by-API stamps set) → no memory → page at the drop."""
    c, s = sh(soc=60, cloud=10, local=None)
    _ledger(c, s, clock, 15, T_CMD_S)
    # APPLIED stamps as `_record_reserve_dispatch` writes them (energy.py
    # 9803-9805) — must NOT count as a witnessed landing.
    s._reserve_last_ok_value = 15
    s._reserve_last_ok_at = c.t0 + timedelta(seconds=T_CMD_S)
    await sweep(c, s, clock, T_LOCAL_S, local=11)  # inside window
    assert c._write_verifier._reserve_witness_confirm is None
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert len(_reverted(c)) == 1
    assert len(_reverted_nm(c)) == 1


@pytest.mark.asyncio
async def test_never_landed_live_local_pages_immediately(sh, clock):
    c, s = sh(soc=60, cloud=10, local=None)
    _ledger(c, s, clock, 15, T_CMD_S)
    await sweep(c, s, clock, T_POST_WINDOW_S, local=11)
    assert len(_reverted(c)) == 1 and len(_reverted_nm(c)) == 1


@pytest.mark.asyncio
async def test_cloud_moved_after_command_pages(sh, clock):
    """Memory (15, V=10); Envoy down; cloud set to 12 → page."""
    c, s = await _witnessed(sh, clock, cmd=15)
    await sweep(c, s, clock, T_DROP_S, local=None, cloud=12)
    assert len(_reverted(c)) == 1
    assert len(_reverted_nm(c)) == 1


@pytest.mark.asyncio
async def test_cloud_moved_while_local_live_then_drop_pages(sh, clock):
    """V is first-stamp only: the cloud moves 10→12 while the local still
    confirms (CLOUD_STALE), then the Envoy drops → page (12 != V=10)."""
    c, s = await _witnessed(sh, clock, cmd=15)
    await sweep(c, s, clock, T_POST_WINDOW_S + 300, cloud=12)
    assert _reverted(c) == []
    assert c._write_verifier._reserve_witness_confirm.cloud_at_first == 10.0
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert len(_reverted(c)) == 1
    assert len(_reverted_nm(c)) == 1


@pytest.mark.asyncio
async def test_contrary_local_clears_memory(sh, clock):
    """Memory set; trusted local 10 with C=15 → memory None; the next sweep
    with the local unavailable pages."""
    c, s = await _witnessed(sh, clock, cmd=15)
    wv = c._write_verifier
    # Contrary reading during the window-free, matched-free path. Use the
    # memory step directly via a sweep while the cloud matches C so the
    # contrary sweep itself never reaches the emitter (isolates the clear).
    await sweep(c, s, clock, T_POST_WINDOW_S + 300, local=10, cloud=15)
    assert wv._reserve_witness_confirm is None
    assert _reverted(c) == []
    await sweep(c, s, clock, T_DROP_S, local=None, cloud=10)
    assert len(_reverted(c)) == 1
    assert len(_reverted_nm(c)) == 1


@pytest.mark.asyncio
async def test_contrary_while_stale_clears_memory(sh, clock, monkeypatch):
    """Record STALE, memory (15), local reads 10 → memory None. A same-value
    schedule(15) revives the record, the Envoy drops, cloud 10 → page."""
    import sys
    c, s = await _witnessed(sh, clock, cmd=15)
    wv = c._write_verifier
    monkeypatch.setattr(
        sys.modules[type(wv).__module__], "async_call_later",
        lambda *a, **k: (lambda: None),
    )
    wv._records[SURFACE].status = ewv.STATUS_STALE
    await sweep(c, s, clock, T_POST_WINDOW_S + 300, local=10)
    assert wv._records[SURFACE].status == ewv.STATUS_STALE  # fast path taken
    assert wv._reserve_witness_confirm is None
    await type(wv).schedule(wv, SURFACE, 15, clock.t)
    # The record revives when the scheduled check body runs (the delayed
    # `_check`), here after the Envoy has dropped.
    clock.t = c.t0 + timedelta(seconds=T_DROP_S - 60)
    c.local_value = None
    from test_ec_reserve_oracle_phase2 import refresh
    refresh(c, clock)
    await wv._check(SURFACE, 15, s._last_reserve_level_at)
    assert wv._records[SURFACE].status != ewv.STATUS_STALE
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert len(_reverted(c)) == 1
    assert len(_reverted_nm(c)) == 1


@pytest.mark.asyncio
async def test_revert_hidden_by_unchanged_cloud_detected_on_envoy_return(
    sh, clock,
):
    """INV-F2(c): deferred, not lost — a revert hidden during the outage is
    paged on the first sweep after the Envoy returns with a contrary value."""
    c, s = await _witnessed(sh, clock, cmd=15)
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert _reverted(c) == []
    await sweep(c, s, clock, T_DROP_S + 600 * 60, local=10)
    assert len(_reverted(c)) == 1
    assert len(_reverted_nm(c)) == 1


@pytest.mark.asyncio
async def test_low_soc_guard_neither_stamps_nor_qualifies(sh, clock):
    """`low_soc_guard` is untrusted: no stamp, no clear, and the helper is
    False while it holds (→ page)."""
    # No stamp: soc 18 <= 15+5 and 15 < 16 <= 38 → guard; 16 within deadband.
    c, s = sh(soc=18, cloud=10, local=None)
    _ledger(c, s, clock, 15, T_CMD_S)
    await sweep(c, s, clock, T_LOCAL_S, local=16)
    assert c._write_verifier._reserve_witness_confirm is None
    # No clear + no qualify: memory stamped at soc 60, then guard regime.
    c2, s2 = await _witnessed(sh, clock, cmd=15)
    mem = c2._write_verifier._reserve_witness_confirm
    await sweep(c2, s2, clock, T_DROP_S, local=30, soc=18)
    assert c2._write_verifier._reserve_witness_confirm is mem
    assert len(_reverted(c2)) == 1
    assert len(_reverted_nm(c2)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("local", [17, 13])
async def test_deadband_boundary_no_stamp(sh, clock, local):
    """Local exactly C±2 → no stamp (strict); the drop then pages."""
    c, s = sh(soc=60, cloud=10, local=None)
    _ledger(c, s, clock, 15, T_CMD_S)
    await sweep(c, s, clock, T_LOCAL_S, local=local)
    assert c._write_verifier._reserve_witness_confirm is None
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert len(_reverted(c)) == 1 and len(_reverted_nm(c)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("local", [16, 14])
async def test_deadband_inside_stamps(sh, clock, local):
    c, s = sh(soc=60, cloud=10, local=None)
    _ledger(c, s, clock, 15, T_CMD_S)
    await sweep(c, s, clock, T_LOCAL_S, local=local)
    assert c._write_verifier._reserve_witness_confirm.value == 15.0


@pytest.mark.asyncio
async def test_ledger_value_change_invalidates_memory(sh, clock):
    c, s = await _witnessed(sh, clock, cmd=15)
    _ledger(c, s, clock, 20, T_POST_WINDOW_S + 60)
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert len(_reverted(c)) == 1 and len(_reverted_nm(c)) == 1


@pytest.mark.asyncio
async def test_ledger_same_value_newer_stamp_invalidates_memory(sh, clock):
    """`first_at >= T_c` checked on its own: same value, T_c after first_at."""
    c, s = await _witnessed(sh, clock, cmd=15)
    _ledger(c, s, clock, 15, T_POST_WINDOW_S + 60)
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert len(_reverted(c)) == 1 and len(_reverted_nm(c)) == 1


@pytest.mark.asyncio
async def test_same_value_newer_stamp_rewitness_restamps(sh, clock):
    """Same value, newer T_c, local confirms again → a fresh memory with
    first_at >= T_c → the drop does not page."""
    c, s = await _witnessed(sh, clock, cmd=15)
    _ledger(c, s, clock, 15, T_POST_WINDOW_S + 60)
    await sweep(c, s, clock, T_POST_WINDOW_S + 120, local=15)
    mem = c._write_verifier._reserve_witness_confirm
    assert mem.first_at == c.t0 + timedelta(seconds=T_POST_WINDOW_S + 120)
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert _reverted(c) == [] and c.nm == []


@pytest.mark.asyncio
async def test_memory_value_mismatch_never_qualifies(sh, clock):
    """`memory.value == C` checked on its own: ledger value replaced with the
    stamp unchanged (defensive) → no qualification → page."""
    c, s = await _witnessed(sh, clock, cmd=15)
    s._last_reserve_level = 20  # T_c left at 21:00:38
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert len(_reverted(c)) == 1 and len(_reverted_nm(c)) == 1


@pytest.mark.asyncio
async def test_pending_episode_still_wins(sh, clock):
    """R1-M7: armed pending episode → existing suppression; no CLOUD_STALE."""
    c, s = await _witnessed(sh, clock, cmd=15)
    wv = c._write_verifier
    n_stale = len(_stale(c))
    wv._cloud_stale_sweep_latch = None
    wv._pending_attempts_fired[SURFACE] = 1
    ep = clock.t - timedelta(minutes=17)
    wv._pending_episode_at[SURFACE] = ep
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert wv._records[SURFACE].status == ewv.STATUS_REVERTED
    assert len(_stale(c)) == n_stale
    assert _reverted(c) == [] and c.nm == []
    assert wv._pending_episode_at[SURFACE] == ep


# ===========================================================================
# Restart (INV-F2(e)) — seeded restored ledger
# ===========================================================================
def _restored_ledger(s, value, iso):
    # As energy.py:2105-2107 restores it: JSON value + parsed aware datetime.
    s._last_reserve_level = value
    s._last_reserve_level_at = datetime.fromisoformat(iso)


@pytest.mark.asyncio
async def test_restart_seeded_ledger_rewitness_then_drop_no_page(sh, clock):
    """Fresh verifier, ledger restored (20, 21:00:38), cloud 10 at boot
    (22:00), local 20 → first post-boot sweep stamps V=10 → 23:06 drop →
    no page."""
    c, s = sh(soc=60, cloud=10, local=None)
    _restored_ledger(s, 20, (c.t0 + timedelta(seconds=T_CMD_S)).isoformat())
    assert c._write_verifier._reserve_witness_confirm is None
    await sweep(c, s, clock, 3600, local=20, cloud=10)  # 22:00 boot
    mem = c._write_verifier._reserve_witness_confirm
    assert mem.value == 20.0 and mem.cloud_at_first == 10.0
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert _reverted(c) == [] and c.nm == []
    assert len(_stale(c)) == 1


@pytest.mark.asyncio
async def test_restart_during_outage_pages(sh, clock):
    """Restart with the local already unavailable → no re-stamp → page
    (fail-closed, R3)."""
    c, s = sh(soc=60, cloud=10, local=None)
    _restored_ledger(s, 20, (c.t0 + timedelta(seconds=T_CMD_S)).isoformat())
    await sweep(c, s, clock, T_DROP_S + 60, local=None, cloud=10)
    assert len(_reverted(c)) == 1 and len(_reverted_nm(c)) == 1


# ===========================================================================
# One read per sweep; kill switch; config extremes
# ===========================================================================
@pytest.mark.asyncio
async def test_one_trusted_read_per_sweep(sh, clock, monkeypatch):
    c, s = await _witnessed(sh, clock)
    wv = c._write_verifier
    calls = []
    orig = wv.trusted_local_reserve

    def spy(*a, **k):
        calls.append(a)
        return orig(*a, **k)
    monkeypatch.setattr(wv, "trusted_local_reserve", spy)
    # Sweep reaching the gate: memory step (1) + `_local_confirms` (1).
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert len(calls) == 2
    # Sweep returning in the verify window: memory step only.
    calls.clear()
    _ledger(c, s, clock, 25, T_DROP_S + 10)
    await sweep(c, s, clock, T_DROP_S + 20)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_kill_switch_byte_identical(sh, clock, monkeypatch):
    """INV-F3: switch False → the 10-30 replay pages as pre-cycle; no memory,
    no cached witness, attrs null."""
    setk(monkeypatch, "RESERVE_WITNESS_MEMORY_ENABLED", False)
    c, s = await _witnessed(sh, clock)
    wv = c._write_verifier
    assert wv._reserve_witness_confirm is None
    assert wv._sweep_witness is None
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert len(_reverted(c)) == 1 and len(_reverted_nm(c)) == 1
    attrs = wv.get_status_attrs()
    for k in ("reserve_witness_confirm", "reserve_witness_confirm_first_at",
              "reserve_witness_confirm_last_at",
              "reserve_witness_cloud_at_first"):
        assert attrs[k] is None


@pytest.mark.asyncio
async def test_kill_switch_off_after_stamp_helper_false(sh, clock, monkeypatch):
    """Switch flipped off mid-outage with a memory (and an "unavailable"
    cached witness read) already held → helper False → page."""
    c, s = await _witnessed(sh, clock)
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert _reverted(c) == []
    setk(monkeypatch, "RESERVE_WITNESS_MEMORY_ENABLED", False)
    await sweep(c, s, clock, T_DROP_S + 300)
    assert len(_reverted(c)) == 1 and len(_reverted_nm(c)) == 1


@pytest.mark.asyncio
async def test_x1_local_witness_disabled_never_stamps(sh, clock, monkeypatch):
    setk(monkeypatch, "RESERVE_LOCAL_WITNESS_ENABLED", False)
    c, s = sh(soc=60, cloud=10, local=None)
    _ledger(c, s, clock, 20, T_CMD_S)
    await sweep(c, s, clock, T_LOCAL_S, local=20)
    assert c._write_verifier._reserve_witness_confirm is None
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert len(_reverted(c)) == 1 and len(_reverted_nm(c)) == 1


@pytest.mark.asyncio
async def test_x2_both_switches_off_pages(sh, clock, monkeypatch):
    setk(monkeypatch, "RESERVE_LOCAL_WITNESS_ENABLED", False)
    setk(monkeypatch, "RESERVE_WITNESS_MEMORY_ENABLED", False)
    c, s = sh(soc=60, cloud=10, local=None)
    _ledger(c, s, clock, 20, T_CMD_S)
    await sweep(c, s, clock, T_LOCAL_S, local=20)
    await sweep(c, s, clock, T_POST_WINDOW_S)
    assert len(_reverted(c)) == 1 and len(_reverted_nm(c)) == 1


@pytest.mark.asyncio
async def test_x3_fallback_only_never_stamps(sh, clock, reg):
    reg["r"] = _registry(with_sensor=False)
    c, s = sh(soc=60, cloud=10, local=None)
    _ledger(c, s, clock, 20, T_CMD_S)
    await sweep(c, s, clock, T_LOCAL_S, local=20)
    assert c._write_verifier._reserve_witness_confirm is None
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert len(_reverted(c)) == 1 and len(_reverted_nm(c)) == 1


@pytest.mark.asyncio
async def test_x4_oracle_unset_no_stamp_no_emit(sh, clock, monkeypatch):
    c, s = sh(soc=60, cloud=10, local=None)
    monkeypatch.setattr(c._write_verifier, "_oracle_entity_for", lambda surf: None)
    _ledger(c, s, clock, 20, T_CMD_S)
    await sweep(c, s, clock, T_LOCAL_S, local=20)
    assert c._write_verifier._reserve_witness_confirm is None
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert _reverted(c) == [] and _stale(c) == [] and c.nm == []


@pytest.mark.asyncio
async def test_x5_observation_mode_same_classification(sh, clock):
    c, s = await _witnessed(sh, clock)
    c._observation_mode = True
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert _reverted(c) == [] and c.nm == []
    assert len(_stale(c)) == 1
    assert c.calls == []  # classification only, no dispatch


@pytest.mark.asyncio
@pytest.mark.parametrize("local,expect_page", [(99, False), (98, True)])
async def test_x6_c100_strict_deadband(sh, clock, local, expect_page):
    """C=100 (nudge target, 99 rests): 99 confirms (1 < 2) → no page at the
    drop; 98 (exactly 2) never stamps → page."""
    c, s = sh(soc=100, cloud=10, local=None)
    _ledger(c, s, clock, 100, T_CMD_S)
    await sweep(c, s, clock, T_LOCAL_S, local=local)
    await sweep(c, s, clock, T_DROP_S, local=None)
    assert bool(_reverted_nm(c)) is expect_page
    assert bool(_reverted(c)) is expect_page
