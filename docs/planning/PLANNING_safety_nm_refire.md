# PLANNING — SAFETY-NM-REFIRE-UNWIRED-1: wire hazard_type/location on the Safety NotificationAction and make `is_hazard_active` hold-aware

- Card: `SAFETY-NM-REFIRE-UNWIRED-1`
- Blocker: `SAFETY-HAZARD-NEVER-CLEARS-1` — shipped v5.103.61 (2026-10-15, live).
- Tier: **Tier 2-DB** (standing policy for regression-prone life-safety work; cross-coordinator safety ↔ NM; touches a shared primitive — the NM re-fire path — consumed by every coordinator).
- Branch / worktree: `plan/safety-refire` under `.claude/worktrees/plan-safety-refire`.
- Scope: **plan only**. Do not build; do not run the full suite.

## 1. Falsifiable invariant

> **INV-REFIRE**: For every life-safety hazard emitted by the Safety Coordinator
> (`HazardType ∈ {SMOKE, FIRE, CARBON_MONOXIDE, WATER_LEAK, FLOODING, FREEZE_RISK, OVERHEAT}`
> — i.e. the subset of `HazardType` that NM classifies as life-safety per
> `const.NM_LIFE_SAFETY_HAZARDS`):
>
> 1. **Still-active ⇒ re-page.** If the raising sensor(s) are still on the hazard
>    side when NM's cooldown expires, `notification_manager._re_evaluate_hazard`
>    (`notification_manager.py:3020-3060`) MUST see `coordinator.is_hazard_active(hazard_type, location) == True` and MUST re-fire.
> 2. **Cleared ⇒ never re-page.** If every raising sensor has recovered AND the
>    `HAZARD_MIN_HOLD_S = 300 s` clear hold has elapsed (key popped from
>    `_active_hazards`), `is_hazard_active(...) == False` and NM returns to IDLE.
> 3. **Pending-clear ⇒ never re-page.** If every raising sensor has recovered
>    but the 300 s clear hold is still running (key in `_hazard_clear_pending`),
>    `is_hazard_active(...) == False` even though the key is still in
>    `_active_hazards`. This is the `constraint_2026_10_14` requirement: the
>    smoke/CO cooldown (120 s, `DEFAULT_NM_COOLDOWN_SMOKE/_CO = 2` min) is
>    shorter than the 300 s clear hold, so without this clause we would re-page
>    CRITICAL for a detector that has already recovered.
> 4. **Re-raise during pending clear ⇒ re-page.** If the hold is pending and a
>    contributor relapses (hold cancelled via `_record_sensor_relapse` →
>    `_hazard_clear_pending.pop`), `is_hazard_active(...) == True`.
>
> Falsification observations (any one disproves the plan):
> - Live `notification_log` row where NM cooldown expired on an active smoke/CO
>   hazard and no re-page row followed → clause 1 false.
> - A re-page row whose `hazard_type` matches a key currently in
>   `_hazard_clear_pending` → clause 3 false.
> - A `_re_evaluate_hazard` call with `hazard_type == ""` or `location == ""`
>   (grep `notification_log` and the structured log line at `nm:3042`) → the
>   wiring did not land.

## 2. Institutional-context verified

Grep surfaces consulted: `const.py`, `config_flow.py`, `options_flow.py`,
`sensor.py`, `binary_sensor.py`, `number.py`, `switch.py`, `select.py`,
`button.py`, `services.yaml`, `domain_coordinators/*.py`, `database.py`,
`docs/Coordinator/*`, `docs/planning/PLANNING_safety_hazard_clear_on_recovery.md`.

Prior-art verdicts (REUSED / NEW with file:line):

- **`NotificationAction.hazard_type` field** — REUSED
  (`domain_coordinators/base.py:136`). String; already propagated by
  `manager.py:1079-1080` into `NM.async_notify(hazard_type=..., location=...)`.
  No new field.
- **`NM.async_notify(hazard_type, location)`** — REUSED
  (`notification_manager.py:530-558`). Already keys cooldown + re-fire on these.
  No signature change.
- **`BaseCoordinator.is_hazard_active`** — REUSED
  (`domain_coordinators/base.py:237`). Default `False`; override lives in
  `safety.py:3398-3410`.
- **`_hazard_clear_pending`** — REUSED
  (`safety.py:1043, 2870, 2878, 2885, 2890, 2927, 2944, 2952, 3051, 3441`).
  Shipped in v5.103.61 as part of SAFETY-HAZARD-NEVER-CLEARS-1. We only read
  from it in this cycle.
- **`HazardType` enum values vs `NM_LIFE_SAFETY_HAZARDS`** — REUSED
  (`safety.py:132-146`, `const.py:3391-3399`). Emitted strings
  (`"smoke"`, `"carbon_monoxide"`, `"water_leak"`, `"flooding"`,
  `"freeze_risk"`) are the exact tokens NM expects. HIGH_HUMIDITY /
  LOW_HUMIDITY / HIGH_CO2 / HIGH_TVOC / HVAC_FAILURE are deliberately
  **not life-safety** — they fall out of INV-REFIRE and continue to use
  the 300 s non-life-safety cadence.
- **NM cooldown constants** — REUSED (`const.py:3335-3363`,
  `DEFAULT_NM_COOLDOWN_SMOKE=2`, `DEFAULT_NM_COOLDOWN_CO=2`,
  `DEFAULT_NM_COOLDOWN_WATER_LEAK=10`, `DEFAULT_NM_COOLDOWN_FREEZE=15`,
  `DEFAULT_NM_COOLDOWN_FLOODING=5`). These are the operator-tunable
  options-flow knobs; this cycle **does not** add or change any cooldown
  knob — just makes the existing re-fire path keyable.
- **Life-safety repeat cadence** — REUSED
  (`const.py:3387-3388, 3391-3399`). Rung 1 (module constants); not touched.
- **Precedent for `hazard_type`-wired NotificationAction** — REUSED. Three
  existing emission sites already pass `hazard_type`+`location`:
  `perimeter_alert.py:1529, 2968`, `zone_monitoring_tripwire.py:125`,
  `button.py:2373` (test), and five EC sites in `energy_battery.py:1313, 1507, 1599, 1769, 1855`.
  Safety is the single remaining outlier. **No new field or wiring is being
  invented** — only the per-site argument is being populated.
- **Existing NotificationAction site in safety** — ENUMERATED, one and only one:
  `safety.py:2579-2587` inside `_respond_to_hazard`. Verified via
  `rg -n 'NotificationAction\(' safety.py` → single match. (This is why the
  card titled it "the" safety NotificationAction.)

Prior planning docs consulted:
- `docs/planning/PLANNING_safety_hazard_clear_on_recovery.md` rev 4 — read §4-G
  (`is_hazard_active` suffix-aware), §10 (SAFETY-NM-REFIRE-UNWIRED fold-out).
  Rev 4 explicitly leaves the hold-aware NM-refire wiring to **this** card and
  flags the smoke/CO cooldown vs clear-hold interaction (card line
  `constraint_2026_10_14`).

Memory bodies pulled: none required beyond CLAUDE.md's standing rules (No
Fabrication, Config-First, Numbers-Get-Knobs, Tier-2-DB default).

Design docs read: `docs/Coordinator/SAFETY_COORDINATOR.md` §5 clear-on-recovery
(line 293: `HAZARD_MIN_HOLD_S = 300` and the per-minute sweep).

Code locations surveyed end-to-end:
- `safety.py:2465-2600` (`_respond_to_hazard` + `NotificationAction` emit)
- `safety.py:2860-2954` (clear-hold machinery, `_record_sensor_recovery`,
  `_try_clear_if_quiet`, `_sweep_hazard_clears`)
- `safety.py:3398-3410` (`is_hazard_active`)
- `manager.py:1070-1095` (NOTIFICATION dispatch)
- `notification_manager.py:520-560, 2980-3060` (cooldown → re-fire loop)
- `base.py:120-240` (`NotificationAction` schema + base `is_hazard_active`)
- `const.py:3335-3399` (NM cooldowns, life-safety set)

## 3. Config-first check

- No configuration (knob, options-flow field, HA setting, operator action)
  resolves this: the data to be propagated — the hazard type and its location —
  are **computed inside the emitter** and are not operator-settable. Live NM
  cooldown values (`DEFAULT_NM_COOLDOWN_SMOKE=2`, `_CO=2`) are tunable but
  irrelevant to the symptom (`is_hazard_active('','')` always-False). Confirmed
  by reading `is_hazard_active` (`safety.py:3405`) which performs exact
  `f"{hazard_type}:{location}"` equality.
- Verdict: **Code change required.** Config-first checked; no knob turn
  substitutes.

## 4. Producer and Consumer map

**Producer** (`safety.py:2465-2587`):
- Arithmetic: `hazard.type.value` (StrEnum → canonical token) and
  `hazard.location` (the room/zone string populated at every `Hazard(...)`
  construction site in `safety.py:1891, 1805, 2073, 2404, 2446, 2175, 2200,
  2229 ...`).
- Dependency health: both are already set at every `Hazard` construction site
  (grep confirms `type=...` and `location=...` are keyword-required by the
  `@dataclass`; absent `location` crashes). We are reading values that are
  already live, not inventing new ones.

**Consumers**:
- `manager.py:1079-1080` (trust): forwards both into NM. Already wired, no
  change.
- `notification_manager.py:551` (trust, log row): writes
  `hazard_type` + `location` into `notification_log`.
- `notification_manager.py:3029-3039` (trust, re-fire gate): the single
  consumer this cycle unblocks. Calls
  `coordinator.is_hazard_active(hazard_type, location)`.
- `sensor.py:8341, 8436, 8548, 14169` (display): dashboard readouts of the
  active-alert `hazard_type`. Already consume whatever shape NM stores; they
  benefit without a code change.
- `database.py:4444-4485` (storage, `log_notification`): persists both;
  authoritative for post-deploy live-validation.

## 5. Deliverables

### D1 — Populate `hazard_type` + `location` on the Safety `NotificationAction`

**File / line:** `custom_components/universal_room_automation/domain_coordinators/safety.py:2579-2587`

**Change (surgical):** inside the one `NotificationAction(...)` constructor,
add two keyword arguments:

```python
hazard_type=hazard.type.value,
location=hazard.location,
```

That is it. No new import; `hazard.type.value` is already the exact token
written to `notification_log` by the activity-logger block one scope up
(`safety.py:2537`), so the two sites now agree on their key.

**Blast radius:** zero for non-life-safety hazard types — NM already handles
`hazard_type` of CO2/TVOC/humidity by routing to the non-life-safety cadence
(300 s), which is a one-shot re-fire. For life-safety types the newly-live
re-fire path is the *intended* feature.

### D2 — Make `is_hazard_active` hold-aware

**File / line:** `custom_components/universal_room_automation/domain_coordinators/safety.py:3398-3410`

**Change:** when evaluating the match, exclude keys currently in
`_hazard_clear_pending` whose contributor set is empty. Reference
implementation:

```python
def is_hazard_active(self, hazard_type: str, location: str) -> bool:
    """SAFETY-NM-REFIRE-UNWIRED-1: hold-aware — a key whose clear hold
    is pending (all contributors recovered, 300 s HAZARD_MIN_HOLD_S not
    yet elapsed) is reported INACTIVE so NM does not re-page a
    detector that has already recovered. A relapse cancels the hold
    (`_record_sensor_relapse`), which re-exposes the key here.
    """
    exact = f"{hazard_type}:{location}"
    for active_key in self._active_hazards:
        base = active_key[:-4] if active_key.endswith(":roc") else active_key
        if base != exact:
            continue
        # Hold-aware: a pending clear with no raising contributors == inactive.
        if (
            active_key in self._hazard_clear_pending
            and not self._hazard_raising_sensors.get(active_key)
        ):
            continue
        return True
    return False
```

Preserves the ROC-suffix behavior shipped in SAFETY-HAZARD-NEVER-CLEARS-1 §4-G.

### D3 — Tests (quality/tests/safety/)

- `test_safety_notification_action_carries_hazard_type_location`: construct a
  `Hazard(type=HazardType.SMOKE, location="Study A", ...)` through
  `_respond_to_hazard`; assert the emitted `NotificationAction.hazard_type ==
  "smoke"` and `.location == "Study A"`. **Mutation anchor:** removing either
  kwarg flips the assertion.
- `test_safety_is_hazard_active_true_when_active`: raise, don't recover —
  `is_hazard_active("smoke", "Study A") is True`.
- `test_safety_is_hazard_active_false_when_cleared`: raise, recover, advance
  past `HAZARD_MIN_HOLD_S + 1` through the sweep — key popped,
  `is_hazard_active(...) is False`.
- `test_safety_is_hazard_active_false_during_clear_hold` (the
  `constraint_2026_10_14` case): raise, recover (hold armed, key still in
  `_active_hazards`), advance 60 s only — key present AND in
  `_hazard_clear_pending` with empty contributor set →
  `is_hazard_active("smoke", "Study A") is False`. **Mutation anchor:** revert
  D2 and this test must fail.
- `test_safety_is_hazard_active_true_on_relapse_during_hold`: raise, recover
  (hold armed), relapse before 300 s elapses →
  `is_hazard_active(...) is True`.
- `test_nm_re_evaluates_safety_hazard_round_trip`: integration — route a
  smoke `NotificationAction` through `manager.py` dispatch to NM, let the
  2-min cooldown fire, assert NM called `is_hazard_active("smoke", "Study A")`
  with the correct non-empty args (fixes the current `("", "")` bug) and
  re-fired CRITICAL exactly once.

### D4 — Doc updates (same commit as build, per §10 rule)

- `docs/Coordinator/SAFETY_COORDINATOR.md` §5: add a one-paragraph note that
  `is_hazard_active` is hold-aware; the clear hold (300 s) and NM smoke/CO
  cooldown (120 s) interact by design.
- `docs/planning/PLANNING_safety_hazard_clear_on_recovery.md` §10: mark the
  SAFETY-NM-REFIRE-UNWIRED fold-out as "shipped v<next>" with back-link.

## 6. Non-goals

- No change to NM cooldown defaults (`DEFAULT_NM_COOLDOWN_SMOKE=2` etc.) —
  explicitly a knob on the entity ladder (operator-tunable), not a code
  decision here.
- No change to the life-safety hazard set (`NM_LIFE_SAFETY_HAZARDS`).
- No new `NotificationAction` emission sites, no new DAO, no schema change.
- No behavior change for CO2/TVOC/humidity hazards (NM treats them as
  non-life-safety; they already use the 300 s cadence).
- Not re-opening SAFETY-HAZARD-NEVER-CLEARS-1 — treat its machinery
  (`_hazard_clear_pending`, `_sweep_hazard_clears`, `HAZARD_MIN_HOLD_S`,
  `_record_sensor_recovery/_relapse`) as a stable primitive to be read.

## 7. Knobs on the ladder

Rule: "Numbers get knobs". New numbers introduced here: **none**. Reused
numbers and their rung:

| Number | Rung | Home | Why |
|---|---|---|---|
| `HAZARD_MIN_HOLD_S = 300` | 1 (module const in `safety.py`) | shipped v5.103.61 | Safety-semantics bound; recovery minimum. |
| `DEFAULT_NM_COOLDOWN_SMOKE/_CO = 2 min` | 2 (options flow) | `const.py:3335-3358` | Operator-tunable paging cadence. |
| `NM_REPEAT_INTERVAL_LIFE_SAFETY = 30 s` | 1 (module const) | `const.py:3387` | Safety contract. |

No new knob to defend.

## 8. Acceptance criteria

### D1 — hazard_type+location on NotificationAction
- **Verify (unit):** `NotificationAction` emitted by `_respond_to_hazard` has
  `hazard_type == hazard.type.value` and `location == hazard.location`.
- **Verify (log):** after a test fire,
  `notification_log` row has `hazard_type` and `location` non-NULL and
  equal to the raising sensor's location (not `""`).
- **Test:** `test_safety_notification_action_carries_hazard_type_location`.
- **Live:** `sqlite3 universal_room_automation.db "SELECT ts, coordinator_id, hazard_type, location FROM notification_log WHERE coordinator_id='safety' AND ts > datetime('now','-1 day');"` — zero rows with `hazard_type IS NULL OR hazard_type=''` (post-deploy, after the next real or test hazard).

### D2 — is_hazard_active hold-aware
- **Verify (still-active):** mid-hazard, `safety.is_hazard_active("smoke", "<room>") is True`.
- **Verify (post-clear, hold elapsed):** 301 s after recovery, key popped,
  `is_hazard_active(...) is False`.
- **Verify (pending-clear discriminator — key disambiguation):** 60 s after
  recovery while key still in `_hazard_clear_pending`, `is_hazard_active(...) is False`. This observation DIFFERS from the "cleared" case (same return value) *but* can be discriminated by inspecting `_active_hazards` membership — the key is present during the pending-clear window and absent after it. Reviewers B/C validate both branches hit via mutation anchors in D3.
- **Verify (relapse):** relapse during hold → `is_hazard_active(...) is True`.
- **Test:** the four `test_safety_is_hazard_active_*` tests in D3.
- **Live:** after the next real alert that recovers, scan the HA log for
  `nm:3042 "Hazard %s at %s still active after cooldown — re-firing"` — expect
  **zero** such lines keyed on a hazard whose contributor had already recovered.
  (Discriminator vs the current bug: today we see **zero** re-fire lines ever,
  including for still-active hazards. Post-ship we expect zero for cleared
  hazards and ≥1 per real still-active life-safety event.)

### D3 — tests
- **Test:** all five functions in D3 PASS on build; mutation-anchored (each
  bypass causes a specific test to fail).

## 9. Review framings (Tier 2-DB, three framing-disjoint reviews)

- **A — data integrity + payload shape.** Does every emission site in
  `safety.py` still produce a well-formed `NotificationAction`? Does
  `notification_log` row shape remain backward-compatible? Any site that
  constructs a `Hazard` without `location` set (would crash now, worth
  re-greping)?
- **B — migration correctness + signal chain integrity.** Full trace from
  `_respond_to_hazard` → `manager.py:1070` → `NM.async_notify` → cooldown →
  `_re_evaluate_hazard` → `is_hazard_active`. Does the smoke/CO 2-min
  cooldown interact correctly with the 300 s clear hold *at every reachable
  state* (hazard active, hazard recovering mid-cooldown, hazard relapsing
  mid-cooldown, hazard cleared before cooldown fires)? Enumerate every
  `is_hazard_active` reader (grep: `coordinator.is_hazard_active`,
  `self.is_hazard_active`) and confirm no caller depends on the
  pre-change behavior (treating a pending-clear key as active).
- **C — new surfaces + test fixture authority.** Mutation-anchor every
  test in D3: delete the `hazard_type=` kwarg → the carrying test MUST
  fail; revert D2 → the hold-aware test MUST fail. Verify tests drive the
  real `_respond_to_hazard` path, not a stub.

Life-safety expectations: the discriminator in §8 ("zero re-fire lines"
→ "one per real event") is the authoritative post-deploy signal; a
sentinels-only live log is a payload-shape failure.

## 10. Open questions

1. **Pending-clear discriminator ambiguity.** D2 reports both "already
   cleared" and "pending-clear hold running" as `is_hazard_active == False`.
   Operator-facing consequence: during the 300 s pending-clear window the
   NM re-fire gate sees "cleared" while the dashboard safety-alert entity
   still reads ON (deliberate, from v5.103.61). This is the intended
   `constraint_2026_10_14` behavior. Flagging for operator confirmation
   that this is the preferred resolution (vs. shortening the clear hold
   or lengthening the smoke/CO cooldown).
2. **Non-life-safety re-fire.** `high_humidity`, `low_humidity`, `high_co2`,
   `high_tvoc`, `hvac_failure` now carry `hazard_type` through the NM
   cooldown gate for the first time. NM will dispatch a 300 s
   non-life-safety re-fire if the hazard is still active. Confirm the
   operator wants a single CRITICAL re-page on, e.g., a hvac_failure that
   stays stuck. Alternative: scope D1 to only emit `hazard_type` for the
   life-safety subset. Default recommendation: emit for all —
   `is_hazard_active` is now hold-aware, so the risk is bounded.
3. **`fire` and `intruder` not emitted by Safety.** Reference only — these
   are in `NM_LIFE_SAFETY_HAZARDS` but emitted by security, not safety.
   Verified by grep: no `HazardType.FIRE` production emission in `safety.py`
   (only the enum definition). No action.

## Orchestrator rulings on open questions (2026-10-15)
- **Q1:** YES. While a hazard's clear hold is pending with no raising sensor, the dashboard may read ON for up to 300 s while the NM re-fire gate reads cleared. This is the card's constraint_2026_10_14, and it avoids touching the shipped hold or the smoke/CO cooldown.
- **Q2:** D1 adds hazard_type/location at the single NotificationAction site, so every hazard round-trips. Whether a hazard re-pages stays governed by NM's existing severity/re-fire policy. No per-type scoping in Safety (one site, no new branch). The reviewer verifies that NM's re-fire policy doesn't start re-paging advisory/MEDIUM comfort hazards; if it would, scope the re-fire to life-safety in NM's existing policy, not in Safety.
- **Q3:** noted; no action.
