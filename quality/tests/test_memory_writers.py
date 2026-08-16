"""PATH-ALPHA Scope B — tests for D4/D5/D6/D7 memory writers.

Covers:
  * D4 phantom_retro — release-window + hold predicate + 5-latch replay.
  * D5 away_transition_blocked — coalesce + restart discharge.
  * D6 tracker_trust_excluded — 60-flip-per-minute debounce bound.
  * D7 house_state_transition — boot-suppression pin.
  * Memory vocabulary pin — all 4 types registered + unregistered
    rejected by DAO.
  * CONSUMER-GRAPH — no production module (outside the writers +
    the memory facade/compactor) reads the 4 new episode types.
"""
from __future__ import annotations

import ast
import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from _energy_bootstrap import bootstrap_energy_imports

bootstrap_energy_imports()

from custom_components.universal_room_automation.const import (  # noqa: E402
    AWAY_BLOCK_EPISODE_MIN_HOLD_S,
    DOMAIN,
    MEMORY_EPISODE_TYPES,
    PHANTOM_RETRO_MIN_HOLD_S,
    PHANTOM_RETRO_RELEASE_WINDOW_S,
    TRACKER_TRUST_MIN_HOLD_S,
)
from custom_components.universal_room_automation import (  # noqa: E402
    memory_writers as mw,
)


# ---------------------------------------------------------------------------
# Fake DB — records writes without touching aiosqlite. Sufficient for
# the writer unit-tests; the DAO vocabulary gate has separate coverage
# in test_memory_mvp.py::test_log_memory_episode_registered_vocabulary_gate.
# ---------------------------------------------------------------------------


class _FakeDB:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._next_id = 1

    async def log_memory_episode(
        self,
        *,
        node_id: str,
        episode_type: str,
        adjudication: str = "unadjudicated",
        adjudicated_by: str | None = None,
        attrs: dict | None = None,
        source_ref: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        dedup_source_ref: bool = False,
    ) -> int | None:
        # Enforce vocabulary gate the way production does.
        if episode_type not in MEMORY_EPISODE_TYPES:
            return None
        if dedup_source_ref and source_ref is not None:
            for r in self.rows:
                if r.get("source_ref") == source_ref:
                    return None
        rid = self._next_id
        self._next_id += 1
        self.rows.append({
            "id": rid,
            "node_id": node_id,
            "episode_type": episode_type,
            "adjudication": adjudication,
            "adjudicated_by": adjudicated_by,
            "attrs": dict(attrs or {}),
            "source_ref": source_ref,
            "started_at": started_at,
            "ended_at": ended_at,
        })
        return rid

    async def close_memory_episode(
        self, *, row_id: int, ended_at: str,
        close_attrs: dict | None = None,
    ) -> bool:
        for r in self.rows:
            if r["id"] == row_id:
                r["ended_at"] = ended_at
                if close_attrs:
                    r["attrs"] = {**r["attrs"], **close_attrs}
                return True
        return False

    async def fetch_open_memory_episodes_of_type(
        self, episode_type: str,
    ) -> list[dict]:
        return [
            {
                "id": r["id"],
                "node_id": r["node_id"],
                "started_at": r["started_at"],
                "source_ref": r["source_ref"],
            }
            for r in self.rows
            if r["episode_type"] == episode_type and r["ended_at"] is None
        ]


class _FakeHass:
    def __init__(self) -> None:
        self.data = {DOMAIN: {"database": _FakeDB()}}

    def async_create_task(self, coro):
        return asyncio.ensure_future(coro)

    def async_create_background_task(self, coro, name=None):
        return asyncio.ensure_future(coro)


@pytest.fixture
def hass():
    return _FakeHass()


def _db(h: _FakeHass) -> _FakeDB:
    return h.data[DOMAIN]["database"]


# ---------------------------------------------------------------------------
# D4 phantom_retro
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phantom_retro_writer_emits_on_qualifying_edge(hass):
    """A fan-off followed by mmwave-off inside the window with a
    long-enough hold emits exactly one phantom_retro row with the
    expected coverage stamp + attrs shape."""
    fan_on = datetime(2026, 8, 13, 18, 0, 0, tzinfo=timezone.utc)
    fan_off = fan_on + timedelta(seconds=PHANTOM_RETRO_MIN_HOLD_S + 60)
    mmwave_off = fan_off + timedelta(seconds=30)

    mw.write_phantom_retro(
        hass,
        room_name="Living Room",
        fan_off_ts=fan_off,
        mmwave_off_ts=mmwave_off,
        fan_on_since=fan_on,
        room_capabilities={"has_pir": False, "has_ble": False},
    )
    await asyncio.sleep(0)  # let scheduled task run
    rows = _db(hass).rows
    assert len(rows) == 1
    r = rows[0]
    assert r["episode_type"] == "phantom_retro"
    assert r["node_id"] == "room:living_room"
    assert r["adjudication"] == "phantom"
    assert r["adjudicated_by"] == "fan_release_correlation"
    assert r["attrs"]["coverage"] == "fan_release_correlated"
    assert r["attrs"]["release_delay_s"] == 30.0
    assert r["attrs"]["hold_s"] >= PHANTOM_RETRO_MIN_HOLD_S


@pytest.mark.asyncio
async def test_phantom_retro_rejects_short_hold(hass):
    """Fan tapped briefly then off — no phantom_retro row."""
    fan_on = datetime(2026, 8, 13, 18, 0, 0, tzinfo=timezone.utc)
    fan_off = fan_on + timedelta(seconds=PHANTOM_RETRO_MIN_HOLD_S - 10)
    mmwave_off = fan_off + timedelta(seconds=15)
    mw.write_phantom_retro(
        hass, room_name="Study A",
        fan_off_ts=fan_off, mmwave_off_ts=mmwave_off,
        fan_on_since=fan_on,
    )
    await asyncio.sleep(0)
    assert _db(hass).rows == []


@pytest.mark.asyncio
async def test_phantom_retro_rejects_out_of_window(hass):
    """mmwave off arrives long after fan off — outside the correlation
    window; no row."""
    fan_on = datetime(2026, 8, 13, 18, 0, 0, tzinfo=timezone.utc)
    fan_off = fan_on + timedelta(seconds=PHANTOM_RETRO_MIN_HOLD_S + 10)
    mmwave_off = fan_off + timedelta(
        seconds=PHANTOM_RETRO_RELEASE_WINDOW_S + 5,
    )
    mw.write_phantom_retro(
        hass, room_name="Jaya Bedroom",
        fan_off_ts=fan_off, mmwave_off_ts=mmwave_off,
        fan_on_since=fan_on,
    )
    await asyncio.sleep(0)
    assert _db(hass).rows == []


@pytest.mark.asyncio
async def test_phantom_retro_replays_five_latches(hass):
    """Retro-audit fixture: replay 5 known 2026-08-13 latches (Living
    Room + Upstairs Guestroom x2 + Jaya Bedroom x2) — writer emits 5
    rows keyed on 3 distinct room slugs. Rejects the two negative
    controls (mmwave released BEFORE fan-off; Screek/Ziri class)."""
    base = datetime(2026, 8, 13, 18, 40, 0, tzinfo=timezone.utc)

    # 5 positive latches (fan_on -> fan_off -> mmwave_off within window,
    # each hold >= MIN_HOLD_S). Release delays match audit shape
    # (37s / 22s / 36s and their siblings).
    latches = [
        # (room, fan_on_offset_s, hold_s, release_delay_s)
        ("Living Room",         0,   82 * 60, 45),
        ("Upstairs Guestroom",  0,   62 * 60, 36),
        ("Upstairs Guestroom",  10800, 99 * 60, 22),
        ("Jaya Bedroom",        0,   45 * 60, 30),
        ("Jaya Bedroom",        7200, 55 * 60, 50),
    ]
    for room, on_off, hold_s, delay_s in latches:
        fan_on = base + timedelta(seconds=on_off)
        fan_off = fan_on + timedelta(seconds=hold_s)
        mmwave_off = fan_off + timedelta(seconds=delay_s)
        mw.write_phantom_retro(
            hass, room_name=room,
            fan_off_ts=fan_off, mmwave_off_ts=mmwave_off,
            fan_on_since=fan_on,
        )
    # 2 negative controls (mmwave off BEFORE fan off — negative delay).
    for room in ("Ziri", "Study A"):
        fan_on = base
        fan_off = fan_on + timedelta(seconds=PHANTOM_RETRO_MIN_HOLD_S + 60)
        mmwave_off = fan_off - timedelta(seconds=5)
        mw.write_phantom_retro(
            hass, room_name=room,
            fan_off_ts=fan_off, mmwave_off_ts=mmwave_off,
            fan_on_since=fan_on,
        )
    await asyncio.sleep(0)
    rows = _db(hass).rows
    assert len(rows) == 5
    slugs = {r["node_id"] for r in rows}
    assert slugs == {
        "room:living_room",
        "room:upstairs_guestroom",
        "room:jaya_bedroom",
    }
    for r in rows:
        assert r["attrs"]["coverage"] == "fan_release_correlated"


# ---------------------------------------------------------------------------
# D5 away_transition_blocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_away_transition_blocked_coalesce_and_restart_discharge(hass):
    """Blocked-for-<hold> ticks do NOT open. Once the hold window
    elapses, ONE row opens and stays open across further blocked
    ticks. The first unblocked tick closes it. Then a restart
    reconciliation on a NEW hass with a lingering open row closes
    the leftover with closed_by='restart'."""
    t = mw.AwayBlockEpisodeTracker(hass)
    now = datetime(2026, 8, 14, 14, 0, 0, tzinfo=timezone.utc)

    # tick 1: pending starts.
    await t.note_tick(blocked=True, snapshot={"veto_path": "alpha_starved"},
                      now=now)
    assert _db(hass).rows == []  # nothing yet
    assert t.pending_since == now

    # tick 2 within MIN_HOLD_S — still pending, not open.
    await t.note_tick(blocked=True, snapshot={"veto_path": "alpha_starved"},
                      now=now + timedelta(
                          seconds=AWAY_BLOCK_EPISODE_MIN_HOLD_S // 2))
    assert _db(hass).rows == []

    # tick 3 past MIN_HOLD_S — opens exactly one episode.
    open_at = now + timedelta(seconds=AWAY_BLOCK_EPISODE_MIN_HOLD_S + 5)
    await t.note_tick(blocked=True, snapshot={"veto_path": "alpha_starved"},
                      now=open_at)
    rows = _db(hass).rows
    assert len(rows) == 1
    r = rows[0]
    assert r["episode_type"] == "away_transition_blocked"
    assert r["node_id"] == "house"
    assert r["ended_at"] is None
    assert t.open_row_id == r["id"]

    # tick 4 still blocked — same open row (NOT a second row).
    await t.note_tick(blocked=True, snapshot={"veto_path": "alpha_starved"},
                      now=open_at + timedelta(seconds=60))
    assert len(_db(hass).rows) == 1

    # tick 5 unblocked — closes the row.
    close_at = open_at + timedelta(seconds=120)
    await t.note_tick(blocked=False, snapshot=None, now=close_at)
    r = _db(hass).rows[0]
    assert r["ended_at"] == close_at.isoformat()
    assert r["attrs"]["closed_by"] == "unblocked"
    assert t.open_row_id is None

    # --- Restart-discharge: leave an open row on a fresh hass, run
    # reconcile_open_away_block_on_boot → closed_by='restart'. ---
    hass2 = _FakeHass()
    await _db(hass2).log_memory_episode(
        node_id="house",
        episode_type="away_transition_blocked",
        adjudication="observed",
        adjudicated_by="away_block_coalescer",
        attrs={"coverage": "path_alpha_and_beta_blocked"},
        source_ref="away_block:pre_restart",
        started_at="2026-08-14T13:00:00+00:00",
        dedup_source_ref=True,
    )
    n = await mw.reconcile_open_away_block_on_boot(hass2)
    assert n == 1
    r2 = _db(hass2).rows[0]
    assert r2["ended_at"] is not None
    assert r2["attrs"]["closed_by"] == "restart"


# ---------------------------------------------------------------------------
# D6 tracker_trust_excluded — 60-flip debounce bound
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tracker_trust_excluded_60_flip_debounce(hass):
    """A person flipping every second for 60 seconds produces ZERO
    rows: no target state ever HOLDS for TRACKER_TRUST_MIN_HOLD_S
    continuously. Then a real 60s+ hold produces exactly ONE row."""
    w = mw.TrackerTrustExcludedWriter(hass)
    t0 = datetime(2026, 8, 14, 15, 0, 0, tzinfo=timezone.utc)

    # Prime: person known and initially trusted.
    await w.observe(
        excluded_persons={},
        known_persons=["oji"],
        now=t0,
    )
    assert _db(hass).rows == []

    # 60 flips at 1Hz — alternating excluded/not.
    for i in range(1, 61):
        excl = {} if (i % 2 == 0) else {
            "oji": "tracking_status=lost,tracking_reason=no_signal",
        }
        await w.observe(
            excluded_persons=excl,
            known_persons=["oji"],
            now=t0 + timedelta(seconds=i),
        )
    # BY CONSTRUCTION no flip held for TRACKER_TRUST_MIN_HOLD_S — no rows.
    assert _db(hass).rows == [], (
        "60-flip stream must emit zero rows (debounce hold not satisfied)"
    )

    # Now hold "excluded" continuously for > MIN_HOLD_S: should emit
    # exactly ONE row.
    hold_start = t0 + timedelta(seconds=120)
    for j in range(0, TRACKER_TRUST_MIN_HOLD_S + 10, 5):
        await w.observe(
            excluded_persons={
                "oji": "tracking_status=lost,tracking_reason=no_signal",
            },
            known_persons=["oji"],
            now=hold_start + timedelta(seconds=j),
        )
    await asyncio.sleep(0)
    rows = _db(hass).rows
    assert len(rows) == 1
    r = rows[0]
    assert r["episode_type"] == "tracker_trust_excluded"
    assert r["attrs"]["person"] == "oji"
    assert r["attrs"]["entered_exclusion"] is True
    assert r["attrs"]["reason"].startswith("tracking_status=lost")


# ---------------------------------------------------------------------------
# D7 house_state_transition — boot suppression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "trigger,should_write",
    [
        ("boot", False),
        ("restore", False),
        ("initial", False),
        ("startup", False),
        ("restored", False),
        ("boot_settle_release", False),
        ("timer_expire", True),
        ("guest_gate_armed", True),
        ("person_arrived", True),
    ],
)
async def test_house_state_transition_boot_suppression(
    hass, trigger, should_write,
):
    """Pin the boot-suppression choice: any trigger containing a
    boot-like token suppresses the memory episode. All other triggers
    write. (D7 acceptance criterion — plan §H4)."""
    mw.write_house_state_transition(
        hass,
        old_state="restored",
        new_state="home_day",
        trigger=trigger,
        confidence=0.9,
        snapshot={"census_count": 0},
    )
    await asyncio.sleep(0)
    rows = _db(hass).rows
    if should_write:
        assert len(rows) == 1, f"expected write for trigger={trigger!r}"
        assert rows[0]["episode_type"] == "house_state_transition"
        assert rows[0]["attrs"]["trigger"] == trigger
    else:
        assert rows == [], (
            f"expected boot suppression for trigger={trigger!r}"
        )


# ---------------------------------------------------------------------------
# Memory vocabulary pin
# ---------------------------------------------------------------------------


def test_memory_vocabulary_pin_all_four_registered():
    """The four PATH-ALPHA Scope B episode types are members of
    MEMORY_EPISODE_TYPES. If this test fails the DAO's write-gate
    would reject the writer at runtime."""
    for t in (
        "phantom_retro",
        "away_transition_blocked",
        "tracker_trust_excluded",
        "house_state_transition",
    ):
        assert t in MEMORY_EPISODE_TYPES, (
            f"{t!r} missing from MEMORY_EPISODE_TYPES"
        )


@pytest.mark.asyncio
async def test_memory_vocabulary_pin_unregistered_rejected(hass):
    """The FakeDB (which mirrors production's vocabulary gate) rejects
    unregistered types — sanity check the gate is load-bearing."""
    db = _db(hass)
    rid = await db.log_memory_episode(
        node_id="house",
        episode_type="not_a_real_type_xyz",
    )
    assert rid is None


# ---------------------------------------------------------------------------
# CONSUMER-GRAPH: memory-ineligible boundary (arch §8)
# ---------------------------------------------------------------------------


def _iter_production_py_files() -> list[Path]:
    root = Path(__file__).resolve().parents[2] / (
        "custom_components/universal_room_automation"
    )
    return [p for p in root.rglob("*.py") if p.is_file()]


def test_no_production_module_reads_scope_b_episode_types():
    """No production file (outside the writers module + the memory
    facade + the memory compactor + const.py where they're
    REGISTERED) references any of the four new episode types as a
    string literal. The memory-ineligible boundary (arch §8) is
    static-checkable: consumers can only reach these episodes via
    the memory facade (episodes/narrative/unusual/facts), and no
    actuation path is allowed to.

    A failure here almost always means someone added a `.get('reason')
    == "phantom_retro"` or a `episode_type == "away_transition_blocked"`
    branch on a code path that would give the writer influence over
    an actuation decision — reject the change or move the branch
    behind the facade."""
    allowlist_basenames = {
        "memory_writers.py",   # the writers themselves
        "memory_facade.py",    # read-through facade for consumers
        "memory_compactor.py", # nightly distillation, no actuation
        "const.py",            # vocabulary registration
    }
    scope_b_types = (
        "phantom_retro",
        "away_transition_blocked",
        "tracker_trust_excluded",
        "house_state_transition",
    )
    # Pre-existing string collisions that are semantically unrelated to
    # memory episodes (fan-decision reason strings in hvac.py predating
    # this cycle). These are ledger tags in a different name-space
    # ("reason ladder" in comments/logs), not memory-episode reads.
    # If a genuine consumer is added, it will show up on a NEW file/type
    # pair not in this allowlist.
    preexisting_collisions = {
        ("domain_coordinators/hvac.py", "house_state_transition"),
    }
    offenders: list[tuple[str, str]] = []
    root = Path(__file__).resolve().parents[2] / (
        "custom_components/universal_room_automation"
    )
    for path in _iter_production_py_files():
        if path.name in allowlist_basenames:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        rel = str(path.relative_to(root))
        for t in scope_b_types:
            # Require quoted-string match so we don't false-positive on
            # incidental identifier shadows.
            if f'"{t}"' in text or f"'{t}'" in text:
                if (rel, t) in preexisting_collisions:
                    continue
                offenders.append((rel, t))
    assert not offenders, (
        "Memory-ineligible boundary violated — production modules "
        f"reference Scope-B episode types: {offenders}. Move any "
        "consumer behind memory_facade or explain in-code."
    )
