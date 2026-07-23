"""Owner-set declaration registry for the EV pool + smart-plug tiers.

Phase 2 of the owner-set registry refactor
(`docs/planning/PLANNING_owner_set_registry_refactor.md`). This module
extracts the enumeration contract for the 12 EV-pool + 5 plug-tier
owner surfaces documented in the planning doc §1a/§1b tables into
declarative `OwnerDeclaration` rows, so the five load-bearing
enumeration sites in `energy_pool.py` + `energy.py` derive from ONE
source of truth:

    - `_prune_removed_evses` / `SmartPlugController.prune_removed_plugs`
    - `EVChargerController._stronger_peer_holds`
    - `EnergyCoordinator._save_evse_state`  (list-shape KV keys)
    - `EnergyCoordinator._restore_evse_state` (list-shape KV keys)
    - `EVChargerController.get_status`'s `_classify_evse` classifier +
      `SmartPlugController.get_status`'s parallel classifier

Behavior invariant (planning doc §0)
------------------------------------
This module is BEHAVIOR-FROZEN. The golden capture at
`quality/tests/golden/owner_registry_v1.jsonl.gz` (schema v2, 3158
rows) holds pre-refactor byte-identical outputs on the five surfaces
above. The registry MUST reproduce every byte. Any deviation is a
FAIL — the oracle test names the tuple and the differing surface.

Design decisions worth calling out (§3d discipline)
---------------------------------------------------
1. **Attr names preserved.** Owner sets stay on the controller
   instance under their original private attr names (`_paused_by_us`,
   `_excess_solar_active`, ...). The registry references them by
   name via `getattr`, not by rebinding. This keeps the 8 test files
   documented in §1c working unchanged.
2. **Load-shed prune quirk preserved.** `_paused_by_load_shed` is
   declared with `prune_participant=False` (EV tier only). This is
   NOT a fix — it captures the pre-existing behavior the operator
   rulings ratified in-cycle (§Operator rulings §3). A one-line
   Tier-1 fix + test lands immediately after this cycle merges.
3. **Two-pass prune shape preserved.** Prune iterates set-shape
   declarations first, then dict-shape declarations, matching the
   two hand-rolled loops in `_prune_removed_evses` (anomaly #2 in the
   phase-1 report). Do NOT unify the passes.
4. **Only list-shape persistence is registry-driven.** Per-EVSE
   bools (`paused_by_energy`, `excess_solar_active` via
   `db.save_evse_state`), the blind-window epoch scalar, the
   force-charge scalar, and every non-persisted RAM-only owner
   stay explicitly inline in save/restore. Declarations still exist
   for them (so the enumeration is complete), but their
   `persistence_kind` is not `"list"` and the iterators skip them.
5. **Restore side effects are inline, not in declarations.** DP
   restore reinstalls the `"dp"` dispatch owner claim; blind-window
   paused restore triggers epoch + pre-engaged; force-charge restore
   uses `set_force_charge_override(...)`. These are captured as
   `RestoreHook` labels on the declaration (documented but the
   coordinator applies the hook body inline for clarity — the
   declaration merely names the hook so reviewers can grep).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Literal


PersistenceKind = Literal[
    "none",         # not persisted (RAM only)
    "list",         # sorted-list KV write (registry-driven)
    "per_evse_bool",  # bundled into db.save_evse_state (inline only)
    "scalar",       # scalar KV (inline only)
]

RestoreHook = Literal[
    "none",
    # DP: after re-adding evse to `_paused_by_dp`, call
    # `_claim_pause_dispatch_owner(evse_id, "dp")` (energy.py:1445).
    "reinstall_dp_dispatch_owner",
    # Blind-window paused: triggers the epoch restore + pre-engaged
    # marking block at energy.py:1490-1515. Applied inline because the
    # hook body is more than a per-id call.
    "blind_window_epoch_and_pre_engaged",
]


@dataclass(frozen=True)
class OwnerDeclaration:
    """One row of the owner enumeration contract.

    Fields intentionally minimal — this is a table, not a policy engine.
    """
    name: str                              # canonical short name
    attr: str                              # controller attr, referenced via getattr
    tier: Literal["evse", "plug"]
    kind: Literal["set", "dict"] = "set"   # RAM shape (drives prune loop pass)

    # §2.4b precedence row (1-12 for real precedence owners; None for
    # intent-state / auxiliary owners). Not consumed for logic — this
    # is the doc-anchor field so reviewers can cross-check the
    # declaration against `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md`.
    precedence_row: int | None = None

    # Registry-driven persistence (list-shape sorted-list KV write).
    # `persistence_kind` NOT "list" ⇒ save/restore keep this owner inline.
    persistence_key: str | None = None
    persistence_kind: PersistenceKind = "none"
    restore_hook: RestoreHook = "none"

    # Peer-holds membership — inclusion in `_stronger_peer_holds`. See
    # planning §1a: `_paused_by_dp` and non-pause "intent" sets are
    # excluded (dp is consulted inline at two sites with different
    # semantics; §1a table row #5 note).
    peer_holds_member: bool = False

    # Reference-counted `_dispatch_owners` tag. None = not a pause
    # dispatcher (e.g. excess_solar grant, proactive_offpeak intent,
    # blind_window liveness-ride latch).
    dispatch_tag: str | None = None

    # Prune participation. Load-shed EV tier: FALSE by design (see
    # planning appendix operator ruling 3). This is a quirk PRESERVED
    # for byte-identical golden compatibility; the one-line Tier-1 fix
    # lands immediately after this cycle merges.
    prune_participant: bool = True
    prune_quirk_note: str = ""  # populated only on the load_shed EV row

    # Classifier data — get_status precedence-ordered owner slice.
    # `classifier_priority` None ⇒ this owner has no explicit
    # classifier branch (falls through to charging/idle/off). The 8 EV
    # owners with an explicit branch use ascending integers
    # (fill_priority=1 … proactive_offpeak=8).
    classifier_priority: int | None = None
    reason_token: str = ""
    reason_human: str = ""
    # Dynamic reason_human resolver (used for fill-priority which
    # includes the target-SOC string). When set, overrides
    # `reason_human` at classifier time. Signature: (ctx: dict) -> str
    # where ctx carries the classifier-supplied fp_msg + any future
    # dynamic bits.
    dynamic_reason: Callable[[dict[str, Any]], str] | None = field(
        default=None, compare=False, repr=False,
    )


class OwnerRegistry:
    """Ordered container of `OwnerDeclaration` rows for one tier.

    Preserves declaration order — the classifier iterator + prune
    iterator sort by their respective fields, but downstream
    consumers relying on stable iteration order get insertion order.
    """
    def __init__(self, tier: Literal["evse", "plug"],
                 declarations: Iterable[OwnerDeclaration]) -> None:
        self._tier = tier
        self._decls: tuple[OwnerDeclaration, ...] = tuple(declarations)
        for d in self._decls:
            if d.tier != tier:
                raise ValueError(
                    f"OwnerDeclaration {d.name!r} tier={d.tier!r} does "
                    f"not match registry tier={tier!r}",
                )

    @property
    def tier(self) -> str:
        return self._tier

    def iter_all(self) -> Iterator[OwnerDeclaration]:
        return iter(self._decls)

    def iter_prune_sets(self) -> Iterator[OwnerDeclaration]:
        """Set-kind owners that participate in prune (two-pass shape,
        pass 1). Load-shed EV tier is EXCLUDED by design (quirk)."""
        for d in self._decls:
            if d.kind == "set" and d.prune_participant:
                yield d

    def iter_prune_dicts(self) -> Iterator[OwnerDeclaration]:
        """Dict-kind participants (two-pass shape, pass 2)."""
        for d in self._decls:
            if d.kind == "dict" and d.prune_participant:
                yield d

    def iter_peer_holds(self) -> Iterator[OwnerDeclaration]:
        for d in self._decls:
            if d.peer_holds_member:
                yield d

    def iter_persisted_lists(self) -> Iterator[OwnerDeclaration]:
        """List-shape KV persistence entries (save + restore side)."""
        for d in self._decls:
            if d.persistence_kind == "list" and d.persistence_key:
                yield d

    def iter_classifier(self) -> Iterator[OwnerDeclaration]:
        """Explicit-branch owners, ordered by classifier_priority ascending."""
        yield from sorted(
            (d for d in self._decls if d.classifier_priority is not None),
            key=lambda d: d.classifier_priority or 0,
        )

    def by_name(self, name: str) -> OwnerDeclaration:
        for d in self._decls:
            if d.name == name:
                return d
        raise KeyError(f"Unknown owner {name!r} in tier {self._tier}")


# ---------------------------------------------------------------------------
# EV-pool owner declarations (§1a table, 12 owners + auxiliaries)
# ---------------------------------------------------------------------------
def _fp_reason(ctx: dict[str, Any]) -> str:
    """Fill-priority dynamic reason_human — target SOC embedded."""
    return ctx["fp_msg"]


EV_DECLARATIONS: tuple[OwnerDeclaration, ...] = (
    # Row 1: TOU pause. Subordinate to protection owners.
    OwnerDeclaration(
        name="tou", attr="_paused_by_us", tier="evse", kind="set",
        precedence_row=1,
        persistence_key=None,  # per-EVSE bool via db.save_evse_state (inline)
        persistence_kind="per_evse_bool",
        peer_holds_member=False,
        dispatch_tag="tou",
        classifier_priority=6, reason_token="paused",
        reason_human="TOU peak/mid-peak pause",
    ),
    # Row 2: Excess-solar grant (not a pause — a grant).
    OwnerDeclaration(
        name="excess_solar", attr="_excess_solar_active", tier="evse", kind="set",
        precedence_row=2,
        persistence_key=None,  # per-EVSE bool via db.save_evse_state (inline)
        persistence_kind="per_evse_bool",
        peer_holds_member=False,
        classifier_priority=7, reason_token="excess_solar",
        reason_human="excess solar (charging)",
    ),
    # Row 3: Grid-cap.
    OwnerDeclaration(
        name="grid_cap", attr="_paused_by_grid_cap", tier="evse", kind="set",
        precedence_row=3,
        persistence_key="evse_grid_cap_paused", persistence_kind="list",
        peer_holds_member=True, dispatch_tag="grid_cap",
        classifier_priority=3, reason_token="grid_capped",
        reason_human="grid import cap",
    ),
    # Row 4: Battery-drain protection.
    OwnerDeclaration(
        name="battery_drain", attr="_paused_by_battery_drain", tier="evse",
        kind="set", precedence_row=4,
        persistence_key="evse_battery_drain_paused", persistence_kind="list",
        peer_holds_member=True, dispatch_tag="battery_drain",
        classifier_priority=2, reason_token="battery_drain_paused",
        reason_human="battery drain protection (paused)",
    ),
    # Row 5: DP (drain-precedence). INTENT-STATE — excluded from peer_holds
    # (dp is consulted INLINE at two sites with different semantics; see
    # `_stronger_peer_holds` docstring + §1a table row #5 note).
    OwnerDeclaration(
        name="dp", attr="_paused_by_dp", tier="evse", kind="set",
        precedence_row=5,
        persistence_key="evse_dp_paused", persistence_kind="list",
        restore_hook="reinstall_dp_dispatch_owner",
        peer_holds_member=False,   # intent-state exclusion (§1a note)
        dispatch_tag="dp",
        classifier_priority=5, reason_token="dp_paused",
        reason_human="drain-precedence transition (paused)",
    ),
    # Row 6: Arbitrage compound-load protection.
    OwnerDeclaration(
        name="arbitrage", attr="_paused_by_arbitrage", tier="evse", kind="set",
        precedence_row=6,
        persistence_key="evse_arbitrage_paused", persistence_kind="list",
        peer_holds_member=True, dispatch_tag="arbitrage",
        classifier_priority=4, reason_token="arbitrage_paused",
        reason_human="arbitrage compound-load protection",
    ),
    # Row 7: Load-shed EV tier. QUIRK: NOT pruned. Preserved in-cycle.
    OwnerDeclaration(
        name="load_shed", attr="_paused_by_load_shed", tier="evse", kind="set",
        precedence_row=7,
        persistence_key=None,  # RAM only, re-derived from cascade at
                               # energy.py:2358 (§1c cross-module coupling).
        persistence_kind="none",
        peer_holds_member=True, dispatch_tag="load_shed",
        prune_participant=False,
        prune_quirk_note=(
            "PRESERVED byte-identically in phase-2 build (operator ruling 3, "
            "planning appendix). One-line Tier-1 fix + test lands "
            "immediately after this cycle merges."
        ),
        # No explicit classifier branch — falls through to state.
    ),
    # Row 8: Fill-priority.
    OwnerDeclaration(
        name="fill_priority", attr="_paused_by_fill_priority", tier="evse",
        kind="set", precedence_row=8,
        persistence_key="evse_fill_priority_paused", persistence_kind="list",
        peer_holds_member=True, dispatch_tag="fill_priority",
        classifier_priority=1, reason_token="fill_priority_paused",
        reason_human="",  # dynamic
        dynamic_reason=_fp_reason,
    ),
    # Row 9: Proactive off-peak intent-state.
    OwnerDeclaration(
        name="proactive_offpeak", attr="_proactive_offpeak_holds", tier="evse",
        kind="set", precedence_row=9,
        persistence_key="evse_proactive_offpeak_holds", persistence_kind="list",
        peer_holds_member=False,  # intent-state, not a pause owner
        classifier_priority=8, reason_token="offpeak_proactive_on",
        reason_human="off-peak proactive turn-on",
    ),
    # Row 10: Blind-window guard pause (v5.28.0).
    OwnerDeclaration(
        name="blind_window", attr="_paused_by_blind_window", tier="evse",
        kind="set", precedence_row=10,
        persistence_key="evse_blind_window_paused", persistence_kind="list",
        restore_hook="blind_window_epoch_and_pre_engaged",
        peer_holds_member=True, dispatch_tag="blind_window",
        # No explicit classifier branch — falls through to state.
    ),
    # Row 11: Blind-window per-epoch liveness-ride latch (v5.28.0 D-HIGH-3).
    OwnerDeclaration(
        name="blind_window_liveness_ride",
        attr="_blind_window_liveness_ride", tier="evse", kind="set",
        precedence_row=11,
        persistence_key="evse_blind_window_liveness_ride",
        persistence_kind="list",
        peer_holds_member=False,  # latch, not a pause owner
        # No explicit classifier branch.
    ),
    # Auxiliary dict-kind owners (side maps + tracking dicts pruned in
    # pass 2). Prune-only participants — no classifier, no persistence,
    # no peer-holds.
    OwnerDeclaration(name="battery_drain_cooldown",
                     attr="_battery_drain_cooldown", tier="evse", kind="dict"),
    OwnerDeclaration(name="pause_dispatch_ts",
                     attr="_pause_dispatch_ts", tier="evse", kind="dict"),
    OwnerDeclaration(name="observed_off_since_pause",
                     attr="_observed_off_since_pause", tier="evse", kind="dict"),
    OwnerDeclaration(name="dispatch_owners",
                     attr="_dispatch_owners", tier="evse", kind="dict"),
    OwnerDeclaration(name="power_sensor_unavail_count",
                     attr="_power_sensor_unavail_count", tier="evse", kind="dict"),
    OwnerDeclaration(name="power_sensor_unavail_since",
                     attr="_power_sensor_unavail_since", tier="evse", kind="dict"),
    OwnerDeclaration(name="arbitrage_pause_reason",
                     attr="_arbitrage_pause_reason", tier="evse", kind="dict"),
)


PLUG_DECLARATIONS: tuple[OwnerDeclaration, ...] = (
    # Plug tier — no persistence today; RAM state re-derived per-tick.
    # Classifier priorities mirror the plug precedence at
    # energy_pool.py:3497 (fill_priority > drain > tou > activity).
    OwnerDeclaration(
        name="tou", attr="_paused_by_us", tier="plug", kind="set",
        peer_holds_member=False,
        classifier_priority=3, reason_token="paused",
        reason_human="TOU peak/mid-peak pause",
    ),
    OwnerDeclaration(
        name="battery_drain", attr="_paused_by_battery_drain", tier="plug",
        kind="set", peer_holds_member=True,
        dispatch_tag="battery_drain",
        classifier_priority=2, reason_token="battery_drain_paused",
        reason_human="battery drain protection (paused)",
    ),
    OwnerDeclaration(
        name="fill_priority", attr="_paused_by_fill_priority", tier="plug",
        kind="set", peer_holds_member=True,
        dispatch_tag="fill_priority",
        classifier_priority=1, reason_token="fill_priority_paused",
        reason_human="",
        dynamic_reason=_fp_reason,
    ),
    OwnerDeclaration(
        name="load_shed", attr="_paused_by_load_shed", tier="plug", kind="set",
        peer_holds_member=True, dispatch_tag="load_shed",
        # Plug tier DOES prune load_shed — the quirk is EV-tier only.
    ),
    OwnerDeclaration(
        name="proactive_offpeak", attr="_proactive_offpeak_holds", tier="plug",
        kind="set", peer_holds_member=False,
    ),
)


EV_REGISTRY = OwnerRegistry("evse", EV_DECLARATIONS)
PLUG_REGISTRY = OwnerRegistry("plug", PLUG_DECLARATIONS)
