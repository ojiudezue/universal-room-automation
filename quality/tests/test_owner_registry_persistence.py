"""Phase-3 owner-registry persistence oracle.

Drives the PRODUCTION `_save_registry_owner_lists` /
`_restore_registry_owner_lists` helpers against a KV-capture fake DB
and asserts:

  (i)  literal key→attr binding for EVERY list-shape declaration
       (C-HIGH-1 — extends the b2c3 DP pattern to all 8 list keys),
  (ii) full round-trip set equality per owner (save → restore →
       compare original set),
  (iii) restore side-effects (DP dispatch owner reclaim per id —
        C-HIGH-3, blind-window pre-engaged marking — C-HIGH-2),
  (iv) corrupt-KV resilience (D-1) — a non-list payload for one key
        does NOT strand later keys behind an unhandled exception,
  (v)  unknown restore_hook value raises AssertionError (A-LOW-2).

These tests replace the `_emit_save_kv` shim in the generator with
real authority. The generator's v3 golden captures the SAME production
writer via the same helper — see `regen_owner_golden.py`.
"""
from __future__ import annotations

import asyncio
import json
import types

import pytest

from _energy_bootstrap import bootstrap_energy_imports
bootstrap_energy_imports()

from custom_components.universal_room_automation.domain_coordinators \
    .energy_pool_owners import (
    EV_REGISTRY, PLUG_REGISTRY, OwnerDeclaration, OwnerRegistry,
)
from tests_owner_registry_helpers import make_fake_energy_coord, FakeKVDB


# ---------------------------------------------------------------------------
# (i) + (ii): full round-trip per persisted declaration
# ---------------------------------------------------------------------------
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _all_persisted():
    return list(EV_REGISTRY.iter_persisted_lists())


def test_every_persisted_declaration_round_trips():
    """C-HIGH-1: for EVERY declaration with persistence_kind='list',
    seed the attr with a known id, drive the production save + restore
    helpers, and confirm the id is preserved.
    """
    persisted = _all_persisted()
    assert len(persisted) == 8, (
        f"expected 8 list-shape declarations; got {len(persisted)}"
    )

    for decl in persisted:
        coord = make_fake_energy_coord()
        getattr(coord._ev, decl.attr).add("garage_a")

        db = FakeKVDB()
        _run(coord._save_registry_owner_lists(db))

        # (i) literal key present with expected payload shape
        assert decl.persistence_key in db.energy_state, (
            f"{decl.name}: KV key {decl.persistence_key!r} missing "
            "from save output"
        )
        payload = json.loads(db.energy_state[decl.persistence_key])
        assert payload == ["garage_a"], (
            f"{decl.name}: save payload wrong ({payload!r})"
        )

        # (ii) restore against a fresh controller with an empty attr
        coord2 = make_fake_energy_coord()
        # Copy the just-saved KV into the fresh DB's read-side map.
        db2 = FakeKVDB()
        db2.energy_state.update(db.energy_state)
        _run(coord2._restore_registry_owner_lists(
            db2, 10.0, {"garage_a", "garage_b"},
        ))
        assert "garage_a" in getattr(coord2._ev, decl.attr), (
            f"{decl.name}: round-trip lost id (attr={decl.attr})"
        )


def test_persist_writes_full_owner_set_contents_not_singleton():
    """C-HIGH-1: multi-id set contents preserved verbatim."""
    coord = make_fake_energy_coord()
    coord._ev._paused_by_grid_cap.add("garage_a")
    coord._ev._paused_by_grid_cap.add("garage_b")
    db = FakeKVDB()
    _run(coord._save_registry_owner_lists(db))
    assert sorted(json.loads(db.energy_state["evse_grid_cap_paused"])) == [
        "garage_a", "garage_b",
    ]


# ---------------------------------------------------------------------------
# (iii) DP dispatch owner reclaim — C-HIGH-3 (also covered in b2c3;
# duplicated here so this file is the single persistence-oracle authority)
# ---------------------------------------------------------------------------
def test_restore_reinstalls_dp_dispatch_owner():
    coord = make_fake_energy_coord()
    db = FakeKVDB()
    db.energy_state["evse_dp_paused"] = json.dumps(["garage_a", "garage_b"])
    _run(coord._restore_registry_owner_lists(
        db, 10.0, {"garage_a", "garage_b"},
    ))
    for eid in ("garage_a", "garage_b"):
        assert eid in coord._ev._paused_by_dp
        assert "dp" in coord._ev._dispatch_owners.get(eid, set()), (
            f"DP dispatch owner missing for {eid}"
        )


def test_restore_does_not_reinstall_dp_owner_on_non_dp_keys():
    """The dp hook must fire ONLY for the dp declaration — a restored
    grid_cap id must not accidentally acquire a `dp` dispatch owner.
    """
    coord = make_fake_energy_coord()
    db = FakeKVDB()
    db.energy_state["evse_grid_cap_paused"] = json.dumps(["garage_a"])
    _run(coord._restore_registry_owner_lists(
        db, 10.0, {"garage_a", "garage_b"},
    ))
    owners = coord._ev._dispatch_owners.get("garage_a", set())
    assert "dp" not in owners


# ---------------------------------------------------------------------------
# (iv) D-1: corrupt-KV resilience
# ---------------------------------------------------------------------------
def test_restore_skips_non_list_payload_and_continues():
    """A malformed row (dict / int / null) for one key must NOT strand
    the remaining keys. The offending declaration's attr is left empty
    but sibling declarations still populate.
    """
    coord = make_fake_energy_coord()
    db = FakeKVDB()
    # Corrupt payload for grid_cap; well-formed for dp; JSON parse-error
    # for arbitrage (garbage), and a bare integer for battery_drain.
    db.energy_state["evse_grid_cap_paused"] = json.dumps(
        {"garage_a": True},  # dict, not list
    )
    db.energy_state["evse_battery_drain_paused"] = json.dumps(42)  # int
    db.energy_state["evse_arbitrage_paused"] = "not-valid-json"
    db.energy_state["evse_dp_paused"] = json.dumps(["garage_a"])
    _run(coord._restore_registry_owner_lists(
        db, 10.0, {"garage_a", "garage_b"},
    ))
    # Corrupt keys → empty owner attrs.
    assert coord._ev._paused_by_grid_cap == set()
    assert coord._ev._paused_by_battery_drain == set()
    assert coord._ev._paused_by_arbitrage == set()
    # Later well-formed key still populated.
    assert "garage_a" in coord._ev._paused_by_dp
    assert "dp" in coord._ev._dispatch_owners.get("garage_a", set())


# ---------------------------------------------------------------------------
# (v) A-LOW-2: unknown restore_hook raises
# ---------------------------------------------------------------------------
def test_unknown_restore_hook_raises_assertion(monkeypatch):
    """A declaration with an unhandled `restore_hook` label MUST raise —
    silent drift on a hook contract is a latent restart-integrity bug.
    """
    # Swap in a temporary registry with one declaration carrying a bogus
    # hook. We can't mutate the frozen dataclass; build a fresh one.
    bogus = OwnerDeclaration(
        name="grid_cap", attr="_paused_by_grid_cap", tier="evse", kind="set",
        precedence_row=3,
        persistence_key="evse_grid_cap_paused", persistence_kind="list",
        restore_hook="not_a_real_hook",  # type: ignore[arg-type]
        peer_holds_member=True, dispatch_tag="grid_cap",
        classifier_priority=3, reason_token="grid_capped",
        reason_human="grid import cap",
    )
    fake_reg = OwnerRegistry("evse", [bogus])
    from custom_components.universal_room_automation.domain_coordinators \
        import energy_pool_owners as _owners_mod
    monkeypatch.setattr(_owners_mod, "EV_REGISTRY", fake_reg)
    coord = make_fake_energy_coord()
    db = FakeKVDB()
    db.energy_state["evse_grid_cap_paused"] = json.dumps(["garage_a"])
    with pytest.raises(AssertionError, match="Unknown restore_hook"):
        _run(coord._restore_registry_owner_lists(
            db, 10.0, {"garage_a", "garage_b"},
        ))


# ---------------------------------------------------------------------------
# (iii) C-HIGH-2: behavioral blind-window pre-engaged restore
# ---------------------------------------------------------------------------
def test_blind_window_restore_marks_pre_engaged_and_epoch():
    """C-HIGH-2: with a persisted `_paused_by_blind_window` set + epoch
    KV, the restore path (registry loop + inline post-loop block) must
    mark `_blind_window_pre_engaged=True` and set
    `_blind_window_epoch_started_at` from the persisted ISO.
    This exercises the full production `_restore_evse_state` flow —
    the inline block sits AFTER the registry helper.
    """
    # We drive the whole `_restore_evse_state` here because the inline
    # blind-window block is not inside the extracted helper. Reuse the
    # helper to set up `_ev`, then bind the real `_restore_evse_state`.
    coord = make_fake_energy_coord()
    from custom_components.universal_room_automation.domain_coordinators \
        import energy as _energy_mod
    coord._restore_evse_state = types.MethodType(
        _energy_mod.EnergyCoordinator._restore_evse_state, coord,
    )
    # `_restore_evse_state` reads db off `hass.data`.
    db = FakeKVDB()
    # Preload blind_window pause set + epoch ISO.
    db.energy_state["evse_blind_window_paused"] = json.dumps(["garage_a"])
    db.energy_state["evse_blind_window_epoch_started_at"] = (
        "2026-07-23T12:00:00+00:00"
    )
    coord.hass.data = {
        "universal_room_automation": {"database": db},
    }
    # The full `_restore_evse_state` also touches WV state + LKG. Stub
    # them off — this test focuses on the blind-window block.
    coord._battery = None
    coord._write_verifier = None
    coord._restore_wv_state = types.MethodType(
        (lambda self, *a, **kw: _noop_coro()),
        coord,
    )
    _run(coord._restore_evse_state())
    assert "garage_a" in coord._ev._paused_by_blind_window
    assert coord._ev._blind_window_pre_engaged is True, (
        "C-HIGH-2: blind-window restore must mark pre-engaged"
    )
    assert coord._ev._blind_window_epoch_started_at is not None
    assert coord._ev._blind_window_epoch_started_at.isoformat() == (
        "2026-07-23T12:00:00+00:00"
    )


async def _noop_coro():
    return None
