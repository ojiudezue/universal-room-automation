# PLANNING — AC-RAMP-NO-RECURRENCE-ESCALATION-1

**Tier:** 3 (delicate shared-primitive; touches compressor-cycling policy,
persists cross-restart state, layers over the just-shipped
HVAC-GOVERNED-EXCURSION-1 nudge path). Elevated because the escalation being
built cycles compressors — the original v4.5.11 design named this "the worst
possible failure mode" — and one missed emission site or one mis-classified
outcome ships silent hardware wear.

**Governing constraint (operator, verbatim):** *"I do not expect you to
rebuild ac reset from scratch. We always work from existing and goals or
enhancements or correctness problems."* Every deliverable in this doc is a
DELTA on working machinery. If the builder finds themselves restructuring
the nudge/reset core, stop and re-read this line.

---

## 0. What already works — do not rebuild

Enumerated with file:line so the builder knows where the seams are and does
not confuse "not yet wired for this cycle" with "missing".

**Detection + soft-nudge path (v4.5.11 core, still fires 31-43x/zone/day):**
- Overshoot detection + kWh gate:
  `hvac_override.py` — `_evaluate_ac_ramp_zone` and helpers.
- Soft-nudge setpoint write: `_perform_soft_nudge` at
  `hvac_override.py:3099` (`set_temperature`, blocking=False).
- 5-min hold → `_restore_after_nudge` at `hvac_override.py:3197`.
- 10-min evaluation window: `AC_NUDGE_EVALUATION_DELAY_S` / operator knob
  `CONF_HVAC_AC_NUDGE_EVAL_DELAY` (default 600s, `hvac_const.py:525-526`).
- Nudge-interval enforcement: `AC_NUDGE_MIN_INTERVAL_S` — this is the
  PATTERN to copy for the missing daily cap.

**Escalation gate (armed, proven, has not fired since 2026-08-15):**
- Single `if escalate:` on nudge-ineffective at
  `hvac_override.py:3757-3772` (verified: the ONLY branch that raises
  `escalate=True` is `classification in {ineffective, ineffective_no_samples}`).
- Hard-reset off/restore: `_perform_ac_reset` at `hvac_override.py:2884` →
  `_restore_after_reset` at `hvac_override.py:2921`.
- Off-window duration: `AC_RESET_OFF_DURATION_SECONDS: Final = 60`
  (`hvac_const.py:493`), consumed at `hvac_override.py:2906` (the
  `async_call_later` delay) and interpolated into the NM alert at :2915.
- Daily hard-reset cap: `DEFAULT_HVAC_AC_HARD_RESET_DAILY_LIMIT = 2`
  (`hvac_const.py:534-535`), enforced at `hvac_override.py:3938`.
- Compressor-protection min interval:
  `DEFAULT_HVAC_AC_HARD_RESET_MIN_INTERVAL = 120` min (`hvac_const.py:537-538`).
- Post-restore verify + 30s retry×2: `_verify_restore` at
  `hvac_override.py:2966+`.

**Persistence (restart-safe, and the exemplar this cycle extends):**
- `ac_reset_state` table at `database.py:1430-1446`, keyed
  `(zone_id, date)`, carries `soft_nudge_count`, `hard_reset_count`,
  `last_soft_nudge_ts`, `last_hard_reset_ts`, `last_overshoot_ts`,
  `in_flight_nudge_original_target`, `in_flight_nudge_started_ts`,
  `in_flight_nudge_duration_s`, `lockout_flag`. Day-rollover reset in-code.
- `ac_ramp_events` append-only ledger at `database.py:1503-1531` — 4
  event types per cycle, ALREADY carries
  `preset_before / preset_after / mode_before / mode_after /
  restore_ok / restore_ok_immediate` (shipped by
  HVAC-GOVERNED-EXCURSION-1 D1 in v5.86.0). See §1 for the direct
  consequence for this cycle's D5.
- Startup restore of in-flight nudges: `async_startup_ramp_audit` at
  `hvac_override.py:3925`. The AC-ramp nudge is the codebase's exemplar
  of restart-safe in-flight excursion (per the
  HVAC-GOVERNED-EXCURSION-1 restart-safety audit — do not re-litigate).

**NM alerts + live sensors:** ramp state and last action per zone,
nudges/hard-resets today, false-positive rate, kWh avoided today/total,
per-zone kW rate, four savings sensors. (Observability audit
"WHAT IS GOOD" list on the card.)

**Empirically settled by the DELTA_T_PROBE** and referenced here so the
builder does not re-open them:
- Adaptive/delta-T nudge sizing: refuted. Do not build.
- Delta-T only earns a place as an escalation VETO (do not hard-reset when
  outdoor very high) — parked, not in this cycle.
- Wide-cycle 300s→150s hold: the RAMP-DOWN data supports shortening for
  cycle-time reasons only, not energy. **Parked** for a separate cycle
  (AC-NUDGE-HOLD-SHORTEN-1) — this cycle needs the current cadence as its
  baseline so the recurrence trigger's N and W are calibrated against
  what ships today. See non-goal 5.

---

## 1. Institutional context verified

### Greps run + REUSED / NEW disposition for every proposed addition

Ran on 2026-08-22 against `custom_components/universal_room_automation/`.

| Proposed | Search | Result | Disposition |
|---|---|---|---|
| Recurrence trigger: window count of `nudge_started` per zone | `grep -n "nudge_started" hvac_override.py database.py` | Event constant `AC_RAMP_EVENT_NUDGE_STARTED` exists; emitted from `_perform_soft_nudge`; already persisted as an `ac_ramp_events` row with `zone_id`+`timestamp` indexed (`idx_ac_ramp_events_zone_ts`, `database.py:1526`). | **REUSED** — the trigger reads the existing ledger. NO new event, NO new sensor for the raw count. Add a live sensor for "nudges in last W" as a display consumer only (D6). |
| Recurrence knobs `N` and `W` | grep `ac_recurrence` / `recurrence_window` / `recurrence_count` in `const.py` + `hvac_const.py` + `number.py` | None. | **NEW** — sibling of the existing hard-reset knobs. See knob ladder §5. |
| Recurrence master enable (default OFF) | grep `_MASTER_ENABLED` `hvac_const.py` | `CONF_HVAC_AC_RAMP_MASTER_ENABLED` exists (`hvac_const.py:509`, default OFF) as the whole-feature kill switch. | **NEW sub-switch** required — the recurrence trigger needs its OWN kill switch that is independent of the master (the master flag flips the whole feature; the recurrence trigger needs to ship OFF while everything else ships ON — see §3-D1 safety). |
| Day/night reset counters | grep `day_reset_count` / `night_reset_count` / `ac_reset_state` in `database.py` + `hvac_override.py` | Only `hard_reset_count` exists (`database.py:1435`, consumed at `hvac_override.py:3938`). Table PK `(zone_id, date)` (`database.py:1443`). | **NEW columns** on `ac_reset_state` — additive `ADD COLUMN` via the codebase's `CREATE TABLE IF NOT EXISTS` pattern, no re-key, no migration. `hard_reset_count` retained as `day_reset_count + night_reset_count` reconciliation invariant during rollout, then may be deprecated (parked). |
| Day/night window boundaries | grep `night_start` / `night_end` / `quiet_hours` in `hvac_const.py` + `const.py` | Not for this axis. `night_hours_start/end` exist elsewhere but are presence/notification concerns; card explicitly argues WALL-CLOCK boundary for compressor policy over house-state coupling. | **NEW knobs** — dedicated to this axis, wall clock. See §5. |
| Soft-nudge daily cap | grep `soft_nudge.*limit` / `soft_nudge.*cap` / `soft_nudge.*max` `hvac_const.py` `hvac_override.py` `number.py` | None. `soft_nudge_count` counter exists but no ceiling. `AC_NUDGE_MIN_INTERVAL_S` enforcement pattern at the nudge-eligibility site is what to copy. | **NEW** — the v4.5.11 design specced 6/day and it never shipped. See §3-D3. |
| `durable` / `durable_minutes` columns | grep `durable` `database.py` | None on `ac_ramp_events`. | **NEW columns** (nullable) on `ac_ramp_events`, additive. Written by a delayed callback modelled on the shipped `_write_settled` pattern at `hvac_override.py:3521-3528` (that pattern already handles cancellation on rapid re-nudge). |
| `preset_before` / `preset_after` on ac_ramp_events | grep | **ALREADY EXIST** on the ledger (`database.py:1519-1520`) AND are already WRITTEN on the nudge path (`hvac_override.py:3341`, `:3496`) by the HVAC-GOVERNED-EXCURSION-1 D1 that shipped in v5.86.0. **Not present on the hard-reset path** (`_perform_ac_reset` / `_restore_after_reset` at `hvac_override.py:2884-2968` — verified: no `preset_before`/`preset_after` capture, and `mode_before` / `mode_after` / `restore_ok` are similarly not written for the reset event). | **REUSED columns; NEW producer wiring on the reset path only.** See §3-D5 correction — this deliverable is narrower than the brief implied. Flagged in §12. |
| Temp at reset start/end | grep `current_temp` around `_perform_ac_reset` / `_restore_after_reset` | Not captured. `ac_ramp_events` has `current_temp` and `target_high` per row (`database.py:1509-1510`) but the reset path currently writes no `ac_ramp_events` row on start/end. | **NEW producer wiring** using the existing `current_temp`/`target_high` columns on the ledger, plus new `hard_reset_started` / `hard_reset_completed` event rows if not already emitted (verify — 11 historical `hard_reset_*` rows exist per the card's `measured:` section, so the event types DO emit; confirm they write `current_temp`). |
| Rung-3 promotion of `AC_RESET_OFF_DURATION_SECONDS` | grep for `number.py` entities that follow the pattern (`ac_hard_reset_daily_limit` at `number.py:2435-2441` per the card). | Sibling knob pattern exists. | **REUSED pattern; NEW Number entity** `hvac_ac_reset_off_duration`. See §5 and §3-D7. |
| Recurrence-considered-and-declined trail | grep `escalation_declined` / `reset_declined` `hvac_override.py` `database.py` | None. Observability audit gap #4. | **NEW** — write an `ac_ramp_events` row with a new `event_type` value (or an existing `hard_reset_declined` type — verify by grep before choosing). Reuses the ledger; no schema change. |

### Prior planning docs consulted

- `docs/planning/PLANNING_v4.5.11_ac_energy_aware_ramp_down.md` — the
  objective doc; goal 3 ("rapid compressor cycling is the worst possible
  failure mode") is the invariant this cycle must not violate. Specced the
  6/day soft-nudge cap that D3 finally builds.
- `docs/planning/PLANNING_hvac_governed_excursion.md` (HVAC-GOVERNED-EXCURSION-1)
  — the just-shipped D1 that added `preset_before / preset_after /
  mode_before / mode_after / restore_ok / restore_ok_immediate` to
  `ac_ramp_events` and wrote them on the nudge path. This cycle rides on
  top; D5 is only the reset-path wiring gap left behind. **D2/D3 of the
  excursion cycle are still UNBUILT per the STATUS_CORRECTED_2026_08_22
  note on that card** — assume they may land during or after this build
  and design D5 to not conflict.
- Kanban card `AC-RAMP-NO-RECURRENCE-ESCALATION-1` — the entire body,
  including every dated addendum. Especially:
  `RESET_DRIFT_CONSTRAINT_2026_08_22`,
  `RECOMMENDATION_EFFECTIVE_REDEFINITION_2026_08_21`,
  `LAYERING_AND_RETROACTIVE_2026_08_21`,
  `LIVE_INSTANCE_AND_MECHANISM_2026_08_22`,
  `AC_RAMP_IS_A_MANUAL_INDUCER_2026_08_21`,
  `OBSERVABILITY_AUDIT_2026_08_21`, `DELTA_T_PROBE_2026_08_21`,
  `RESET_BUDGET_WINDOWING_2026_08_21`,
  `CYCLE_ANATOMY_AND_TIMING_2026_08_21`,
  `RAMPDOWN_PROBE_2026_08_21`,
  `WIDE_CYCLE_REFUTED_LOAD_MATCHED_2026_08_21` (SUPERSEDES the earlier
  `WIDE_CYCLE_EFFECTIVENESS_2026_08_21` block — respected).

### Memories pulled

- `feedback_measure_before_build.md` — the probe-first gate is already
  discharged on this card (DELTA_T_PROBE, RAMPDOWN_PROBE,
  WIDE_CYCLE_REFUTED_LOAD_MATCHED). Do not re-run these; do run one new
  probe (see §7) to size N and W against real cadence.
- `feedback_marginal_benefit_pushback.md` — applied to D2 (day/night
  budgets) below: the SIMPLEST version raises the daily cap to 3; the
  fancier version PARTITIONS it. The partition is justified only because
  night is where the measured damage lives.
- `feedback_cross_investigation_synthesis.md` — this cycle intersects
  HVAC-GOVERNED-EXCURSION-1 D2/D3 (still unbuilt) and
  HVAC-MANUAL-PRESET-CONTRACT-1. D5 of this cycle sits inside the same
  restore-preset-on-exit territory. Order-of-ship discussed §11.
- `feedback_suppression_needs_discharge.md` — the recurrence trigger's
  kill switch is a suppression: if disabled, what re-arms it, and does a
  restart re-arm to enabled or preserve disabled? Answered §6-D1.
- `reference_ec_reserve_verifiable_backout_knob.md` — precedent for a
  safety kill knob that ships defaulted to a specific safe value. The
  recurrence-trigger enable is the sibling here.

### Code read end-to-end during scoping

- `custom_components/universal_room_automation/domain_coordinators/hvac_override.py`
  lines 2880-2970 (`_perform_ac_reset`, `_restore_after_reset`,
  `_verify_restore`), 3080-3260 (`_perform_soft_nudge`,
  `_restore_after_nudge`), 3450-3560 (settled/telemetry writeback),
  3720-3800 (classifier + `if escalate:`), 3870-4020 (hard-reset
  eligibility, cap check, lockout write).
- `custom_components/universal_room_automation/domain_coordinators/hvac_const.py`
  lines 480-540 (AC reset legacy + v4.5.11 knobs).
- `custom_components/universal_room_automation/database.py` lines
  1425-1531 (ac_reset_state + ac_ramp_events DDL) and 7275-7530 (state
  read/write DAO).

---

## 2. The falsifiable invariant

The cycle must guarantee, in breakable form:

> **Invariant I:** Given any 24h window, the total number of
> `hard_reset_started` events for a single zone is bounded by
> `day_reset_budget + night_reset_budget`, with per-partition counts
> bounded individually AND respecting the existing
> `hard_reset_min_interval` gap between any two consecutive
> `hard_reset_started` events on the same zone across partitions.
> Additionally, **no `hard_reset_started` event may fire while the
> recurrence-trigger master knob is OFF unless it was armed by the
> pre-existing `escalate=True` classifier at `hvac_override.py:3757-3772`
> (i.e. the pre-existing ineffective-nudge path).**

The second clause is what Reviewer D exists to break: enumerate every
path that reaches `_perform_ac_reset` and prove none of the new
recurrence code paths route around the OFF switch.

Corollary invariant for D6 (temp measurement):

> **Invariant II:** Every `hard_reset_completed` row in `ac_ramp_events`
> carries a non-NULL `current_temp` recorded at reset-END, and every
> `hard_reset_started` row carries a non-NULL `current_temp` recorded at
> reset-START, whenever the zone's temperature sensor is available. Any
> classification that scores a reset as "failed" MUST have both temps
> present or must classify inconclusive.

---

## 3. Deliverables (all deltas)

Each deliverable states LIVE-ON-SHIP vs OFF-BY-DEFAULT explicitly per the
safety constraint.

### D1 — Recurrence trigger (SECOND, orthogonal escalation path)

**Status on ship: OFF by default.** Ships complete, ships tested, ships
observable in shadow mode; enabling is a deliberate operator flip.
Mirror the v5.85.0 STEP-chatter shadow pattern.

**Behaviour when enabled:** N `nudge_started` events on one zone within
rolling window W → arm hard-reset escalation, subject to the pre-existing
`_hard_reset_eligible` gate (day/night budget from D2, 120-min min
interval, lockout flag). Reads only `nudge_started` timestamps from
`ac_ramp_events` (indexed) or the in-memory rolling counter — never
consults `effective`, `durable`, `classification`, or `kwh_avoided`.

**Behaviour when OFF (shadow):** compute the trigger and emit a
`recurrence_would_fire` row (new event_type value on the existing ledger)
with `notes="shadow"`. Zero effect on `_perform_ac_reset`. This is what
lets the operator watch the cadence for a week before enabling.

**Kill switch:** new `CONF_HVAC_AC_RECURRENCE_ENABLED`
(rung 2 — config/options flow), default False. When False, the code path
runs but the emission-arming branch is unreachable — verified by mutation
drill (Tier 3 test-authority requirement §8).

**Interaction with the existing `if escalate:` at line 3757-3772:** the
recurrence trigger is a SECOND caller of `_hard_reset_eligible` →
`_perform_ac_reset`. The pre-existing ineffective-nudge branch is
untouched. Two independent triggers can request the reset in the same
window; the existing eligibility gate (interval + budget + lockout)
already deduplicates by refusing back-to-back requests.

**Producer:** N nudge_started rows in ≤ W seconds on zone Z.
**Consumers:** `_hard_reset_eligible` (trust), `sensor.ac_recurrence_window_count_<zone>` (display, D8),
`ac_ramp_events` shadow rows (audit).

### D2 — Day/night partitioned reset budgets, no borrowing

**Status on ship: LIVE.** This is a policy change to an existing cap; it
does not add automated actions the operator has not already approved.

**Schema:** ADD COLUMN `day_reset_count INTEGER NOT NULL DEFAULT 0` and
`night_reset_count INTEGER NOT NULL DEFAULT 0` on `ac_reset_state`.
Retain `hard_reset_count` as the SUM invariant for one release; it
becomes `day_reset_count + night_reset_count` and can be deprecated in a
follow-up (parked). Additive per the codebase's `CREATE TABLE IF NOT
EXISTS` pattern; no migration.

**Enforcement:** `_hard_reset_eligible` at `hvac_override.py:3938` now
computes the current partition from wall-clock time against the
day-boundary knobs, reads the matching counter, denies if
`>= partition_limit`. Global 120-min min-interval remains unchanged.

**Defaults:** `day_reset_budget = 1`, `night_reset_budget = 2`. Total 3 —
this IS a rise from today's 2. Justified because the measurement lives
overnight (49 kWh burn, 03:00 waste) and the DP-hazard tail is bounded by
the 120-min min-interval. Flagged §12 for operator confirmation.

**Window definition (wall clock):** `night_start = 22:00`,
`night_end = 06:00` (local). Rationale in the card
(`RESET_BUDGET_WINDOWING_2026_08_21`): decouples compressor protection
from the presence stack, which has been observed sitting wrong for
hours.

**Restart safety:** counters PERSIST across restart (existing pattern —
`ac_reset_state` is rebuilt from DB on boot).

**Producer:** `_perform_ac_reset` increments the correct partition
counter based on now().
**Consumer:** `_hard_reset_eligible` (trust); day/night sensors (display).

### D3 — Soft-nudge daily cap (specced v4.5.11, never built)

**Status on ship: LIVE.** Runaway guard, not a policy lever. Default is
above today's observed 31-43/day so it never fires under current
behaviour.

**Enforcement pattern:** copy the existing `AC_NUDGE_MIN_INTERVAL_S`
enforcement site in `_evaluate_ac_ramp_zone`. Add the same-shape check
against `state["soft_nudge_count"]` before calling `_perform_soft_nudge`.

**Knob:** `CONF_HVAC_AC_SOFT_NUDGE_DAILY_LIMIT`, default **50**
(rung 3 — Number entity). Placed above measured 31-43 so a change in
weather does not silently trip it.

**Producer:** `state["soft_nudge_count"]` (already exists).
**Consumer:** the new eligibility gate + existing daily counter sensor.

**Restart safety:** REUSED — the counter already persists.

### D4 — Durable effectiveness (additive columns, NON-MUTATING)

**Status on ship: LIVE for column presence + delayed write; the
classification derived from `durable` is DISPLAY-ONLY at first (no
consumer flips savings math).** This preserves the ledger invariant the
card argues for extensively in `LAYERING_AND_RETROACTIVE_2026_08_21`.

**Schema:** ADD COLUMN `durable INTEGER` (nullable) and
`durable_minutes INTEGER` (nullable) on `ac_ramp_events`.

**Producer:** on `nudge_evaluated`, schedule a `_write_durable` callback
at now + D minutes (D = `CONF_HVAC_AC_DURABILITY_WINDOW`, default 30 min,
rung 2). At fire time, passive re-read of kW; if the load stayed below
`AC_NUDGE_EVAL_MIN_DROP_FRAC * kwh_rate_before` for the whole window,
set `durable=1`; else `durable=0`. `durable_minutes` = the interval
actually observed (may be < D if a subsequent nudge on the same zone
fired within the window — then `durable_minutes` records the truncated
observation and `durable=0`).

Pattern SOURCE: `_write_settled` in `hvac_override.py:3521-3528` — copy
the cancellation-on-teardown handling verbatim.

**Consumers:**
- `sensor.ac_ramp_durability_rate_<zone>` (display).
- Savings arithmetic: **NOT wired in this cycle.** Additive, reversible,
  makes no headline number move. A follow-up cycle
  (AC-RAMP-SAVINGS-REBASE-1) decides whether to re-base savings on
  `durable`. Parked.

**Non-goal:** MUST NOT overwrite `effective`. Reviewer D checks this via
mutation drill.

**Restart safety:** the delayed callback is scheduled via
`async_call_later` and is REBUILT on restart from an
`in_flight_durable_started_ts` column added to `ac_reset_state`
(mirroring the existing `in_flight_nudge_*` pattern at `database.py:1439-1441`).
Startup audit at `async_startup_ramp_audit` (`hvac_override.py:3925`)
gets a sibling call that resumes durable evaluations with elapsed-time
arithmetic; a durable callback whose remaining time is ≤0 fires
immediately post-boot; missing kW history at boot returns `durable=NULL`
(the "measurement in flight or lost" case documented at
`hvac_override.py:3500-3502`).

### D5 — Preset/mode/restore telemetry on the HARD-RESET path

**CORRECTED SCOPE (see §12 flag #1):** the columns `preset_before`,
`preset_after`, `mode_before`, `mode_after`, `restore_ok`,
`restore_ok_immediate` **already exist** on `ac_ramp_events`
(`database.py:1519-1524`) and are already written by the NUDGE path
(shipped by HVAC-GOVERNED-EXCURSION-1 D1 in v5.86.0, sites at
`hvac_override.py:3341` and `:3496`). The brief-implied "add these
columns" is redundant.

**Actual scope:** wire the same telemetry into the HARD-RESET path.
Producer sites `_perform_ac_reset` (`hvac_override.py:2884`) and
`_restore_after_reset` (`hvac_override.py:2921`) currently record no
`ac_ramp_events` rows for the reset itself (11 historical
`hard_reset_started`/`_completed` rows exist per the card — verify
which method emits them; if none, add via the existing
`_track_zone_action` helper).

**Deliverable:** on hard-reset start, write a `hard_reset_started`
`ac_ramp_events` row carrying `preset_before`, `mode_before`,
`current_temp` at reset-start (this is D6's producer half). On
hard-reset complete AND after settle window, write
`hard_reset_completed` carrying `preset_after`, `mode_after`,
`restore_ok`, and `current_temp` at reset-end (D6's other half).

**Status on ship: LIVE** — telemetry only, no behaviour change.

**Producer:** `_perform_ac_reset` (start row) + `_restore_after_reset`
(completed row).
**Consumer:** operator diagnostics + D6 drift discriminator.

### D6 — Room temp at reset-start and reset-end (drift discriminator)

**Status on ship: LIVE for capture; DRIFT-BASED CLASSIFICATION IS
DIAGNOSTIC-ONLY.** No automated behaviour keys off drift in this cycle.
The escalation trigger (D1) is a nudge-count trigger, not a drift
trigger.

**Rationale:** per `RESET_DRIFT_CONSTRAINT_2026_08_22`, two indistinguishable
power traces mean opposite things. This deliverable is the PREREQUISITE
that makes future drift-informed policy possible; it captures the data
from day one even while the reset window stays fixed.

**Implementation:** ride on D5's producer sites — `current_temp`
column already exists on `ac_ramp_events`. Read the zone's temperature
sensor at reset-start (into the `hard_reset_started` row) and at
reset-end after the `_restore_after_reset` verify success (into the
`hard_reset_completed` row).

**Classifier (diagnostic only, no consumer flips behaviour):**
- `temp_end > target_high` → `reset_outcome = "justified_ramp"` (case
  (b) in the card — the reset WORKED, subsequent ramp is expected).
- `temp_end ≈ target_high AND post_kW ramps back` →
  `reset_outcome = "floor_survived"` (case (a) — reset FAILED).
- `temp_end unavailable OR temp_start unavailable` →
  `reset_outcome = "inconclusive"`.
- Written as a new nullable `reset_outcome TEXT` column on
  `ac_ramp_events`. Additive. Live sensor
  `sensor.ac_reset_last_outcome_<zone>` exposes it.

**Non-goal:** MUST NOT feed the recurrence trigger or the day/night
budget in this cycle. Data collection first; policy in a later cycle
once the operator has seen ≥ 20 samples.

**Restart safety:** N/A — temps are captured synchronously at the
producer sites; no in-flight state to persist.

### D7 — Promote `AC_RESET_OFF_DURATION_SECONDS` to rung 3

**Status on ship: LIVE.** Pure knob-rung change; no algorithmic
difference on day zero.

**From:** module constant `AC_RESET_OFF_DURATION_SECONDS: Final = 60`
(`hvac_const.py:493`).
**To:** Number entity `hvac_ac_reset_off_duration` (default 60, range
30-300 seconds), stored via the URA Number-persistence machinery,
consumed at `hvac_override.py:2906` and `:2915` via the coordinator's
config-value accessor (same shape as `_hard_reset_daily_limit` at
`hvac_override.py:3938` sourced from the existing Number sibling at
`number.py:2435-2441` per the card).

**Rationale:** the operator's manual technique IS this parameter
("off and back to auto to reclaim some energy. If I am lucky it is
short enough..."). It is policy tuned by observation, not a safety
bound.

**Backward compatibility:** the module constant remains as the default
seed value (mirror the `DEFAULT_HVAC_AC_NUDGE_EVAL_DELAY` pattern at
`hvac_const.py:526`). First-boot after upgrade instantiates the Number
at the constant's current value → zero behaviour change on ship.

**Producer:** operator (dashboard slider).
**Consumer:** `_perform_ac_reset` off-window scheduler; NM alert text.

### D8 — Live sensors + declined-decision trail (observability audit
gaps #2 and #4)

**Status on ship: LIVE.** Read-only display; unblocks operator tuning
of D1's N/W.

- `sensor.ac_recurrence_window_count_<zone>` — nudge_started count in
  the last W seconds per zone.
- `sensor.ac_reset_last_outcome_<zone>` — from D6.
- `sensor.ac_reset_day_count_<zone>` / `sensor.ac_reset_night_count_<zone>` —
  the two D2 partition counters exposed live.
- Every escalation-denied path (cap, min-interval, disabled,
  comfort-deferred, master OFF, recurrence-OFF) writes an event row
  with `event_type = "hard_reset_declined"` and a `notes` field of
  `reason=<code>`. Reuses the existing ledger — no schema change.

---

## 4. Non-goals — explicit

1. **Do NOT redefine `effective`.** The existing column stays a TRUE
   statement about the instant of measurement. `LAYERING_AND_RETROACTIVE_2026_08_21`
   documents the ledger + monotonic-lifetime-sensor + savings-baseline
   reasoning.
2. **Do NOT create an "excursion / borrow kind" for reset.** No new
   enum kind; use the existing hard-reset code path with additional
   telemetry.
3. **Do NOT rebuild working machinery.** Detection, soft nudge, the
   `if escalate:` branch, `_hard_reset_eligible`, `_perform_ac_reset`,
   `_restore_after_reset`, verify+retry, `async_startup_ramp_audit`,
   `ac_reset_state`, and `ac_ramp_events` all remain. Every deliverable
   is an ADD (column, sensor, knob, sibling emission site).
4. **Do NOT change the nudge hold duration (300s → shorter).** Parked
   as a separate cycle (see `WIDE_CYCLE_REFUTED_LOAD_MATCHED_2026_08_21`).
   Sample-rate concerns for calibrating N and W are addressed by the
   §7 probe, not by a code change here.
5. **Do NOT wire `durable` into savings arithmetic in this cycle.** D4
   is instrumentation. Rebasing savings is a separate cycle after ≥ 2
   weeks of `durable` data.
6. **Do NOT re-do the restart-safety story for the nudge path.** The
   nudge is the codebase exemplar; the HVAC-GOVERNED-EXCURSION-1
   restart-safety audit refuted the earlier hazard claim. New in-flight
   state added here (D4's `in_flight_durable_started_ts`) follows the
   same pattern; do not perturb the existing fields.
7. **Do NOT couple to house-state.** Wall-clock boundary only for
   day/night budgets. House-state is available if a later cycle proves
   it worth the coupling risk.
8. **Do NOT touch the excursion primitive** landing under
   HVAC-GOVERNED-EXCURSION-1 D2/D3 (still unbuilt as of 2026-08-22).
   D5 here writes telemetry directly at the reset producer sites, not
   via the excursion API, so the two cycles can ship in either order.
   If the excursion primitive lands first, D5 can be re-plumbed as a
   consumer in a follow-up; that is not a goal of this cycle.

---

## 5. Knob ladder — every new number, placed and justified

Per CLAUDE.md "Numbers Get Knobs". Every threshold, duration, window
below is a named configurable with an explicit rung.

| Knob | Default | Rung | Why here |
|---|---|---|---|
| `CONF_HVAC_AC_RECURRENCE_ENABLED` | `False` | 2 (config/options) | Kill switch for automated compressor cycling. Ships OFF; enabling is a deliberate operator flip. Not rung 3 because the operator does not flip it by dashboard-tuning; it's a one-time arm. |
| `CONF_HVAC_AC_RECURRENCE_COUNT_N` | `2` | 3 (Number) | Policy tuned by observation of the shadow data. Value chosen off measured cadence per §7 probe. |
| `CONF_HVAC_AC_RECURRENCE_WINDOW_MIN` | `90` (minutes) | 3 (Number) | Same. Card recommends N=2 within W=90min per observed ~1 nudge/30min pathological cadence. |
| `CONF_HVAC_AC_RESET_DAY_BUDGET` | `1` | 3 (Number, 0-4) | Policy — operator wants the balance-finding tunable per the card. 0 disables day resets entirely. |
| `CONF_HVAC_AC_RESET_NIGHT_BUDGET` | `2` | 3 (Number, 0-4) | Same. Night gets the larger share where measured damage lives. |
| `CONF_HVAC_AC_NIGHT_START_HHMM` | `"22:00"` | 2 (options flow, string) | Wall-clock boundary. Rung 2 not 3 because it is set once for a household, not tuned by observation. |
| `CONF_HVAC_AC_NIGHT_END_HHMM` | `"06:00"` | 2 | Same. |
| `CONF_HVAC_AC_SOFT_NUDGE_DAILY_LIMIT` | `50` | 3 (Number) | Runaway guard above measured 31-43/day. Operator explicitly wanted this configurable — card `RECOMMENDATION_EFFECTIVE_REDEFINITION_2026_08_21`. |
| `CONF_HVAC_AC_DURABILITY_WINDOW` | `30` (minutes) | 2 (options flow) | Set once per household to match observed recurrence cadence. Not rung 3 because moving it retroactively re-classifies past rows (confusing telemetry). |
| `hvac_ac_reset_off_duration` (Number) | `60` (seconds) | 3 (Number, 30-300s) | Operator tunes by hand today. See D7 rationale. |

Kill-switch semantics documented on each: `RECURRENCE_ENABLED=False` →
D1 runs in shadow, no `_perform_ac_reset` call from the recurrence
branch. `SOFT_NUDGE_DAILY_LIMIT=0` disables the cap. `RESET_DAY_BUDGET=0`
or `RESET_NIGHT_BUDGET=0` disables resets in that partition entirely
(useful for guest-in-house night suppression later).

---

## 6. Producer/consumer map — every new value

### D1 — recurrence window count

- **Producer:** the count is a live rolling read over `ac_ramp_events`
  rows WHERE `event_type='nudge_started' AND zone_id=Z AND timestamp >
  now() - W`. Depends on: the existing `_track_zone_action` writing
  `nudge_started` rows (verified live, 47 rows in one night per the
  card). Dependency healthy.
- **Consumers:**
  - `_hard_reset_eligible` (trust decision) — only when
    `CONF_HVAC_AC_RECURRENCE_ENABLED=True`.
  - `sensor.ac_recurrence_window_count_<zone>` (display).
  - `ac_ramp_events` shadow row `recurrence_would_fire` (audit).

### D2 — day/night reset counts

- **Producer:** `_perform_ac_reset` increments the partition matching
  wall-clock now against the boundary knobs.
- **Consumers:** `_hard_reset_eligible` (trust); two live sensors
  (display); day-rollover reset code in `ac_reset_state` DAO.

### D3 — soft-nudge daily count check

- **Producer:** `state["soft_nudge_count"]` (already written).
- **Consumer:** new eligibility check in `_evaluate_ac_ramp_zone`.

### D4 — durable / durable_minutes

- **Producer:** `_write_durable` callback scheduled from
  `nudge_evaluated`.
- **Consumers:** `sensor.ac_ramp_durability_rate_<zone>` (display).
  No trust consumer in this cycle.

### D5/D6 — reset telemetry rows + reset_outcome

- **Producer:** `_perform_ac_reset` (start row) + `_restore_after_reset`
  post-verify (completed row) + a delayed `_classify_reset_outcome`
  callback that reads temp_end.
- **Consumers:** `sensor.ac_reset_last_outcome_<zone>` (display).
  No trust consumer in this cycle.

### D7 — reset off-duration knob

- **Producer:** operator (dashboard slider) via Number entity.
- **Consumer:** `_perform_ac_reset` off-window scheduler.

---

## 7. Measure-before-build probe — calibrating N and W

**One-shot read-only probe, cheap.** Runs on the HA host via SSH against
`ac_ramp_events` (already has 6+ days of `nudge_started` rows on 3
zones). Output goes into this doc under §7 before D1 code lands.

For each zone, compute:

1. Distribution of inter-nudge intervals — median, p25, p75, count of
   intervals < 30min, < 60min, < 90min.
2. For candidate (N, W) pairs in {(2, 60), (2, 90), (2, 120), (3, 90),
   (3, 120)}, count how many times per day the trigger WOULD have
   fired historically.
3. Cross-reference with the 11 historical `hard_reset_*` events: does
   the recurrence trigger fire at least as often as the ineffective
   branch did?

**Decision:** if any candidate would have fired > 4x/day on any zone,
the default is too aggressive and D2 budgets will refuse anyway — but
the operator experience is "the automation keeps proposing resets it
won't do", which pollutes the declined trail. Prefer the largest (N, W)
that still fires ≥ 1x on the 08-20 overnight case (47 nudges) — that is
the founding operator complaint and the acceptance case.

**Do this before dispatching the build.** Result goes into a new §7.1
in this doc. Builder reads §7.1 for the default values, not the table
in §5 (which is provisional).

---

## 8. Acceptance criteria — DISCRIMINATING

Each criterion states what the observation looks like under the fix
AND under a plausible different failure. If the two look identical,
the criterion is rejected and rewritten.

### AC1 (D1 — recurrence trigger shadow, ships live-observable)

- **Verify:** with `CONF_HVAC_AC_RECURRENCE_ENABLED=False`, force
  N+1 nudges on zone_1 within W by manipulating detection thresholds
  in a test harness. Expect exactly N `recurrence_would_fire` shadow
  rows in `ac_ramp_events` for zone_1 in the run window, and ZERO
  `hard_reset_started` rows attributable to the recurrence branch.
- **Under a plausible failure** (recurrence code accidentally live
  despite kill switch): a `hard_reset_started` row appears with
  `triggered_by='recurrence'`. The criterion discriminates because it
  asserts BOTH the shadow row presence AND the reset absence.
- **Live:** after enabling in production for one overnight, at least
  one `recurrence_would_fire` row appears on the 08-20-shape night;
  and after arming, at least one `hard_reset_started` row with
  `triggered_by='recurrence'` appears within 7 days.

### AC2 (D2 — day/night budgets)

- **Sensor:** `sensor.ac_reset_day_count_<zone>` and
  `sensor.ac_reset_night_count_<zone>` both present and non-negative
  post-restart.
- **Verify (mutation):** temporarily set `day_reset_count=1,
  night_reset_count=0` in DB for a zone, then trigger a reset request
  during the day window — the request is denied with
  `reason=day_budget_exhausted` written to a
  `hard_reset_declined` row; a reset request the same minute during
  the night window (by clock override in test) succeeds.
- **Under a plausible failure** (budget check uses the wrong
  partition or falls back to combined counter): the daytime request
  succeeds when it should be denied. The criterion discriminates
  because the DENIED row's `reason` code is inspected, not merely the
  count.

### AC3 (D3 — soft-nudge daily cap)

- **Verify (in-suite):** hand-craft `ac_reset_state.soft_nudge_count =
  50` for a zone; trigger `_evaluate_ac_ramp_zone`; assert no
  `_perform_soft_nudge` call AND a log line
  `"soft_nudge_daily_limit_reached"`.
- **Under a plausible failure** (cap check uses previous day's
  counter or off-by-one): the 50th nudge fires. Discriminates because
  the counter and the log line are both asserted.
- **Live:** soft-nudge count in `ac_reset_state` never exceeds 50 for
  any zone in any single day post-deploy.

### AC4 (D4 — durable columns + delayed write)

- **Verify (in-suite):** simulate a nudge_evaluated with
  kwh_rate_before=2.5, post_min=0.2; advance simulated clock by 30
  min with kW staying at 0.3; assert `durable=1, durable_minutes=30`.
  Then repeat with kW returning to 2.4 at t+15 min: assert
  `durable=0, durable_minutes=15`.
- **Under a plausible failure** (`_write_durable` mutates `effective`):
  the classifier's `effective=1` on the original evaluated row would
  read back different. Discriminates because the test asserts BOTH
  `durable=0` AND `effective=1` on the same row (not just one).
- **Live:** ≥ 24 hours post-deploy, at least one `ac_ramp_events` row
  has non-NULL `durable` for each zone that saw nudge activity.

### AC5 (D5/D6 — reset telemetry + drift)

- **Verify (in-suite):** trigger a hard reset in a test with
  temp_start=76.0, target=76.0. After
  `_restore_after_reset` completes with temp_end=76.1, assert
  `hard_reset_completed` row has `current_temp=76.1`,
  `preset_after=<known>`, `mode_after='heat_cool'`,
  `reset_outcome='floor_survived'`. Repeat with temp_end=77.5 →
  `reset_outcome='justified_ramp'`.
- **Under a plausible failure** (temp captured before restore, so
  temp_end == temp_start): both scenarios above collapse to the same
  outcome. Discriminates because two temperatures produce two
  different outcomes.
- **Live:** the first live hard reset post-deploy writes both a
  `hard_reset_started` row with non-NULL `current_temp` and a
  `hard_reset_completed` row with non-NULL `current_temp` and a
  non-NULL `reset_outcome`.

### AC6 (D7 — off-duration knob)

- **Verify:** set Number entity to 90; trigger a reset; measure
  `async_call_later` delay = 90s (not 60s). NM alert message
  interpolates "90s".
- **Under a plausible failure** (module constant still consumed):
  delay is 60s. Discriminates on the observed delay AND the alert
  string.

### AC7 (invariant I — non-negotiable)

- **Test:** for any 24h window in a simulated day-loop that runs the
  cycle 100x under randomised nudge cadence, total
  `hard_reset_started` per zone ≤ `day_budget + night_budget`, AND
  every consecutive pair on the same zone is ≥ 120 min apart, AND if
  `RECURRENCE_ENABLED=False` throughout, no row has
  `triggered_by='recurrence'`. All three sub-assertions must hold on
  every iteration.

---

## 9. Restart-safety declaration

| New state | Category | Mechanism |
|---|---|---|
| `day_reset_count` / `night_reset_count` | **PERSIST** | Columns on existing `ac_reset_state`; loaded by existing DAO on boot. |
| Rolling `nudge_started` window for D1 | **REBUILD** | Computed on demand from `ac_ramp_events` (indexed on `zone_id, timestamp`); no in-memory state that must survive. |
| `_write_durable` in-flight callback | **PERSIST via `in_flight_durable_started_ts`** | Sibling column on `ac_reset_state`, sibling audit step in `async_startup_ramp_audit`; elapsed-time arithmetic; callback ≤ 0 remaining fires immediately post-boot. |
| Number entity `hvac_ac_reset_off_duration` | **PERSIST** | URA Number-persistence machinery (existing). |
| Config/options flow knobs | **PERSIST** | HA config-entry storage (existing). |
| `recurrence_would_fire` shadow rows | **PERSIST** | Written to `ac_ramp_events` — the ledger is the record. |

No state category is RESET — the existing day-rollover logic on
`ac_reset_state` handles daily zeroing of counters and the two new
partition counters ride on the same rollover.

---

## 10. Layering with HVAC-GOVERNED-EXCURSION-1

Both cycles touch the reset producer sites (`_perform_ac_reset`,
`_restore_after_reset`). Ship order:

- **This cycle first:** D5's producer wiring writes telemetry directly
  via `_track_zone_action` (the existing helper). No dependency on
  the excursion primitive.
- **Excursion cycle D2/D3 later:** re-plumbs the reset path through
  the excursion API. D5's rows become a consumer of the primitive
  rather than a peer emitter.

The two orderings are compatible because D5 writes the SAME column
set the excursion cycle would (columns already exist on
`ac_ramp_events` from EXCURSION D1). A follow-up refactor consolidates
the writer.

**Do NOT block this cycle on excursion D2/D3.** The measured defect is
recurring and operator-costing; the excursion primitive is
architectural cleanup.

---

## 11. Tier 3 test-authority (real per-site source mutation)

For Reviewer C (test authority) and the mandatory orchestrator
verification before ship:

- **Site 1:** `_hard_reset_eligible` day/night partition gate. Neuter
  the partition check (make it always return true). Expect AC7's
  budget invariant test to fail with a specific over-budget count.
- **Site 2:** D1 recurrence-enabled kill switch. Neuter (make the
  branch always live). Expect AC1's shadow-mode test to fail with
  a `hard_reset_started/triggered_by=recurrence` row.
- **Site 3:** D3 soft-nudge cap. Neuter. Expect AC3's counter test to
  fail at N=51.
- **Site 4:** D4 durable non-mutation. Mutate `_write_durable` to
  overwrite `effective`. Expect AC4's "both durable and effective on
  the same row" assertion to fail.
- **Site 5:** D6 temp-end capture. Neuter (write temp_end = temp_start).
  Expect AC5's two-outcome test to fail.
- **Site 6:** D7 knob read. Neuter (always read module constant).
  Expect AC6 delay assertion to fail at knob=90.

A site whose neutering leaves the suite green is untested = unacceptable.
Orchestrator re-runs sites 1, 2, and 4 personally before ship (highest
blast radius).

---

## 12. Flags on the brief — issues raised for the orchestrator

Per instruction "flag anything in this brief you believe is wrong":

1. **D5 as written is redundant on the nudge path.** The columns
   `preset_before`, `preset_after`, `mode_before`, `mode_after`,
   `restore_ok`, `restore_ok_immediate` already exist on
   `ac_ramp_events` (`database.py:1519-1524`) and are written on the
   nudge path by HVAC-GOVERNED-EXCURSION-1 D1 (v5.86.0). The remaining
   gap is HARD-RESET-path telemetry — narrower than "add
   `preset_before`/`preset_after` columns" implies. §3-D5 documents
   the corrected scope. Confirm the corrected framing before build.

2. **D2 defaults raise total daily cap from 2 to 3.** DAY 1 + NIGHT 2
   = 3, versus today's `DEFAULT_HVAC_AC_HARD_RESET_DAILY_LIMIT=2`.
   The 120-min min-interval bounds the worst case (max ~12
   theoretical, in practice far fewer), but this IS a policy
   loosening on top of the partitioning. Alternatives: DAY 1 +
   NIGHT 1 (holds total at 2, simplest); DAY 0 + NIGHT 2 (rare in
   day, generous at night, matches "measured damage lives overnight"
   most literally). Recommend operator picks one before ship.
   Provisionally planned as 1/2 per the card's suggestion.

3. **"Defaults OFF" is under-specified: hard-off vs shadow-mode-on?**
   The brief cites the STEP-chatter shadow pattern which is a
   THIRD option (compute + log + do-not-act, distinct from both
   feature-disabled and full-live). §3-D1 assumes shadow-on-by-default
   with the live-arming as the operator flip. This is more valuable
   than hard-off because it collects the tuning data. Confirm.

4. **`AC_RESET_STUCK_MINUTES = 10` at `hvac_const.py:492` was not
   mentioned in the brief.** It is a sibling reset constant; not
   promoting it is defensible (it is a detection threshold, not the
   operator's manual technique). Flagging so the decision is
   explicit rather than accidental.

5. **The brief's phrase "ships complete and tested" for D1 conflicts
   subtly with the shadow-on-by-default interpretation above.** In
   shadow, the RESET-firing branch is untested-in-production until
   the operator arms it — the shadow rows are tested, the reset
   emission is only in-suite tested. This is by design (that's the
   point of shadow), but worth stating: enabling in production is a
   separate live-validation event and belongs on the post-ship
   validation table.

6. **D6's `reset_outcome` classification runs against a moving
   target.** `temp_end` is read at some delay after
   `_restore_after_reset` — the card says the point of the OFF
   window is short enough that temp has not drifted meaningfully,
   but the classifier itself needs a settle window (analogous to
   the 12s D1 settle in HVAC-GOVERNED-EXCURSION-1). Recommend a
   parallel `_write_reset_outcome` delayed callback modelled on
   `_write_settled`, with a fixed 60-second settle. Not called out
   explicitly in the brief but the classifier needs it.

7. **The observability audit gap #5 (savings unreconciled — ~35
   kWh claimed on a 49 kWh night) is not addressed by this cycle.**
   D4 lays the groundwork (durability metric), but reconciliation
   with metered whole-house energy is a separate cycle
   (AC-RAMP-SAVINGS-RECONCILE-1). Parked.

---

## 13. Files touched (summary for the builder)

- `custom_components/universal_room_automation/domain_coordinators/hvac_const.py`
  — new CONF_/DEFAULT_ constants per §5.
- `custom_components/universal_room_automation/domain_coordinators/hvac_override.py`
  — recurrence trigger + shadow emit; day/night partition check in
  `_hard_reset_eligible`; soft-nudge cap check in
  `_evaluate_ac_ramp_zone`; `_write_durable` delayed callback +
  startup audit sibling; reset telemetry writes at
  `_perform_ac_reset` + `_restore_after_reset`; `_write_reset_outcome`
  delayed callback; consume Number entity for off-duration.
- `custom_components/universal_room_automation/database.py`
  — ADD COLUMN on `ac_reset_state` (`day_reset_count`,
  `night_reset_count`, `in_flight_durable_started_ts`); ADD COLUMN
  on `ac_ramp_events` (`durable`, `durable_minutes`,
  `reset_outcome`); DAO read/write updates for the new columns.
- `custom_components/universal_room_automation/number.py`
  — new Number entity `hvac_ac_reset_off_duration`; two new Number
  entities for `RECURRENCE_COUNT_N` and `RECURRENCE_WINDOW_MIN`; two
  for `RESET_DAY_BUDGET` and `RESET_NIGHT_BUDGET`; one for
  `SOFT_NUDGE_DAILY_LIMIT`.
- `custom_components/universal_room_automation/config_flow.py` +
  `options_flow.py` — `RECURRENCE_ENABLED` toggle, night boundary
  strings, `DURABILITY_WINDOW`.
- `custom_components/universal_room_automation/sensor.py`
  — the D8 live sensors.
- Tests under `quality/tests/` — one test per acceptance criterion,
  plus the mutation drill fixtures per §11.

Builder: verify the exact file names/paths before editing (Institutional
Context First applies to your edits as well as to this plan).

---

## 13. Orchestrator rulings on the planner's §12 pushbacks (2026-08-22)

Operator is asleep; these are orchestrator calls, each flagged as such and reversible.

**§12.1 — D5 largely already built. ACCEPTED, and it is the plan's best finding.**
`preset_before` / `preset_after` / `mode_before` / `mode_after` / `restore_ok` /
`restore_ok_immediate` already exist (`database.py:1519-1524`) and are already written on the
NUDGE path (v5.86.0 D1, `hvac_override.py:3341`, `:3496`). Only the HARD-RESET path is missing.
This is exactly the "extend, do not rebuild" principle paying out — a deliverable I had listed as
new was two-thirds shipped. D5 is rescoped to the reset path only.

**§12.2 — DAY/NIGHT budget defaults. RULED: ship DAY 1 / NIGHT 1, not 1/2.**
The planner is right that DAY 1 + NIGHT 2 raises the total daily cap from 2 to 3, which is a
policy LOOSENING smuggled in as a default. Ship **1 + 1**, keeping the existing total of 2
unchanged, with both values as knobs. Rationale: the recurrence trigger ships in SHADOW, so no
additional resets fire either way — there is no cost to the conservative default and it avoids
pre-deciding a policy question while the operator sleeps. The operator's own card suggested
NIGHT 2 and that remains the likely end state; it becomes a one-knob flip they make deliberately
after seeing shadow data. **Flag this for confirmation in the morning.**

**§12.3 — "Defaults OFF" under-specified. ACCEPTED: shadow, not hard-off.**
Compute the recurrence condition, write `recurrence_would_fire` shadow rows, do NOT act. Strictly
better than hard-off: it collects the (N, W) tuning data from the moment it ships, and it mirrors
the STEP-chatter v5.85.0 pattern. Satisfies the operator safety constraint in full — nothing new
actuates unattended. The kill switch must still exist and must still be able to disable the
shadow computation.

**§12.4 — `AC_RESET_STUCK_MINUTES` stays rung 1. ACCEPTED.** It is a detection threshold, not the
operator's hand-tuned technique. The rung-3 promotion applies to `AC_RESET_OFF_DURATION_SECONDS`
only.

**§12.5 — D6 needs a settle-window callback. ACCEPTED, and this is a correctness fix.** A direct
temp read at `_restore_after_reset` return measures too early to detect drift. Model
`_write_reset_outcome` on the shipped `_write_settled` (`hvac_override.py:3521-3528`).

**§12.6 — savings-vs-metered reconciliation parked as `AC-RAMP-SAVINGS-RECONCILE-1`. ACCEPTED.**
Out of scope; the operator has already ruled the savings figure is directional-not-forensic.

**§12.7 — D4 needs `in_flight_durable_started_ts` + a startup-audit sibling. ACCEPTED, required
for correctness.** Without it the durable callback is stranded by a restart. Mirrors the existing
`in_flight_nudge_*` pattern, which the card correctly identifies as the exemplar.

### Standing constraint restated for the builder
Nothing in this cycle may cause a hard reset to fire that would not have fired before, until the
operator deliberately enables the recurrence trigger. Columns, telemetry, the soft-nudge cap and
the knob promotions ship live; the trigger ships in shadow.
