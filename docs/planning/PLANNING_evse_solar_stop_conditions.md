# PLANNING — EVSE solar-session per-car stop conditions (suppressed-membership)

**Card:** `EVSE-SOLAR-STOP-CONDITIONS-1`
**Status:** draft, awaiting plan review (Tier 3 — TWO framing-disjoint plan reviews before build).
**Tier:** **3.** Threads a value (suppressed-membership) through a peer-precedence claim leg
that owns physical `switch.turn_on/off` calls to EV chargers; a single missed site is either
a re-claim oscillator (kills the feature) or a stuck-off session (kills the car). Cost-and-
safety impacting; the founding problem IS a state-machine seam.
**Depends on / does NOT re-open:** `PLANNING_evse_solar_follow_amps.md` (D1 amp modulation).
This cycle owns SESSION START/STOP; amp modulation stays byte-identical.
**Companion / precedes:** none. Ships after D1 amp modulation on the same claim leg.

---

## 0. Problem

The excess-solar path in `EVChargerController.determine_excess_solar_actions`
(`energy_pool.py:1321-1704`) ends a session only on WHOLE-HOUSE conditions:

- `tou_period == "peak"` (peak-time drop),
- `not conditions_met` — SOC `< 95` OR remaining forecast `< 5 kWh` (`:1577-1582`),
- blind-window DROP leg (`:1534-1575`).

There is **no per-car stop.** A car that finishes at 2 pm on a sunny day, or is unplugged and
driven off, leaves URA claiming the charger for hours. The switch stays `on`, the car is
either full (drawing ~0) or absent (drawing 0), and the whole-house predicate cannot see it.

## 0a. Why this is not a "just add an early return"

**Founding problem (the reason this was split from `PLANNING_evse_solar_follow_amps.md`).**
A naive per-EVSE stop sited ABOVE the claim leg is an **oscillator**: the stop discards the
EVSE from `_excess_solar_active` and issues `switch.turn_off`; on the very next tick the
claim leg (`:1577-1687`) re-tests the whole-house predicate, finds it still True, and
re-claims the same EVSE. `switch.turn_on` fires. The car — full, or gone — is turned back on.
On the tick after that the stop fires again. The claim leg does not read "we already tried
to stop this bay"; it only reads global surplus and per-EVSE peer holds.

Two rejected resolutions and why:
1. **Claim-leg cooldown** ("don't re-claim within N minutes"). Adds a hidden time seam to a
   set that has never had one, breaks the CLAIM-ON-EDGE contract every peer relies on (a
   drain-cleared EVSE would fail to re-claim until the cooldown elapsed), and does not solve
   the finished-car case in principle — it just extends the oscillator period.
2. **No per-EVSE stops** ("only whole-house stops, accept the waste"). Ships the defect.

## 0b. Chosen resolution — SUPPRESSED-MEMBERSHIP

Mirror the existing owner-set primitive. Introduce a new declared owner set,
`_solar_follow_suppressed`, and add ONE gate at the top of the claim loop:

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

The stop path (§4) discards from `_excess_solar_active`, ADDS to
`_solar_follow_suppressed`, and issues `switch.turn_off`. On the next tick the claim leg
sees the EVSE in the suppressed set and SKIPS it — no re-claim, no oscillator. The
suppression is discharged (§5) by a bounded set of events, each of which is what the
operator would call "conditions have meaningfully changed since we stopped."

This is architecturally the same shape as `_paused_by_dp`: a set consulted inline by the
claim leg to skip an EVSE that a sibling policy has spoken for. It is NOT a peer-hold
(§3 explains why not).

---

## 1. Institutional context verified

Greps and reads performed for this plan. Every ADD is justified against what exists.

### Claim leg + membership
- `EVChargerController.determine_excess_solar_actions` — `energy_pool.py:1321-1704`.
  Whole-house predicate at `:1577-1582`; claim loop `:1591-1687`; stop loop `:1688-1702`.
  Every actionable branch reads or writes `self._excess_solar_active`. No other module
  writes this set (verified: `grep -rn "_excess_solar_active" custom_components/` — reads
  in `energy.py`, writes only inside `EVChargerController`).
- `_stronger_peer_holds` — `energy_pool.py:383-412`. Enumerates
  `EV_REGISTRY.iter_peer_holds()` (6 owners today). The new suppressed set is deliberately
  **NOT** a peer-hold — see §3 INV-STOP-4.
- `_get_evse_state` — `energy_pool.py:653-710`. Returns dict keyed
  `is_on`, `power`, `status`, `charging`, `power_source`. `status` comes from
  `switch_state.attributes.get("status", "unknown")` (`:691`) — this is the string we key
  the UNPLUGGED discharge on (§5.1). `charging = power > EVSE_CHARGING_POWER_THRESHOLD`
  (100 W) at `:695` — this is what we key the FINISHED discharge on (§5.2).

### Owner registry (the pattern to REUSE)
- `energy_pool_owners.py:100-157` — `OwnerDeclaration` dataclass; `attr` refs the
  controller-instance owner set; `kind="set"` participates in the prune sets pass
  (`iter_prune_sets`, `:185-190`); `peer_holds_member` gates inclusion in
  `_stronger_peer_holds`; `persistence_kind="list"` opts into registry-driven KV
  save/restore (`iter_persisted_lists`, `:203-207`).
- `EV_DECLARATIONS` — `:231-370`. 12 owners + 8 auxiliary dicts. The rows this cycle
  models against: `dp` (`:274-283`, intent-state, `peer_holds_member=False`, consulted
  inline; classifier_priority=5) and `load_shed` (`:295-304`, RAM-only,
  `persistence_kind="none"`).
- **BEHAVIOR-FROZEN header** (`:20-24`) is asserted against the golden at
  `quality/tests/golden/owner_registry_v1.jsonl.gz`. Adding an `OwnerDeclaration` row
  **regenerates the golden with a named header note**, precedent set by the Tier-1
  load_shed prune-quirk fix (`:36-42`: "The golden was regenerated with a header note
  naming this cycle"). This is the endorsed path, not a violation. The regenerate step is
  a deliverable (§7 D2).

### Persistence precedent
- `_KNOWN_HOOKS` / `iter_persisted_lists` — the sorted-list KV save/restore path used by
  the 6 `persistence_kind="list"` owners. Because this cycle wants restore to be a HARD
  DROP (§6), and not to reinstall a `switch.turn_off` on boot, `_solar_follow_suppressed`
  is declared **`persistence_kind="none"`** — mirrors `load_shed` (`:298-300`). Boot
  behaviour is spelled out in §6.

### Config surface
- `CONF_ENERGY_*` — enumerated via `ura-config-and-flags`. No existing knob names
  "solar-follow stop" or "EVSE idle timeout" — every knob in §7 D5 is **NEW because no
  equivalent found** after grepping `energy_const.py` for `SOLAR_*`, `EVSE_*`, `STOP_*`,
  `NO_DRAW_*`, `IDLE_*`.

### Docs consulted
- `docs/planning/PLANNING_evse_solar_follow_amps.md` — full read. This cycle inherits
  its scope fence: modulation and stop are DISJOINT surfaces, share no code path except
  the claim leg's inline gate list. D1 amp modulation writes `current_limit`; this cycle
  writes `switch` + owner-set membership.
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` — precedence table for the claim leg.
  Suppressed-membership is NOT a precedence row; it is a same-owner "we already stopped
  this bay" latch (§3 INV-STOP-4).

### Session pickup
- Memory `project_session_pickup_2026_08_24.md` — this plan is one of the two build-
  ready plans awaiting operator go; the other is D1 amp modulation, which ships first.

---

## 2. Non-goals

1. NOT amp modulation. D1 (`PLANNING_evse_solar_follow_amps.md`) owns it. This plan
   changes NO amp value and reads no grid entity.
2. NOT changing the whole-house end conditions (SOC, remaining forecast, peak, blind-
   window DROP leg). All existing exit paths are byte-identical.
3. NOT changing peer precedence. `_solar_follow_suppressed` is not added to
   `iter_peer_holds()`.
4. NOT persisting the suppressed set across restart (§6). A restart is a legitimate
   "conditions have changed" event; the claim leg will re-evaluate against fresh state.
5. NOT reading car SoC or decoding J1772 pilot. Stop reasons are keyed off the two
   channels already parsed by `_get_evse_state` (`status`, `power`).
6. NOT modifying `_get_evse_state`.
7. NOT deleting the whole-house stop loop (`:1688-1702`). The two paths coexist; §7 D3
   spells out ordering.

---

## 3. Falsifiable invariants

**INV-STOP-1 (the core no-oscillator invariant — Tier-3 falsifiable form).**
> Under any legal grid + peer + SOC configuration, an EVSE that has been
> discharged from `_excess_solar_active` into `_solar_follow_suppressed` in tick `T`
> is NOT re-added to `_excess_solar_active` by `determine_excess_solar_actions` in
> any tick `T+k` (`k ≥ 1`) until its suppression is discharged by one of the events
> enumerated in §5.

**Falsified by:** any observed transition `evse_id ∈ _solar_follow_suppressed` →
`evse_id ∈ _excess_solar_active` on a tick where none of the §5 discharge conditions
fired. Reviewer D's job is to break this by combining knobs (`conditions_met` True,
peer set empty, suppressed set carrying `garage_a`) and asserting a claim never issues.

**INV-STOP-2 (discharge covers every stop reason).** Every stop path that adds an
EVSE to `_solar_follow_suppressed` names ONE `stop_reason` from the enumerated set
(§5.0). No stop is issued without a reason recorded in `_stop_reason_ledger`.

**INV-STOP-3 (bounded suppression — no permanent stuck-off).** For every EVSE ever
added to `_solar_follow_suppressed`, at least one discharge condition will fire
within a bounded horizon: (a) a replug edge, (b) the timeout backstop
`SOLAR_STOP_SUPPRESSION_MAX_S` (§5.3), or (c) restart (§6). No code path adds to the
set without at least one of (a)/(b)/(c) being reachable.

**INV-STOP-4 (suppression is not a peer-hold, and never blocks a peer).** No sibling
owner (drain, grid_cap, arbitrage, fill_priority, blind_window, load_shed, TOU) reads
`_solar_follow_suppressed`. Adding an EVSE to it does NOT prevent drain-precedence
from pausing it, does NOT prevent load-shed from pausing it, does NOT prevent a
future excess-solar RECLAIM once discharged. **Peer holds continue to operate exactly
as they do today.** Consequence: `_solar_follow_suppressed` is declared with
`peer_holds_member=False` and does NOT appear in `iter_peer_holds()`. This is the
DP-row shape, not the drain-row shape.

**INV-STOP-5 (idempotence at the stop path).** Re-entering the stop path on an EVSE
already in `_solar_follow_suppressed` is a no-op: no additional `switch.turn_off`,
no ledger row, no timer reset. The stop is edge-triggered on `evse_id ∈
_excess_solar_active AND stop_condition_true` — leaving the ACTIVE set is the edge.

**INV-STOP-6 (byte-identical whole-house paths).** The peak drop (`:1358-1377`), the
blind-window CONTINUE / DROP legs (`:1400-1575`), and the whole-house stop loop
(`:1688-1702`) are unchanged by this cycle. Their `git diff` is empty except for the
addition of the two-line suppressed-membership gate at the top of the claim loop
(§0b) and the suppressed-set discard at the discharge sites (§5).

---

## 4. Deliverables

### D1 — Declare the suppressed set (owner registry)

**Site:** `energy_pool_owners.py`, EV_DECLARATIONS block (`:231-370`), appended AFTER
the `blind_window_liveness_ride` row (`:334-342`) and BEFORE the auxiliary dict rows.

```python
# Row 12: Solar-follow per-EVSE suppression (v<next>).
# Not a peer-hold and not a pause owner — a same-owner "we already
# stopped this bay this session" latch consulted inline by the
# excess-solar claim leg. Discharged by replug, no-draw-for-N,
# or a timeout backstop (see PLANNING_evse_solar_stop_conditions.md).
# RAM-only: restart is a legitimate discharge event.
OwnerDeclaration(
    name="solar_follow_suppressed",
    attr="_solar_follow_suppressed", tier="evse", kind="set",
    precedence_row=None,             # not a precedence row (§3 INV-STOP-4)
    persistence_key=None,
    persistence_kind="none",         # §6 boot behavior
    peer_holds_member=False,         # §3 INV-STOP-4
    dispatch_tag=None,               # not a pause dispatcher
    prune_participant=True,          # participates in _prune_removed_evses set pass
    # No explicit classifier branch: an EVSE in this set that is not
    # in _excess_solar_active is CHARGING-STOPPED, not URA-paused;
    # falls through to the charging/idle/off classifier tail.
),
```

**Golden regen.** The `owner_registry_v1.jsonl.gz` golden is regenerated with a
header note: `"Tier-3 cycle: EVSE-SOLAR-STOP-CONDITIONS-1 — add
solar_follow_suppressed owner row"`. Precedent: the Tier-1 load_shed prune fix note
(`energy_pool_owners.py:36-42`). The regen script + the mutation-matrix update are
part of D1 (not a separate deliverable), matching how load_shed was handled.

**Controller-instance init.** In `EVChargerController.__init__`, initialise
`self._solar_follow_suppressed: set[str] = set()`. Location: alongside
`self._excess_solar_active` (grep-verified single-site init).

### D2 — Add the claim-leg gate (single-line effective change)

**Site:** `energy_pool.py`, inside the claim `for evse_id, config in self._evse.items()`
loop at `:1591`, immediately AFTER the `if evse_id in self._excess_solar_active: continue`
check at `:1595-1596`, BEFORE the `_stronger_peer_holds` check at `:1602`.

```python
if evse_id in self._excess_solar_active:
    continue  # Already on by us
if evse_id in self._solar_follow_suppressed:                          # NEW
    _LOGGER.debug(                                                    # NEW
        "Excess solar: %s in solar_follow_suppressed — skipping "     # NEW
        "(reason=%s, since=%s); discharge on replug / no-draw / timeout",  # NEW
        evse_id,                                                      # NEW
        self._stop_reason_ledger.get(evse_id, {}).get("reason", "?"), # NEW
        self._stop_reason_ledger.get(evse_id, {}).get("stamped", "?"),# NEW
    )                                                                 # NEW
    continue                                                          # NEW
if self._stronger_peer_holds(evse_id):
    ...
```

**Ordering matters.** The suppressed gate is BELOW the "already ours" check (so an
active bay is not accidentally re-suppressed by a diagnostic race) and ABOVE the peer
guard (so we do not waste a peer read on a bay we would have skipped anyway; also
guarantees the reviewer's completeness check has a single gate site).

### D3 — Add the per-tick stop-condition scan

**Site:** new method `_evaluate_solar_follow_stops(self) -> list[dict[str, Any]]`
on `EVChargerController`. Called from `determine_excess_solar_actions` **AFTER** the
whole-house peak / blind-window / `conditions_met` legs run their existing loops and
BEFORE the method returns. This ordering guarantees:

- if the whole-house path already dropped the EVSE (`_excess_solar_active.discard`
  in `:1360-1377`, `:1567`, `:1702`), the per-EVSE stop scan sees an empty set for
  those bays and no-ops for them (INV-STOP-5);
- suppression is added only for bays STILL in `_excess_solar_active` after the
  whole-house path, i.e. cases the whole-house path did not already handle. This is
  exactly the surface the card names.

**Body (specification, not code):**

```
for evse_id in list(self._excess_solar_active):
    reason = self._solar_follow_stop_reason(evse_id, now_monotonic)
    if reason is None:
        continue
    config = self._evse.get(evse_id, {})
    switch_entity = config.get("switch", "")
    st = self._get_evse_state(evse_id)
    if switch_entity and st["is_on"]:
        actions.append({"service": "switch.turn_off",
                        "target": switch_entity, "data": {}})
    self._excess_solar_active.discard(evse_id)
    self._solar_follow_suppressed.add(evse_id)
    self._stop_reason_ledger[evse_id] = {
        "reason": reason, "stamped": now_iso,
        "power_at_stop": st["power"], "status_at_stop": st["status"],
    }
    _LOGGER.info(
        "excess solar: per-EVSE stop for %s (reason=%s, power=%.0fW, status=%s)",
        evse_id, reason, st["power"], st["status"],
    )
```

`_solar_follow_stop_reason(evse_id, now)` returns one of the tokens in §5.0 or `None`.
The method is small, pure of I/O beyond the one `_get_evse_state` read reused across
all reason checks (single read per bay per tick — do not re-read).

### D4 — Discharge sites (three of them; see §5)

- **Replug discharge (§5.1)** — invoked at the TOP of
  `determine_excess_solar_actions` on every tick, before any other logic, so a
  replug clears suppression BEFORE the claim leg re-evaluates conditions.
- **Timeout discharge (§5.3)** — invoked in the same top-of-tick sweep as the
  replug discharge (they share the loop over `_solar_follow_suppressed`).
- **No-draw discharge is NOT its own discharge event.** No-draw-for-N is a STOP
  cause (§5.2), not a discharge. Discharges are only replug, timeout, and restart
  (§6). This prevents the "no-draw stopped it → still no-draw → re-claim" oscillator.

### D5 — Stop-reason ledger (evidence for tuning)

`self._stop_reason_ledger: dict[str, dict[str, Any]]` on `EVChargerController`.
Keys: `evse_id`; values: `{reason, stamped, power_at_stop, status_at_stop}` and,
after the eventual discharge, extended with `{discharged_reason, discharged_stamped}`.
RAM-only, bounded by the size of `self._evse` (2 today). Read-only surface exposed on
the `ev_charging_status` sensor as `solar_follow_stop_ledger` (§9).

### D6 — Prune + teardown

- Registry-driven prune (`_prune_removed_evses`) already covers `set`-kind
  `prune_participant=True` rows (`iter_prune_sets`, `energy_pool_owners.py:185-190`).
  No new prune code.
- No timers, no `async_call_later` handles. The stop scan is per-tick (called from
  the existing `determine_excess_solar_actions` invocation), so there is no
  outstanding callback to cancel at teardown.

### D7 — Tests + mutation drills

Behavioural, per the §10-style protocol used by the amp-modulation cycle. Tests are
mutation-anchored and DISCRIMINATING (§8) — no test asserts a value that the bug
would also produce.

---

## 5. Discharge model — MANDATORY per "suppression needs a discharge"

**Every event-driven suppression must specify: what CLEARS it, what BACKSTOPS the
clear, and what happens at RESTART.** This section is that specification.

### 5.0 — Stop-reason enumeration

Every add to `_solar_follow_suppressed` records ONE token in `_stop_reason_ledger`:

| Token | Trigger | § |
|---|---|---|
| `unplugged` | `status` transitioned to a `not_connected`-family token | 5.1 |
| `no_draw_for_n` | `charging is False` for `SOLAR_STOP_NO_DRAW_S` (default 300 s) | 5.2 |
| `finished_full_current_zero` | `charging is False` AND `power < FINISHED_POWER_W` AND status is `connected`-family for `SOLAR_STOP_FINISHED_S` (default 120 s) | 5.2 |

`finished_full_current_zero` is the "car at 100%, taper complete, charger connected"
case. Distinguishing it from `no_draw_for_n` is what makes the ledger operator-
tunable — a house that sees mostly `finished_full_current_zero` wants a shorter
`SOLAR_STOP_FINISHED_S`, while one that sees mostly `no_draw_for_n` wants to tune the
generic timeout. Discrimination is worth the extra token.

**Status-token sets (probe-first — see §5.5).** The exact strings Emporia publishes
on the switch's `status` attribute are integration-defined. The plan does NOT hard-
code them; §5.5 mandates a one-shot recorder probe before build to enumerate the
live set and commit the mapping to `energy_const.py` as `SOLAR_STOP_STATUS_UNPLUGGED`
and `SOLAR_STOP_STATUS_CONNECTED` (both `frozenset[str]`). Common members:
`{"not_connected", "disconnected", "unplugged"}` vs `{"connected", "charging",
"awaiting_start"}` — but the probe is authoritative.

### 5.1 — UNPLUGGED (a stop AND a discharge trigger)

**Stop side.** In `_solar_follow_stop_reason`, if
`state["status"].lower() in SOLAR_STOP_STATUS_UNPLUGGED`, return `"unplugged"`.

**Discharge side.** In the top-of-tick discharge sweep, for every
`evse_id ∈ _solar_follow_suppressed`, if
`state["status"].lower() in SOLAR_STOP_STATUS_CONNECTED`, DISCHARGE — remove from
`_solar_follow_suppressed`, extend the ledger with `discharged_reason="replug"`,
INFO-log. The claim leg then re-evaluates against fresh state; if conditions still
hold, a fresh session claims the bay. The oscillator does not fire because the
STATE has meaningfully changed (a physical replug event).

**Why status, not `is_on`.** `is_on` is a URA-controlled shadow of our last
`switch.turn_on/off` call — using it as the discharge witness reintroduces the
oscillator (URA-off → URA reads its own off → asserts unplug → re-claim). `status`
is charger-reported.

### 5.2 — NO-DRAW-FOR-N and FINISHED-FULL-CURRENT-ZERO (stops without discharge)

**Track no-draw streaks.** `self._solar_follow_no_draw_since: dict[str, float]` on
`EVChargerController`, keyed monotonic. On each tick, for every EVSE in
`_excess_solar_active`:

- if `charging` is True, delete the key (draw resumed);
- if `charging` is False, set the key if absent, leave otherwise.

Stop reason resolution (in the order tried):

- if `now - since >= SOLAR_STOP_FINISHED_S` AND `power < FINISHED_POWER_W`
  (default 50 W) AND `status ∈ SOLAR_STOP_STATUS_CONNECTED`, return
  `"finished_full_current_zero"`;
- else if `now - since >= SOLAR_STOP_NO_DRAW_S`, return `"no_draw_for_n"`;
- else return None (keep charging session alive; car may resume).

**Why these two do NOT auto-discharge.** The discharge condition would have to be
"the car started drawing again" — but URA has just turned the switch off. The car
CAN'T draw. Attempting to re-verify by turning the switch back on is exactly the
oscillator. Discharge for these reasons requires either (a) a physical replug (§5.1
detects it) or (b) the timeout backstop (§5.3). This is deliberate and preserves
INV-STOP-1.

### 5.3 — TIMEOUT BACKSTOP (`SOLAR_STOP_SUPPRESSION_MAX_S`)

Default `SOLAR_STOP_SUPPRESSION_MAX_S = 7200` (2 h). In the top-of-tick discharge
sweep, if `now - _stop_reason_ledger[evse_id]["stamped_monotonic"] >=
SOLAR_STOP_SUPPRESSION_MAX_S`, DISCHARGE with `discharged_reason="timeout"`.

**Purpose.** Backstops the `no_draw_for_n` and `finished_full_current_zero` cases in
the pathological universe where the operator never replugs (car is left plugged in
past sundown, sits at 100% overnight, sun rises, we should try again after a while
in case the SoC has drifted down enough that the car will accept charge). Two hours
is long enough to avoid the oscillator in practice — a finished car will taper to
100% and NOT accept meaningful charge for hours — and short enough that a truly
idle-but-plugged car gets one honest re-attempt per solar afternoon.

**Backstop is rung-3 tunable** (§7 D5). If operator observation shows it retries too
aggressively, they can raise it without a code change.

### 5.4 — RESTART BEHAVIOR

`_solar_follow_suppressed` is `persistence_kind="none"` (§D1). On boot:

- the set is empty;
- the claim leg re-evaluates whole-house conditions and, if met, claims the bay;
- if the car is still full or still unplugged, the FRESH tick's stop scan will
  IMMEDIATELY re-suppress on the same reason with a fresh timestamp.

The observable cost of not persisting: one `switch.turn_on` + one `switch.turn_off`
per restart per finished/unplugged bay. This is bounded (2 bays), cheap (Emporia
tolerates), and preferable to the alternatives:

- Persisting the set would strand a bay that was legitimately unplugged and
  replugged during the outage (we would refuse to re-claim on a plugged, ready car
  because we still hold the RAM-stamped suppression). Restart IS a legitimate
  "conditions may have changed" event.
- Persisting only the ledger (not the set) would show operator-visible stop
  history across restart, which is nice-to-have but not required by the card.
  Deferred to a follow-up if the operator asks.

### 5.5 — Probe-first requirement (measure-before-build)

BEFORE build dispatch, run a ~15-line recorder probe against the live HA instance to
enumerate the distinct values of the `status` attribute observed on
`switch.garage_a_evse_...` and `switch.garage_b_evse_...` over the last 30 days.
Output goes in `docs/planning/AUDIT_evse_status_tokens_probe.md` and directly
populates `SOLAR_STOP_STATUS_UNPLUGGED` / `SOLAR_STOP_STATUS_CONNECTED` in
`energy_const.py`. **A build that hard-codes `{"not_connected"}` without the probe
is a process violation** (per "Measure before you build" — trigger fires because
D3's correctness depends on the exact token set the integration emits).

The probe is one-shot, read-only, exits fast, and commits its output. It is not a
runtime feature.

---

## 6. Boot / restart behaviour (summary)

Summarised for the reviewer's convenience (bodies in §5.4):

- `_solar_follow_suppressed` restores empty (RAM-only, `persistence_kind="none"`).
- `_stop_reason_ledger` restores empty.
- `_solar_follow_no_draw_since` restores empty; first tick after boot re-seeds it
  for any EVSE currently in `_excess_solar_active` with `charging is False`.
- The first tick's whole-house predicate + stop scan will re-populate suppression
  on any finished/unplugged bay within `SOLAR_STOP_FINISHED_S` /
  `SOLAR_STOP_NO_DRAW_S` — bounded, one `switch.turn_on/turn_off` blip per bay per
  restart.

---

## 7. Knobs — numbers get knobs (placement ladder)

Every new number lives in `energy_const.py`, with rung placement per CLAUDE.md:

| Constant | Rung | Default | Why THIS rung |
|---|---|---|---|
| `SOLAR_STOP_NO_DRAW_S` | 3 (Number entity) | 300 | Operator legitimately tunes by observation of the stop-reason ledger; "how long a car can hesitate before we call it done." Persisted via the existing Number-persistence machinery. |
| `SOLAR_STOP_FINISHED_S` | 3 (Number entity) | 120 | Same — distinguishes "car fell off charge for a moment" from "car is at 100%, taper done." |
| `SOLAR_STOP_SUPPRESSION_MAX_S` | 3 (Number entity) | 7200 | Backstop retry interval — the pure operator observation knob. |
| `SOLAR_STOP_FINISHED_POWER_W` | 1 (module constant) | 50 | Safety/protocol floor: a car pulling ≥50 W is not finished. Changing it should require code review — hence rung 1, not exposed. |
| `SOLAR_STOP_STATUS_UNPLUGGED` | 1 (module constant) | `frozenset` from §5.5 probe | Integration-defined string set; a wrong value silently breaks the discharge. Change requires review. |
| `SOLAR_STOP_STATUS_CONNECTED` | 1 (module constant) | `frozenset` from §5.5 probe | Same. |

**Kill switch.** `SOLAR_STOP_NO_DRAW_S = 0` OR `SOLAR_STOP_FINISHED_S = 0` disables
the corresponding stop reason (guard: `if S > 0`). `SOLAR_STOP_SUPPRESSION_MAX_S = 0`
means "never backstop" — documented on the Number entity's help text. Setting all
three to 0 reduces this cycle to a no-op (behaviour equal to today).

**Number entity wiring.** Mirror `set_offpeak_drain` (`energy.py:8645`) — setter on
`EnergyCoordinator` that assigns onto the `EVChargerController`. Persisted via the
Number-persistence machinery already used by other rung-3 knobs; no new persistence
code, no config-flow change.

**Every knob is NEW because no equivalent found** after grep of `energy_const.py`,
`config_flow.py`, `options_flow.py`, `number.py`, `select.py`, `switch.py`.

---

## 8. Acceptance criteria — DISCRIMINATING

Per CLAUDE.md: every acceptance observation must look DIFFERENT under the fix vs
under a plausible alternative failure. Where two candidates could produce the same
sensor reading, a second observation is added.

### The invariant

- **Verify (INV-STOP-1):** with `_solar_follow_suppressed = {"garage_a"}` seeded
  and `conditions_met=True`, 10 consecutive `determine_excess_solar_actions` calls
  produce ZERO `switch.turn_on` actions targeting `garage_a`. Under a naive
  early-return stop above the claim leg: 10 `switch.turn_on` actions.
- **Verify (INV-STOP-3):** setting `SOLAR_STOP_SUPPRESSION_MAX_S = 60` and
  advancing the injected clock 61 s discharges `garage_a` and the next tick
  issues ONE `switch.turn_on` (proving the backstop is reachable).

### Stop-reason discrimination

- **Verify (unplugged vs finished):** with `status="not_connected"` and
  `power=0`, the ledger records `"unplugged"`. With `status="connected"`,
  `power=20`, `charging=False` for 121 s, the ledger records
  `"finished_full_current_zero"`. Discriminating: `"no_draw_for_n"` would fire
  earlier only if `SOLAR_STOP_NO_DRAW_S <= 121` — the two defaults (120 finished,
  300 no-draw) guarantee `finished` wins for the connected-power-zero case.
- **Verify (still charging):** with `status="charging"`, `power=8000`,
  `charging=True`, NO stop fires; ledger is empty; suppressed set is empty; the
  bay stays in `_excess_solar_active` indefinitely. This is the negative case the
  original bug ALSO handled correctly — asserting it here proves we did not
  regress the "session runs" path.

### Discharge discrimination

- **Verify (replug discharge):** seed `_solar_follow_suppressed = {"garage_a"}`
  with `reason="finished_full_current_zero"`. Flip `status` to `"connected"`
  (already connected) — no discharge (the transition would be a replug only if
  status came FROM an unplugged token). Flip status through
  `"not_connected" → "connected"` — discharge fires, ledger extended,
  `discharged_reason="replug"`. Discriminating: a naive "any status change
  discharges" implementation would fire on the first observation.
- **Verify (no phantom discharge on no-draw case):** seed suppressed with
  `reason="no_draw_for_n"`, hold `charging=False`, advance clock 30 min. NO
  discharge. Only replug or timeout can clear a no-draw suppression. This is the
  falsification target for the oscillator: if the reviewer can produce a
  discharge here from anything OTHER than the two enumerated events, INV-STOP-1
  is broken.

### Non-perturbation

- **Verify:** `git diff HEAD~1 -- energy_pool.py` in the region
  `:1358-1377`, `:1400-1575`, `:1688-1702` is EMPTY (INV-STOP-6). Grep gate in
  §7-cycle-close.
- **Verify:** `_paused_by_dp`, `_paused_by_grid_cap`, `_paused_by_battery_drain`
  behaviour on `garage_a` is unchanged with `_solar_follow_suppressed` non-empty.
  A stronger-peer-hold path fires as before (INV-STOP-4).

### Live (post-deploy validation, recorded back into the README)

- **Live:** in the recorder history for the `switch.garage_*` entities, after a
  session ends by a per-EVSE stop, the `on → off` transition appears exactly
  ONCE within one tick of the stop and the switch stays off for at least
  `SOLAR_STOP_SUPPRESSION_MAX_S`. Under an oscillator: multiple `on/off` cycles
  within minutes.
- **Live:** `sensor.ura_energy_coordinator_ev_charging_status` attribute
  `solar_follow_stop_ledger` shows at least one entry within 48 h of first
  finished-car event, with a discriminating `reason`.
- **Live:** across at least one deliberate unplug event, the ledger shows
  `discharged_reason="replug"` within one tick of the replug (timestamp diff
  < 90 s).

---

## 9. Observability

**No new entity.** Extend `sensor.ura_energy_coordinator_ev_charging_status` with
two attributes:

| Attribute | Value | Why |
|---|---|---|
| `solar_follow_suppressed` | `sorted(list(self._ev._solar_follow_suppressed))` | The membership itself — required to diagnose why a claim did not fire. |
| `solar_follow_stop_ledger` | `dict(self._ev._stop_reason_ledger)` (bounded, RAM-only) | The evidence trail the card wants to make behavior evidence-tunable. Shows `reason`, `stamped`, `power_at_stop`, `status_at_stop`, and after discharge, `discharged_reason` + `discharged_stamped`. |

Both attributes are populated by the same one-shot read pattern used by the 23
existing attributes on that sensor. Read-only, no dispatch, no coordination.

---

## 10. Tier, review, and process

**Tier 3.** Per CLAUDE.md Tier 3 protocol: FOUR framing-disjoint code reviews after
build. Framings:

- **A — local correctness:** the stop scan; the stop-reason resolver order; the
  ledger row shape; the kill-switch guards; the status-token frozenset equality.
- **B — integration / state-machine integrity:** the claim-leg gate ordering (below
  "already ours", above `_stronger_peer_holds`); no regression of the peak /
  blind-window / whole-house stop paths (INV-STOP-6); the DP-yield leg
  (`:1624-1634`) still fires when appropriate — verify a DP-yielded EVSE that
  reaches `finished_full_current_zero` follows the stop path cleanly and does not
  strand DP ownership; restart re-population.
- **C — test authority via REAL per-site source mutation** (§7 D7); one mutation
  at a time; every mutation MUST bite a specific test.
- **D — adversarial completeness, diff-blind, over the full invariant surface,
  including pre-existing code.** State INV-STOP-1 up-front. Break it. Enumerate
  every write to `_excess_solar_active` in the entire file — including future
  paths not yet written — and prove none of them can add a bay currently in
  `_solar_follow_suppressed`. Specifically re-enumerate the four whole-house
  legs (`:1360-1377`, `:1400-1575`, `:1584-1687`, `:1688-1702`) plus D2's new
  gate and confirm the suppressed-set check is present on every path that could
  add. If a claim can happen via a path D did not check, that is a HIGH.

**Two framing-disjoint PLAN reviews before build** (CLAUDE.md Tier 3):

- **Plan Review 1 — completeness:** independently re-enumerate every write to
  `_excess_solar_active` and every read of the switch `status` attribute; verify
  the discharge model closes every stop reason; verify the probe (§5.5) is
  scheduled BEFORE build.
- **Plan Review 2 — adversarial build-prediction:** "what will the builder get
  wrong reading this?" Ambiguity in gate ordering, in the two-token FROZEN sets,
  in the ledger shape, in the ordering of the stop scan vs the whole-house legs
  — any of these becomes a HIGH.

**Orchestrator independent verification before ship:** personally re-grep every
write to `_excess_solar_active`, re-run a real source mutation on the D2 gate
(delete it, confirm the INV-STOP-1 tests fail on live production code), restore.

**Operator checkpoint BEFORE deploy** (Tier 3 mandate).

**Cycle close checklist:**
- [ ] §5.5 probe committed as `docs/planning/AUDIT_evse_status_tokens_probe.md`.
- [ ] `owner_registry_v1.jsonl.gz` golden regenerated with the header note; the
      old mutation-matrix rows still pass, and the new row for
      `solar_follow_suppressed` is asserted.
- [ ] `determine_excess_solar_actions` legs at `:1358-1377`, `:1400-1575`,
      `:1688-1702` byte-identical (grep-verified).
- [ ] `_stronger_peer_holds` behaviour unchanged on every existing owner.
- [ ] All §7 D7 mutation drills bite; tree clean after each.
- [ ] README carries a post-restart `Validated <date>` table populated from live.

---

## Summary of what this plan is and is not

**Is:** a single new owner-set declaration + a two-line gate at the claim leg +
a per-tick stop scan with a bounded three-reason ledger + a three-event discharge
model (replug, timeout, restart) + a probe-verified status-token mapping. The
oscillator is prevented by construction: the claim leg cannot re-claim a bay it is
told (in the same primitive it consults for every other owner) has been spoken for.

**Is not:** amp modulation, whole-house condition changes, peer-precedence
changes, cross-cycle coordination with DP, a persisted latch across restart, or
J1772 SoC decoding.
