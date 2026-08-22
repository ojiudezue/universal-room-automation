# PLANNING — AC-RAMP-PIPELINE-HARDENING-1

**Tier:** 3.
**Supersedes:** `PLANNING_ac_ramp_recurrence_escalation.md` (which now
carries a supersession header). Read that header first, then that
document's **§7.1** (the measured rejection of the count trigger — do
not resurrect), **§12** (numbered corrections carried in), and **§13**
(files-touched inventory for the D2-D8 carry-forward set). This plan
CITES those sections; it does not repeat them. Where line numbers below
diverge from the superseded plan the divergence is deliberate — the
tree has moved, every anchor here was re-grepped 2026-08-22.

**Governing frame:** ONE pipeline, THREE compounding leaks. Fixing any
in isolation is throwing money away because the next leak eats the
gain. The invariant on the whole pipeline is stated in §2. The three
leaks are Gate 4 (detect), scoring (classify), and escalation (act).

**Central argument — repeat prominently to reviewers:** once scoring
can honestly say "this nudge did not hold", the EXISTING
`if escalate:` branch at `hvac_override.py:3891` fires on its own. No
recurrence counter, no N/W to calibrate. The count-based trigger the
probe killed (superseded §7.1) becomes UNNECESSARY, not merely
unbuilt. Deleting the need is the deliverable.

---

## 0. Verified pipeline — re-grepped 2026-08-22

Every anchor below was `grep -n`ed on 2026-08-22 against
`custom_components/universal_room_automation/`. Line numbers here
supersede the superseded plan's §0 where they differ (the tree has
moved since v5.86.0).

- **STAGE 1 — DETECT.** `check_ac_reset` at
  `domain_coordinators/hvac_override.py:2684`. Gate ladder 0a→9 at
  `:2720-2860`. **Gate 4 (the LEAK):** `if zone.hvac_action !=
  "cooling"` at `:2779`.
- **STAGE 2 — NUDGE.** `_perform_soft_nudge` at `:3210`;
  `_restore_after_nudge` at `:3414`. Mechanically effective ~99%.
- **STAGE 3 — SCORE.** Classifier at `:3802-3823`. Four branches:
  `inconclusive` (escalate=False, `:3808`); `ineffective_no_samples`
  (escalate=True, `:3814`); **`effective` (escalate=False, `:3819`) —
  the LEAK: 307/308**; `ineffective` (escalate=True, `:3823`).
  Keys off `post_min` in the trailing window.
- **STAGE 4 — ESCALATE.** `if escalate:` at `:3891`, calling
  `_perform_hard_reset_escalation` at `:3901`; definition at
  `:3925`. Never fires because Stage 3 never says failed. Wired,
  working, waiting.
- **STAGE 5 — RESET.** `_perform_ac_reset` at `:2871`
  (`AC_RESET_OFF_DURATION_SECONDS = 60` at `hvac_const.py:493`);
  `_restore_after_reset` at `:2938`; `_verify_restore` at `:2985`.
  9 executions ever, all mechanically fine. Preset restore fixed in
  v5.88.1.

**STRUCTURAL FACT — restate in every review round:** `check_ac_reset`
is named for RESET but is the SOFT-NUDGE entry point (see its Gate 0b
comment at `:2728-2741`: "`check_ac_reset` is the soft-nudge entry
point; with nudges disabled it has no work"). **The ONLY automatic
route to a hard reset runs through a nudge.** Gate 4 therefore
gates the ENTIRE ladder — detect, nudge, score, escalate, reset — not
just nudging. This is why leak 1 compounds with leaks 2 and 3 rather
than adding to them.

---

## 1. Institutional context verified

### Greps run 2026-08-22

| Proposed | Grep | Result | Disposition |
|---|---|---|---|
| Draw-based Gate-4 predicate helper | `grep -n "def .*eligible_for_nudge\|def .*compressor_active" hvac_override.py` | None. | **NEW helper** `_zone_is_actively_cooling(zone, state)` in `hvac_override.py`; consumes existing `zone.ac_load_sensor` (Gate 3, `:2774`) and `climate` entity attrs. |
| SPAN circuit draw per zone | `grep -n "ac_load_sensor" hvac_override.py` | Wired at Gate 3 (`:2774`) as `zone.ac_load_sensor`; already the trust signal for Gates 7-8 (kWh threshold + sustained). | **REUSED** — this is the ground-truth already in the coordinator. |
| `hvac_mode` (config, `heat_cool`/`heat`/`off`) | zone attr | `zone.hvac_mode` populated from climate entity state. | **REUSED.** |
| `blower_rpm` availability | Not in URA code today (`grep -n "blower_rpm"` on `hvac_override.py` → 0 hits). | Present on the Carrier climate entity per operator observation (~1000 while `conditioning` said idle). | **NEW** attribute read via `hass.states.get(zone.climate_entity).attributes.get("blower_rpm")`. Corroboration only, never the primary predicate. |
| Periodic `homeassistant.update_entity` service call from URA | `grep -n "update_entity" custom_components/universal_room_automation/*.py` | Only entity-registry `async_update_entity` (unique-id/rename ops in `__init__.py`, `switch.py`, `person_coordinator.py`). No periodic state-refresh caller exists in URA today. | **NEW** — see §3-D9. |
| Actuation-lag columns on `ac_ramp_events` | `grep -n "reported_at_ts\|physical_at_ts" database.py` | None. | **NEW columns** via the same guarded-ALTER pattern the superseded plan D4 uses (`database.py:1681-1712`). See §3-D10. |
| Draw-based Gate-4 knob | grep | None. | **NEW** module constants at rung 1 (§5); no operator-facing knob (safety-adjacent). |
| Refresh cadence + entities knobs | grep | None. | **NEW** options-flow (rung 2) for cadence; **REUSED** `zone.climate_entity` list for the target set. |

### Prior planning docs consulted

- **`PLANNING_ac_ramp_recurrence_escalation.md`** — full read. §0 (verified
  anchors), §7.1 (probe rejection of the count trigger), §12 (numbered
  corrections), §13 (files-touched inventory), plus D2/D3/D5/D6/D7/D8
  which this plan carries forward unchanged in intent.
- **`PLANNING_v4.5.11_ac_energy_aware_ramp_down.md`** — the objective doc
  ("rapid compressor cycling is the worst failure mode") drives
  Invariant I here.
- **`PLANNING_hvac_governed_excursion.md`** — v5.86.0 shipped the
  preset/mode/restore telemetry columns and their nudge-path producer;
  D5 here (from superseded plan) enriches the hard-reset producer sites
  directly, so ship order between the two cycles remains free.

### Memories pulled

- `feedback_measure_before_build.md` — a §7 probe discharge is scoped
  for the actuation-lag canary (D10) BEFORE build; the fresh-poll
  workaround (D9) is scoped without a probe because the operator has
  already reproduced it manually (reload → truth appears).
- `feedback_marginal_benefit_pushback.md` — applied twice in §11.
- `feedback_falsify_before_asserting.md` — §2 states both invariants
  in falsifiable form; §8 discriminates.
- `feedback_wire_in_anchor_mandatory.md` — §12 pairs every deliverable
  with its enclosing method AND a mutation-drill site that MUST fail.
- `feedback_parent_reload_watchdog_hazard.md` — cited in §3-D9 to
  justify `homeassistant.update_entity` over a config-entry reload.
- `feedback_no_fabrication.md` — `ha_carrier` internals are cited from
  operator report (climate.py:190-195); this repo does not read that
  file, and D9's design does NOT depend on knowing its exact shape.
- `project_optimizer_db_write_flood_incident_2026_06_09.md` — invoked in
  §3-D10 to require append-only rows and no per-tick UPDATEs.

### Design docs

- `docs/Coordinator/HVAC.md` (if present) — read end-to-end. Any
  discrepancy with the greps here is a doc bug; source wins.

### Code read end-to-end during scoping (this cycle)

- `hvac_override.py`: 2720-2860 (`check_ac_reset` ladder including Gate
  4 at 2779); 2871-3055 (`_perform_ac_reset` / `_restore_after_reset` /
  `_verify_restore`); 3210-3260 (soft nudge perform); 3414-3540
  (restore-after-nudge + settled telemetry); 3802-3823 (classifier);
  3891-3925 (escalate branch and `_perform_hard_reset_escalation`
  entry).
- `hvac_const.py`: 480-540 (AC reset legacy) and 570-590
  (`AC_NUDGE_RESTORE_SETTLE_DELAY_S = 12` — rung-1 sibling for D6).
- Superseded plan §0-§13 (full).

---

## 2. Falsifiable invariants — the whole pipeline

**Invariant P — Pipeline Blindness Ceiling (leak 1).**
> Over any rolling 7-day window, the duration-weighted fraction of time
> in which BOTH (a) the zone's SPAN `ac_load_sensor` reads above the
> per-zone kWh-rate threshold AND (b) `check_ac_reset` short-circuits at
> Gate 4 (`zone.hvac_action != "cooling"`) is bounded by
> `GATE4_MAX_BLIND_FRACTION` (see §5, default 1.0%). Under the fix the
> observed fraction should be near zero for all three zones. Under a
> plausible different failure (Gate 4 replaced but the replacement
> predicate is itself stale — e.g. still keys off a cloud-reported
> attribute) the fraction stays at the pre-fix 7-13%. The two
> observations diverge; the invariant is falsifiable and discriminating.

**Invariant S — Scoring Honesty (leak 2).**
> Every `nudge_evaluated` row classified `effective=True` whose zone's
> `ac_load_sensor` returns to a rate above the Gate-7 threshold within
> `CONF_HVAC_AC_DURABILITY_WINDOW` minutes (default 30) MUST land in
> `ac_ramp_events` with `durable=0` and a non-NULL `durable_minutes`.
> Under a plausible different failure (`durable` set to `1` because the
> callback closed over the wrong `event_id` or read kW too early) the
> observation is `durable=1` on rows the compressor demonstrably
> re-ramped after. Discriminates because the passive `ac_load_sensor`
> series and the row's `durable` are independently authored.

**Invariant E — Escalation is Reachable (leak 3, and the central claim).**
> For every zone, if there exist `N_ESC` consecutive `nudge_evaluated`
> rows (default N_ESC = 2, §5) within `CONF_HVAC_AC_DURABILITY_WINDOW`
> minutes each carrying `durable=0`, then the immediately-following
> classifier evaluation MUST produce `escalate=True` and MUST route
> through the EXISTING `if escalate:` branch at
> `hvac_override.py:3891`. NO new escalation predicate outside that
> branch is introduced. Under a plausible different failure ("we added
> another escalation path") the observation is a `hard_reset_started`
> row not preceded by that branch executing — falsifiable via an
> in-suite call-graph assertion.

**Invariant I** (Bounded Compressor Cycling) and **Invariant III**
(Aggregator Non-Pollution) — REUSED verbatim from the superseded plan's
§2. Not repeated here.

---

## 3. Deliverables

### D-GATE4 — Replace cloud-reported veto with a draw-based predicate  (**status on ship: LIVE**)

**Site:** `hvac_override.py:2779` (Gate 4). Today: `if zone.hvac_action
!= "cooling": ... continue`. Replaces with a call to a new helper
`_zone_is_actively_cooling(zone, state) -> bool`, and short-circuits
`continue` only when the helper returns False.

**Predicate — TRUST LADDER, in order:**

1. **CONFIG guard (still Gate 4's real job, do not lose it).**
   `zone.hvac_mode` must be in `{"cool", "heat_cool", "auto"}`. If
   `heat`/`off`/`unknown`/`None`, return False. `hvac_mode` is CONFIG
   (stable, changes only on operator action), not a momentary
   coordinator field, so it does NOT flap with a stale poll. This
   preserves the "do not fire a cooling nudge while the system is
   heating" behaviour Gate 4 was legitimately for.
2. **GROUND-TRUTH draw.** `zone.ac_load_sensor` state parsed as float
   ≥ `AC_ACTIVELY_COOLING_KW_MIN` (default 0.5 kW, rung 1, §5). SPAN
   circuit metering is not cloud-cached — it is polled locally. This
   is the load-bearing signal.
3. **CORROBORATION (optional bump, not required).** If the climate
   entity's `blower_rpm` attribute is present AND > 0, corroborates
   step 2. If step 2 already passes, step 3 is not required. If step 2
   fails, step 3 CANNOT rescue — draw at or near zero means the
   compressor is off regardless of blower.
4. **`hvac_action` is CORROBORATION ONLY, never a veto.** If step 1
   and step 2 pass, we proceed even if `hvac_action` says `idle`. Log
   a one-line INFO with a rate-limit key (per §3-D10 write-flood
   rules) so the divergence is observable but does not spam.

The helper returns True iff step 1 AND step 2 pass.

**What is NOT here:** No dependency on D9 (the refresh workaround).
Gate 4's fix stands on SPAN + hvac_mode alone. The Non-Goals section
restates this.

**Producer / consumer.**
- Producer of the predicate: `_zone_is_actively_cooling` reads
  `zone.hvac_mode`, `zone.ac_load_sensor` state, and (optionally) the
  climate entity's `blower_rpm` attribute. Dependencies: SPAN
  integration healthy (its own availability sensor);
  `zone.climate_entity` state resolvable.
- Consumers: `check_ac_reset` at `:2779` (trust — the ONLY consumer);
  a new diagnostic sensor `sensor.ac_gate4_blind_fraction_7d_<zone>`
  (display, see §3-D8-extension) computed by comparing the incoming
  SPAN rate against the Gate-7 threshold over the last 7 days AND
  cross-referencing the historical Gate-4 short-circuit.

**Restart safety:** REBUILD. Helper is stateless. No new persistent
fields.

**Rollout guard:** knob `hvac_ac_gate4_predicate_mode` (Select),
values `legacy` / `shadow` / `live`, default `shadow` on FIRST BOOT
after deploy, flipped to `live` by the operator after 24-48 h of
shadow observation. In `shadow` mode the legacy Gate-4 veto still
runs, AND the new helper's decision is logged (one event per
divergence, edge-triggered) as `ac_ramp_events` type
`gate4_divergence_shadow`. In `live` mode the new helper decides.
This mirrors the D1 3-state Select pattern from the superseded plan
§3-D1 and inherits its kill-switch semantics.

### D-SCORE — `durable`/`durable_minutes` delayed classifier (**status on ship: LIVE, additive**)

**IDENTICAL to the superseded plan's D4** — carried forward unchanged.
Read superseded §3-D4 for producer/consumer, cancel-vs-truncate rule,
`event_id` back-fill (requires `log_ac_ramp_event` to return
`cursor.lastrowid`), and `in_flight_durable_started_ts` restart-safety
column. Do not re-litigate; do not modify.

**The central argument, restated as a plan clause:** the ONLY new
consumer that reads `durable` for trust is a small change at the
classifier — see D-ESC-CONSUME below. No recurrence counter. No new
escalation path. **The existing `if escalate:` branch is the only
route out.**

### D-ESC-CONSUME — Teach the classifier to use `durable` (**status on ship: SHADOW → LIVE via a Select**)

**Site:** `hvac_override.py:3802-3823`. The classifier today keys off
`post_min` alone. This deliverable adds ONE new branch, evaluated
AFTER the existing four:

- If the just-computed classification is `effective` AND the previous
  `N_ESC - 1` (default 1) `nudge_evaluated` rows for this zone within
  the durability window carry `durable=0`, THEN promote to
  `classification="ineffective_durable_fail"`, set `effective=False`
  (see non-goal 1 for the caveat), `escalate=True`.

**Non-goal 1 explanation (critical, read twice):** the superseded plan
D4 forbids MUTATING `effective` on the already-written row from the
delayed callback. That rule stands. This deliverable does NOT mutate
past rows; it uses PAST rows' `durable` field (already written) as
inputs to classify the CURRENT row, whose `effective` has not yet been
written. The distinction is producer identity: `_write_durable` never
touches `effective`; only the classifier writes `effective`, and only
on the row it is currently evaluating. Reviewer C mutation drill Site 4
(carried forward from superseded §11 Site 4) still applies as a
regression guard.

**Rollout guard:** knob `hvac_ac_escalation_source` (Select), values
`legacy` (only `ineffective`/`ineffective_no_samples` escalate — TODAY)
/ `shadow` (compute the new branch; on hit, write ONE
`ac_ramp_events` row `escalation_would_promote` and DO NOT call
`_perform_hard_reset_escalation`) / `live` (on hit, call
`_perform_hard_reset_escalation` with `triggered_by="durability_fail"`).
Default `shadow` on first boot; flip to `live` after ≥ 3 shadow
observations that look right per the operator. Kill-switch: `legacy`.

**No lockout on cap.** The `engage_lockout_on_cap=False` requirement
from superseded §3-D1 (Reviewer critical #1) MUST be applied to the
`durability_fail` caller too. A partitioned-budget denial for a
durability escalation is "budget spent", NOT "controller is broken".
Copy that discipline verbatim.

**Consumer count on `durable`:** two — this classifier branch (trust)
and the display sensor from D4. No third consumer.

**Restart safety:** REBUILD. The classifier reads the DB on entry; no
new in-memory state to persist.

### D2-D8 carry-forward from the superseded plan

All eight (D2 partitioned budgets · D3 soft-nudge daily cap · D5
hard-reset row enrichment · D6 reset-outcome drift discriminator · D7
`AC_RESET_OFF_DURATION_SECONDS` rung-3 promotion · D8 observability
sensors + declined trail) ship UNCHANGED IN INTENT from the superseded
plan.

Two orchestrator rulings (operator-locked, do not revisit):
- **D2 defaults: DAY 2 / NIGHT 2.** OPERATOR-STATED 2026-08-22 ("I said 2/2").
  CORRECTION OF RECORD: an earlier note attributed "DAY 1, NIGHT 2" to the
  operator. That was the ORCHESTRATOR's invention written into the card as if it
  were the operator's suggestion, and then later argued against by the same
  orchestrator as "a loosening arriving as a default". Both the proposal and the
  objection were self-generated. The operator's actual stated intent was that
  resets be time-windowed so they cannot all be burned during the day.
  THE MECHANISM IS A RESERVE, NOT A CAP. 2/2 means the night ALWAYS has its full
  allowance regardless of daytime consumption — which is precisely the failure the
  operator anticipated ("so they cannot all be burned up during the day").
  CONSEQUENCE, stated plainly: the theoretical per-zone daily maximum rises from 2
  to 4. The 120-minute global minimum interval still bounds the rate, and no reset
  fires at all until D-SCORE is flipped live. Do not "helpfully" restore a lower
  default.
- **D6 reset-end temp** is read at `restore + AC_RESET_OUTCOME_SETTLE_S`
  (rung 1, sibling of `AC_NUDGE_RESTORE_SETTLE_DELAY_S = 12` at
  `hvac_const.py:579`), NOT at the instant `_restore_after_reset`
  returns.

Line-number anchors in the superseded §0 are older than the tree.
Builder MUST re-grep per §0 above. Specifically: `_perform_soft_nudge`
is at `:3210` (not `:3099`); `_restore_after_reset` at `:2938` (not
`:2921`); `_perform_hard_reset_escalation` at `:3925` (not `:3874`);
`_perform_ac_reset` at `:2871` (not `:2884`). Every superseded-plan
site referenced by builder work MUST be re-grepped before edit.

### D9 — Periodic freshness refresh for `ha_carrier`  (**status on ship: LIVE, defaulted OFF**)

**This is a workaround for a third-party integration defect.** State it
in-code, state it in-doc, and state it here: `ha_carrier` derives
`hvac_action` from `status_zone.conditioning` and its cloud poll goes
stale under conditions the operator has reproduced (reload → truth
appears). The correct long-term fix is upstream. This deliverable buys
observability and one class of freshness recovery in the meantime.

**Design.**

- **⚠️ MECHANISM IS NOT YET ESTABLISHED — D9 IS PROBE-GATED. DO NOT BUILD IT
  UNTIL PROBE C RETURNS.** An earlier draft of this plan prescribed
  `homeassistant.update_entity`. That prescription is WITHDRAWN as unproven, and
  the evidence points AGAINST it:
    * `ha_carrier` entities ARE `CoordinatorEntity` (verified,
      `carrier_entity.py:17`), so `update_entity` →
      `CoordinatorEntity.async_update()` → `coordinator.async_request_refresh()`
      does reach a refresh. The MECHANISM EXISTS.
    * BUT that is THE SAME FETCH PATH as the periodic poll, and
      `DEFAULT_UPDATE_INTERVAL_MINUTES = 30` (`const.py:46`). Measured blind
      episodes ran **96, 108 and 68 minutes** — i.e. roughly three scheduled polls
      occurred inside a single blind window and `hvac_action` stayed `idle`
      throughout. **Polling sooner cannot fix a value that survived three polls.**
    * The operator's RELOAD does clear it. Reload tears down and rebuilds the
      `carrier_api` client and its session; refresh reuses them. That points at a
      stale CLIENT/SESSION object, not a stale poll — a fault class `update_entity`
      does not touch.
    * The post-write intercept guard is NOT the cause: its own docstring states
      volatile status (temperature, humidity, **conditioning**, blower) is
      "deliberately excluded". Ruled out.
  **PROBE C (blocking, cheap):** at the next blind episode (draw above threshold
  AND `hvac_action != cooling` — these occurred on 8 of 8 observed days, so the
  wait is short), call `homeassistant.update_entity` and record whether the value
  clears. If it does not, call a config-entry reload and confirm that does. ONE
  episode settles it. Write the result here as §D9.1 before building.
  **If `update_entity` proves ineffective**, the deliverable must either use the
  mechanism that IS proven to work (accepting the reload blast-radius argument
  below as a cost to be justified, not a rule to be obeyed) or be DROPPED and the
  defect pursued upstream. Do NOT ship a refresh that does not refresh.
  Reload caveat retained for whichever path is chosen: see
  `feedback_parent_reload_watchdog_hazard.md`. `ha_carrier`'s entry is not URA's
  parent entry, but the general "reload has hidden lifecycle blast radius"
  reasoning still applies.
- **Target set:** the climate entities configured for every HVAC zone
  (`zone.climate_entity` collected across all zones). No sibling
  sensors. Refreshing the climate entity refreshes the coordinator
  which then repopulates `hvac_action`, `blower_rpm`, and setpoint
  attrs together.
- **Cadence knob:** `hvac_ac_carrier_refresh_interval_s`, options-flow
  integer, default `0` (feature disabled), operator-set minimum `120`
  when enabled, maximum `900`. Rung 2 (§5) — set once per household,
  not a live tuning slider. Setting to `0` disables the periodic
  task.
- **Failure mode of the refresh itself.** The scheduled task calls
  `hass.services.async_call("homeassistant", "update_entity",
  {"entity_id": [...]})` inside a try/except with a 10s timeout. On
  timeout or exception: log a WARN with a rate-limit key
  (`ac_ramp_refresh_stall`), increment a diagnostic counter, DO NOT
  retry until the next scheduled tick. Repeated failures over 6 ticks
  fire ONE NM notification (edge-triggered) suggesting the operator
  inspect `ha_carrier`. Under NO circumstance does this deliverable
  reload a config entry as a fallback.
- **Scheduler:** single coordinator-level `async_track_time_interval`
  registered in HVAC coordinator setup, unregistered in teardown
  (existing pattern at `hvac_override.py:1439-1459` reused).

**Producer / consumer.**
- Producer: the scheduled callback.
- Consumers: `ha_carrier` (external — pushes fresh values into HA
  state); INDIRECTLY the diagnostic sensor
  `sensor.ac_carrier_refresh_last_ok_ts`. **D-GATE4 does NOT depend
  on this refresh** (restated because it matters).

**Restart safety:** REBUILD. Interval knob persists; the task itself
is re-registered on setup.

**Non-goal for D9 (critical):** D-GATE4 MUST NOT read the
"last-refresh-ok timestamp" or otherwise gate on refresh health.
Coupling them would collapse two independent mitigations into one
compound point of failure. Reviewer B specifically checks this.

### D10 — Actuation-lag canary  (**probe first, then LIVE telemetry**)

Three timestamps per nudge, all stored on the `nudge_started` row (or
its paired evaluated row where clock precision matters):

- **(a) `commanded_ts`** — the existing `timestamp` on `nudge_started`
  in `ac_ramp_events` — no new column needed.
- **(b) `reported_at_ts`** — first HA state change on the zone's
  climate entity whose `target_temp_high` attribute equals the
  nudged value, within a 60s window post-command. NEW column on
  `ac_ramp_events`, nullable.
- **(c) `physical_at_ts`** — first SPAN sample where
  `ac_load_sensor` drops below `AC_ACTIVELY_COOLING_KW_MIN` within
  the same 60s window. NEW column, nullable. (Already measured on
  average as ~72s median physical lag; per-nudge storage is new.)

**Measure BEFORE build — mandatory probe (§7).** The (a)→(b) gap has
NEVER been measured. Before building this deliverable, run a one-shot
retrospective probe over the HA recorder joining the existing
`ac_ramp_events.nudge_started` rows to the HA recorder history of
`climate.<zone>.target_temp_high` state changes. If the (a)→(b)
gap is consistently near-zero (< 2s), retrospective computation
suffices and the NEW columns are UNNECESSARY — kill the build of D10
and rely on the probe artefact. If the gap is meaningful (> 5s p50)
OR high-variance, build the columns.

**Producer:** `_perform_soft_nudge` records `commanded_ts`
(implicitly, via existing writes); a lightweight per-zone async
listener registered for the duration of the nudge captures (b) and
(c) and calls `update_ac_ramp_event_fields(event_id, ...)`. Both
listeners are `async_track_state_change_event` handles with a hard
timeout of `command + 60s`, unregistered on fire OR timeout OR
teardown.

**Consumer:** two display sensors
`sensor.ac_nudge_report_lag_p50_<zone>` and
`sensor.ac_nudge_physical_lag_p50_<zone>`, both rolling over last 24 h.
No trust consumer. This is telemetry.

**Restart safety:** REBUILD. Any in-flight lag listener that misses its
fire due to a restart writes NULL for the missed field; the row is
still on disk with `commanded_ts`, so the miss is visible and
attributable.

**Rate-limit / write-flood discipline:** each nudge produces AT MOST
one row write and at most two column back-fills within 60s. Bounded
above by the D3 daily cap (default 50/day per zone). Well below any
write-queue threshold; the optimizer-write-flood incident precedent
(memory `project_optimizer_db_write_flood_incident_2026_06_09.md`)
is satisfied.

---

## 4. Non-goals — explicit

1. Do NOT redefine `effective` on already-written rows. (Superseded
   plan non-goal 1, carried.)
2. Do NOT introduce a count-based recurrence trigger. Superseded §7.1
   rejected it on measured grounds; the successor central claim is
   that D-ESC-CONSUME makes it unnecessary.
3. Do NOT make D-GATE4 depend on D9. Two mitigations, kept
   independent.
4. Do NOT use `config_entry.async_reload` or
   `homeassistant.reload_config_entry` for periodic refresh. Named and
   forbidden.
5. Do NOT let `hvac_action` veto D-GATE4. Corroboration only. Any
   builder-added code path that lets a cloud-reported momentary
   attribute short-circuit a SPAN-based predicate is a Reviewer D
   finding.
6. Do NOT rebuild working machinery: soft-nudge perform/restore,
   `_perform_hard_reset_escalation` actuator, `_perform_ac_reset`,
   `_restore_after_reset`, `_verify_restore`, `async_startup_ramp_audit`,
   the `ac_reset_state` / `ac_ramp_events` DDL. Deltas only.
7. Do NOT couple D-GATE4 or D-ESC-CONSUME to house-state, occupancy,
   or preset. Pure HVAC-domain signals only.
8. Do NOT create a new escalation code path outside
   `if escalate:` at `hvac_override.py:3891`. The whole cycle's
   value depends on routing everything through it.
9. Do NOT delete `AC_RESET_MAX_PER_DAY` — KEEP + WIRE per superseded
   plan §3-D8 / §12-22.
10. Do NOT extend the D3 soft-nudge cap to the manual `force_nudge`
    button. Superseded plan non-goal 9, carried.

---

## 5. Knob ladder — every new number, placed and justified

| Knob | Default | Rung | Why here |
|---|---|---|---|
| `hvac_ac_gate4_predicate_mode` (Select) | `shadow` on first boot | 3 (Select) | Kill-switch + 24-48h operator observation gate; boolean insufficient because we need `legacy`+`shadow`+`live`. |
| `hvac_ac_escalation_source` (Select) | `shadow` on first boot | 3 (Select) | Same three-state discipline; changing escalation eligibility is a trust decision. |
| `AC_ACTIVELY_COOLING_KW_MIN` (module const, kW) | `0.5` | 1 | Safety-adjacent primitive. A change alters what "actively cooling" means; must require code review. NOT operator-tunable. |
| `AC_ACTIVELY_COOLING_BLOWER_RPM_MIN` (module const, rpm) | `100` | 1 | Same reasoning; corroboration threshold only. |
| `GATE4_MAX_BLIND_FRACTION` (module const, ratio) | `0.01` | 1 | Invariant P bound; changing it changes what we assert. Rung 1. |
| `CONF_HVAC_AC_DURABILITY_WINDOW` (options int, minutes) | `30` | 2 | Set once; retroactive re-classification hazard means it should not be a live slider. (Superseded plan §5, carried.) |
| `hvac_ac_esc_consume_n` (Number int) | `2` | 3 | The `N_ESC` in Invariant E. Live-tunable by observation of shadow-mode data. |
| `hvac_ac_carrier_refresh_interval_s` (options int, s) | `0` (disabled) | 2 | Workaround knob; if the operator turns it on it stays on. Not a live-tuning surface. |
| **Carried from superseded §5** — the D2/D3/D6/D7 knob rows apply verbatim. Re-print not repeated here. |

**Kill-switch semantics.** `hvac_ac_gate4_predicate_mode = legacy`
restores the pre-fix Gate 4 verbatim (single-line
`hvac_action != "cooling"` guard). `hvac_ac_escalation_source =
legacy` restores today's classifier behaviour verbatim.
`hvac_ac_carrier_refresh_interval_s = 0` cancels the periodic task on
the next coordinator tick.

---

## 6. Producer / consumer map — every new value

### `_zone_is_actively_cooling` predicate (D-GATE4)

- **Producer.** New helper on the HVAC coordinator. Reads
  `zone.hvac_mode` (CONFIG); `hass.states.get(zone.ac_load_sensor).state`
  parsed float; optional
  `hass.states.get(zone.climate_entity).attributes.get("blower_rpm")`.
  Dependencies healthy: SPAN integration (its own availability
  sensor), climate entity resolvable (not `unavailable`).
- **Consumers.** ONE trust consumer:
  `check_ac_reset` at `:2779` (replacing the cloud-veto Gate 4 body).
  ONE display consumer: `sensor.ac_gate4_blind_fraction_7d_<zone>`.

### `durable` / `durable_minutes` (D-SCORE, carried) + new trust consumer (D-ESC-CONSUME)

- **Producer.** `_write_durable` (superseded plan §3-D4), unchanged.
- **Consumers.** (1) The classifier's new post-hoc branch (trust); (2)
  `sensor.ac_ramp_durability_rate_<zone>` (display).

### `escalation_would_promote` shadow rows (D-ESC-CONSUME shadow mode)

- **Producer.** The classifier when `hvac_ac_escalation_source = shadow`
  AND the durability-fail condition hits. Edge-triggered: one row per
  distinct triggering `nudge_evaluated` `event_id`, no repeat within
  15 minutes on the same zone.
- **Consumers.** Operator diagnostics only; not read by any trust
  path.

### `gate4_divergence_shadow` rows (D-GATE4 shadow mode)

- **Producer.** In shadow mode the new helper is computed but the
  legacy Gate 4 still decides. When their decisions disagree
  (legacy=veto, new=proceed OR vice versa), write ONE row per
  divergence, edge-triggered per §3-D8's write-flood discipline.
- **Consumers.** Operator diagnostics only.

### D9 refresh telemetry

- **Producer.** The scheduled task's success / stall counters.
- **Consumers.** `sensor.ac_carrier_refresh_last_ok_ts` and a WARN log
  scanner. NOT consumed by D-GATE4 (non-goal 3).

### D10 lag columns

- **Producer.** Per-nudge state-change listeners; see §3-D10.
- **Consumers.** Two display sensors; no trust consumer.

---

## 7. Measure-before-build probes

Two probes; both run BEFORE any build dispatch. Their outputs go into
§7.1 (D-GATE4 sizing) and §7.2 (D10 go/no-go).

### Probe A — D-GATE4 sizing over 7-14 days

Read-only join over `ac_ramp_events` and the HA recorder / SPAN
history. For each zone:

1. Duration-weighted fraction of time where SPAN `ac_load_sensor` >
   Gate-7 threshold AND `climate.<zone>.hvac_action == "idle"`.
   Compare to the operator's cited 12.2% / 7.1% / 12.9%. Sanity check
   we reproduce them; if not, the probe is broken, not the finding.
2. Same fraction, restricted to `hvac_mode ∈ {cool, heat_cool, auto}`.
   Confirms the fix does not accidentally re-enable heating mistakes.
3. Distribution of blower_rpm when SPAN reads > threshold AND
   `hvac_action == "idle"`. Validates the corroboration threshold
   default of 100 rpm.

**Go/no-go.** If step 2's fraction is meaningfully lower than step 1
(i.e. some blind time was actually heating), narrow §5's
`GATE4_MAX_BLIND_FRACTION` accordingly. If step 3 shows blower_rpm
uniformly near-zero when SPAN says otherwise, drop the blower
corroboration entirely and note it in §7.1.

### Probe B — D10 retrospective lag

Join `ac_ramp_events.nudge_started` rows to
`climate.<zone>.target_temp_high` state history from the recorder.
Compute (a)→(b) gap distribution per zone. If p50 < 2s and p95 < 5s,
**cancel the D10 build** — the retrospective join answers the
question and the columns are wasted work. If gap is meaningful, build
D10 as specified.

### §7.1 and §7.2

Placeholders; populated by the orchestrator before build dispatch.
Build blocks on both.

---

## 8. Acceptance criteria — DISCRIMINATING

### AC-P (Invariant P)

- **Live (post-deploy, 7 days after flip to `live`):**
  `sensor.ac_gate4_blind_fraction_7d_<zone>` ≤
  `GATE4_MAX_BLIND_FRACTION` (0.01) for all three zones.
  - **Fix observation:** near zero (<0.5%) — the SPAN predicate is
    routing correctly.
  - **Plausible different failure:** value stuck at pre-fix 7-13% —
    the helper's predicate is still cloud-derived (e.g. still reads
    `hvac_action`). The two observations diverge.

- **In-suite discrimination:** synth a state where `hvac_mode=cool`,
  `ac_load_sensor=1.2 kW`, `hvac_action="idle"`. Assert the helper
  returns True. Then flip `hvac_mode=heat` with the same draw
  (physical impossibility, tests the config guard). Assert helper
  returns False. Then flip `hvac_mode=cool` back and set
  `ac_load_sensor=0.1 kW`. Assert False. Three data points, three
  outcomes; a monolithic implementation cannot pass all three by
  accident.

- **Shadow-mode divergence (in-suite):** with mode=`shadow`, engineer
  one legacy-veto + new-proceed case and one legacy-proceed +
  new-veto case. Assert exactly TWO `gate4_divergence_shadow` rows
  written, one per direction.

### AC-S (Invariant S — D-SCORE)

Reuse superseded plan **AC4** verbatim (full-window, truncated,
cancel-on-teardown, live). No new tests here.

### AC-E (Invariant E — D-ESC-CONSUME)

- **In-suite positive control (live mode):** hand-craft 2 prior
  `nudge_evaluated` rows for zone_1 with `durable=0` within the last
  30 min. Trigger a fresh `nudge_evaluated` that WOULD classify
  `effective=True` under legacy. Assert:
  (a) new row's `classification="ineffective_durable_fail"`,
  `effective=False`, `escalate=True`;
  (b) `_perform_hard_reset_escalation` was called once with
  `triggered_by="durability_fail"` and `engage_lockout_on_cap=False`;
  (c) exactly ONE new `hard_reset_started` row with
  `triggered_by="durability_fail"`.

- **Shadow-mode absence (in-suite):** same setup with mode=`shadow`.
  Assert: (a) new row's `classification="effective"`, `escalate=False`
  (unchanged from legacy — the classifier does NOT rewrite itself in
  shadow, it only emits the shadow row); (b) ZERO
  `_perform_hard_reset_escalation` calls; (c) exactly ONE
  `escalation_would_promote` shadow row.
  - **Failure shape that discriminates:** a `hard_reset_started` row
    appears — the shadow gate leaked. Or the classifier's live-mode
    branch executes in shadow — a boolean mistake in the mode check.

- **Legacy-mode absence (in-suite):** same setup with mode=`legacy`.
  Assert ZERO rows of either shadow or `hard_reset_started/durability_fail`
  type. If the shadow row appears, `legacy` is not disabling shadow —
  precisely the failure a boolean can't guard against (superseded
  §12-13).

- **No-lockout-on-cap (in-suite):** live mode, D2 `day_budget=0`,
  day-time now. Trigger the durability-fail branch. Assert one
  `hard_reset_declined` row with
  `notes="reason=day_budget_exhausted"`; `lockout_flag` UNCHANGED; no
  "controller may be broken" NM notification. Same shape as
  superseded plan AC1 no-lockout-on-recurrence-cap, adapted to the
  new caller.

- **Live (post-deploy, 14 days after flip to live):** at least one
  `hard_reset_started` row exists with
  `triggered_by="durability_fail"` OR (better) the operator confirms
  the ~10 kW / 49 kWh overnight has not recurred despite HVAC
  conditions similar to 2026-08-20.

### AC-D9 — Refresh workaround

- **In-suite:** set `hvac_ac_carrier_refresh_interval_s=120`. Advance
  simulated clock 130s. Assert `hass.services.async_call("homeassistant",
  "update_entity", ...)` was called exactly once with the correct
  `target: entity_id` list.
- **Stall behaviour (in-suite):** monkey-patch the service call to
  raise `asyncio.TimeoutError`. Advance clock 6 intervals. Assert:
  no exception propagates to the coordinator; WARN log fires with
  the rate-limit key; exactly ONE NM notification is emitted.
- **Independence discrimination:** disable D9
  (`interval_s=0`) AND run AC-P live. If AC-P still passes, D-GATE4
  is indeed independent of D9 (non-goal 3 satisfied). If AC-P
  regresses only when D9 is off, the coupling exists and must be
  found.

### AC-D10 — Actuation lag

- **Probe-driven:** if Probe B rejected the build, this AC block is
  vacuous — record the rejection in §7.2 and move on.
- **In-suite (if built):** synth a nudge; drive a target_temp_high
  state change at command+3s; drive a SPAN drop at command+40s.
  Assert `reported_at_ts` and `physical_at_ts` land on the correct
  event row via `event_id`.

### AC-I / AC-III

Reuse superseded plan **AC7** (Invariant I bounded cycling) and
**AC8** (Invariant III aggregator non-pollution) verbatim, with the
new event types (`gate4_divergence_shadow`,
`escalation_would_promote`) added to the non-pollution insert list.

---

## 9. Restart-safety declaration

| New state | Category | Mechanism |
|---|---|---|
| `_zone_is_actively_cooling` (D-GATE4) | REBUILD | Stateless helper, computed each tick from live attrs. |
| `hvac_ac_gate4_predicate_mode` (Select) | PERSIST | HA Select entity persistence. A restart never re-arms a disabled trigger. |
| `hvac_ac_escalation_source` (Select) | PERSIST | Same. |
| `hvac_ac_esc_consume_n` (Number) | PERSIST | URA Number-persistence. |
| `hvac_ac_carrier_refresh_interval_s` (options int) | PERSIST | HA config-entry storage. |
| D9 periodic task | REBUILD | Re-registered on coordinator setup; interval read from persisted options. |
| D10 lag columns | PERSIST as columns; in-flight listener REBUILD (drop) | Any in-flight listener across restart is lost; row keeps NULL — visible + attributable. |
| `escalation_would_promote` / `gate4_divergence_shadow` rows | PERSIST | `ac_ramp_events` ledger. Both edge-triggered per superseded §3-D8. |
| All D2-D8 carry-forward state | PER SUPERSEDED §9 | Not repeated. |

---

## 10. Ship order

1. D-GATE4 (shadow) + D-SCORE columns (LIVE) + D2-D8 carry-forward
   (per superseded §3) — one build.
2. Operator flips D-GATE4 to `live` after ≥ 24 h of shadow.
3. D-ESC-CONSUME (shadow) — piggybacks on the same build, activates
   in shadow after D-SCORE data starts landing.
4. Operator flips D-ESC-CONSUME to `live` after ≥ 3 shadow hits look
   right.
5. D9 default OFF ships in the same build; operator sets a non-zero
   interval when they want the workaround.
6. D10 ships iff Probe B says the columns are worth building.

Independent-of-excursion-cycle claim from superseded §10 stands: D5
enrichments write to the existing producer sites directly.

---

## 11. Marginal-benefit decomposition

Applied to the two most fanciness-prone additions:

- **D9 (periodic refresh).** Simplest version: nothing (already
  workaround-able manually via a reload). Marginal benefit: automated
  recovery of ONE class of Carrier staleness, defaulted OFF. Marginal
  ingredient risk: a new writer-of-service-calls on a periodic timer.
  Contained by (a) service is `homeassistant.update_entity` not a
  reload; (b) default OFF; (c) failure-mode NM alert. **VERDICT:
  ship, defaulted off.** The MARGIN over "manual reload when it
  breaks" is the automated recovery — not free, but the ingredient
  risk is small because reload is explicitly forbidden and the
  service call is bounded in blast radius. If the operator never
  turns it on, we lose only the sensor + about 30 LoC.

- **D10 (per-nudge lag columns).** Simplest version: the retrospective
  probe (Probe B) — zero code shipped. Marginal benefit of the
  columns: continuous rolling lag telemetry instead of a one-shot
  measurement. Marginal ingredient risk: two new state-change
  listeners per nudge with 60s timeouts; new columns; new writer for
  each nudge. **VERDICT: probe first, ship only if probe justifies.**
  If the (a)→(b) gap is boring, the columns are pure churn.

The parked-but-recorded pattern (superseded plan's discipline for the
count trigger) applies: if Probe B rejects D10, record the rejection
in §7.2 with the evidence trigger that would justify revisiting
("if operator reports diverging report vs command in a Frigate-visible
event, rerun the probe on the current window").

---

## 12. Tier 3 test-authority — real per-site source mutation

Every deliverable's load-bearing site is named with its neuter drill
and the specific test that MUST fail. A site whose neutering leaves
the suite green is untested.

| # | Site | Enclosing method | Neuter drill | Test that MUST fail |
|---|---|---|---|---|
| 1 | D-GATE4 config guard | `_zone_is_actively_cooling` | Delete the `hvac_mode` check | AC-P in-suite discrimination (`heat` + draw case) |
| 2 | D-GATE4 SPAN gate | same | Return True unconditionally when `zone.hvac_mode == "cool"` | AC-P in-suite discrimination (draw=0.1 kW case) |
| 3 | D-GATE4 shadow-vs-live | `check_ac_reset` at `:2779` | In shadow mode, use the NEW helper for the decision | AC-P shadow-mode divergence (both dirs) |
| 4 | D-SCORE non-mutation | `_write_durable` | Also SET `effective=?` in the UPDATE | superseded AC4 same-row-both-columns |
| 5 | D-SCORE event_id identity | `_write_durable` | Replace `WHERE event_id=?` with `ORDER BY timestamp DESC LIMIT 1` | superseded AC4 truncated-vs-fresh-nudge |
| 6 | D-ESC-CONSUME classifier branch | classifier at `:3823+` (new branch) | Skip the `durable=0`-count check, always classify as `effective` | AC-E positive control |
| 7 | D-ESC-CONSUME shadow gate | classifier mode dispatch | Force live path regardless of Select value | AC-E shadow-mode absence |
| 8 | D-ESC-CONSUME no-lockout-on-cap | `_perform_hard_reset_escalation` (`:3925`) | Ignore `engage_lockout_on_cap`; always call `_engage_lockout` on cap-fail | AC-E no-lockout-on-cap |
| 9 | D2 partition gate (carried) | superseded §11 Site 1 | (as superseded) | (as superseded) |
| 10 | D2 save-tuple (carried) | superseded §11 Site 11 | (as superseded) | (as superseded) |
| 11 | D9 forbidden-reload | scheduled callback | Replace `homeassistant.update_entity` with `homeassistant.reload_config_entry` | New reviewer-authored test asserting the service name; also grep-guarded in CI |
| 12 | D9 independence (non-goal 3) | `_zone_is_actively_cooling` | Add `if not self._d9_healthy: return False` at the top | AC-D9 independence-discrimination test |

**Orchestrator personally re-runs sites 1, 2, 3, 6, 8, and 11 before
ship.** Highest blast radius: Gate-4 config guard, Gate-4 SPAN gate,
Gate-4 rollout gate, the trust consumer that fires escalation, the
no-lockout carve-out, and the forbidden-reload guard.

**Reviewer D (adversarial completeness)** must state Invariants P, S,
E in falsifiable form and re-enumerate every emission site of
`_perform_hard_reset_escalation` including pre-existing code (the
`if escalate:` at `:3891` AND the manual `force_ac_reset` at
`:4338`), confirming NO NEW ESCALATION PATH has been introduced (non-
goal 8). Every flagged leak must ship with a legal-config reachable
repro.

---

## 13. Files touched — for the builder

Superseded plan §13 lists the D2-D8 file set exhaustively; that
inventory stands. This plan ADDS:

- `custom_components/universal_room_automation/domain_coordinators/hvac_override.py`
  — new `_zone_is_actively_cooling` helper; replaces Gate 4 body at
  `:2779`; new classifier branch appended after `:3823`; new
  scheduled task registration + teardown for D9; new per-nudge lag
  listeners for D10 (if built); coordinator setters for the two new
  Selects.
- `custom_components/universal_room_automation/domain_coordinators/hvac_const.py`
  — new module constants `AC_ACTIVELY_COOLING_KW_MIN`,
  `AC_ACTIVELY_COOLING_BLOWER_RPM_MIN`, `GATE4_MAX_BLIND_FRACTION`;
  new event-type constants `AC_RAMP_EVENT_GATE4_DIVERGENCE_SHADOW`,
  `AC_RAMP_EVENT_ESCALATION_WOULD_PROMOTE`.
- `custom_components/universal_room_automation/select.py`
  — new `hvac_ac_gate4_predicate_mode`, `hvac_ac_escalation_source`
  Selects (in addition to superseded plan's
  `hvac_ac_recurrence_mode` — but that Select is now REMOVED from
  scope: superseded §7.1 killed the count trigger).
- `custom_components/universal_room_automation/number.py`
  — new `hvac_ac_esc_consume_n` Number (in addition to superseded
  plan's set; the superseded plan's `hvac_ac_recurrence_count_n` and
  `hvac_ac_recurrence_window_min` Numbers are REMOVED from scope).
- `custom_components/universal_room_automation/config_flow.py` +
  `options_flow.py`
  — `hvac_ac_carrier_refresh_interval_s` integer field.
- `custom_components/universal_room_automation/database.py`
  — extend the existing `ac_ramp_events` guarded ALTER block
  (`:1681-1712`) with `reported_at_ts TEXT NULL`,
  `physical_at_ts TEXT NULL` (D10, if built). No further DDL beyond
  the superseded plan set.
- `custom_components/universal_room_automation/sensor.py`
  — new `sensor.ac_gate4_blind_fraction_7d_<zone>`,
  `sensor.ac_carrier_refresh_last_ok_ts`, D10 sensors (if built).
- `quality/tests/` — one file per deliverable covering §8 ACs and the
  §12 mutation-drill fixtures.

Builder: **re-grep every superseded-plan anchor before using it.** The
tree has moved.

---

## 14. Flags on the brief

Two items the assistant flagged during scoping:

1. **`_perform_hard_reset_escalation` line number.** The brief cites
   `:3891`. Actual definition is at `:3925`; `:3891` is the `if
   escalate:` branch that CALLS it (at `:3901`). Both facts matter,
   both are correct in context, but the anchor in this plan reflects
   the grep.
2. **D10 "computable retrospectively" claim.** True in principle IF the
   HA recorder retains state changes for
   `climate.<zone>.target_temp_high` at sufficient resolution across
   the window. This repo's recorder retention posture is not restated
   here; Probe B implicitly verifies it (a broken probe means retention
   is inadequate, which is itself an actionable finding). Not a
   blocker; noted so a reviewer does not treat retrospective
   computability as proven.

No other errors identified in the brief.
