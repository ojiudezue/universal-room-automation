# PLANNING — EVSE/L1 charge-onset time (surgical clause at TWO drain-release sites)

Card: **EVSE-CHARGE-ONSET-TIME-1** (docs/planning/kanban.data.yaml)
Status: PLAN — post-Rev-5 fix-up (soc_recovered split + anchor corrections + strictly-after pin).
Ready for final targeted re-review on the soc_recovered split only.
Priority: HIGH. Ships alongside the EC-maintenance batch.
Recommended tier: **Tier 2-DB** (unchanged).

**Rescope lineage:**
- Rev 1/2 (superseded): AND-gate at the off-peak ensure-on. Too much surface.
- Rev 3 (superseded): single-clause at `EVChargerController:2032`. Missed the L1 mirror.
- Rev 4 (superseded): TWO clauses gating the WHOLE `(battery_out_of_capacity or soc_recovered)` conjunction — would strand daytime-solar charging for ~13h.
- **Rev 5 (this doc):** onset gates ONLY the overnight `battery_out_of_capacity` leg at BOTH sites; `soc_recovered` (daytime-solar release) is left untouched. Anchor citations corrected. `next_occurrence_of_hhmm` pinned strictly-after.

**Fix summary (Rev 5):**
- **HIGH — soc_recovered split.** The prior clause
  `(battery_out_of_capacity or soc_recovered) and (onset_reached or dp_forcing)`
  distributed the onset gate over the daytime-solar release leg
  (`soc_recovered` at `energy_pool.py:1990-2006` / `:3337-3341` is
  documented as "solar refilled the battery, EV can share" — a DAYTIME
  condition). Legal repro: onset `"01:00"`, pause anchored 10:00,
  `soc_recovered=True` at 12:00 → held until 01:00 next day (~13h
  daytime over-hold). This contradicts §4 non-goal #2 (daytime solar
  out of scope) and there is no escape (excess-solar / off-peak paths
  veto on `_paused_by_battery_drain` membership). **Fixed** by
  re-associating: `(battery_out_of_capacity and (onset_reached or
  dp_forcing)) or soc_recovered` at BOTH `:2008` and `:3343`. Onset now
  gates the reserve/overnight leg only.
- **MED (F3b accuracy) — save/restore anchors corrected.** The real
  save side is `_save_evse_state` at `energy.py:1925`, owner iteration
  loop `_save_registry_owner_lists` called at `:1956` (defined
  `:1671-1691`). The restore-side dispatch iterates
  `iter_persisted_lists()` at `:1687` and again at `:1722` inside
  `_restore_registry_owner_lists(:1693)`. The `_KNOWN_HOOKS` literal
  set is at `:1712-1721`. The prior `energy.py:1500/1715-1720/1963-1973`
  citations were wrong (`:1495-1505` is inside `_restore_evse_state`
  itself starting at `:1434`; `:1715-1720` is the hook literal, not
  the dispatch; `:1963-1973` is the blind-window save block inside
  `_save_evse_state`, an inline example — not the general mechanism).
  All corrected in §2.1 and §10.
- **LOW — `next_occurrence_of_hhmm` pinned STRICTLY-after.**
  `compute_must_start_by` uses `if now < today_target` (strict), so
  at exactly HH:MM the function returns TOMORROW. The prior "(or at)"
  hedging is dropped; the extraction equivalence test asserts the
  strict boundary at `now == today_target`.
- F1 (both sites gated) confirmed closed by prior review.
- F2 resolver confirmed correct for the three cases by prior review.

---

## 1. Operator intent (rescoped)

Overnight charge on both L2 EV chargers and L1 smart-plug chargers is
already reserve-gated: at night the ONLY release path is
`battery_out_of_capacity` (documented in code at
`energy_pool.py:1998-2001`). `soc_recovered` is the DAYTIME-solar
release ("solar refilled the battery, EV can share"). We add one
time-check to the reserve leg ONLY, leaving the daytime path untouched:

```
if (battery_out_of_capacity and _charge_onset_reached(now)) or soc_recovered:
    <existing peer-pause divert + turn_on>
```

When onset not reached AND daytime `soc_recovered` is False: the
EVSE/plug stays in `_paused_by_battery_drain`. No new pause set. When
`soc_recovered=True` (day, solar available): release fires immediately
regardless of the nightly onset. DP re-evaluates each tick; once `now`
reaches the session's onset AND `battery_out_of_capacity` is met, the
release fires naturally next tick.

Result: `overnight_charge_start = max(battery_out_of_capacity_time,
onset_instant_governing_this_session)`; daytime solar release is
unchanged.

**Behavior change on deploy.** Default onset `"01:00"` ACTIVE on both
L2 and L1. Kill-switch: blank onset → gate short-circuits to True →
byte-identical to today.

---

## 2. Institutional context verified

### 2.1 Greps run + results (REUSED vs NEW)

- **REUSED — the TWO actuation sites + the split condition semantics.**
  - **L2 EV:** `EVChargerController.determine_battery_drain_actions`
    at `energy_pool.py:1779`. `battery_out_of_capacity` computed
    `:1984-1989`; `soc_recovered` computed `:1990-2006` (docstring
    at `:1990-2001` explicitly frames it as the DAYTIME-solar leg
    with a solar-active gate; the code comment "at night the ONLY
    release is `battery_out_of_capacity`" is the exact anchor for
    Rev 5's split). Release conjunction `:2008`; `switch.turn_on`
    `:2031-2035`; peer-pause divert `:2014-2021`. Class defined
    `:189`.
  - **L1 smart plug:** `SmartPlugController.determine_battery_drain_actions`
    at `:3192`. `battery_out_of_capacity` `:3325-3332`; `soc_recovered`
    `:3333-3341` (parity comment references the EV docstring).
    Release conjunction `:3343`; `switch.turn_on` `:3363-3366`;
    peer-pause divert `:3347-3360`. Class defined `:2856`.
  Both branches are literal mirrors. The onset clause is added at
  each site by re-associating the conjunction to gate only
  `battery_out_of_capacity`.

- **REUSED — `_paused_by_battery_drain` sets** (per controller).

- **REUSED — `next_occurrence_of_hhmm` pattern.**
  `energy_drain_precedence.py:356-373` `compute_must_start_by`:
  ```
  hour, minute = divmod(minutes_past_midnight, 60)
  today_target = now.replace(hour=hour, minute=minute, ...)
  if now < today_target: return today_target
  return today_target + timedelta(days=1)
  ```
  **STRICTLY-after:** at `now == today_target`, the `<` fails → returns
  TOMORROW. Extraction preserves this exactly.

- **REUSED — owner-registry persistence & restore hooks (CORRECTED CITATIONS).**
  - Hook enumeration: `energy_pool_owners.py:96`
    (`"blind_window_epoch_and_pre_engaged"`) — correct.
  - `OwnerDeclaration` schema: `energy_pool_owners.py:100-119` —
    correct.
  - **Save-side wiring:** `_save_evse_state` at `energy.py:1925`
    calls `_save_registry_owner_lists` at `:1956`. The registry
    iteration lives in `_save_registry_owner_lists` at `:1671-1691`
    (`for _decl in _EV_REG.iter_persisted_lists(): ...`).
  - **Restore-side wiring:** `_restore_registry_owner_lists` at
    `energy.py:1693`; `_KNOWN_HOOKS` literal at `:1712-1721`
    (documents the enum, doesn't dispatch); dispatch loop at `:1722`
    (`for _decl in _EV_REG.iter_persisted_lists(): ...`); hook-body
    dispatch (per-decl `restore_hook` case selection) happens inside
    that loop after payload decode.
  - Sample restore-side controller target:
    `EVChargerController.mark_pre_engaged_from_restore(epoch_started_at)`
    at `energy_pool.py:578-594` — correct model.
  The new drain-session anchor gets its own registry entry per
  controller + hook name (D2 spec). Save and restore extensions
  land inside `_save_registry_owner_lists`/`_restore_registry_owner_lists`
  (not `_save_evse_state`/`_restore_evse_state` directly — those
  are the outer callers).

- **REUSED — hard backstop machinery.** `DPState.MUST_START_FORCED`
  at `energy_drain_precedence.py:77`; timer callback
  `_on_dp_must_start_by` at `energy.py:5527-5556`; release worker
  `_apply_dp_must_start_release` at `energy.py:5249-5344`. **The
  release worker dispatches `switch.turn_on` DIRECTLY at
  `:5330-5336`** — iterates `self._ev._paused_by_dp` and calls the
  switch service without traversing the `:2032` or `:3343` release
  branches. Consequences:
  1. EV `dp_forcing` OR-clause at `:2008` is inert today (backstop
     bypasses this branch). Kept as belt-and-suspenders.
  2. L1 SmartPlugController is NOT in `_paused_by_dp` — L1 plugs
     have NO must-start-by backstop today. Known gap; §D3.

- **REUSED — dual-knob (config-flow + live time entity) pattern.**
  `OffPeakDrainNumber` at `number.py:1036-1133`, post-v4.7.26: no
  `RestoreEntity`; re-seed via `{**entry.data, **entry.options}`.

- **REUSED — CM reload-suppression allowlist.** `_EC_SETTER_DISPATCH`
  at `__init__.py:6009`; consumed at `:6456` (union) and `:6657`
  (live apply loop).

- **REUSED — `PLATFORMS`.** `__init__.py:329-336`. Add `Platform.TIME`.

- **NEW (1) — `CONF_ENERGY_EVSE_CHARGE_ONSET_TIME`.** In
  `energy_const.py` alongside `CONF_ENERGY_EV_BATTERY_DRAIN_SOC:862`.
  Default `"01:00"`; blank = disabled.

- **NEW (1) — module const `ONSET_SESSION_LOOKBACK_H = 6`** in
  `energy_const.py`. Rung 1.

- **NEW (1) — module const `DRAIN_SESSION_MAX_RESTORE_AGE_H = 24`**
  in `energy_const.py`. Rung 1. Fail-safe bound on stale anchors.

- **NEW (1 shared helper) — `_charge_onset_reached(now_local,
  anchor_local, parsed_onset) -> bool`.** Module-level free function.

- **NEW (2 per-controller anchors) — `_drain_session_started_at`**
  on `EVChargerController` and `SmartPlugController`.

- **NEW (1 time entity) — `EVChargeOnsetTimeEntity`.** Global scope.

**REUSED (no changes):** the entire drain-target / DP / reserve-gating
subsystem. `_drain_target_reached` not introduced.

### 2.2 Prior planning docs consulted

- Prior revisions of this doc (rev 1-4).
- `docs/planning/PLANNING_ec_blind_window_evse_guard.md` — anchor
  pattern.

### 2.3 Memory bodies pulled

- `feedback_extend_existing_never_rebuild` — F1 discipline.
- `feedback_parent_entry_reload_watchdog_hazard` — allowlist add.
- `feedback_coincidental_equality_masks_concept_split` — default
  `"01:00"` independent of TOU off-peak start.
- `feedback_verify_claim_types_not_felt_uncertainty` —
  MUST_START_FORCED reachability check.
- `feedback_hollow_test_anchors` — mutation drills on real
  `determine_battery_drain_actions`.

### 2.4 Code locations surveyed end-to-end

- `energy_pool.py:189-260` (EVChargerController class header).
- `energy_pool.py:1779-2048` (EV drain branch).
- `energy_pool.py:2856+` (SmartPlugController class header).
- `energy_pool.py:3192-3375` (L1 drain branch).
- `energy_pool.py:310-620` (blind-window anchor +
  `mark_pre_engaged_from_restore` model).
- `energy_pool_owners.py:1-140` (registry contract).
- `energy.py:1671-1691` (`_save_registry_owner_lists`),
  `:1693-1770` (`_restore_registry_owner_lists`, `_KNOWN_HOOKS` at
  `:1712-1721`, dispatch loop at `:1722+`),
  `:1925+` (`_save_evse_state` outer caller),
  `:5249-5344` (`_apply_dp_must_start_release`),
  `:5527-5556` (`_on_dp_must_start_by`).
- `energy_drain_precedence.py:70-420`.
- `number.py:1036-1133` + `:142,:3260,:3371,:3402,:3892`
  (no-RestoreEntity references).
- `__init__.py:329-344, 6009, 6456, 6657`.

---

## 3. Deliverables

### D1 — Dual knob (config-flow + live time entity), global scope

**D1a — Config-flow field.** `CONF_ENERGY_EVSE_CHARGE_ONSET_TIME` in
`energy_const.py`; HA `TimeSelector`; default `"01:00"`; blank =
disabled. Added to Energy Coordinator options-flow schema.

**D1b — Live time entity.** `EVChargeOnsetTimeEntity(TimeEntity)` in a
new `time.py`. Mirrors OffPeakDrainNumber post-v4.7.26 (no
`RestoreEntity`; seed from `{**entry.data, **entry.options}`).

**D1c — Coordinator glue.**
- `EnergyCoordinator.set_ev_charge_onset_time(value: str)` on `energy.py`.
- Property `ev_charge_onset_time -> datetime.time | None`.
- Register in `_EC_SETTER_DISPATCH` (`__init__.py:6009`):
  `CONF_ENERGY_EVSE_CHARGE_ONSET_TIME: ("set_ev_charge_onset_time", str)`.
- Add `Platform.TIME` to `PLATFORMS` (`__init__.py:329-336`).

**Scope:** global — single onset governs BOTH controllers.

#### D1 Acceptance criteria

- Const exists; options-flow shows TimeSelector; default `"01:00"`.
- Blank onset → both `EVChargerController.determine_battery_drain_actions`
  AND `SmartPlugController.determine_battery_drain_actions` byte-identical
  to baseline (tests `D1-KILL-BYTE-IDENTICAL-EV` and `-L1`).
- Dual sync both directions; no reload on save.
- Restart: live entity hydrates from `entry.options` (not RestoreEntity).
- Fail-open on `"25:99"`; kill-switch log on blank clear.

### D2 — Onset clause at BOTH drain-release sites, gating ONLY the reserve leg

**Site A — L2 EV, `EVChargerController.determine_battery_drain_actions`,
line `:2008`:**

```python
now_local = dt_util.as_local(dt_util.utcnow())
anchor_local = (
    dt_util.as_local(self._drain_session_started_at)
    if self._drain_session_started_at is not None else None
)
onset_reached = _charge_onset_reached(
    now_local=now_local,
    anchor_local=anchor_local,
    parsed_onset=(coord.ev_charge_onset_time if coord else None),
)
# Defensive belt-and-suspenders — MUST_START_FORCED currently
# bypasses this site (energy.py:5330-5336 dispatches directly), so
# this OR is inert today. Kept so a future refactor routing
# MUST_START_FORCED through the release branch does not silently
# strand the car.
dp_carrier = getattr(coord, "_dp_carrier", None) if coord else None
dp_forcing = (
    dp_carrier is not None
    and dp_carrier.state == DPState.MUST_START_FORCED
    and evse_id in getattr(coord._ev, "_paused_by_dp", set())
)
# HIGH fix (Rev 5): gate ONLY the overnight reserve leg
# (battery_out_of_capacity). soc_recovered is the DAYTIME-solar
# release leg (:1990-2006 docstring — "solar refilled the battery,
# EV can share") and MUST NOT be gated by the nightly onset,
# or daytime charging would strand for ~13h. Reassociation:
if (
    (battery_out_of_capacity and (onset_reached or dp_forcing))
    or soc_recovered
):
    if not state["is_on"]:
        # ... existing peer-pause divert at :2014-2021, unchanged ...
        # ... existing turn_on at :2031-2035, unchanged ...
```

**Site B — L1 smart plug,
`SmartPlugController.determine_battery_drain_actions`, line `:3343`:**

Textually identical re-association. L1 has NO DP participation today,
so `dp_forcing` is always False on this leg. Kept present as a no-op
for symmetry + future extensibility. The soc_recovered daytime path
is likewise preserved unchanged.

**Shared helper** (module-level free function in `energy_pool.py`):

```python
def _charge_onset_reached(
    now_local: datetime,
    anchor_local: datetime | None,
    parsed_onset: time | None,
) -> bool:
    """Session-anchored, day-boundary-safe onset gate.

    Returns True iff the onset instant governing THIS drain session
    has been reached, OR the feature is disabled, OR no session is
    active. Semantics:

      * `parsed_onset is None`  → kill-switch (feature disabled) → True.
      * `anchor_local is None`  → no active session → True (outer gate
        at the caller is False in that case anyway; conservative).
      * Otherwise, compute the ONSET INSTANT GOVERNING THIS SESSION
        as `next_occurrence_of_hhmm(anchor_local - LOOKBACK, hh, mm)`
        (STRICTLY-after semantics: at exactly HH:MM the resolver
        returns tomorrow). Three cases:
          (i)   anchor 20:00 day1, onset 01:00 → lookback 14:00 day1
                → next 01:00 = 01:00 day2. Gate opens 01:00 day2.
          (ii)  anchor 22:00 day1, onset 01:00 → lookback 16:00 day1
                → 01:00 day2. Operator's worked example.
          (iii) anchor 02:15 day2, onset 01:00 → lookback 20:15 day1
                → 01:00 day2 (already PAST relative to now=02:15).
                Gate open immediately — session started AFTER
                tonight's onset.
      * The gate is True iff `now_local >= onset_instant`.
    """
    if parsed_onset is None:
        return True
    if anchor_local is None:
        return True
    lookback_anchor = anchor_local - timedelta(hours=ONSET_SESSION_LOOKBACK_H)
    hh, mm = parsed_onset.hour, parsed_onset.minute
    onset_instant = next_occurrence_of_hhmm(lookback_anchor, hh, mm)
    return now_local >= onset_instant
```

**Why the `- LOOKBACK` shift solves case (iii).** `next_occurrence_of_hhmm`
returns the FIRST HH:MM STRICTLY-after its argument. Passing the anchor
directly would return `next(02:15) = 01:00 next day` — ~23h over-hold.
Shifting the anchor BACK by LOOKBACK places the search origin BEFORE
any HH:MM that could reasonably have already governed this session,
so the FIRST occurrence found is the correct governing instant (past
or future).

**Strictly-after boundary note.** At `anchor = 01:00 day-2` exactly
(anchor coincides with an onset instant), the `- 6h` shift places the
lookback at 19:00 day-1 and the resolver returns 01:00 day-2. The
gate opens at `now >= 01:00 day-2` — inclusive of the anchor
instant, which is desirable (a session that anchors AT the onset
should not be held). The strictly-after property applies to the
resolver's own boundary (`now == today_target` → tomorrow), NOT to
the gate's final `>=` comparison.

**ONSET_SESSION_LOOKBACK_H = 6.** Rationale: drain sessions in the
operator's config close within ~5-6h of onset. Anchors observed >6h
AFTER the previous onset are new-session anchors that should wait
for the NEXT onset. Rung 1 module constant.

**Session anchor lifecycle (per-controller):**
- Field: `_drain_session_started_at: datetime | None = None` on each
  of `EVChargerController` and `SmartPlugController`.
- **Set** immediately BEFORE the first add to
  `_paused_by_battery_drain` in a new session (empty→non-empty):
  ```python
  if not self._paused_by_battery_drain:
      self._drain_session_started_at = dt_util.utcnow()
  self._paused_by_battery_drain.add(evse_id)
  ```
- **Cleared** on the final `discard()` that empties the set (wrap
  the discard sites at `:2022, :2043, :3352, :3372`):
  ```python
  self._paused_by_battery_drain.discard(evse_id)
  if not self._paused_by_battery_drain:
      self._drain_session_started_at = None
  ```
- **Persisted via owner-registry.** Add two rows to
  `energy_pool_owners.py`'s `OwnerDeclaration` table (one per
  controller) with `persistence_kind='list'` (using a
  single-element list to carry the ISO timestamp — matches the
  existing owner-list save shape) OR a small extension for a
  scalar payload if the reviewer prefers. Proposed hook names:
  `"drain_session_epoch_ev"` and `"drain_session_epoch_plug"`.
  Both added to `_KNOWN_HOOKS` literal at `energy.py:1712-1721`.
  Dispatch inside `_restore_registry_owner_lists` at `:1722+`
  calls a new controller helper
  `mark_drain_session_from_restore(anchor_utc)` on each controller
  (modeled after `mark_pre_engaged_from_restore` at
  `energy_pool.py:578-594`).
- **Restart contract:** if restored anchor age >
  `DRAIN_SESSION_MAX_RESTORE_AGE_H` (24h), treat as None — fail-safe
  re-anchor on next transition.

#### D2 Acceptance criteria (discriminating)

All tests drive REAL `determine_battery_drain_actions` on the REAL
controller class.

- **Kill-switch (blank onset) BYTE-IDENTICAL** — both EV and L1
  fixtures vs baseline.
- **Case (i) — anchor before onset, distant:** anchor 20:00 day-1;
  `battery_out_of_capacity=True` at 20:00 day-1; onset `"01:00"`;
  now = 20:00 day-1 → NO turn_on. Advance to 00:59 day-2 → NO turn_on.
  Advance to 01:00 day-2 → turn_on.
- **Case (ii) — operator worked example (LOAD-BEARING, naive-impl
  killer):** anchor 22:00 day-1; `battery_out_of_capacity=True` at
  22:00 day-1; onset `"01:00"`; now = 22:00 day-1 → NO turn_on.
  Advance to 01:00 day-2 → turn_on. Naive `now.hour(22) >=
  onset.hour(1)` fires at 22:00 → this test MUST fail on the naive
  implementation.
- **Case (iii) — anchor AFTER tonight's onset (F2):** anchor 02:15
  day-2; `battery_out_of_capacity=True` at 02:15 day-2; onset
  `"01:00"`; now = 02:15 day-2 → turn_on fires IMMEDIATELY (not
  ~23h later).
- **DAYTIME `soc_recovered` NOT gated (Rev 5 HIGH fix — new
  discriminator):** anchor 10:00 day-1 (pause started midday);
  `battery_out_of_capacity=False` (SOC well above reserve);
  `soc_recovered=True` at 12:00 day-1 (solar has refilled the
  battery); onset `"01:00"` → `switch.turn_on` FIRES at 12:00 day-1,
  NOT held to 01:00 day-2. Repeat on the L1 site with identical
  expectations. Prior (Rev 4) distributed clause would fail this
  test with a ~13h over-hold.
- **Post-onset drain-release, same session:** anchor 22:00 day-1;
  onset `"01:00"`; `battery_out_of_capacity` becomes True at 02:00
  day-2 → turn_on at 02:00.
- **Session anchor restart (per-controller):** drain session on BOTH
  controllers starts 22:00 day-1; restart HA at 23:30 day-1; on
  resume, each controller's anchor restores from its own registry
  entry to 22:00 day-1; onset `"01:00"` resolves to 01:00 day-2.
  Asymmetric cases (only EV or only L1 has live session) included.
- **Anchor expiry:** restored anchor 30h old → treated as None →
  gate returns True; drain-release fires on the next
  drain-condition trigger.
- **Anchor re-arm across nights:** anchor 22:00 day-1; empties
  06:00 day-2; new session opens 22:00 day-2 → anchor 22:00 day-2;
  onset `"01:00"` resolves to 01:00 day-3.
- **L1 no-backstop (documented):** onset `"05:00"`,
  `battery_out_of_capacity=True` at 02:00 (contrived); L1 does NOT
  fire until 05:00 (no DP membership). Sensor
  `sensor.ura_ev_charge_onset_l1_over_hold_seconds` accumulates
  the over-hold seconds.
- **Mutation drills:**
  1. At BOTH `:2008` and `:3343`, replace the reassociated conjunction
     with the ORIGINAL `battery_out_of_capacity or soc_recovered` →
     the operator worked-example test (case ii) MUST fail on the
     mutated site. Restore.
  2. **Rev 5 discriminator:** at BOTH `:2008` and `:3343`, mutate
     the reassociation to distribute the gate over soc_recovered
     (`(battery_out_of_capacity or soc_recovered) and (onset_reached
     or dp_forcing)`) → the DAYTIME `soc_recovered` test MUST fail
     (release blocked until 01:00 day-2). Restore.
  3. Mutate the F2 resolver: change
     `anchor_local - timedelta(hours=ONSET_SESSION_LOOKBACK_H)` to
     `anchor_local` → case (iii) test MUST fail. Restore.
- **Sensor:** `binary_sensor.ura_ev_charge_onset_gate_open`
  (aggregate); attributes expose per-controller anchor + onset_instant
  + `soc_recovered_active` (so operator can see the daytime bypass).

### D3 — Hard backstop (verify + document, no new code)

**EV leg.** `_apply_dp_must_start_release` (`energy.py:5249-5344`)
dispatches `switch.turn_on` DIRECTLY at `:5330-5336`, iterating
`self._ev._paused_by_dp`. BYPASSES `:2008`. The onset clause never
runs in the must-start-forced path; the `dp_forcing` OR-clause at
`:2008` is inert today (defense-in-depth only).

**L1 leg.** No DP participation. **L1 plugs have NO must-start-by
backstop today.** Rev 5 note: this gap is now materially SMALLER
because daytime `soc_recovered` release is unaffected — the L1
over-hold risk is confined to overnight reserve sessions where
onset is set later than off-peak-end. Mitigation:
- Default onset `"01:00"` + typical off-peak end 06:00 → 5h runway.
- ~1.4 kW load; bounded overnight energy.
- Follow-up card trigger: observed L1 stranding in production
  (`sensor.ura_ev_charge_onset_l1_over_hold_seconds` accumulates
  measurably).

#### D3 Acceptance criteria

- EV backstop preserved via direct dispatch (log line
  `"drain-precedence must-start-by fire: forced EVSE %s ON"` at
  `energy.py:5337-5340`).
- L1 no-backstop documented behavior verified by fixture.
- Build-time enumeration: review record lists every
  MUST_START_FORCED downstream and confirms EV-only reach.

---

## 4. Non-goals (unchanged from Rev 4; Rev 5 tightens #2 by construction)

Onset applies at exactly TWO sites: `energy_pool.py:2008` (EV) and
`:3343` (L1), and gates ONLY the `battery_out_of_capacity` leg at
each. The following are EXPLICITLY out of scope:

1. Off-peak proactive ensure-on.
2. **Daytime solar-share release (`soc_recovered`)** — Rev 5's HIGH
   fix ensures this is truly non-gated by construction (not merely
   "in a different branch").
3. Excess-solar activation (`determine_excess_solar_actions`).
4. Solar-follow amp modulation.
5. Arbitrage grid-charge.
6. Grid-cap release.
7. Fill-priority release.
8. Force-charge preempt.
9. `_apply_dp_must_start_release` direct dispatch at `energy.py:5330-5336`.
10. release_all / teardown.

Reviewer confirmation shape: **2 sites reassociated (EV `:2008` + L1
`:3343`), gating ONLY the `battery_out_of_capacity` sub-leg;
`soc_recovered` sub-leg unchanged at both; 10 other paths unchanged.**

Other non-goals: per-controller onset knob (global v1); scheduled
callbacks; RestoreEntity on the time entity; new backstop knob; L1
must-start-by machinery (known gap, §D3).

---

## 5. Falsifiable invariant

> **INV-ONSET-1 (EV site):** At `energy_pool.py:2032` (EV drain-pause
> release `switch.turn_on`), actuation is emitted iff
>
>     (
>       (battery_out_of_capacity AND (onset_reached OR onset_disabled))
>       OR soc_recovered
>     )
>     AND (existing peer-pause divert at :2014-2021 does not fire)
>
> The `dp_forcing` OR-clause is inert today; kept for future-proofing.
> The car's must-start-by liveness is preserved by
> `_apply_dp_must_start_release`'s direct dispatch at `energy.py:5330-5336`.
>
> **INV-ONSET-1L1 (L1 site):** At `energy_pool.py:3363`, actuation is
> emitted iff
>
>     (
>       (battery_out_of_capacity AND (onset_reached OR onset_disabled))
>       OR soc_recovered
>     )
>     AND (existing peer-pause divert at :3347-3360 does not fire)
>
> L1 has no MUST_START_FORCED backstop today (§D3).
>
> **INV-ONSET-2 (kill-switch):** When onset is blank, both sites'
> action streams are BYTE-IDENTICAL to baseline for every recorded
> fixture.
>
> **INV-ONSET-3 (session-anchor semantics):** For a drain session
> anchored at `T_anchor` with reserve-leg release becoming True at
> `T_release`, the OVERNIGHT reserve release fires at
> `max(T_release, next_occurrence_of_hhmm(T_anchor -
> ONSET_SESSION_LOOKBACK_H, hh, mm))`. The DAYTIME `soc_recovered`
> release path is UNAFFECTED by onset.
>
> **INV-ONSET-4 (dual-knob):** `entry.options[...]` is sole source of
> truth; live entity converges within one tick, both directions; no
> CM reload on onset change.

Falsification recipes (Reviewer C / adversarial):
1. Operator worked example (case ii) at BOTH sites.
2. Case (iii) — anchor 02:15, onset 01:00 → immediate fire.
3. **Rev 5 discriminator: daytime `soc_recovered=True` at noon with
   onset 01:00 → fires at noon, NOT held.** Both sites.
4. Blank onset → both sites byte-identical.
5. MUST_START_FORCED at 02:00 with onset `"05:00"` → EV fires at
   02:00 via `_apply_dp_must_start_release`; L1 does not fire
   until 05:00.
6. Session-anchor restart on both controllers via owner-registry
   restore hooks.
7. Grep every `switch.turn_on` under EVSE/plug control in
   `energy_pool.py` — confirm §4 exclusion complete.

---

## 6. Tier classification

**Recommended: Tier 2-DB (unchanged).**

Rev 5 is a re-association fix on a single conjunction at each of two
sites plus documentation of what was already the intended semantics
(daytime path unaffected). No new state machine; no new invariant.
The remaining regression-prone surface is unchanged from Rev 4:
- Two `:2008`/`:3343` clause changes on shared primitives (now with
  a tighter reassociation, verified by explicit daytime test).
- Two per-controller `_drain_session_started_at` lifecycles.
- Two owner-registry entries + one restore-hook body dispatched to
  two controllers.
- One shared helper `_charge_onset_reached`.
- Dual-knob wiring + allowlist + Platform.TIME.

**Framings:**
- **A — Local correctness.** Resolver expression across cases
  (i/ii/iii); `next_occurrence_of_hhmm` STRICTLY-after preserved;
  reassociation is boolean-algebra-correct; kill-switch fail-open;
  blank onset byte-identical.
- **B — Integration / lifecycle / persistence.** Per-controller
  anchor lifecycle (set/clear/persist/restore via
  `_save_registry_owner_lists:1671-1691` /
  `_restore_registry_owner_lists:1693` with hook dispatch at `:1722+`);
  restart contract (age bound + fail-safe); MUST_START_FORCED
  reachability documented; daytime `soc_recovered` untouched
  end-to-end.
- **C — New surfaces + test authority.** Dual knob round-trip; no
  RestoreEntity; `Platform.TIME` loaded; tests drive real
  `determine_battery_drain_actions`; three mutation drills (original
  restore, distribute-over-soc_recovered, resolver-shift).

**Plan review:** Final targeted re-review on the soc_recovered split
only. Reviewer:
- traces the reassociated boolean at BOTH sites for the four sub-cases
  `(battery_out_of_capacity ∈ {T,F}) × (soc_recovered ∈ {T,F})`;
- confirms the daytime `soc_recovered=True` path bypasses the onset
  gate;
- confirms the corrected save/restore anchor citations point to real
  code (`energy.py:1671-1691`, `:1693`, `:1712-1721`, `:1722+`).

---

## 7. Final knob inventory (Numbers-Get-Knobs)

**NEW (3):**
- `CONF_ENERGY_EVSE_CHARGE_ONSET_TIME` — Rung 2 config-flow
  TimeSelector (default `"01:00"`, blank=disabled) + Rung 3 live
  time entity `time.ura_ev_charge_onset_time`. Global.
- `ONSET_SESSION_LOOKBACK_H = 6` — Rung 1 module const.
- `DRAIN_SESSION_MAX_RESTORE_AGE_H = 24` — Rung 1 module const.

**REUSED (no changes):** `CONF_DP_MUST_START_BY_MIN_PAST_MIDNIGHT`,
`compute_must_start_by` (extraction of `next_occurrence_of_hhmm`
STRICTLY-after preserved), `DPState.MUST_START_FORCED`,
`battery_out_of_capacity`, **`soc_recovered` (untouched — Rev 5
guarantee)**, `_paused_by_battery_drain`, DP carrier, HA
`TimeSelector`, `OffPeakDrainNumber` pattern, owner-registry
`restore_hook` mechanism.

---

## 8. Plan-completion tracking

Non-carry-overs:
- `_drain_target_reached` — NOT introduced (rev 3 P1).
- Single-site claim — CORRECTED to two sites (Rev 4 F1).
- Free-form `_save_evse_state`/`_restore_evse_state` for the anchor —
  REPLACED by `_save_registry_owner_lists` / `_restore_registry_owner_lists`
  extensions (Rev 4 F3b, citations corrected in Rev 5).
- Distributed `(A or B) and (X or Y)` conjunction — CORRECTED to
  `(A and (X or Y)) or B` to preserve daytime path (Rev 5 HIGH).

## 9. Ship-alongside notes

Deploys with the EC-maintenance batch. Additive owner-registry entries
+ additive `entry.options` field — no schema migration.

**Behavior change on deploy (overnight reserve only):** default onset
`"01:00"` ACTIVE gates the OVERNIGHT reserve leg only; daytime
solar-share release is unchanged. README v<next>.md MUST document
this split explicitly.

Version cadence: PATCH bump (5.90.x line).

## 10. Files touched (final production surface)

- `custom_components/universal_room_automation/domain_coordinators/energy_const.py`
  — add `CONF_ENERGY_EVSE_CHARGE_ONSET_TIME` default `"01:00"`;
  `ONSET_SESSION_LOOKBACK_H = 6`; `DRAIN_SESSION_MAX_RESTORE_AGE_H = 24`.
- `custom_components/universal_room_automation/domain_coordinators/energy_pool.py`
  — `EVChargerController` (`:189`): add `_drain_session_started_at`
  field; set/clear at `_paused_by_battery_drain` empty↔non-empty
  transitions; add `mark_drain_session_from_restore(anchor_utc)`;
  reassociate the conjunction at `:2008` to
  `(battery_out_of_capacity and (onset_reached or dp_forcing)) or soc_recovered`.
  `SmartPlugController` (`:2856`): identical additions;
  reassociate the conjunction at `:3343` identically (dp_forcing
  always False on this leg, kept for symmetry).
  Add shared module-level helper `_charge_onset_reached(now_local,
  anchor_local, parsed_onset)`.
- `custom_components/universal_room_automation/domain_coordinators/energy_pool_owners.py`
  — add TWO `OwnerDeclaration` rows for the drain-session anchors
  (EV + plug), each with its own `restore_hook` name
  (`"drain_session_epoch_ev"`, `"drain_session_epoch_plug"`); add
  both names to the hook-name literal enumeration at `:96`.
- `custom_components/universal_room_automation/domain_coordinators/energy_drain_precedence.py`
  — extract `next_occurrence_of_hhmm(now, hh, mm)` (STRICTLY-after
  semantics); refactor `compute_must_start_by` to call it (semantics
  preserved). Equivalence test asserts strict boundary at
  `now == today_target`.
- `custom_components/universal_room_automation/domain_coordinators/energy.py`
  — add `set_ev_charge_onset_time(value: str)` + `ev_charge_onset_time`
  property + parsed cache. Extend `_save_registry_owner_lists`
  (`:1671-1691`) to write the two new anchor keys, and extend
  `_restore_registry_owner_lists` (`:1693+`) to add both new hook
  names to `_KNOWN_HOOKS` (`:1712-1721`) and dispatch them inside
  the loop at `:1722+` by calling
  `controller.mark_drain_session_from_restore(anchor_utc)`.
- `custom_components/universal_room_automation/config_flow.py` +
  `options_flow.py` — add `TimeSelector` field.
- `custom_components/universal_room_automation/time.py` (NEW) —
  `EVChargeOnsetTimeEntity(TimeEntity)` (no RestoreEntity).
- `custom_components/universal_room_automation/__init__.py`
  — add `Platform.TIME` at `:329-336`; add
  `CONF_ENERGY_EVSE_CHARGE_ONSET_TIME: ("set_ev_charge_onset_time", str)`
  to `_EC_SETTER_DISPATCH` at `:6009`.
- `custom_components/universal_room_automation/sensor.py` +
  `binary_sensor.py` — add
  `binary_sensor.ura_ev_charge_onset_gate_open` (aggregate),
  `sensor.ura_ev_charge_onset_time_effective`,
  `sensor.ura_ev_charge_onset_l1_over_hold_seconds`.
- `custom_components/universal_room_automation/translations/en.json` +
  `strings.json` — labels.
- `quality/tests/energy_pool/test_charge_onset_gate_ev.py` — new
  (cases i/ii/iii + kill-switch + operator worked example + Rev 5
  daytime `soc_recovered` case + session-anchor restart + THREE
  mutation drills at `:2008`).
- `quality/tests/energy_pool/test_charge_onset_gate_l1.py` — new
  (same matrix + Rev 5 daytime case + THREE mutation drills at
  `:3343` + no-backstop documented behavior).
- `quality/tests/energy_drain_precedence/test_next_occurrence_extraction.py`
  — new (≥3 boundary cases including strict-boundary at
  `now == today_target` → tomorrow).
- `quality/tests/energy_pool/test_drain_session_owner_persistence.py`
  — new (per-controller anchor round-trips via owner-registry
  restore-hook; asymmetric EV-only / L1-only scenarios; age-expiry).
- `docs/readmes/README_v<next>.md` — behavior-change callout (overnight
  reserve only; daytime solar unchanged); kill-switch instruction;
  L1 no-backstop gap note; post-restart Validated table.
