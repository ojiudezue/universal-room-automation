# PLANNING — EVSE solar-session per-car stop conditions (discard-and-suppress)

**Card:** `EVSE-SOLAR-STOP-CONDITIONS-1`
**Status:** REWORKED 2026-08-26 to address 15 must-fixes from the two framing-disjoint
plan reviews (`PLAN_REVIEW_evse_solar_stop_conditions.md`). Awaiting **RE-REVIEW**
(two framing-disjoint plan reviews) before build dispatch. Do NOT build until re-review
clears.
**Tier:** **3.** Threads a value (`_solar_follow_suppressed` membership + a discard
from `_excess_solar_active`) through the peer-precedence claim leg that owns physical
`switch.turn_on/off` calls to EV chargers. A single missed site is either a re-claim
oscillator (kills the feature) or a stuck-off session (kills the car). Cost-and-
safety impacting; the founding problem IS a state-machine seam. Plan review 1
(completeness) and plan review 2 (build-prediction) both returned FIX-PLAN-FIRST;
this document is that fix.
**Depends on / does NOT re-open:** `PLANNING_evse_solar_follow_amps.md` (D1 amp
modulation). This cycle owns SESSION START/STOP; amp modulation stays byte-identical.
**Cites (prior art):** `docs/planning/AUDIT_excess_solar_and_evse_prior_art.md`
(2026-08-23) — reuse table, whole-house-only stop diagnosis (§1.1), yo-yo location
(§1.2), and the `self_modulates` name-collision warning (§2.2, §7 confusable pair).
**Companion / precedes:** none. Ships after D1 amp modulation on the same claim leg.

---

## 0. Problem

The excess-solar path in `EVChargerController.determine_excess_solar_actions`
(`energy_pool.py:1321-1704`) ends a session only on WHOLE-HOUSE conditions:

- `tou_period == "peak"` (peak-time drop, `:1358-1377`),
- `not conditions_met` — SOC `< 95` OR remaining forecast `< 5 kWh` (`:1577-1582`
  gate + `:1688-1702` discard loop),
- blind-window DROP leg (`:1534-1575`).

There is **no per-car stop.** A car that finishes at 2 pm on a sunny day, or is
unplugged and driven off, leaves URA claiming the charger for hours. The switch stays
`on`, the car is either full (drawing ~0) or absent (drawing 0), and the whole-house
predicate cannot see it. Live evidence: the AUDIT prior-art doc §1.1 confirms whole-
house-only exits are the ONLY exits today.

## 0a. Why this is not a "just add an early return"

**Founding problem (the reason this was split from `PLANNING_evse_solar_follow_amps.md`).**
A naive per-EVSE stop sited ABOVE the claim leg is an **oscillator**: the stop discards
the EVSE from `_excess_solar_active` and issues `switch.turn_off`; on the very next tick
the claim leg (`:1584-1687`) re-tests the whole-house predicate, finds it still True,
and re-claims the same EVSE. `switch.turn_on` fires. The car — full, or gone — is
turned back on. On the tick after that the stop fires again. The claim leg does not
read "we already tried to stop this bay"; it only reads global surplus and per-EVSE
peer holds.

Two rejected resolutions and why:
1. **Claim-leg cooldown** ("don't re-claim within N minutes"). Adds a hidden time seam
   to a set that has never had one, breaks the CLAIM-ON-EDGE contract every peer
   relies on (a drain-cleared EVSE would fail to re-claim until the cooldown elapsed),
   and does not solve the finished-car case in principle — it just extends the
   oscillator period.
2. **No per-EVSE stops** ("only whole-house stops, accept the waste"). Ships the
   defect.

## 0b. Chosen resolution — DISCARD-AND-MOVE (a refinement of operator option (b))

**Deviation declaration (must-fix C1 / plan-review 1).** The operator's literal option
(b) was "keep the EVSE in `_excess_solar_active`, mark it suppressed via a companion
set" — i.e. **keep-in-set + mark**. This plan implements a **refinement** of (b):
**discard-and-move** — the stop path REMOVES the bay from `_excess_solar_active` AND
ADDS it to a separate `_solar_follow_suppressed` set; the claim leg gates on the
suppressed set.

**Why discard-and-move beats literal keep-in-set.** `_excess_solar_active` is read by
**at least 11 downstream consumers** across `energy_pool.py`, `energy_pool_owners.py`,
and `energy.py` (see §1a table). Every one of them was written under the invariant
"membership in this set ⇒ this bay is actively charging on our claim." Keep-in-set
would silently retarget every one of those consumers — the TOU peak-pause skip at
:909 would still skip a bay we've just turned off; the classifier at owners.py:245
would still report `reason_token="excess_solar"` / "excess solar (charging)" for a
bay whose switch is OFF; the sensor attrs at :2553-4 would advertise a stopped bay
as active on the WebSocket. Auditing and patching 11 consumers to distinguish
"in-set-and-charging" from "in-set-but-suppressed" is a wider blast radius than
moving membership. **Discard-and-move preserves each consumer's existing invariant
by construction:** a suppressed bay is NOT in `_excess_solar_active`, so those
consumers see it as "not our claim" — which is what they should see, because our
switch call has physically stopped the session. The new gate is a single, named
site with the same shape as `_paused_by_dp` (a same-owner "we spoke for this bay"
latch consulted inline by the claim loop).

The cost of discard-and-move is that a handful of consumers **legitimately want to
know** the bay is "URA-suppressed, not idle." Those are enumerated in §1a and handled
either by (i) the same "not our claim" answer being correct (the majority) or (ii) an
explicit read of `_solar_follow_suppressed` alongside the active set (minority — the
classifier + the sensor-attrs surface).

The two-line gate (top of claim loop):

```python
for evse_id, config in self._evse.items():
    ...
    if evse_id in self._excess_solar_active:
        continue                                     # already ours
    if evse_id in self._solar_follow_suppressed:     # NEW
        continue                                     # suppressed until discharged
    if self._stronger_peer_holds(evse_id):
        continue
    ...
```

## 0c. Interaction with `self_modulates` (name-collision warning)

`_self_modulates_for(evse_id)` (`energy_pool.py:713-724`) is an EXISTING per-EVSE flag
whose meaning is "the CHARGER modulates itself" — semantically INVERTED from anything
this cycle does (URA modulating / stopping). The flag is dormant (no `CONF_*`, no
config-flow field; AUDIT §2.2). This cycle:

- Introduces NO new "modulate" naming.
- Does NOT read or write `self_modulates`.
- Does NOT change the classifier row for `excess_solar` (which reason-token remains
  `"excess_solar"` — see §1a row for :2646-58).

Any future re-hydration of `self_modulates` is orthogonal to suppression.

---

## 1. Institutional context verified

Greps and reads performed for this plan. Every ADD is justified against what exists.

### Claim leg + membership

- `EVChargerController.determine_excess_solar_actions` — `energy_pool.py:1321-1704`.
  Whole-house predicate at `:1577-1582`; claim loop `:1591-1687`; stop loop
  `:1688-1702`. Every actionable branch reads or writes `self._excess_solar_active`.
- **Writers to `_excess_solar_active` (grep-verified, `custom_components/`).** Four
  intra-controller sites (`energy_pool.py:1372, :1567, :1659/:1674/:1682, :1702` —
  the last three are three variants of the claim `.add`, one write per code path,
  plus the three discard sites), the prune-set pass at `energy_pool.py:790-794`
  (registry-driven, applies to `_excess_solar_active` because its owner row declares
  `kind="set"`), AND the DB-restore `.add` in `energy.py:1467-8`. **Correcting the
  prior plan's claim** ("no other module writes this set" was refuted by plan-review
  C5): `energy.py:1467-8` is an outside-controller writer. The suppressed set has
  the same shape and MUST carry equivalent restore-side behavior (documented as
  "empty on boot" in §6 — no cross-module writer added).
- `_stronger_peer_holds` — `energy_pool.py:383-412`. Enumerates
  `EV_REGISTRY.iter_peer_holds()` (6 owners today). The new suppressed set is
  deliberately **NOT** a peer-hold — see §3 INV-STOP-4.
- `_get_evse_state` — `energy_pool.py:653-710`. Returns dict keyed
  `is_on`, `power`, `status`, `charging`, `power_source`. `status` comes from
  `switch_state.attributes.get("status", "unknown")` (`:691`) — this is the string we
  key the UNPLUGGED discharge on (§5.1). `charging = power > EVSE_CHARGING_POWER_THRESHOLD`
  (100 W) at `:695` — this is what we key the FINISHED discharge on (§5.2).
  **`power_source`** is `"sensor"` when a real power sensor is providing the value
  and `"unavailable"` / other tokens otherwise — this cycle's timed stops MUST gate
  on `power_source == "sensor"` (see §5.2 and §7 D3 body). The controller already
  tracks unavailability streaks in `_power_sensor_unavail_since`
  (`energy_pool.py:254, 2479-2504`) — the STALE_POWER guard the amp-modulation cycle
  ships is reused here.

### Owner registry (the pattern to REUSE)

- `energy_pool_owners.py:100-157` — `OwnerDeclaration` dataclass; `attr` refs the
  controller-instance owner set; `kind="set"` participates in the prune sets pass
  (`iter_prune_sets`, `:185-190`); `peer_holds_member` gates inclusion in
  `_stronger_peer_holds`; `persistence_kind="list"` opts into registry-driven KV
  save/restore (`iter_persisted_lists`, `:203-207`).
- `EV_DECLARATIONS` — `:231-370`. 12 owners + 8 auxiliary dicts. The rows this cycle
  models against: `dp` (`:274-283`, intent-state, `peer_holds_member=False`,
  consulted inline; classifier_priority=5) and `load_shed` (`:295-304`, RAM-only,
  `persistence_kind="none"`).
- **BEHAVIOR-FROZEN header** (`:20-24`) is asserted against the golden at
  `quality/tests/golden/owner_registry_v1.jsonl.gz`. Adding an `OwnerDeclaration`
  row **regenerates the golden with a named header note**, precedent set by the
  Tier-1 load_shed prune-quirk fix (`:36-42`). This is the endorsed path, not a
  violation. The regen step is a deliverable (§7 D1).

### Persistence precedent

- `_KNOWN_HOOKS` / `iter_persisted_lists` — the sorted-list KV save/restore path used
  by the 6 `persistence_kind="list"` owners. Because this cycle wants restore to be
  a HARD DROP (§6), and not to reinstall a `switch.turn_off` on boot,
  `_solar_follow_suppressed` is declared **`persistence_kind="none"`** — mirrors
  `load_shed` (`:298-300`). Boot behaviour is spelled out in §6.

### Config surface

- `CONF_ENERGY_*` — enumerated via `ura-config-and-flags`. No existing knob names
  "solar-follow stop" or "EVSE idle timeout" — every knob in §7 is **NEW because no
  equivalent found** after grepping `energy_const.py` for `SOLAR_*`, `EVSE_*`,
  `STOP_*`, `NO_DRAW_*`, `IDLE_*`, `MIN_ON_*`.

### Docs consulted

- `docs/planning/PLANNING_evse_solar_follow_amps.md` — full read. This cycle inherits
  its scope fence for AMP-MODULATION only. See §1a for the **corrected scope-fence
  claim**: SolarFollowController reads `_excess_solar_active` at three sites; a
  discard is NOT invisible to it.
- `docs/planning/AUDIT_excess_solar_and_evse_prior_art.md` — full read. §1.1
  (whole-house-only-exits diagnosis), §1.2 (yo-yo location), §2.2 (`self_modulates`
  name collision), §7 confusable pairs table.
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` — precedence table for the claim
  leg. Suppressed-membership is NOT a precedence row; it is a same-owner "we already
  stopped this bay" latch (§3 INV-STOP-4).

### Session pickup

- Memory `project_session_pickup_2026_08_24.md` — this plan is one of the two
  build-ready plans awaiting operator go; the other is D1 amp modulation, which
  ships first.

---

## 1a. Consumer enumeration of `_excess_solar_active` — MANDATED CENTRAL TASK (C2)

Every read site of `_excess_solar_active`, and how it MUST behave when a bay has been
discarded-and-moved into `_solar_follow_suppressed`. This table is the plan's core
correctness proof for the discard-and-move mechanism.

Meaning to consumer of the transition: `evse_id ∈ _excess_solar_active` in tick T,
then in tick T+1 `evse_id ∈ _solar_follow_suppressed` (URA has issued `switch.turn_off`
and moved membership).

| # | Site (file:line) | What it reads | Consumer's intent | Behavior under discard | Correct? | Action |
|---|---|---|---|---|---|---|
| 1 | `energy_pool.py:909` (TOU peak-pause skip) | `if evse_id in _excess_solar_active: continue` | "Don't TOU-pause a bay we're actively solar-charging." | Discarded bay is NOT skipped → TOU peak-pause loop will `switch.turn_off` the bay | **YES — correct behavior.** URA has already turned it off; a redundant idempotent turn_off in peak is harmless. INV-STOP-5 idempotence applies. Peak also clears `_proactive_offpeak_holds` at :907. | None. Verified benign. |
| 2 | `energy_pool.py:1259` (dual-membership comment guard) | Comment-only reference (fix-up note) | N/A | N/A | N/A | None. |
| 3 | `energy_pool.py:1360` (peak-drop discard loop, own file) | Iteration + discard | Turn off any bays we activated when peak arrives | Discarded bay is not in the loop → no double turn_off | **YES.** Also correctly clears `_proactive_offpeak_holds` at :1376 — the stop path §5 MUST do the same (see must-fix #12). | Ensure §5 stop path also clears `_proactive_offpeak_holds`. |
| 4 | `energy_pool.py:1521` (blind-window CONTINUE liveness check) | `for _active in _excess_solar_active` | Log liveness of the still-granted set | Suppressed bay not enumerated → no misleading "granted" log | **YES.** | None. |
| 5 | `energy_pool.py:1535` (blind-window DROP loop, own file) | Iteration + discard + add to `_paused_by_blind_window` | Fail-safe pause during blind window | Suppressed bay is not in the loop → not moved into `_paused_by_blind_window` | **YES.** A suppressed bay has physically stopped; it is not competing for the blind-window pause list. Discharge on replug will re-evaluate; if blind window still active, next tick sees no active bay to drop. | None. |
| 6 | `energy_pool.py:1595` (claim loop "already ours") | `if in _active: continue` | Don't double-claim | Suppressed bay NOT in active set → falls through to the NEW `if in _solar_follow_suppressed: continue` at D2 | **YES by construction (D2).** | D2 gate MUST land immediately after this line. |
| 7 | `energy_pool.py:2217` (fill-priority "defer when excess solar firing") | `if in _active and pause_conditions_global: continue` | Don't fill-priority-pause a bay actively solar-charging | Suppressed bay does NOT match → fill-priority pause proceeds if `pause_conditions_global` | **YES — correct.** URA has stopped solar-charging this bay; it is a legitimate target for fill-priority pause now. Fill-priority claim is a peer-hold and will (via INV-STOP-4) not be blocked by suppression. Note: if fill-priority `switch.turn_off` fires on a bay we already turned off, it is idempotent. | None. Verified benign. |
| 8 | `energy_pool.py:2553-2554` (`get_status` sensor attrs) | `bool(_active)` + `list(_active)` | Publish "is any excess-solar bay active" + the list | Suppressed bay NOT listed → sensor no longer advertises a stopped bay as actively charging | **YES — that is the desired user-visible outcome.** Suppressed set is separately surfaced at §9 as `solar_follow_suppressed`. | Add `solar_follow_suppressed` + `solar_follow_stop_ledger` attrs (§9). |
| 9 | `energy_pool.py:2646-2658` + `energy_pool_owners.py:245` (classifier via `_classify_evse` → owner-row `classifier_priority=7`, `reason_token="excess_solar"`) | `if evse_id in getattr(self, _decl.attr): return (reason_token, reason_human)` | Publish a per-EVSE human status | Suppressed bay does NOT match the `excess_solar` row → falls through the priority list → lands on the tail `charging/idle/off` classifier (line :2655-2659). Because we've called `switch.turn_off`, `is_on` is False and `charging` is False → returns `("off", "off")` | **PARTIALLY CORRECT.** The bay reports `"off"` which is a **regression in operator observability**: the reason we stopped it (`unplugged` / `finished_full_current_zero` / `no_draw_for_n`) is not surfaced on the classifier. **RESOLUTION:** the ledger surfaces the reason via §9 `solar_follow_stop_ledger`. The classifier itself is INTENTIONALLY not extended (adding a `solar_follow_suppressed` classifier row would re-couple it to the very consumer set we're moving away from). Documented trade-off. | Document in §9. Do NOT add a suppressed classifier row. |
| 10 | `energy_pool.py:3889` (SolarFollowController amp-modulation `_restore_pass` gate — INSIDE `PLANNING_evse_solar_follow_amps.md` scope) | `if evse_id in _ev._excess_solar_active: continue` | "Skip restore for bays still actively solar-following" | Discarded bay IS NOT skipped → `_restore_pass` will attempt to write amps BACK TO SAVED VALUE on a charger URA is turning off this same tick | **CRITICAL ORDERING PROBLEM** — see §1b scope-fence correction. RESOLUTION: the stop scan runs BEFORE `SolarFollowController._restore_pass` reads active membership in a given tick; but the amp restore runs on its own sub-tick clock. The stop path §D3 sets `_solar_follow_suppressed` atomically with the discard; the amp `_restore_pass` MUST additionally check `_solar_follow_suppressed` and skip suppressed bays. **NEW D2a deliverable** below. | Add suppressed-set skip at :3889/:4077/:4304. |
| 11 | `energy_pool.py:4077` (SolarFollowController `_maybe_tick` active-set read) | `active = _ev._excess_solar_active` | "If nothing active, run restore-only + return" | Discarded bay removed → controller sees smaller/empty `active` → skips modulation for it | **YES for modulation direction; NO for the restore that runs FIRST at :4083-4084** — the restore leg reads the OLD `_original_amps` and would write back to a bay we've just stopped. RESOLUTION: `_restore_pass` skips bays in `_solar_follow_suppressed` (D2a). | Same as row 10. |
| 12 | `energy_pool.py:4304` (SolarFollowController `_backstop_boot_reconcile` scope check) | `active = _ev._excess_solar_active` | "Session took it back — nothing for backstop to do" | Discarded bay removed from `active` → backstop treats bay as needing reconciliation → may write amps | **UNSAFE without D2a.** Same resolution: `_backstop_boot_reconcile` skips bays in `_solar_follow_suppressed`. | Same as row 10. |
| 13 | `energy.py:1467-8` (DB-restore path adds to active set on boot) | `if state.get("excess_solar_active"): _ev._excess_solar_active.add(evse_id)` | Restore membership across restart | Boot: suppressed set is empty (§6); active is restored from DB. First tick's stop scan runs and re-suppresses if the bay is still finished/unplugged. | **YES.** Documented in §6. | None. Note in §1 corrections that this refutes the "no other writer" claim. |
| 14 | `energy.py:1656` (INFO log line on restore) | `list(_ev._excess_solar_active)` | Log restored membership | Suppressed set is empty on boot → not logged with active list | **YES.** | None. |
| 15 | `energy.py:1941` (persist tick: `excess_solar_active=evse_id in _active`) | Bool for DB write | Persist active membership | Suppressed bay is NOT in `_active` → DB row records `excess_solar_active=False`. Correct. Suppressed set is `persistence_kind="none"` → not persisted. Restart re-derives (§6). | **YES.** | None. |
| 16 | `energy.py:5402` (torn-restart reconcile: `_paused_by_dp ∩ _excess_solar_active`) | `if eid in _active` | "Excess wins — drop the DP membership" | Suppressed bay NOT in `_active` → this reconciler does NOT clear DP membership on it. Correct: a suppressed bay that is also DP-paused should stay DP-paused. Suppression and DP-pause are orthogonal (INV-STOP-4). | **YES.** | None. |
| 17 | `energy.py:5410` (log string only) | Log | N/A | N/A | N/A | None. |
| 18 | `energy.py:5415-45` (torn-restart HOLD_ONLY branch, reads `_paused_by_dp`) | Reads `_paused_by_dp` (not `_active` directly in this block) | Reconcile HOLD_ONLY-with-no-excess-claim | Unchanged — this block does not read `_active` on its main branch. | **YES.** | None. |
| 19 | `energy_pool_owners.py:245` (declaration row) | Registry declaration | Prune / classifier / persistence wiring | See row 9 for classifier; row for prune below. | **YES.** | Add sibling declaration for `solar_follow_suppressed` (D1). |
| 20 | `energy_pool.py:790-794` (prune set pass, registry-driven) | Iterates `iter_prune_sets()` including `_excess_solar_active` | Drop EVSE ids no longer in `self._evse.keys()` | Same code path will prune `_solar_follow_suppressed` because the new declaration sets `prune_participant=True` (D1). | **YES.** | Verify D1 declaration includes `prune_participant=True`. |
| 21 | `energy_pool.py:351` (comment) | Comment only | N/A | N/A | N/A | None. |

**Summary of consumer impact.** Of 21 read sites, 18 are BENIGN under discard-and-move
(the "not our claim" semantics carry over correctly), 3 require the D2a amp-restore
skip (SolarFollowController at :3889 / :4077 / :4304), and 1 is a documented operator-
observability trade-off (classifier :2646-58 returns `"off"` for suppressed bays; the
ledger surfaces the reason instead).

**Discard-and-move is proven correct for the enumerated consumer set,** subject to
D2a landing and to the §5 stop path clearing `_proactive_offpeak_holds` (must-fix
#12) atomically with the set move.

## 1b. Scope-fence correction — SolarFollowController IS a cross-surface consumer

Plan-review C3 refuted the prior version's "disjoint surfaces" claim. Correcting:

**SolarFollowController** (`energy_pool.py:3717+`) reads `_excess_solar_active` at
`:3889` (`_restore_pass`), `:4077` (`_maybe_tick`), and `:4304`
(`_backstop_boot_reconcile`). It runs on its own sub-tick clock. A discard from
`_excess_solar_active` without a corresponding suppressed-set signal to the amp
controller would cause a `_restore_pass` amp write TO A CHARGER URA IS TURNING OFF
THIS SAME TICK — either racing the switch call, or worse, writing amps to a charger
whose switch flip happens before the amp write, wasting a write on a stopped bay.

**Ordering contract (mandatory).** Within a single EC decision cycle:
1. `determine_excess_solar_actions` runs (`energy.py:5757` in the EC dispatch), and
   its per-tick stop scan (§D3) is invoked as the LAST leg. The stop scan mutates
   `_excess_solar_active` and `_solar_follow_suppressed` atomically at each site
   (§D3 body). The generated `switch.turn_off` action is APPENDED to the returned
   `actions` list.
2. `_execute_service_action` dispatches the turn_off (later in the tick).
3. `SolarFollowController._maybe_tick` may run in the SAME EC tick or on its own
   sub-tick clock; the ordering across the two is NOT guaranteed to have the amp
   controller see the mutated sets before it reads them.

**Therefore (D2a — new deliverable):** `SolarFollowController._restore_pass`,
`_maybe_tick`, and `_backstop_boot_reconcile` MUST all skip bays in
`_solar_follow_suppressed` at their existing `_excess_solar_active` read sites. This
is a two-line augmentation at each of :3889, :4077, and :4304 (add
`or evse_id in self._ev._solar_follow_suppressed` to the existing membership check,
or an equivalent early-continue).

**Effect on the "disjoint surfaces" claim in `PLANNING_evse_solar_follow_amps.md`:**
this cycle DOES touch the amp controller's read sites. The touches are additive
(new set membership checks alongside existing ones) and byte-preserving of amp
values — the amp controller writes zero new amp values as a consequence of this
cycle. INV-STOP-6 is amended accordingly.

---

## 2. Non-goals

1. NOT amp modulation. D1 (`PLANNING_evse_solar_follow_amps.md`) owns amp values.
   This plan changes NO amp value and reads no grid entity. (Note: D2a IS a
   compatibility augmentation of the amp controller's read sites — the amp
   controller's arithmetic and write shape are unchanged.)
2. NOT changing the whole-house end conditions (SOC, remaining forecast, peak,
   blind-window DROP leg). All existing exit paths are byte-identical (see §8
   verification).
3. NOT changing peer precedence. `_solar_follow_suppressed` is not added to
   `iter_peer_holds()`.
4. NOT persisting the suppressed set across restart (§6). A restart is a
   legitimate "conditions have changed" event; the claim leg will re-evaluate
   against fresh state.
5. NOT reading car SoC or decoding J1772 pilot. Stop reasons are keyed off the two
   channels already parsed by `_get_evse_state` (`status`, `power`).
6. NOT modifying `_get_evse_state`.
7. NOT deleting the whole-house stop loop (`:1688-1702`). The two paths coexist;
   §D3 spells out ordering.
8. **NOT building the SOC-hysteresis pair in this cycle.** The desired shape
   (start at `excess_solar_soc`, stop at `fill_priority_soc`) exists as a defensive
   `min()` proposal because `number.py:1670-1678` does NOT enforce
   `fill_priority_soc < excess_solar_soc`. **Deferred** to a follow-up card
   `EVSE-SOLAR-SOC-HYSTERESIS-1` (to be filed) for two reasons: (a) the pair
   change belongs in the whole-house predicate (`:1577-1582`), which is INV-STOP-6
   BYTE-IDENTICAL for this cycle; (b) the defensive `min()` + operator warning
   needs its own review because it silently rewrites operator input. Card carries
   the site (`energy_pool.py:1577-1582` whole-house gate; `number.py:1670`
   ordering-invariant not enforced) and the reason for the defensive clamp.
9. **NOT deleting the SolarFollowController's own byte-identical amp arithmetic.**
   D2a is additive membership checks only.

---

## 3. Falsifiable invariants

**INV-STOP-1 (the core no-oscillator invariant — Tier-3 falsifiable form).**
> Under any legal grid + peer + SOC configuration, an EVSE that has been
> discharged from `_excess_solar_active` into `_solar_follow_suppressed` in tick `T`
> is NOT re-added to `_excess_solar_active` by `determine_excess_solar_actions` in
> any tick `T+k` (`k ≥ 1`) until its suppression is discharged by one of the events
> enumerated in §5.
>
> **Falsified by:** any observed transition `evse_id ∈ _solar_follow_suppressed` →
> `evse_id ∈ _excess_solar_active` on a tick where none of the §5 discharge conditions
> fired. Reviewer D's job is to break this by combining knobs (`conditions_met` True,
> peer set empty, suppressed set carrying `garage_a`) and asserting a claim never
> issues.

**INV-STOP-2 (discharge covers every stop reason — falsifiable form).**
> Every add to `_solar_follow_suppressed` writes an atomic ledger row in
> `_stop_reason_ledger[evse_id]` naming ONE token from §5.0 AND a
> `stamped_monotonic` float. There is no code path that adds to
> `_solar_follow_suppressed` without writing the ledger row in the same statement
> group.
>
> **Falsified by:** at any tick, `evse_id ∈ _solar_follow_suppressed AND
> (evse_id ∉ _stop_reason_ledger OR "stamped_monotonic" ∉
> _stop_reason_ledger[evse_id] OR "reason" ∉ _stop_reason_ledger[evse_id])`. If this
> co-occurrence is observed, INV-STOP-2 is falsified and INV-STOP-3 becomes
> unreachable via the timeout backstop for the offending bay (see §5.3
> unparseable-stamp discharge policy).

**INV-STOP-3 (bounded suppression — no permanent stuck-off).** For every EVSE ever
added to `_solar_follow_suppressed`, at least one discharge condition will fire
within a bounded horizon: (a) a replug edge (§5.1), (b) the timeout backstop
`SOLAR_STOP_SUPPRESSION_MAX_S` (§5.3), OR (c) restart (§6). No code path adds to
the set without at least one of (a)/(b)/(c) being reachable. **Missing/unparseable
`stamped_monotonic` triggers IMMEDIATE discharge** (§5.3) — a suppressed bay with no
verifiable timeout is treated as age = ∞ and discharged the same tick.

**INV-STOP-4 (suppression is not a peer-hold, and never blocks a peer).** No sibling
owner (drain, grid_cap, arbitrage, fill_priority, blind_window, load_shed, TOU) reads
`_solar_follow_suppressed`. Adding an EVSE to it does NOT prevent drain-precedence
from pausing it, does NOT prevent load-shed from pausing it, does NOT prevent a
future excess-solar RECLAIM once discharged. **Peer holds continue to operate exactly
as they do today.** Consequence: `_solar_follow_suppressed` is declared with
`peer_holds_member=False` and does NOT appear in `iter_peer_holds()`.

**INV-STOP-5 (idempotence at the stop path — falsifiable form).**
> Re-entering the stop path on an EVSE already in `_solar_follow_suppressed` is a
> no-op: no additional `switch.turn_off` action is emitted, no ledger row is
> re-written, no timer is reset. The stop is edge-triggered on
> `evse_id ∈ _excess_solar_active AND stop_condition_true` — leaving the ACTIVE set
> is the edge.
>
> **Falsified by:** two consecutive ticks with `evse_id ∈ _solar_follow_suppressed`
> at both t0 and t1, where the returned `actions` at t1 contains ANY entry with
> `target == config["switch"]`, OR `_stop_reason_ledger[evse_id]["stamped_monotonic"]`
> at t1 differs from t0 without an intervening discharge → re-add cycle.

**INV-STOP-6 (byte-identical whole-house paths + additive-only amp-controller
touches).** The peak drop (`:1358-1377`), the blind-window CONTINUE / DROP legs
(`:1400-1575`), the whole-house predicate (`:1577-1582`), the claim loop
(`:1584-1687`), and the whole-house stop loop (`:1688-1702`) are unchanged by this
cycle except for:
- the two-line suppressed-membership gate at the top of the claim loop (D2), and
- the append of the new `_evaluate_solar_follow_stops` call as the LAST leg before
  `return actions` in the non-blind branch (D3 wiring).

The SolarFollowController touches at :3889 / :4077 / :4304 are ADDITIVE membership
checks (D2a); amp arithmetic is byte-identical.

**INV-STOP-7 (stop precedes / suppresses amp restore).** In every tick where D3
adds a bay to `_solar_follow_suppressed`, no `SolarFollowController._restore_pass`
write to `number.set_value` occurs for that bay in the same tick or any subsequent
tick until the bay is discharged from `_solar_follow_suppressed`. D2a enforces
this at the amp-controller read sites.
> **Falsified by:** an `actions` sequence in a single tick containing both
> `{service: "switch.turn_off", target: config["switch"]}` for `evse_id` AND
> `{service: "number.set_value", target: config["current_limit_entity"]}` for the
> same `evse_id`, OR a `number.set_value` fired on a subsequent tick against a
> suppressed bay.

---

## 4. Deliverables

### D1 — Declare the suppressed set (owner registry)

**Site:** `energy_pool_owners.py`, EV_DECLARATIONS block (`:231-370`), appended
AFTER the `blind_window_liveness_ride` row (`:334-342`) and BEFORE the auxiliary
dict rows.

```python
# Row 12: Solar-follow per-EVSE suppression (v<next>).
# Not a peer-hold and not a pause owner — a same-owner "we already
# stopped this bay this session" latch consulted inline by the
# excess-solar claim leg. Discharged by replug, timeout backstop,
# or restart (§5). RAM-only.
OwnerDeclaration(
    name="solar_follow_suppressed",
    attr="_solar_follow_suppressed", tier="evse", kind="set",
    precedence_row=None,             # not a precedence row (§3 INV-STOP-4)
    persistence_key=None,
    persistence_kind="none",         # §6 boot behavior
    peer_holds_member=False,         # §3 INV-STOP-4
    dispatch_tag=None,               # not a pause dispatcher
    prune_participant=True,          # participates in _prune_removed_evses set pass
    # No explicit classifier row: a suppressed bay is CHARGING-STOPPED,
    # falls through to the tail ("off"). Reason surfaced via ledger (§9).
),
```

**Aux-dict declarations for prune (must-fix C11).** `_stop_reason_ledger` and
`_solar_follow_no_draw_since` are per-EVSE dicts consulted by this cycle. Both MUST
be declared to the registry's `iter_prune_dicts` pass so removed EVSE ids do not leak
forever. Add TWO auxiliary rows to `EV_AUX_DICT_DECLARATIONS` (the block adjacent to
`EV_DECLARATIONS` — grep-verify exact name; if the aux block uses a different
mechanism, wire via the same primitive `_prune_removed_evses` iterates at
`energy_pool.py:795-799`):

```python
# aux dict: stop-reason ledger (RAM-only, per-EVSE).
OwnerDeclaration(
    name="stop_reason_ledger", attr="_stop_reason_ledger",
    tier="evse", kind="dict",
    persistence_kind="none", peer_holds_member=False,
    prune_participant=True,
),
# aux dict: no-draw streak monotonic seed (RAM-only, per-EVSE).
OwnerDeclaration(
    name="solar_follow_no_draw_since", attr="_solar_follow_no_draw_since",
    tier="evse", kind="dict",
    persistence_kind="none", peer_holds_member=False,
    prune_participant=True,
),
```

**Golden regen.** The `owner_registry_v1.jsonl.gz` golden is regenerated with a
header note: `"Tier-3 cycle: EVSE-SOLAR-STOP-CONDITIONS-1 — add
solar_follow_suppressed owner row + stop_reason_ledger + solar_follow_no_draw_since
aux rows"`. Precedent: the Tier-1 load_shed prune fix note
(`energy_pool_owners.py:36-42`). The regen script + the mutation-matrix update are
part of D1 (not a separate deliverable), matching how load_shed was handled.

**Controller-instance init.** In `EVChargerController.__init__`, initialise
`self._solar_follow_suppressed: set[str] = set()`,
`self._stop_reason_ledger: dict[str, dict[str, Any]] = {}`,
`self._solar_follow_no_draw_since: dict[str, float] = {}`. Location: alongside
`self._excess_solar_active` (grep-verified single-site init at `energy_pool.py:205`).

### D2 — Add the claim-leg gate (single effective new check)

**Site:** `energy_pool.py`, inside the claim `for evse_id, config in self._evse.items()`
loop at `:1591`, immediately AFTER the `if evse_id in self._excess_solar_active: continue`
check at `:1595-1596`, BEFORE the `_stronger_peer_holds` check at `:1602`.

```python
if evse_id in self._excess_solar_active:
    continue  # Already on by us
if evse_id in self._solar_follow_suppressed:                          # NEW
    _LOGGER.debug(                                                    # NEW
        "Excess solar: %s in solar_follow_suppressed — skipping "     # NEW
        "(reason=%s, stamped_iso=%s, age_s=%s); "                     # NEW
        "discharge on replug / timeout / restart",                    # NEW
        evse_id,                                                      # NEW
        self._stop_reason_ledger.get(evse_id, {}).get("reason", "?"), # NEW
        self._stop_reason_ledger.get(evse_id, {}).get("stamped_iso", "?"),
        (now_monotonic - self._stop_reason_ledger.get(evse_id, {}).get(
            "stamped_monotonic", now_monotonic)),                     # NEW
    )                                                                 # NEW
    continue                                                          # NEW
if self._stronger_peer_holds(evse_id):
    ...
```

**Ordering matters.** The suppressed gate is BELOW the "already ours" check (so an
active bay is not accidentally re-suppressed by a diagnostic race) and ABOVE the peer
guard (so a suppressed bay does not waste a peer read; also guarantees the reviewer's
completeness check has a single gate site).

### D2a — SolarFollowController suppressed-skip augmentation (NEW — from C3 fix)

**Sites (all in `energy_pool.py`):**
- `:3889` — `_restore_pass`: augment the `if evse_id in self._ev._excess_solar_active:
  continue` to also skip when `evse_id in self._ev._solar_follow_suppressed`. The
  restore MUST NOT write amps to a suppressed bay (INV-STOP-7).
- `:4077` — `_maybe_tick`: after reading `active = self._ev._excess_solar_active`,
  also read `suppressed = self._ev._solar_follow_suppressed`; if `not active and not
  self._original_amps` OR (all `_original_amps` keys are in `suppressed`), the
  restore-only leg still runs but skips suppressed bays (via :3889 augmentation).
  Amp modulation loop skips bays in `suppressed`.
- `:4304` — `_backstop_boot_reconcile`: skip bays in `suppressed` in the touched-set
  reconcile loop (a suppressed bay's amp value is fixed until discharged; boot
  reconciliation is not authorized to write amps against a suppressed bay).

**Effect.** INV-STOP-7 holds: no amp restore fires against a suppressed bay. Amp
controller arithmetic on non-suppressed bays is byte-identical.

**D2a byte-identity proof.** Grep gate in §D7: the only amp-controller changes in
`git diff <merge-base>..HEAD -- energy_pool.py` in the range `:3717-:4400` are the
three additive membership checks named above. Any other change is a HIGH.

### D3 — Add the per-tick stop-condition scan

**Site:** new method `_evaluate_solar_follow_stops(self, now_monotonic: float,
now_iso: str) -> list[dict[str, Any]]` on `EVChargerController`.

**Where it runs across the FOUR returns of `determine_excess_solar_actions` (must-fix
C6/B?? — the plan's prior wording elided that this method has four early returns).**
The method's four return sites are:

- `:1377` — peak-period early return (whole-house peak drop already ran).
- `:1533` — blind-window CONTINUE early return (whole-house DROP not run;
  liveness ride active).
- `:1575` — blind-window DROP early return.
- `:1704` — the tail (non-blind, either `conditions_met` claim path or
  `not conditions_met` whole-house discard path).

**Stop-scan invocation policy (per leg):**

| Return leg | Invoke stop scan? | Reason |
|---|---|---|
| `:1377` peak | **NO.** | Peak already discards every active bay at :1372 and issues turn_off for every `is_on` bay. There is nothing left in `_excess_solar_active` for the stop scan to act on. INV-STOP-5 idempotence guarantees a stop-scan call would be a no-op, but calling it is wasted work; explicit "no-invoke" is documented. |
| `:1533` blind CONTINUE | **NO — blind-window blind spot, INTENTIONAL.** | Blind-window CONTINUE granted liveness-ride authority; power/status readings during blind window are exactly what the guard treats as untrustworthy. Firing a `finished_full_current_zero` stop against a bay whose `power` reading is questionable is the failure mode the guard exists to prevent. Documented blind spot. `unplugged` (§5.1) is a status-family read, not a power read — but the blind window's charter is "trust nothing from this bay this epoch," so we honor it for the whole scan. |
| `:1575` blind DROP | **NO.** | DROP leg discards active membership and adds to `_paused_by_blind_window`; nothing left for the stop scan. |
| `:1704` tail | **YES — invoked immediately BEFORE the return.** | The two tail branches (`conditions_met` and `not conditions_met`) both leave the ACTIVE set in a consistent state; the stop scan operates on whatever remains in `_excess_solar_active` AFTER the tail's own discard loop. Invoked after `:1687` (end of claim loop) in the `conditions_met` branch, and after `:1702` (end of discard loop) in the `else` branch. |

**Ordering guarantees under the `:1704` tail invocation:**

- If the whole-house path already dropped the EVSE (`_excess_solar_active.discard`
  in `:1567`, `:1702`), the per-EVSE stop scan sees an empty set for those bays and
  no-ops for them (INV-STOP-5).
- Suppression is added only for bays STILL in `_excess_solar_active` after the
  whole-house path, i.e. cases the whole-house path did not already handle. This
  is exactly the surface the card names.

**Body (specification — the ONE authoritative clock is `time.monotonic()`,
captured ONCE at the top of the method and passed through; every reason resolver
uses this exact value):**

```
def _evaluate_solar_follow_stops(self, now_monotonic, now_iso):
    actions = []
    for evse_id in list(self._excess_solar_active):
        config = self._evse.get(evse_id, {})
        switch_entity = config.get("switch", "")
        # Single power/status read per bay per tick (INV-STOP idempotence).
        st = self._get_evse_state(evse_id)
        # Update the no-draw streak seed BEFORE consulting reasons.
        if st["charging"]:
            self._solar_follow_no_draw_since.pop(evse_id, None)
        else:
            self._solar_follow_no_draw_since.setdefault(evse_id, now_monotonic)
        reason = self._solar_follow_stop_reason(
            evse_id, st, now_monotonic,
        )
        if reason is None:
            continue
        # SOLAR_MIN_ON_S guard (see §7).
        # Session-start monotonic is recorded at the .add site; a bay
        # not in _solar_follow_session_start_ms was added on this exact
        # tick (unlikely) or restored from DB (§6) → seed now.
        started = self._solar_follow_session_start_ms.setdefault(
            evse_id, now_monotonic,
        )
        if (now_monotonic - started) < SOLAR_MIN_ON_S:
            continue  # too young to stop; retry next tick
        if switch_entity and st["is_on"]:
            actions.append({"service": "switch.turn_off",
                            "target": switch_entity, "data": {}})
        # ATOMIC: set-membership move + ledger row in one uninterruptible
        # block. Failing to write EITHER of the two dicts is treated as
        # a bug and would be caught by INV-STOP-2 tests.
        self._excess_solar_active.discard(evse_id)
        self._solar_follow_suppressed.add(evse_id)
        self._stop_reason_ledger[evse_id] = {
            "reason": reason,
            "stamped_monotonic": now_monotonic,   # authoritative for §5.3
            "stamped_iso": now_iso,               # display only
            "power_at_stop": st["power"],
            "status_at_stop": st["status"],
            "power_source_at_stop": st["power_source"],
        }
        # must-fix C12: clear proactive off-peak hold on stop, mirroring
        # the peak-clear path at :907 / :1376. A stopped bay must not
        # continue to advertise "off-peak proactive turn-on".
        self._proactive_offpeak_holds.discard(evse_id)
        _LOGGER.info(
            "excess solar: per-EVSE stop for %s (reason=%s, power=%.0fW, "
            "status=%s, power_source=%s)",
            evse_id, reason, st["power"], st["status"], st["power_source"],
        )
    return actions
```

`_solar_follow_stop_reason(evse_id, state, now)` returns one of the tokens in §5.0
or `None`. It reads NO clock of its own; it uses `now` as passed. It reads NO
`_get_evse_state` of its own; it uses `state` as passed.

**Session-start seed (`_solar_follow_session_start_ms`).** Every `.add` to
`_excess_solar_active` inside `determine_excess_solar_actions` (three sites: `:1659`,
`:1674`, `:1682`) MUST also `self._solar_follow_session_start_ms[evse_id] =
now_monotonic`. Delete on discard (both the whole-house discard sites `:1567`,
`:1702` and the stop-scan discard here). This is the SOLAR_MIN_ON_S support dict.
Declared to prune-dicts as with the other aux dicts (D1).

### D4 — Discharge sites (three of them; see §5)

- **Replug discharge (§5.1)** — invoked at the TOP of
  `determine_excess_solar_actions` on every tick (BEFORE any of the four return
  legs' logic runs), so a replug clears suppression BEFORE the claim leg re-evaluates
  conditions.
- **Timeout discharge (§5.3)** — invoked in the same top-of-tick sweep as the replug
  discharge (they share the loop over `_solar_follow_suppressed`).
- **No-draw discharge is NOT its own discharge event.** No-draw-for-N is a STOP
  cause (§5.2), not a discharge. Discharges are only replug, timeout, and restart
  (§6). This prevents the "no-draw stopped it → still no-draw → re-claim" oscillator.

### D5 — Stop-reason ledger (evidence for tuning)

`self._stop_reason_ledger: dict[str, dict[str, Any]]` on `EVChargerController`.
Keys: `evse_id`; values: `{reason, stamped_monotonic, stamped_iso, power_at_stop,
status_at_stop, power_source_at_stop}` and, after the eventual discharge, extended
with `{discharged_reason, discharged_stamped_iso, discharged_stamped_monotonic}`.
RAM-only, pruned via D1 declaration. Read-only surface exposed on the
`ev_charging_status` sensor as `solar_follow_stop_ledger` (§9).

### D6 — Prune + teardown

- Registry-driven prune covers `_solar_follow_suppressed` (`set`,
  `prune_participant=True`) via `iter_prune_sets` (`energy_pool_owners.py:185-190`)
  AND covers `_stop_reason_ledger`, `_solar_follow_no_draw_since`,
  `_solar_follow_session_start_ms` (`dict`, `prune_participant=True`) via
  `iter_prune_dicts` — D1 declares all three.
- No timers, no `async_call_later` handles. The stop scan is per-tick (called from
  the existing `determine_excess_solar_actions` invocation), so there is no
  outstanding callback to cancel at teardown.

### D7 — Tests + mutation drills — the REAL test deliverable (must-fix B9/C-implied)

Each test is DISCRIMINATING per CLAUDE.md — the observation looks different under
the fix vs a plausible alternative failure. Each is anchored by a mutation site:
edit production source to bypass/neuter the site, run the test, confirm the named
RED failure, restore. A site whose bypass leaves the suite green is an untested site
and is a HIGH.

**Mutation-site × named-RED-test table:**

| # | Mutation site (file:line under D2/D2a/D3/D4) | Neuter | Named test that MUST go RED | Assertion |
|---|---|---|---|---|
| T1 | D2 gate at `energy_pool.py:~1597` | Delete the two-line `if evse_id in _solar_follow_suppressed: continue` block | `test_inv_stop_1_no_reclaim_when_suppressed` | With `_solar_follow_suppressed={"garage_a"}`, `conditions_met=True`, peer set empty: 10 consecutive `determine_excess_solar_actions` calls produce ZERO `switch.turn_on` on `garage_a`. Under neuter: ≥1 `switch.turn_on`. |
| T2 | D3 `_solar_follow_suppressed.add(evse_id)` in the stop scan | Comment out the `.add` line (keep the `.discard(_excess_solar_active)`) | `test_stop_moves_bay_into_suppressed_atomically` | After stop scan fires on a `finished_full_current_zero` bay, `evse_id in _solar_follow_suppressed AND evse_id not in _excess_solar_active AND evse_id in _stop_reason_ledger AND "stamped_monotonic" in ledger row`. Under neuter: bay is discarded but not suppressed → next tick re-claims (oscillator). |
| T3 | D3 `_stop_reason_ledger[evse_id] = {...}` write | Replace ledger dict with `{"reason": reason}` only (drop `stamped_monotonic`) | `test_inv_stop_2_ledger_stamp_present` | After any stop, `"stamped_monotonic" in _stop_reason_ledger[evse_id]`. Also tests INV-STOP-3 timeout is reachable (T7). Under neuter: INV-STOP-2 falsified. |
| T4 | `_solar_follow_stop_reason` unplugged branch (§5.1) | Return `None` for unplugged status | `test_unplugged_records_stop` | `status="not_connected"` bay in `_excess_solar_active` → after one tick, bay in `_solar_follow_suppressed` with `reason="unplugged"`. Under neuter: bay stays active. |
| T5 | `_solar_follow_stop_reason` finished branch | Return `None` for `finished_full_current_zero` | `test_finished_full_current_zero_records_stop` | `status="connected"`, `power=20W`, `charging=False`, `power_source="sensor"` for 121s → `reason="finished_full_current_zero"`. Under neuter: bay stays active past the 120s FINISHED window. |
| T6 | `_solar_follow_stop_reason` no-draw branch | Return `None` for `no_draw_for_n` | `test_no_draw_for_n_records_stop` | `charging=False`, `power_source="sensor"`, streak ≥ 300s, not finished-eligible → `reason="no_draw_for_n"`. Under neuter: bay stays active. |
| T7 | §5.3 timeout discharge check | Delete the `now - stamped_monotonic >= SOLAR_STOP_SUPPRESSION_MAX_S` branch | `test_inv_stop_3_timeout_discharges` | `SOLAR_STOP_SUPPRESSION_MAX_S=60`, seeded suppressed at t0, advance clock to t0+61 → bay discharged, `discharged_reason="timeout"`, next tick may re-claim. Under neuter: bay stuck forever. |
| T8 | §5.3 unparseable-stamp discharge | Comment out the "missing/unparseable stamp → discharge same tick" branch | `test_missing_stamp_discharges_immediately` | Seed `_solar_follow_suppressed={"garage_a"}` WITHOUT a ledger row → on first tick's top-of-tick sweep, bay is discharged with `discharged_reason="stamp_missing"`. Under neuter: bay stuck forever (INV-STOP-3 falsified). |
| T9 | §5.1 replug discharge (edge-triggered) | Change the edge check to level-triggered (`if status ∈ CONNECTED: discharge`) | `test_replug_edge_triggered_not_level` | Seed suppressed with `prior_status="connected"`; hold `status="connected"` for 10 ticks → NO discharge (no edge). Then transition through `not_connected → connected` → discharge fires exactly once. Under neuter: discharges on tick 1 (level-triggered), enabling oscillator on a bay that never unplugged. |
| T10 | D3 `_proactive_offpeak_holds.discard(evse_id)` | Comment out the discard | `test_stop_clears_proactive_offpeak_hold` | Seed `_proactive_offpeak_holds={"garage_a"}`; fire a stop on garage_a; next `get_status()` shows `proactive_offpeak_holds=[]`. Under neuter: sensor still reports garage_a in proactive-hold set (must-fix C12 failure). |
| T11 | D2a suppressed-skip at `energy_pool.py:3889` | Delete the `or evse_id in _ev._solar_follow_suppressed` check | `test_inv_stop_7_no_amp_restore_on_suppressed` | With `garage_a` in `_solar_follow_suppressed` and a saved `_original_amps["garage_a"]`, run `_restore_pass`: ZERO `number.set_value` actions targeting garage_a's current_limit entity. Under neuter: ≥1 amp write to a bay URA has stopped. |
| T12 | Stop-scan invocation at `:1704` tail | Delete the `actions += self._evaluate_solar_follow_stops(...)` call | `test_wire_in_stop_scan_at_tail_leg` | With a finished-eligible bay in `_excess_solar_active` and `conditions_met=True`, `determine_excess_solar_actions` returns actions containing a `switch.turn_off` for that bay. Under neuter (call removed): NO turn_off; bay stays active forever → INV-STOP-1 trivially holds but the FEATURE IS DEAD. **THIS IS THE WIRE-IN ANCHOR: an `_evaluate_solar_follow_stops` method that exists but is never called must fail T12.** |
| T13 | SOLAR_MIN_ON_S guard | Set `SOLAR_MIN_ON_S = 0` in the test AND delete the age check in D3 body | Same test: `test_solar_min_on_s_delays_stop` | With `SOLAR_MIN_ON_S=30`, add bay to `_excess_solar_active` at t0 with `status="not_connected"`; first tick's stop scan does NOT stop (age < 30); advance clock to t0+31 → stop fires. Under neuter (guard removed): stop fires on tick 1 (same-tick claim→stop, breaks J1772 handshake). |
| T14 | STALE_POWER health gate on timed stops (§5.2) | Delete the `power_source == "sensor"` guard on `finished_full_current_zero` / `no_draw_for_n` resolvers | `test_stale_power_does_not_stop_charging_bay` | Set `power_source="unavailable"` (or `_power_sensor_unavail_since[garage_a]` non-None) on a genuinely charging bay (real amps ≥ 8A). Fake power reads may read 0; stop scan MUST NOT fire either timed stop. Under neuter: stop fires on a charging car → catastrophic. |

**Wire-in anchor (per "wire-in anchors mandatory").** T12 is the enclosing-method
behavioral anchor: the `determine_excess_solar_actions` tail-leg call to
`_evaluate_solar_follow_stops` is the load-bearing wire. A method defined but never
called MUST fail T12. Similarly, T2 anchors the atomic set-move (a `.discard` without
a `.add` is caught).

**Test infrastructure.** Behavioral tests use the real controller construction path
(no `FakeCoordinator`) mirroring recent Tier-3 discipline. Clock is injected via a
monotonic clock hook on the controller (same pattern as recent EC cycles); no
`time.monotonic()` wall-clock coupling.

---

## 5. Discharge model — MANDATORY per "suppression needs a discharge"

**Every event-driven suppression must specify: what CLEARS it, what BACKSTOPS the
clear, and what happens at RESTART.** This section is that specification.

### 5.0 — Stop-reason enumeration + status-family disjointness

Every add to `_solar_follow_suppressed` records ONE token in `_stop_reason_ledger`:

| Token | Trigger | § |
|---|---|---|
| `unplugged` | `status` transitioned to a `SOLAR_STOP_STATUS_UNPLUGGED`-family token (§5.1) | 5.1 |
| `no_draw_for_n` | `charging is False` AND `power_source == "sensor"` for `SOLAR_STOP_NO_DRAW_S` (default 300 s) | 5.2 |
| `finished_full_current_zero` | `charging is False` AND `power < SOLAR_STOP_FINISHED_POWER_W` AND `power_source == "sensor"` AND status is `SOLAR_STOP_STATUS_CONNECTED`-family for `SOLAR_STOP_FINISHED_S` (default 120 s) | 5.2 |

**Status-family disjointness (must-fix C13/B11).** `SOLAR_STOP_STATUS_UNPLUGGED`
and `SOLAR_STOP_STATUS_CONNECTED` are asserted DISJOINT (empty intersection) at
`_evse_config_reconcile` load time. A status string in NEITHER set is treated as
`"unknown"` (see next).

**Unknown status behavior.** A `status` value that is not in
`SOLAR_STOP_STATUS_UNPLUGGED` AND not in `SOLAR_STOP_STATUS_CONNECTED` (including
the literal `"unknown"` returned by `_get_evse_state` when the switch state has no
`status` attribute):

- Provides NO stop signal (does not trigger `unplugged`).
- Provides NO discharge signal (does not trigger replug).
- The bay remains in whatever set it is currently in.

**Rationale.** An unmapped status token is a signal-quality event, not a state
event. The bay may still be finished-stopped via `finished_full_current_zero`
(power+charging channel, independent of status), and the timeout backstop always
fires.

**Status-token sets (probe-first — see §5.5).** The exact strings Emporia publishes
on the switch's `status` attribute are integration-defined. The plan does NOT
hard-code them; §5.5 mandates a one-shot recorder probe before build to enumerate
the live set and commit the mapping to `energy_const.py` as
`SOLAR_STOP_STATUS_UNPLUGGED` and `SOLAR_STOP_STATUS_CONNECTED` (both
`frozenset[str]`). Common members: `{"not_connected", "disconnected", "unplugged"}`
vs `{"connected", "charging", "awaiting_start"}` — but the probe is authoritative.

`finished_full_current_zero` is the "car at 100%, taper complete, charger
connected" case. Distinguishing it from `no_draw_for_n` is what makes the ledger
operator-tunable — a house that sees mostly `finished_full_current_zero` wants a
shorter `SOLAR_STOP_FINISHED_S`, while one that sees mostly `no_draw_for_n` wants
to tune the generic timeout. Discrimination is worth the extra token.

### 5.1 — UNPLUGGED (a stop AND a discharge trigger — EDGE-TRIGGERED)

**Stop side.** In `_solar_follow_stop_reason`, if
`state["status"].lower() in SOLAR_STOP_STATUS_UNPLUGGED`, return `"unplugged"`.

**Discharge side (edge-triggered — must-fix B1).** The naive "level-triggered
discharge" (`if status ∈ CONNECTED: discharge`) RE-CREATES THE OSCILLATOR for the
`finished_full_current_zero` case: a car connected+full+stopped has
`status="connected"` on every tick after being stopped; level-triggered discharge
would fire every tick, hand back to the claim leg, which re-suppresses next tick
on the same `finished` reason. Level-triggered = oscillator.

**Edge-triggered specification.** The ledger row includes `status_at_stop` (written
at the D3 atomic block). The discharge check is:

```
if evse_id in self._solar_follow_suppressed:
    prior_status = self._stop_reason_ledger[evse_id].get("status_at_stop", "")
    now_status = state["status"].lower()
    prior_was_unplugged = prior_status in SOLAR_STOP_STATUS_UNPLUGGED
    now_is_connected = now_status in SOLAR_STOP_STATUS_CONNECTED
    if prior_was_unplugged and now_is_connected:
        # replug edge: unplugged→connected transition
        discharge(evse_id, reason="replug")
```

**What "prior status" means.** `status_at_stop` is written at the D3 atomic block
(§4 D3 body). Its meaning: "the status observed at the tick the bay was moved into
`_solar_follow_suppressed`." **When it is missing** (theoretically impossible under
the atomic write; if observed at runtime it is a bug): the discharge check treats
missing `status_at_stop` as `"unknown"` → not-in-UNPLUGGED → no replug edge from
this side; the timeout backstop still fires and the stamp-missing branch (§5.3)
also fires. Cleared on discharge (both the whole ledger row and the aux dicts are
scoped to a single suppression epoch).

**Why status, not `is_on`.** `is_on` is a URA-controlled shadow of our last
`switch.turn_on/off` call — using it as the discharge witness reintroduces the
oscillator (URA-off → URA reads its own off → asserts unplug → re-claim). `status`
is charger-reported.

### 5.2 — NO-DRAW-FOR-N and FINISHED-FULL-CURRENT-ZERO (stops without discharge)

**Track no-draw streaks.** `self._solar_follow_no_draw_since: dict[str, float]` on
`EVChargerController`, keyed monotonic. Updated in D3's per-tick loop BEFORE the
reason resolver (§4 D3 body).

**Power-sensor health gate (must-fix B7/C7 — this is the STALE_POWER guard the amp
plan carries, reused here).** Both `no_draw_for_n` and `finished_full_current_zero`
gate on `state["power_source"] == "sensor"` AND `evse_id not in
_power_sensor_unavail_since` (which is the same signal `_get_evse_state`
consults). A degraded, unavailable, or absent power sensor **synthesizes zero**
in some code paths; without this gate we would turn off a genuinely charging car
+ suppress for 2h. Explicit reason label in code comments: "sensor-accuracy
correctness gate — a stopped stop is preferable to a wrongful stop."

Stop-reason resolution (in the order tried):

- if `state["power_source"] != "sensor"` OR `evse_id in
  _power_sensor_unavail_since`: SKIP timed stops (return None from the resolver
  for both branches); unplugged branch is unaffected (status-only).
- else if `now - since >= SOLAR_STOP_FINISHED_S` AND `power <
  SOLAR_STOP_FINISHED_POWER_W` (default 50 W) AND `status ∈
  SOLAR_STOP_STATUS_CONNECTED`, return `"finished_full_current_zero"`;
- else if `now - since >= SOLAR_STOP_NO_DRAW_S`, return `"no_draw_for_n"`;
- else return None (keep charging session alive; car may resume).

**Why these two do NOT auto-discharge.** The discharge condition would have to be
"the car started drawing again" — but URA has just turned the switch off. The car
CAN'T draw. Attempting to re-verify by turning the switch back on is exactly the
oscillator. Discharge for these reasons requires either (a) a physical replug
(§5.1 detects it via edge trigger) or (b) the timeout backstop (§5.3). This is
deliberate and preserves INV-STOP-1.

### 5.3 — TIMEOUT BACKSTOP (`SOLAR_STOP_SUPPRESSION_MAX_S`)

Default `SOLAR_STOP_SUPPRESSION_MAX_S = 7200` (2 h). **Authoritative clock: the same
`time.monotonic()` captured once at the top of the tick and threaded through** — the
top-of-tick discharge sweep receives `now_monotonic` from the same source as D3's
stop scan (both are called from `determine_excess_solar_actions`).

**Timeout discharge check:**

```
for evse_id in list(self._solar_follow_suppressed):
    row = self._stop_reason_ledger.get(evse_id)
    stamped = row.get("stamped_monotonic") if row else None
    # Missing/unparseable stamp: DISCHARGE IMMEDIATELY (age=0 treated as ∞).
    # Rationale: INV-STOP-3 requires bounded suppression; a bay we cannot
    # measure the age of has no bounded horizon → conservative release.
    if stamped is None or not isinstance(stamped, (int, float)):
        _LOGGER.warning(
            "excess solar: suppressed bay %s has no stamped_monotonic — "
            "discharging (reason=stamp_missing). Investigate: ledger=%r",
            evse_id, row,
        )
        discharge(evse_id, reason="stamp_missing", now_monotonic=now_monotonic,
                  now_iso=now_iso)
        continue
    if (now_monotonic - stamped) >= SOLAR_STOP_SUPPRESSION_MAX_S:
        discharge(evse_id, reason="timeout", now_monotonic=now_monotonic,
                  now_iso=now_iso)
```

`discharge(evse_id, reason, ...)` removes from `_solar_follow_suppressed`, extends
the ledger row with `discharged_reason`, `discharged_stamped_monotonic`,
`discharged_stamped_iso`, and INFO-logs. The claim leg then re-evaluates against
fresh state; if conditions still hold, a fresh session claims the bay. The
oscillator does not fire because the STATE has meaningfully changed (either a
physical replug event or a bounded-time re-try window).

**Purpose.** Backstops the `no_draw_for_n` and `finished_full_current_zero` cases
in the pathological universe where the operator never replugs. Two hours is long
enough to avoid the oscillator in practice — a finished car will taper to 100% and
NOT accept meaningful charge for hours — and short enough that a truly
idle-but-plugged car gets one honest re-attempt per solar afternoon.

**Backstop is rung-3 tunable** (§7). If operator observation shows it retries too
aggressively, they can raise it without a code change.

### 5.4 — RESTART BEHAVIOR

`_solar_follow_suppressed` is `persistence_kind="none"` (§D1). On boot:

- the set is empty;
- the ledger + no-draw + session-start aux dicts are all empty;
- the claim leg re-evaluates whole-house conditions and, if met, claims the bay
  (also seeding `_solar_follow_session_start_ms[evse_id] = now_monotonic`);
- if the car is still full or still unplugged, the FRESH tick's stop scan will
  IMMEDIATELY re-suppress on the same reason with a fresh timestamp — GATED by
  `SOLAR_MIN_ON_S` (so the very first post-boot tick may not stop; the second
  will).

**The AUDIT §1.1 diagnosis (whole-house-only exits) is what this restart flow
inherits.** Nothing about restart depends on the suppressed set surviving; the
whole-house predicate + the fresh stop scan converge on the same steady state
within `SOLAR_STOP_FINISHED_S` / `SOLAR_STOP_NO_DRAW_S` of boot.

The observable cost of not persisting: one `switch.turn_on` + one `switch.turn_off`
per restart per finished/unplugged bay. Bounded (2 bays), cheap (Emporia tolerates),
and preferable to persisting (would strand a bay legitimately unplugged and
replugged during the outage).

### 5.5 — Probe-first requirement (measure-before-build)

BEFORE build dispatch, run a ~15-line recorder probe against the live HA instance
to enumerate the distinct values of the `status` attribute observed on
`switch.garage_a_evse_...` and `switch.garage_b_evse_...` over the last 30 days.
Output goes in `docs/planning/AUDIT_evse_status_tokens_probe.md` and directly
populates `SOLAR_STOP_STATUS_UNPLUGGED` / `SOLAR_STOP_STATUS_CONNECTED` in
`energy_const.py`. The probe MUST also verify the two frozensets are disjoint
(§5.0). A build that hard-codes tokens without the probe is a process violation.

### 5.6 — Enumeration of the FIVE discard sites (must-fix C13 tail)

Every place `_excess_solar_active.discard` is called under this cycle's control
flow, plus the one intra-controller housekeeping site:

| # | Site | Purpose |
|---|---|---|
| 1 | `energy_pool.py:1372` | Peak-drop discard (whole-house). Unchanged. |
| 2 | `energy_pool.py:1567` | Blind-window DROP-leg discard. Unchanged. |
| 3 | `energy_pool.py:1702` | Whole-house `not conditions_met` tail discard. Unchanged. |
| 4 | D3 stop scan (new, at `:~1703` before return) | Per-EVSE stop discard, ATOMIC with `.add(_solar_follow_suppressed)` and ledger row. |
| 5 | `energy_pool.py:790-794` (prune set pass, registry-driven) | EVSE removed from `self._evse` — housekeeping. |

Sites 1-3 do NOT add to `_solar_follow_suppressed`; they end sessions on whole-
house conditions, which is a legitimate "conditions have changed" event. Site 4
is the ONLY site that populates `_solar_follow_suppressed`. Site 5 is registry-
driven and applies uniformly to both `_excess_solar_active` and (via D1)
`_solar_follow_suppressed`.

---

## 6. Boot / restart behaviour (summary)

Summarised for the reviewer's convenience (bodies in §5.4):

- `_solar_follow_suppressed` restores empty (RAM-only, `persistence_kind="none"`).
- `_stop_reason_ledger`, `_solar_follow_no_draw_since`,
  `_solar_follow_session_start_ms` restore empty (RAM-only, aux dicts).
- The first tick after boot seeds `_solar_follow_no_draw_since` for any EVSE
  currently in `_excess_solar_active` with `charging is False`, and seeds
  `_solar_follow_session_start_ms` for any EVSE restored to `_excess_solar_active`
  by `energy.py:1467-8`.
- The first tick's whole-house predicate + stop scan will re-populate suppression
  on any finished/unplugged bay within `SOLAR_STOP_FINISHED_S` /
  `SOLAR_STOP_NO_DRAW_S` (gated by `SOLAR_MIN_ON_S`) — bounded, one
  `switch.turn_on/turn_off` blip per bay per restart.

---

## 7. Knobs — numbers get knobs (placement ladder)

Every new number lives in `energy_const.py`, with rung placement per CLAUDE.md:

| Constant | Rung | Default | Why THIS rung |
|---|---|---|---|
| `SOLAR_STOP_NO_DRAW_S` | 3 (Number entity) | 300 | Operator legitimately tunes by observation of the stop-reason ledger; "how long a car can hesitate before we call it done." Persisted via the existing Number-persistence machinery. |
| `SOLAR_STOP_FINISHED_S` | 3 (Number entity) | 120 | Same — distinguishes "car fell off charge for a moment" from "car is at 100%, taper done." |
| `SOLAR_STOP_SUPPRESSION_MAX_S` | 3 (Number entity) | 7200 | Backstop retry interval — the pure operator observation knob. |
| `SOLAR_MIN_ON_S` | 3 (Number entity) | 60 | Minimum session age before any stop can fire (must-fix B6/C8). Prevents the same-tick claim→stop pathology that would break the J1772 handshake (a newly plugged car may take 5-10s to start drawing; if we stop it before it draws, the plug session is lost). |
| `SOLAR_STOP_FINISHED_POWER_W` | 1 (module constant) | 50 | Safety/protocol floor: a car pulling ≥50 W is not finished. Changing it should require code review — hence rung 1. |
| `SOLAR_STOP_STATUS_UNPLUGGED` | 1 (module constant) | `frozenset` from §5.5 probe | Integration-defined string set; a wrong value silently breaks the discharge. Change requires review. |
| `SOLAR_STOP_STATUS_CONNECTED` | 1 (module constant) | `frozenset` from §5.5 probe | Same. |

**Naming drift fixed (must-fix): every occurrence uses the `SOLAR_STOP_*` prefix.**
The prior plan used bare `FINISHED_POWER_W` in the §5.0 table — corrected to
`SOLAR_STOP_FINISHED_POWER_W` throughout. The `SOLAR_FOLLOW_*` naming from the
amp-modulation plan is deliberately NOT reused here (`SOLAR_STOP_*` names disambiguate
stop-side knobs from amp-side knobs; the `_solar_follow_suppressed` set name uses
"follow" because it is a follow-controller-adjacent primitive).

**Kill switches.** `SOLAR_STOP_NO_DRAW_S = 0` OR `SOLAR_STOP_FINISHED_S = 0`
disables the corresponding stop reason (guard: `if S > 0`).
`SOLAR_STOP_SUPPRESSION_MAX_S = 0` means "never backstop" — documented on the
Number entity's help text. `SOLAR_MIN_ON_S = 0` disables the minimum-on-time guard.
Setting all four to 0 reduces this cycle to a no-op (behaviour equal to today)
except for the D2 gate (which is a no-op when `_solar_follow_suppressed` never
gains a member).

**Number entity wiring.** Mirror `set_offpeak_drain` (`energy.py:8645`) — setter on
`EnergyCoordinator` that assigns onto the `EVChargerController`. Persisted via the
Number-persistence machinery already used by other rung-3 knobs; no new persistence
code, no config-flow change.

---

## 8. Acceptance criteria — DISCRIMINATING

Per CLAUDE.md: every acceptance observation must look DIFFERENT under the fix vs
under a plausible alternative failure.

### The invariants

- **Verify (INV-STOP-1):** T1 (§D7).
- **Verify (INV-STOP-2):** T3.
- **Verify (INV-STOP-3):** T7 + T8.
- **Verify (INV-STOP-5):** T2 + T3 (idempotence-in-name: same-tick repeated stop
  scan on a suppressed bay produces zero additional actions and no ledger
  rewrite).
- **Verify (INV-STOP-6):** the non-perturbation section below (hunk-level).
- **Verify (INV-STOP-7):** T11.

### Stop-reason discrimination

- **Verify (unplugged vs finished):** T4 + T5.
- **Verify (still charging):** with `status="charging"`, `power=8000`,
  `charging=True`, `power_source="sensor"`, NO stop fires; ledger is empty;
  suppressed set is empty; the bay stays in `_excess_solar_active` indefinitely.
  This is the negative case the original bug ALSO handled correctly — asserting it
  here proves we did not regress the "session runs" path.
- **Verify (STALE_POWER guard):** T14.
- **Verify (SOLAR_MIN_ON_S):** T13.

### Discharge discrimination

- **Verify (replug edge, not level):** T9.
- **Verify (no phantom discharge on no-draw case):** seed suppressed with
  `reason="no_draw_for_n"`, hold `charging=False`, advance clock 30 min. NO
  discharge. Only replug (§5.1 edge) or timeout (§5.3) can clear a no-draw
  suppression.
- **Verify (missing-stamp discharge):** T8.

### Non-perturbation — hunk-level, not line-range (must-fix B8/C10)

**Prior plan used a hard-coded line-range `git diff HEAD~1 -- energy_pool.py` on
`:1358-1377`, `:1400-1575`, `:1688-1702`. That is broken two ways:**
(a) `HEAD~1` is the cycle's own previous commit, not the merge-base into `develop`;
(b) inserting D3 shifts every line number AFTER the insertion point, so the
range `:1688-1702` no longer denotes the tail discard loop after the build lands.

**Corrected assertion.** In a merge-base diff (`git diff $(git merge-base HEAD
origin/develop)..HEAD -- energy_pool.py`), the ONLY functional hunks touching
`determine_excess_solar_actions` are:

1. Two-line D2 gate inserted between the "already ours" check and the
   `_stronger_peer_holds` check (the enclosing method is
   `determine_excess_solar_actions`; the anchor is the exact `if evse_id in
   self._excess_solar_active: continue` line).
2. One-line stop-scan invocation appended immediately before each `return actions`
   at the tail (`:1704`) — one hunk in the `conditions_met` branch, one in the
   `else` branch. Both hunks are `actions.extend(self._evaluate_solar_follow_stops(
   now_monotonic, now_iso))` shape.
3. Three `.add` sites in the claim loop (`:1659`, `:1674`, `:1682`) each grow one
   line: `self._solar_follow_session_start_ms[evse_id] = now_monotonic`. These are
   ADDITIVE (do not perturb existing arithmetic).
4. The three `.discard(_excess_solar_active)` sites in the whole-house paths
   (`:1372`, `:1567`, `:1702`) each grow one line:
   `self._solar_follow_session_start_ms.pop(evse_id, None)`. ADDITIVE.

**No other hunks in `determine_excess_solar_actions`.** The peak-drop loop
(`:1358-1377`), blind-window CONTINUE (`:1400-1533`), blind-window DROP
(`:1534-1575`), the whole-house predicate (`:1577-1582`), and the claim-loop
peer-guard branches are byte-identical modulo the additive lines named above.

**SolarFollowController hunks (D2a):** at exactly three sites (`:3889`, `:4077`,
`:4304`), a single membership check is EXTENDED with `or evse_id in
self._ev._solar_follow_suppressed`. Amp arithmetic, write shapes, and control
flow otherwise byte-identical.

### Golden diff — row-by-row justification (must-fix B8/C10)

The `owner_registry_v1.jsonl.gz` golden IS the byte-identity oracle for the owner
registry. D1 regenerates it. **Cycle-close diff MUST be a row-by-row comparison of
the regenerated golden against the pre-cycle golden.** Expected diff:

| Change | Justified by |
|---|---|
| Header note appended | `energy_pool_owners.py:36-42` precedent (load_shed cycle regenerated with note). |
| NEW row: `solar_follow_suppressed` | D1. |
| NEW row: `stop_reason_ledger` (aux dict) | D1. |
| NEW row: `solar_follow_no_draw_since` (aux dict) | D1. |
| NEW row: `solar_follow_session_start_ms` (aux dict) | D1. |
| No changes to the 12 existing owner rows | INV-STOP-6 (registry shape byte-identical for existing owners). |

Any row-diff outside the four NEW rows + header is a HIGH — the load_shed
precedent modified ONE row; this cycle modifies ZERO existing rows.

### Live (post-deploy validation, recorded back into the README)

- **Live:** in the recorder history for the `switch.garage_*` entities, after a
  session ends by a per-EVSE stop, the `on → off` transition appears exactly ONCE
  within one tick of the stop and the switch stays off for at least
  `SOLAR_STOP_SUPPRESSION_MAX_S`. Under an oscillator: multiple `on/off` cycles
  within minutes.
- **Live:** `sensor.ura_energy_coordinator_ev_charging_status` attribute
  `solar_follow_stop_ledger` shows at least one entry within 48 h of first
  finished-car event, with a discriminating `reason`.
- **Live:** across at least one deliberate unplug event, the ledger shows
  `discharged_reason="replug"` within one tick of the replug (timestamp diff
  < 90 s), AND `discharged_reason="replug"` fires ONLY on an unplug→replug edge
  (not on a status flap within the CONNECTED family).
- **Live:** during a genuine long charge session on `garage_a`, the sensor
  attribute `excess_solar_evses` continues to include `garage_a` (no false stop);
  the ledger has no rows for `garage_a`.

---

## 9. Observability

**No new entity.** Extend `sensor.ura_energy_coordinator_ev_charging_status` with
two attributes:

| Attribute | Value | Why |
|---|---|---|
| `solar_follow_suppressed` | `sorted(list(self._ev._solar_follow_suppressed))` | The membership itself — required to diagnose why a claim did not fire. |
| `solar_follow_stop_ledger` | `dict(self._ev._stop_reason_ledger)` (bounded, RAM-only) | The evidence trail the card wants to make behavior evidence-tunable. Shows `reason`, `stamped_monotonic`, `stamped_iso`, `power_at_stop`, `status_at_stop`, `power_source_at_stop`, and after discharge, `discharged_reason` + `discharged_stamped_iso` + `discharged_stamped_monotonic`. |

**Classifier-row trade-off documented (§1a row 9).** A suppressed bay classifies as
`"off"` — the reason is discoverable via `solar_follow_stop_ledger`, not via the
per-EVSE `energy_status` token. This is intentional (adding a suppressed classifier
row would re-couple the very consumer set discard-and-move separates).

Both attributes are populated by the same one-shot read pattern used by the 23
existing attributes on that sensor. Read-only, no dispatch, no coordination.

---

## 10. Tier, review, and process

**Tier 3.** Per CLAUDE.md Tier 3 protocol: FOUR framing-disjoint code reviews after
build. Framings:

- **A — local correctness:** the stop scan; the stop-reason resolver order; the
  ledger row shape; the kill-switch guards; the status-token frozenset equality
  and disjointness; the SOLAR_MIN_ON_S seed/pop lifecycle; the STALE_POWER guard.
- **B — integration / state-machine integrity:** the claim-leg gate ordering
  (below "already ours", above `_stronger_peer_holds`); the ordering of the stop
  scan across the FOUR return legs of `determine_excess_solar_actions` (peak/
  blind-CONTINUE/blind-DROP/tail); INV-STOP-6 byte-identity of the four whole-
  house paths + INV-STOP-7 stop-precedes-restore for the amp controller;
  restart re-population; the DP-yield leg (`:1624-1634`) still fires when
  appropriate (verify a DP-yielded EVSE that reaches
  `finished_full_current_zero` follows the stop path cleanly and does not
  strand DP ownership).
- **C — test authority via REAL per-site source mutation** (§D7 T1..T14); one
  mutation at a time; every mutation MUST bite a specific test. Mutation drills
  restored + status-checked per "unrestored drill" rule.
- **D — adversarial completeness, diff-blind, over the full invariant surface,
  including pre-existing code.** State INV-STOP-1 up-front. Break it. Enumerate
  every write to `_excess_solar_active` in the entire tree — including
  `energy.py:1467-8` (correcting the prior plan's blind spot) and future paths not
  yet written — and prove none of them can add a bay currently in
  `_solar_follow_suppressed`. Specifically re-enumerate the four whole-house legs
  (`:1360-1377`, `:1400-1575`, `:1584-1687`, `:1688-1702`) plus D2's new gate and
  confirm the suppressed-set check is present on every path that could add. Also
  re-enumerate every read of `_excess_solar_active` against §1a — any consumer
  whose behavior under discard-and-move is not in that table is a HIGH.

**Two framing-disjoint PLAN reviews before build** (CLAUDE.md Tier 3):

- **Plan Review 1 — completeness:** independently re-enumerate every write AND
  every read of `_excess_solar_active` and every read of the switch `status`
  attribute; verify the §1a consumer table is complete; verify the discharge model
  closes every stop reason; verify the probe (§5.5) is scheduled BEFORE build;
  verify §5.6 lists the correct discard sites (five).
- **Plan Review 2 — adversarial build-prediction:** "what will the builder get
  wrong reading this?" Ambiguity in gate ordering, in the two-token FROZEN sets,
  in the ledger shape, in the ordering of the stop scan vs the whole-house legs,
  in the STALE_POWER guard site, in the SOLAR_MIN_ON_S seed/pop, in the D2a
  amp-controller augmentation — any of these becomes a HIGH.

**Orchestrator independent verification before ship:** personally re-grep every
write to `_excess_solar_active` (including cross-module writer at `energy.py:1467-8`),
re-run a real source mutation on the D2 gate (delete it, confirm T1 fails on live
production code), and separately on the D2a suppressed-skip (confirm T11 fails
on live production code), restore.

**Operator checkpoint BEFORE deploy** (Tier 3 mandate).

**Cycle close checklist:**
- [ ] §5.5 probe committed as `docs/planning/AUDIT_evse_status_tokens_probe.md`,
      with the frozensets disjoint.
- [ ] `owner_registry_v1.jsonl.gz` golden regenerated with the header note; the
      row-by-row diff matches §8 golden-diff table exactly.
- [ ] `determine_excess_solar_actions` hunks match §8 non-perturbation list; no
      other hunks.
- [ ] SolarFollowController hunks (D2a) at `:3889`, `:4077`, `:4304` are the
      only amp-controller changes; amp arithmetic byte-identical.
- [ ] `_stronger_peer_holds` behaviour unchanged on every existing owner.
- [ ] All §D7 mutation drills (T1..T14) bite; tree clean after each.
- [ ] `_stop_reason_ledger`, `_solar_follow_no_draw_since`,
      `_solar_follow_session_start_ms` prune correctly under an EVSE removal
      config change.
- [ ] `_proactive_offpeak_holds` cleared on stop (T10).
- [ ] README carries a post-restart `Validated <date>` table populated from live.

---

## Summary of what this plan is and is not

**Is:** a single new owner-set declaration + three aux-dict declarations + a
two-line gate at the claim leg + additive suppressed-skip checks at three
SolarFollowController read sites + a per-tick stop scan with a bounded reason
ledger + a three-event discharge model (edge-triggered replug, timeout backstop,
restart) + a probe-verified status-token mapping + a session-start seed to guard
SOLAR_MIN_ON_S. The oscillator is prevented by construction (D2), the stop is
made safe by construction (STALE_POWER + SOLAR_MIN_ON_S + edge-triggered replug),
and the amp controller is barred from writing to a stopped bay (D2a, INV-STOP-7).

**Is not:** amp modulation arithmetic changes, whole-house condition changes,
peer-precedence changes, cross-cycle coordination with DP, a persisted latch
across restart, J1772 SoC decoding, the SOC-hysteresis pair change (deferred to
`EVSE-SOLAR-SOC-HYSTERESIS-1`), or a classifier row for suppressed bays.
