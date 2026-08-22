# PLANNING — AC-RAMP-NO-RECURRENCE-ESCALATION-1

**Tier:** 3.
**Revision:** 2 (2026-08-22). Revised in response to two framing-disjoint
plan reviews that returned REVISE FIRST — both converged on the same
class of defect: the previous revision named functions and gates that
do not exist, understated the migration + DAO discipline, and offered
choices where a decision is required. This revision GREPS every anchor
before naming it, asserts every decision, and propagates each ruling
into every section that consumes it.

**Governing constraint (operator, verbatim):** *"I do not expect you to
rebuild ac reset from scratch. We always work from existing and goals
or enhancements or correctness problems."* Every deliverable below is a
delta on real, verified anchors. If the builder finds themselves
restructuring, stop.

---

## 0. What already works — verified anchors (do not rebuild)

Every line:number here was grepped against
`custom_components/universal_room_automation/` on 2026-08-22. Where the
previous revision was wrong, the correction is called out.

### Detection ladder (soft-nudge entry point)

- Entry: `check_ac_reset` at `hvac_override.py:2684`, invoked from the
  5-minute HVAC decision cycle.
- Gate ladder 0a → 9 at `:2720-2860`:
  - 0a/0b — master + nudge-enabled short-circuits (`:2720-2741`).
  - 1 — `_ramp_master_enabled` (`:2743`).
  - 2 — per-zone `zone.ramp_zone_enabled` (`:2769`).
  - 3 — `zone.ac_load_sensor` configured (`:2774`).
  - 4 — `hvac_action == "cooling"` + valid temps (`:2779, :2785`).
  - 5 — DB `lockout_flag` (`:2789-2793`).
  - 6 — overshoot at-or-below setpoint (`:2795-2813`).
  - 7 — kWh rate above threshold N consecutive samples
    (`:2825-2836`).
  - 8 — time-sustained ≥ detection_time_gate min (`:2838-2856`).
  - 9 — not already `in _nudge_in_flight` (`:2857-2858`).
- **CORRECTION vs revision 1 and vs the card body:** there is NO
  `AC_NUDGE_MIN_INTERVAL_S` constant and NO `_evaluate_ac_ramp_zone`
  function anywhere in the repo. The card's claim that "the 30-minute
  min interval IS being honoured / the interval knob shipped and the
  cap did not" is FACTUALLY WRONG at the code level — the ~2/hour
  cadence is EMERGENT from Gates 8 (10-min sustained overshoot) + the
  5-min hold + the 600s eval + Gate 9 (no re-entry while in-flight),
  not from an interval enforcement. This finding is flagged §12; the
  card's "measured:" section should be corrected downstream.

### Soft nudge — perform / restore / evaluate / classify

- `_perform_soft_nudge` at `hvac_override.py:3099` (setpoint write,
  blocking=False; manual-invoke path enters here at `:4205`).
- `_restore_after_nudge` at `hvac_override.py:3197`.
- Telemetry writeback (SETTLED sample) at `:3462-3540` — this is the
  in-repo pattern D4 and D6 mirror.
- Classifier at `hvac_override.py:3745-3772` — the ONLY branch that
  raises `escalate=True` is the ineffective / ineffective_no_samples
  paths at `:3763` and `:3772`; on `escalate=True` the caller invokes
  `_perform_hard_reset_escalation`.

### Escalation actuator (NOT a predicate)

- **CORRECTION:** the function is `_perform_hard_reset_escalation` at
  `hvac_override.py:3874` — not `_hard_reset_eligible` as the previous
  revision incorrectly named 6-8 times. It is an actuator with side
  effects, not a boolean gate. Its shape:
  - Early-return guards: `_ac_reset_enabled` (`:3911`); corrective
    writes suppressed (`:3924`); no DB (`:3931`).
  - Gate A (daily cap): `hard_reset_count >= _hard_reset_daily_limit`
    → **`_engage_lockout(zone, state)`** at `:3937-3940`.
    `_engage_lockout` sets `lockout_flag=1`, fires a persistent
    "controller may be broken" NM notification, and disables the
    zone's ramp feature at Gate 5 for the rest of the day.
  - Gate B (global min-interval, across day-rollover) at `:3942-3957`
    using `get_global_last_hard_reset_ts` — logs and skips on fail
    (no lockout).
  - On both gates passing: increment `hard_reset_count` at `:3960`;
    persist via `save_ac_reset_state` at `:3962`; **already writes
    `hard_reset_started` via `log_ac_ramp_event` at `:3967-3972`**;
    then calls `_perform_ac_reset` at `:3977`.
- `_perform_ac_reset` at `hvac_override.py:2884` — issues
  `set_hvac_mode=off` (blocking=True), schedules `_on_reset_fire` via
  `async_call_later(AC_RESET_OFF_DURATION_SECONDS)` at `:2904-2908`,
  sends NM alert at `:2911-2919` interpolating
  `AC_RESET_OFF_DURATION_SECONDS` at `:2915` and
  `AC_RESET_MAX_PER_DAY` at `:2916`.
- `_restore_after_reset` at `hvac_override.py:2921`, chooses
  `target_mode = heat_cool if _supports_heat_cool(...) else
  original_mode` at `:2937-2939`, issues `set_hvac_mode` at
  `:2952-2958`, launches `_verify_restore` at `:2968+` with three
  terminal branches:
  - Success at `:3022-3027` (logs "verified").
  - Failure after 2 retries at `:3005-3021` (critical NM).
  - Cancelled/pop at `:2999-3001`.
- **Already writes `hard_reset_completed`** via `log_ac_ramp_event`
  at `:3049-3055`.
- **SECOND CALLER of `_restore_after_reset`** at `hvac_override.py:2000`
  — the `ac_reset_enabled` property setter's disable-path calls
  `_restore_after_reset(zone, "heat_cool")` to unstick mid-reset
  zones when the operator flips the feature OFF. This is an ABORT,
  not a completion.

### Persistence

- Table `ac_reset_state` DDL at `database.py:1431-1446`. PK is
  `(zone_id, date)`. Carries `soft_nudge_count`, `hard_reset_count`,
  three timestamps, three `in_flight_nudge_*` fields, `lockout_flag`.
- Table `ac_ramp_events` DDL at `database.py:1503-1531`. Already
  carries `preset_before`, `preset_after`, `mode_before`, `mode_after`,
  `restore_ok`, `restore_ok_immediate`, `excursion_id` (all added by
  HVAC-GOVERNED-EXCURSION-1 D1 in v5.86.0). Indexed on
  `(zone_id, timestamp)` and on `timestamp`.
- Live-DB migration pattern (the ONLY one that actually runs against
  the 1.18 GB DB): `PRAGMA table_info` + guarded
  `ALTER TABLE ... ADD COLUMN` inside a try/except that logs on
  failure. **Precedent for `ac_ramp_events` at
  `database.py:1681-1712`.** There is currently NO such block for
  `ac_reset_state`; this cycle MUST create one (see §3-D2 and §12-3).
- Save DAO: `save_ac_reset_state` at `database.py:7306-7340` —
  **`INSERT OR REPLACE` with an EXPLICIT COLUMN TUPLE** at
  `:7314-7322`. Any column added to DDL that is not also added to
  this tuple resets to its DEFAULT on every save. This is the highest-
  probability silent failure in the cycle (Reviewer B).
- Read DAO: `get_ac_reset_state` above at `:7250-7305`; returns dict
  with defaults for missing keys.
- Global min-interval read: `get_global_last_hard_reset_ts` at
  `database.py:7344+`.

### Startup / teardown

- Startup restore of in-flight nudges: `async_startup_ramp_audit` at
  `hvac_override.py:3925` — codebase exemplar of restart-safe
  in-flight excursion.
- Teardown registries + cancel loops live at
  `hvac_override.py:1439-1459` — includes `_verify_tasks`,
  `_reset_timers`, `_nudge_settled_timers`. New delayed callbacks in
  this cycle register here.

### Aggregators that must not be polluted

- Savings aggregator: `database.py:7806-7830` — reads
  `ac_ramp_events` with NO `event_type` filter, summing
  `kwh_avoided` extracted from `notes`.
- False-positive aggregator: `database.py:7896-7906` — same shape,
  no `event_type` filter.
- Consequence: any NEW event_type this cycle emits MUST leave
  `effective` NULL AND MUST NOT carry a `kwh_avoided=` token in
  `notes`, or the live savings/FP sensors mis-count. This is an
  invariant, not a suggestion (§3-D8, AC-INVARIANT-AGG).

### Coordinator write-through for Number-backed knobs

- Precedent: `set_hard_reset_daily_limit` at
  `hvac_override.py:1276+`. Every Number entity in this cycle needs
  a sibling setter, or the slider moves and the coordinator never
  sees the new value.

### Manual buttons

- Manual soft-nudge: `force_nudge` invokes `_perform_soft_nudge`
  with `triggered_by="manual"` at `hvac_override.py:4205`.
- Manual hard reset: `force_ac_reset` at `hvac_override.py:4207+`.

### Sibling constant for settle delays

- `AC_NUDGE_RESTORE_SETTLE_DELAY_S = 12` (`hvac_const.py`, rung 1).
  D6's reset-outcome settle knob follows this precedent.

---

## 1. Institutional context verified

### Grep table — REUSED vs NEW, one row per proposed addition

Ran on 2026-08-22 against `custom_components/universal_room_automation/`
and `docs/`.

| Proposed | Search | Result | Disposition |
|---|---|---|---|
| Rolling count of `nudge_started` per zone in window W | `grep -n "nudge_started" hvac_override.py database.py` | `AC_RAMP_EVENT_NUDGE_STARTED` emitted from `_perform_soft_nudge`; already persisted via `log_ac_ramp_event`; indexed on `(zone_id, timestamp)` (`database.py:1526`). | **REUSED** — no new event type, no new counter table. |
| Recurrence knobs N and W | grep `recurrence` in `hvac_const.py` `number.py` | None. | **NEW** — Number entities per §5. |
| Recurrence-mode 3-state select | grep `AC_RECURRENCE_MODE` | None. | **NEW** — Select entity (`off`/`shadow`/`live`, default `shadow`). §5, §12-13. |
| Day/night reset counters | grep `day_reset_count` `night_reset_count` `database.py` `hvac_override.py` | None. | **NEW columns** on `ac_reset_state` via guarded ADD COLUMN block (see §3-D2). |
| Wall-clock night-window knobs | grep `night_start` `night_end` this axis | None on this axis. | **NEW** options-flow knobs, string HH:MM. |
| Soft-nudge daily cap | grep `soft_nudge.*limit` | None. | **NEW** — Number entity + gate site between real Gate 5 and Gate 6 (see §3-D3). |
| `durable` / `durable_minutes` on ac_ramp_events | grep | None. | **NEW columns** via the existing ac_ramp_events ALTER pattern at `database.py:1681-1712`. |
| `in_flight_durable_started_ts` on ac_reset_state | grep | None. | **NEW column** in the same new ALTER block as D2's counters. |
| `reset_outcome` on ac_ramp_events | grep | None. | **NEW column** via the same ac_ramp_events ALTER pattern. |
| `preset_before/after`, `mode_before/after`, `restore_ok*` on ac_ramp_events | grep | **ALREADY EXIST** (`database.py:1519-1524`), producer wired for nudge path only. | **REUSED**; D5 only wires the HARD-RESET-path producer as an ENRICHMENT of the existing `log_ac_ramp_event` calls at `:3967` and `:3050` (see §3-D5). |
| `hard_reset_declined` event type | grep constants for the string | None. | **NEW** — add `AC_RAMP_EVENT_HARD_RESET_DECLINED` to `hvac_const.py`. |
| Recurrence-shadow event type | grep | None. | **NEW** — `AC_RAMP_EVENT_RECURRENCE_WOULD_FIRE`. |
| Rung-3 promotion of `AC_RESET_OFF_DURATION_SECONDS` | Number siblings at `number.py:2435-2441` per card. | Sibling knob pattern exists; setter precedent `set_hard_reset_daily_limit` at `:1276`. | **REUSED pattern; NEW Number entity + coordinator setter** (see §3-D7). |

### Prior planning docs consulted

- `docs/planning/PLANNING_v4.5.11_ac_energy_aware_ramp_down.md` — the
  objective doc; goal 3 ("rapid compressor cycling is the worst possible
  failure mode") drives Invariant I. Specced the 6/day soft-nudge cap
  that D3 finally builds.
- `docs/planning/PLANNING_hvac_governed_excursion.md`
  (HVAC-GOVERNED-EXCURSION-1) — D1 shipped the preset/mode/restore
  columns on `ac_ramp_events` and their nudge-path producer wiring
  in v5.86.0. D2/D3 (primitive) are UNBUILT per that card's
  STATUS_CORRECTED_2026_08_22 note. This cycle is designed to be
  compatible with either ship order; D5 writes telemetry DIRECTLY at
  the reset producer sites (enriching the existing `log_ac_ramp_event`
  calls) and does not create a new writer.
- Kanban card `AC-RAMP-NO-RECURRENCE-ESCALATION-1` — every dated
  addendum, in particular `RESET_DRIFT_CONSTRAINT_2026_08_22`,
  `RECOMMENDATION_EFFECTIVE_REDEFINITION_2026_08_21`,
  `LAYERING_AND_RETROACTIVE_2026_08_21`,
  `LIVE_INSTANCE_AND_MECHANISM_2026_08_22`,
  `AC_RAMP_IS_A_MANUAL_INDUCER_2026_08_21`,
  `OBSERVABILITY_AUDIT_2026_08_21`, `DELTA_T_PROBE_2026_08_21`,
  `RESET_BUDGET_WINDOWING_2026_08_21`,
  `WIDE_CYCLE_REFUTED_LOAD_MATCHED_2026_08_21` (SUPERSEDES the
  earlier `WIDE_CYCLE_EFFECTIVENESS_2026_08_21` — respected).

### Memories pulled

- `feedback_measure_before_build.md` — probe-first gate discharged
  on the card; one further calibration probe scoped in §7.
- `feedback_marginal_benefit_pushback.md` — applied to D1 (three-mode
  Select vs boolean; Select wins because §12-3 requires disabling
  shadow too).
- `feedback_cross_investigation_synthesis.md` — D5 sits inside
  HVAC-GOVERNED-EXCURSION-1 D2/D3 territory; §10 states the ship
  order.
- `feedback_suppression_needs_discharge.md` — the recurrence-mode
  Select is a suppression: what re-arms it, and what does a restart
  observe? Answered §6, §9.
- `feedback_wire_in_anchor_mandatory.md` — every deliverable names
  its enclosing method + the neuter drill that must fail (§11).
- `reference_ec_reserve_verifiable_backout_knob.md` — precedent for
  a safety kill knob defaulted to a specific safe value.

### Code read end-to-end during scoping

- `hvac_override.py`: lines 1276-1310 (Number write-throughs),
  1439-1459 (teardown), 1990-2005 (setter abort path into
  `_restore_after_reset`), 2680-2870 (`check_ac_reset` gate ladder),
  2884-3055 (`_perform_ac_reset` + `_restore_after_reset` +
  `_verify_restore` + `hard_reset_completed` write),
  3099-3260 (soft nudge perform/restore), 3450-3540
  (telemetry SETTLED), 3745-3800 (classifier + escalate),
  3874-4020 (`_perform_hard_reset_escalation` + `_engage_lockout`),
  4200-4260 (`force_nudge`, `force_ac_reset`), 3925 (startup audit).
- `hvac_const.py`: 480-540 (AC reset legacy + v4.5.11 knobs), and
  the `AC_NUDGE_RESTORE_SETTLE_DELAY_S = 12` sibling.
- `database.py`: 1431-1531 (DDL), 1681-1712 (live ALTER precedent),
  7250-7345 (ac_reset_state DAO — critical INSERT OR REPLACE tuple),
  7480-7530 (`log_ac_ramp_event` — verified it returns from execute
  but does NOT currently expose `lastrowid`; §3-D4 requires that).
- `database.py`: 7806-7830 (savings aggregator, no event_type filter);
  7896-7906 (FP aggregator, no event_type filter).

---

## 2. The falsifiable invariants

### Invariant I — bounded compressor cycling under the new trigger

> Given any 24h window, the total number of `hard_reset_started`
> events for a single zone is bounded by `day_reset_budget +
> night_reset_budget`, with per-partition counts bounded
> individually, and every consecutive pair on the same zone is ≥
> `hard_reset_min_interval` minutes apart across the day-rollover
> boundary. When `hvac_ac_recurrence_mode ∈ {off, shadow}` throughout
> the window, ZERO `ac_ramp_events` rows have
> `triggered_by = 'recurrence'` AND `event_type =
> 'hard_reset_started'`. Furthermore, a denied-by-cap recurrence
> request MUST NOT call `_engage_lockout` — lockout is reserved for
> the ineffective-nudge path where the classifier concluded the
> controller may be broken.

### Invariant II — reset outcome measurability

> Every `hard_reset_started` row in `ac_ramp_events` written by the
> automatic path (i.e. NOT the `ac_reset_enabled` setter abort at
> `hvac_override.py:2000`) carries a non-NULL `current_temp` if the
> zone's temperature sensor was reporting a valid value at that
> instant; the paired `hard_reset_completed` row (identified by
> `event_id` from the started-row via the D4/D6 event_id thread —
> §3-D4-3, §3-D5) carries `reset_outcome ∈ {'floor_survived',
> 'justified_ramp', 'inconclusive'}` and a non-NULL `current_temp`
> if the sensor was reporting at the outcome-settle point. Rows
> written by the setter-abort path at `:2000` carry `reset_outcome =
> NULL` and `triggered_by = 'abort_reason=feature_disabled'`.

Reviewer D's sole job: break these. Every enumeration below (call
sites, decline paths, restart branches, aborts) is a candidate leak.

### Invariant III — aggregator non-pollution

> New event types introduced by this cycle
> (`recurrence_would_fire`, `hard_reset_declined`) MUST leave
> `effective` NULL AND MUST NOT include a `kwh_avoided=` substring
> in `notes`. Enforced by a test that inserts one of each new type
> and asserts the shipped savings and false-positive aggregators
> return unchanged results.

---

## 3. Deliverables (all deltas — every decision asserted)

Every deliverable states LIVE-ON-SHIP vs SHADOW vs OFF explicitly.

### D1 — Recurrence trigger (SECOND, orthogonal escalation path)

**Status on ship: SHADOW.** Ships complete, ships tested, ships
observable in shadow mode. The operator moves the Select from
`shadow` to `live` when the recurrence data looks right.

**Mode knob — ASSERTED as a 3-state Select, not a boolean:**
`hvac_ac_recurrence_mode` with values `off` / `shadow` / `live`,
default `shadow` (see §5 and §12-13). A boolean cannot express three
behaviours, and the ruling below requires disabling shadow too.

- `off` — the recurrence code path returns immediately from its
  gate site; no computation, no shadow rows, no reset requests.
- `shadow` — computes the trigger; if N in W is met, writes ONE
  `recurrence_would_fire` event row per **window crossing**
  (edge-triggered — see §12-19; state kept in the coordinator as
  `_last_shadow_fire_ts` per zone). No call into the escalation
  actuator.
- `live` — same computation; on fire, calls
  `_perform_hard_reset_escalation` via a new keyword-only param
  `triggered_by="recurrence"`, AND passes `engage_lockout_on_cap=False`
  (see next paragraph).

**No-lockout-on-cap for recurrence — ASSERTED (Reviewer critical #1).**
`_perform_hard_reset_escalation` at `hvac_override.py:3874` gains a
new keyword-only parameter `engage_lockout_on_cap: bool = True`
(default preserves today's behaviour for the ineffective-nudge
path). When the recurrence caller passes `False` and Gate A fails,
the function MUST NOT call `_engage_lockout`; it MUST write ONE
`hard_reset_declined` event row with
`notes="reason=day_budget_exhausted"` (or `night_budget_exhausted`)
and return with `zone.ramp_state = AC_RAMP_STATE_IDLE`. Rationale
embedded in code comment: *"lockout means 'the controller is broken',
earned only by the ineffective-nudge classification path; a
recurrence-count denial is 'we already spent our budget', not a
controller pathology, and must not disable the working
ineffective-nudge escalation path."* Same discipline for Gate B
(min-interval); today it already skips without lockout, so the
recurrence caller inherits the correct behaviour.

**`triggered_by` plumbing — ASSERTED (Reviewer critical #10).**
`_perform_hard_reset_escalation` currently writes
`log_ac_ramp_event(...event_type=HARD_RESET_STARTED, ...)` at
`:3967-3972` WITHOUT passing `triggered_by`, which defaults to
`'auto'`. The parameter must be threaded from the caller through
the actuator into both the `_track_zone_action` call at `:3963-3966`
AND the `log_ac_ramp_event` call at `:3967-3972`. The
ineffective-nudge caller passes `"auto"`; the recurrence caller
passes `"recurrence"`. The setter-abort caller (§3-D5-B) passes
`"abort_reason=feature_disabled"`.

**Positive-control test requirement:** the AC1/AC7 test suite
includes, BEFORE the absence assertions, a positive-control test
that deliberately triggers the recurrence branch in `live` mode and
asserts EXACTLY ONE row exists with
`event_type='hard_reset_started' AND triggered_by='recurrence'`.
Only after that assertion passes does the shadow-mode absence
assertion mean anything.

**Producer of the count:** rolling read over `ac_ramp_events`
`WHERE event_type='nudge_started' AND zone_id=Z AND
timestamp > now() - W`. Dependency healthy (47 rows/night verified
on 08-20).
**Consumers:**
- `_perform_hard_reset_escalation` (trust) — only when mode=`live`.
- `sensor.ac_recurrence_window_count_<zone>` (display, D8).
- `ac_ramp_events` `recurrence_would_fire` rows in shadow (audit).

### D2 — Day/night partitioned reset budgets, no borrowing

**Status on ship: LIVE.**

**Defaults — ASSERTED as DAY 1 / NIGHT 1 (Reviewer critical #12).**
Total daily cap remains 2, matching today's
`DEFAULT_HVAC_AC_HARD_RESET_DAILY_LIMIT`. Do not raise the total in
this cycle; partitioning is the change. Both `§3-D2`, `§5`, and every
sensor default read the same value.

**Wall-clock window — ASSERTED as `[22:00:00, 06:00:00)` local, wrap
around midnight (Reviewer HIGH #17).** Boundary-string knobs
`hvac_ac_night_start_hhmm = "22:00"` and
`hvac_ac_night_end_hhmm = "06:00"`. Partition membership is computed
by a helper `_is_night_now(now, start_hhmm, end_hhmm)` with the
wrap-around case handled EXPLICITLY: `if start > end: night =
now >= start OR now < end`. Unparseable input fails CLOSED to
`day` (the smaller budget). This is the ONLY sanctioned
implementation; the plan states this so a builder writing
`start <= now < end` gets caught by review.

**Night-session date-key — ASSERTED (Reviewer HIGH #7).** The DB PK is
`(zone_id, date)`, and a naïve night bucket keyed on `now.date()`
lets a `night_budget=1` policy fire once at 23:30 (date=D) and
again at 00:30 (date=D+1) because the second reset reads a
fresh row. The rule: the night-partition counter is keyed to the
`night_session_date`, defined as `now.date()` if
`now.time() >= 06:00` else `now.date() - 1`. The night counter
lives on the row whose `date = night_session_date`. Producer and
consumer BOTH compute `night_session_date` via the same helper
`_night_session_date(now, night_start_hhmm, night_end_hhmm)`. A
test firing 23:30 + 00:30 with `night_budget=1` asserts the second
request is DENIED with `notes="reason=night_budget_exhausted"`.

**Schema (guarded ALTER — Reviewer critical #3):** create a new
migration block for `ac_reset_state` modelled EXACTLY on the
`ac_ramp_events` block at `database.py:1681-1712`. Use
`PRAGMA table_info(ac_reset_state)` → `are_columns = {row[1] ...}`
→ per-column guarded `ALTER TABLE ac_reset_state ADD COLUMN ...`
inside a try/except. Columns:

| column | type | default |
|---|---|---|
| `day_reset_count` | INTEGER | NOT NULL DEFAULT 0 |
| `night_reset_count` | INTEGER | NOT NULL DEFAULT 0 |
| `night_session_date` | TEXT | NULL |
| `in_flight_durable_started_ts` | TEXT | NULL |

**`save_ac_reset_state` tuple — ASSERTED must be extended
(Reviewer critical #5).** The INSERT OR REPLACE column list at
`database.py:7314-7322` MUST list the four new columns AND the
parameter tuple at `:7323-7335` MUST bind them, or every save
resets partition counters to 0 and the budget never denies. The
plan flags this as the highest-probability silent failure; the D2
test suite includes a specific case that saves a state with
`day_reset_count=1`, reads it back, asserts the returned dict has
`day_reset_count == 1`. This test fails deterministically if the
tuple is not extended.

**Partition increment site — ASSERTED at
`hvac_override.py:3960`, in the same read-modify-write block as
`hard_reset_count`, BEFORE `_perform_ac_reset` (Reviewer #14).**
Ordering is deliberate — a reset whose off-call fails still
consumes budget (fail-closed compressor protection). Comment
in-source: *"do not move this after `_perform_ac_reset`; charge
budget before actuating."* `hard_reset_count` continues to
increment as `day_reset_count + night_reset_count` reconciliation
invariant during rollout, then the next cycle may deprecate it
(parked).

**Enforcement site — ASSERTED at
`hvac_override.py:3938` (Gate A):** replace the single-counter
check with a partition-aware check that reads the current
partition, compares against the matching budget knob, and (via
D1) either calls `_engage_lockout` (ineffective-nudge caller) or
writes a decline row (recurrence caller, via
`engage_lockout_on_cap=False`).

**Restart safety:** PERSIST — counters and `night_session_date`
live on `ac_reset_state`, loaded on boot by the existing DAO.

**Producer:** `_perform_hard_reset_escalation` increments the
correct partition counter based on `_is_night_now(now, ...)`.
**Consumers:** the partition check inside
`_perform_hard_reset_escalation`; two display sensors
(`sensor.ac_reset_day_count_<zone>`,
`sensor.ac_reset_night_count_<zone>`).

### D3 — Soft-nudge daily cap

**Status on ship: LIVE.** Runaway guard, not a policy lever. Default
`50/day` above measured 31-43/day.

**Gate site — ASSERTED between real Gate 5 and real Gate 6 in
`check_ac_reset` (`hvac_override.py:2793-2795`), immediately BEFORE
the `_perform_soft_nudge` call reached at `:3157` via the detection
path (Reviewer critical #2).** Not "at the `AC_NUDGE_MIN_INTERVAL_S`
enforcement site" — no such site exists. Add:

```
# Gate 5b (D3): soft-nudge daily cap — runaway guard
if int(state.get("soft_nudge_count", 0)) >= self._soft_nudge_daily_limit:
    zone.ramp_state = AC_RAMP_STATE_LOCKED_OUT
    _LOGGER.info("soft_nudge_daily_limit_reached zone=%s count=%d",
                 zone.zone_id, state["soft_nudge_count"])
    continue
```

**Applies to auto only — ASSERTED (Reviewer #16).** The manual
`force_nudge` entry at `hvac_override.py:4205` (`_perform_soft_nudge`
called with `triggered_by="manual"`) BYPASSES the D3 cap. Operator
intent beats a runaway guard. Documented in the manual-button
docstring and in the D3 acceptance test.

**Coordinator setter for the Number:** `set_soft_nudge_daily_limit`
following `set_hard_reset_daily_limit` precedent at
`hvac_override.py:1276+`.

**Producer:** `state["soft_nudge_count"]` (already written).
**Consumer:** the new Gate 5b + display sensor.

**Restart safety:** REUSED — counter already persists on
`ac_reset_state`.

### D4 — Durable effectiveness (additive, non-mutating)

**Status on ship:** columns LIVE, delayed write LIVE, classification
DISPLAY-ONLY. No consumer flips savings math this cycle.

**Schema (ac_ramp_events ALTER block at `:1681-1712`):**
- `durable INTEGER` — nullable.
- `durable_minutes INTEGER` — nullable.

Neither column is referenced by `save_ac_reset_state`; they live on
`ac_ramp_events` which is append-only, so no INSERT OR REPLACE
tuple discipline applies here.

**Producer:** on `nudge_evaluated`, schedule `_write_durable` at
`now + D` minutes (`D = CONF_HVAC_AC_DURABILITY_WINDOW`, default
30, rung 2). Captured on the outer scope: the `event_id` returned
by the `nudge_evaluated` `log_ac_ramp_event` call — see next
paragraph.

**Row identity — ASSERTED (Reviewer critical #6).**
`log_ac_ramp_event` at `database.py:7480+` MUST be extended to
return `cursor.lastrowid` (an `int`). The callback closes over that
`event_id` and updates precisely that row:
`UPDATE ac_ramp_events SET durable=?, durable_minutes=? WHERE
event_id=?`. This eliminates the "UPDATE latest row" race that
would land the old measurement on a NEW nudge at the measured
31-43/day cadence.

**Cancel vs truncate — ASSERTED (Reviewer HIGH #11).** The rule:
- **Re-nudge on the same zone inside D fires the pending callback
  EARLY** with the elapsed interval as `durable_minutes` and
  `durable = 1 if kW stayed below threshold across the elapsed
  interval else 0`. Implementation: on entering
  `_perform_soft_nudge` for zone Z, look up
  `self._durable_timers[Z]`; if present, cancel the async_call_later
  handle AND immediately invoke the `_write_durable` closure with
  `truncated=True`.
- **Cancellation applies to teardown/unload only** — no write.
- **D reached without a re-nudge:** `_write_durable` fires,
  passive-reads kW, writes `durable=1, durable_minutes=D` (or 0 if
  kW recovered mid-window).

Pattern SOURCE for the cancellation-handle registry:
`_nudge_settled_timers` at `hvac_override.py:3512`. New registry
`self._durable_timers[zone_id]` follows the same shape and is
cancelled in the teardown block at `hvac_override.py:1439-1459`
(see D6 for the same discipline).

**Restart safety:** PERSIST via `in_flight_durable_started_ts`
column on `ac_reset_state` (added in D2's ALTER block; the
`save_ac_reset_state` INSERT OR REPLACE tuple ALSO carries this
column — same discipline as D2). `async_startup_ramp_audit` at
`hvac_override.py:3925` gains a sibling call
`_resume_in_flight_durable_evaluations` that computes remaining
time and reschedules; remaining ≤ 0 fires immediately post-boot;
missing kW history at boot writes `durable=NULL`.

**Consumers:** `sensor.ac_ramp_durability_rate_<zone>` (display).
No trust consumer.

**Non-goal:** MUST NOT overwrite `effective`. Reviewer D mutation
drill site #4 (§11).

### D5 — Enrich the EXISTING hard-reset event writes (not new rows)

**CORRECTED SCOPE — ASSERTED as ENRICHMENT (Reviewer critical #4).**
The `hard_reset_started` and `hard_reset_completed` rows are ALREADY
written today at `hvac_override.py:3967-3972` and `:3050-3055`.
Adding new rows via `_track_zone_action` (which is IN-MEMORY ONLY,
per its docstring at `:1250` — "no DB hit") would write NOTHING to
the DB AND double-count in the in-memory tracker if the plan
mistakes it for a DB writer. This deliverable is EXCLUSIVELY the
enrichment of those two existing `log_ac_ramp_event` calls with the
additional kwargs described below.

**D5-A — hard-reset started row enrichment (at `:3967-3972`).**
Threading `triggered_by` per D1, PLUS:
- `current_temp = zone.current_temperature` (feeds D6 Invariant II).
- `target_high = zone.target_temp_high`.
- `preset_before = zone.climate_entity state's preset_mode attr` at
  the instant of the call (read `hass.states.get(...)` once,
  extract preset).
- `mode_before = zone.climate_entity state's `state` at that
  instant.

The `log_ac_ramp_event` DAO already accepts these kwargs (all six
telemetry columns exist per `database.py:1519-1524`); this is
producer-side wiring only.

**D5-B — hard-reset completed row enrichment (at `:3050-3055`).**
- Read `hass.states.get(zone.climate_entity)` after
  `set_hvac_mode` returns; extract `preset_after`, `mode_after`,
  `current_temp` (from the zone's temp sensor, not the climate
  entity's target).
- `restore_ok = NULL` at write time — the completion row goes in
  IMMEDIATELY after `set_hvac_mode` returns, but the 30s +
  possible retry `_verify_restore` at `:2966+` is what actually
  proves restoration (Reviewer HIGH #9). Back-fill via `event_id`
  (extend `log_ac_ramp_event` to return `lastrowid` — the same
  extension D4 requires) from `_verify_restore`'s three terminal
  branches:
  - Success at `hvac_override.py:3022-3027` →
    `UPDATE ... SET restore_ok=1 WHERE event_id=?`.
  - Failure after retries at `:3005-3021` →
    `UPDATE ... SET restore_ok=0 WHERE event_id=?`.
  - Cancelled/pop at `:2999-3001` → no update (row stays NULL,
    correctly reflecting "measurement lost").

**D5-B setter-abort branch — ASSERTED (Reviewer HIGH #8).**
`_restore_after_reset` has a SECOND caller at
`hvac_override.py:2000` — the `ac_reset_enabled` setter's disable
path — which invokes it with a hardcoded `"heat_cool"` after the
operator toggles the feature OFF. This is an ABORT, not a
completion. The plan threads an explicit `completed: bool = True`
keyword-only parameter to `_restore_after_reset`. The setter caller
passes `completed=False, abort_reason="feature_disabled"`. When
`completed=False`, the enriched `hard_reset_completed` write:
- Sets `triggered_by = f"abort_reason={abort_reason}"`.
- Sets `reset_outcome = NULL` (D6 does not classify aborts —
  §3-D6).
- Skips scheduling `_write_reset_outcome` (D6).

**Status on ship: LIVE** — telemetry only, no behaviour change on
the automatic path. The setter-abort branch is instrumented for
the first time.

**Producer:** enriched `log_ac_ramp_event` calls at `:3967` and
`:3050` (both callers), plus back-fill from `_verify_restore`.
**Consumers:** operator diagnostics + D6 drift classifier.

### D6 — Room temp at reset-start and reset-outcome (drift discriminator)

**Status on ship: LIVE for capture; drift classification is
DIAGNOSTIC-ONLY.** No automated behaviour keys off drift this cycle.

**Measurement definition — ASSERTED (Reviewer #20).** Reset-end
temp is read at `restore + AC_RESET_OUTCOME_SETTLE_S` seconds,
NOT at the instant `_restore_after_reset` returns. Named this way
in-source and in-doc so a future change to
`hvac_ac_reset_off_duration` cannot silently change what is
measured. `AC_RESET_OUTCOME_SETTLE_S = 60` (module constant, rung
1, sibling of `AC_NUDGE_RESTORE_SETTLE_DELAY_S = 12`; §5).

**Delayed callback:** `_write_reset_outcome`, scheduled from
`_restore_after_reset` at reset-restore time, closes over the
`hard_reset_completed` `event_id` (via `log_ac_ramp_event`
returning `lastrowid`). At fire time:
- Passive-read zone temp.
- Compute:
  - `reset_outcome = "justified_ramp"` if
    `temp_settle > target_high` (drift above setpoint — the reset
    WORKED; subsequent ramp is expected).
  - `reset_outcome = "floor_survived"` if
    `temp_settle <= target_high AND post_kW ramps back` (the
    modulation floor SURVIVED — the reset FAILED).
  - `reset_outcome = "inconclusive"` if `temp_settle` unavailable
    OR `temp_start` unavailable (recorded on the started row).
- `UPDATE ac_ramp_events SET reset_outcome=?, current_temp=?
  WHERE event_id=?`.

**Schema (ac_ramp_events ALTER block):** `reset_outcome TEXT`
nullable.

**Registry + teardown — ASSERTED (Reviewer #18).**
`self._reset_outcome_timers[zone_id]` follows the
`_nudge_settled_timers` shape and is cancelled in the teardown
block at `hvac_override.py:1439-1459`.

**Setter-abort exclusion — ASSERTED.** When D5-B's `completed=False`
path fires, `_write_reset_outcome` is NOT scheduled and the
completed row's `reset_outcome` stays NULL.

**Restart safety:** REBUILD. The reset_outcome timer is short-lived
(60s); if the process restarts inside that window, the pending
callback is lost and the row keeps `reset_outcome=NULL`. The
row IS on disk (D5-B wrote it), so the miss is visible and
attributed correctly. Not worth persisting a per-zone in-flight
row for a 60s window.

**Producer:** `_write_reset_outcome` callback.
**Consumers:** `sensor.ac_reset_last_outcome_<zone>` (display).
No trust consumer.

**Non-goal:** MUST NOT feed the recurrence trigger or the budget in
this cycle. Data first; policy later once ≥ 20 samples exist.

### D7 — Promote `AC_RESET_OFF_DURATION_SECONDS` to rung 3

**Status on ship: LIVE.** Pure knob-rung change; day-zero behaviour
unchanged.

- From: module constant `AC_RESET_OFF_DURATION_SECONDS: Final = 60`
  (`hvac_const.py:493`).
- To: Number entity `hvac_ac_reset_off_duration` (default 60,
  range 30-300 seconds). The module constant remains as the
  first-boot seed value (mirror the
  `DEFAULT_HVAC_AC_NUDGE_EVAL_DELAY` pattern at
  `hvac_const.py:526`).
- **Coordinator write-through — ASSERTED
  (Reviewer #23):** new `set_ac_reset_off_duration` on the HVAC
  coordinator, modelled on `set_hard_reset_daily_limit` at
  `hvac_override.py:1276+`. Number entity `.async_set_native_value`
  calls this setter. Without it the slider moves and
  `_perform_ac_reset` at `:2906` keeps reading the stale
  coordinator attribute.
- **Consumption sites updated:** `hvac_override.py:2906` (the
  `async_call_later` delay) AND `:2915` (NM alert string
  interpolation) both read `self._ac_reset_off_duration_s`, not
  the module constant.

**Producer:** operator (dashboard slider).
**Consumer:** `_perform_ac_reset` off-window scheduler + NM alert.

### D8 — Observability: live sensors + declined-decision trail

**Status on ship: LIVE.**

- `sensor.ac_recurrence_window_count_<zone>` — rolling count over
  `ac_ramp_events` in the last W seconds. Attributes: `mode`
  (from D1 Select), `N`, `W`, `next_would_fire_estimate` (based
  on cadence).
- `sensor.ac_reset_day_count_<zone>` /
  `sensor.ac_reset_night_count_<zone>` — the two partition
  counters exposed live.
- `sensor.ac_reset_last_outcome_<zone>` — most recent D6
  `reset_outcome` value + timestamp attribute.
- **Declined-decision trail — ASSERTED via a new event type
  (Reviewer #19).** `AC_RAMP_EVENT_HARD_RESET_DECLINED` constant
  added to `hvac_const.py`. Every escalation-denied path writes
  ONE row of this type with `notes = f"reason={code}"` where
  `code ∈ {day_budget_exhausted, night_budget_exhausted,
  global_min_interval, feature_disabled, master_off,
  recurrence_shadow, comfort_deferred}`. Writes are edge-triggered
  (see §12-19): the coordinator tracks the last-declined reason
  per zone and only writes when reason changes or ≥ 15 minutes
  since last decline of same reason. This repo has a
  DB-write-flood rollback in its history — level-triggered writes
  are unacceptable.

**Invariant III enforcement — ASSERTED (Reviewer #15).** The
`hard_reset_declined` and `recurrence_would_fire` writes MUST leave
`effective = NULL` AND MUST NOT include a `kwh_avoided=` substring
in `notes`. Enforced by a test that inserts one of each and
diffs the shipped savings and FP aggregator return values before /
after.

**NM alert repair — ASSERTED (Reviewer #22).** The NM alert string
at `hvac_override.py:2915-2916` currently interpolates
`AC_RESET_OFF_DURATION_SECONDS` (D7 — updated to read the
coordinator attr) AND `AC_RESET_MAX_PER_DAY = 2` at
`hvac_const.py:491`. Under partitioned budgets the "N/2 today"
string is misleading. Change to
`f"Reset #{used_this_partition}/{partition_budget} ({partition}). "`
where `partition ∈ {"day","night"}`. Do NOT delete
`AC_RESET_MAX_PER_DAY` (KEEP + WIRE per the supersession-triage
discipline); rewire it to `day_budget + night_budget` as the
"total daily" reference value.

---

## 4. Non-goals — explicit

1. Do NOT redefine `effective`.
2. Do NOT create an "excursion / borrow kind" for reset.
3. Do NOT rebuild working machinery (detection, soft nudge, the
   escalate branch, `_perform_hard_reset_escalation`,
   `_perform_ac_reset`, `_restore_after_reset`, verify+retry,
   `async_startup_ramp_audit`, `ac_reset_state`, `ac_ramp_events`).
4. Do NOT change the nudge hold duration (300s → shorter). Parked
   as AC-NUDGE-HOLD-SHORTEN-1 per
   `WIDE_CYCLE_REFUTED_LOAD_MATCHED_2026_08_21`.
5. Do NOT wire `durable` into savings arithmetic this cycle.
6. Do NOT re-do restart-safety for the nudge path (the
   HVAC-GOVERNED-EXCURSION-1 audit refuted the earlier hazard
   claim).
7. Do NOT couple partitioned budgets to house-state. Wall-clock
   only.
8. Do NOT touch the excursion primitive (HVAC-GOVERNED-EXCURSION-1
   D2/D3) — D5 writes directly at the reset producer sites so
   ship-order between the two cycles is free.
9. Do NOT extend the D3 soft-nudge cap to the manual `force_nudge`
   button (`:4205`). Operator intent beats runaway guard.
10. Do NOT delete `AC_RESET_MAX_PER_DAY` (KEEP + WIRE per §3-D8).
11. Do NOT `_engage_lockout` on a recurrence-triggered cap failure.

---

## 5. Knob ladder — every new number, placed and justified

| Knob | Default | Rung | Why here |
|---|---|---|---|
| `hvac_ac_recurrence_mode` (Select) | `shadow` | 3 (Select) | 3-state (`off`/`shadow`/`live`) — a boolean cannot express three behaviours per §12-13. Rung 3 because the operator moves it by observation of the shadow rows. |
| `hvac_ac_recurrence_count_n` (Number int) | `2` | 3 | Tuned by observation. Calibrated by §7 probe. |
| `hvac_ac_recurrence_window_min` (Number int, minutes) | `90` | 3 | Same. |
| `hvac_ac_reset_day_budget` (Number int, 0-4) | `1` | 3 | Policy per operator. 0 disables day resets entirely. |
| `hvac_ac_reset_night_budget` (Number int, 0-4) | `1` | 3 | Same. Together = today's total cap of 2 per §12-12. |
| `hvac_ac_night_start_hhmm` (options string) | `"22:00"` | 2 | Set once per household. String HH:MM. |
| `hvac_ac_night_end_hhmm` (options string) | `"06:00"` | 2 | Same. Wrap-around handled per §3-D2. |
| `hvac_ac_soft_nudge_daily_limit` (Number int) | `50` | 3 | Runaway guard above measured 31-43/day; operator wanted it configurable. |
| `hvac_ac_durability_window` (options int, minutes) | `30` | 2 | Set once; moving it retroactively re-classifies rows. |
| `hvac_ac_reset_off_duration` (Number int, seconds, 30-300) | `60` | 3 | Operator technique parameter (§3-D7). |
| `AC_RESET_OUTCOME_SETTLE_S` (module const, seconds) | `60` | 1 | Measurement primitive; sibling of `AC_NUDGE_RESTORE_SETTLE_DELAY_S = 12`. Changing it changes what "reset outcome" means; must require review. |

Kill-switch semantics: `hvac_ac_recurrence_mode = off` → D1 code
path exits at the mode gate; no compute, no shadow rows, no
reset requests. `shadow` → compute + edge-triggered shadow rows
only. `soft_nudge_daily_limit=0` → cap disables the check.
`reset_day_budget=0` OR `reset_night_budget=0` → the corresponding
partition is disabled entirely (day denies with
`reason=day_budget_exhausted`; night denies with
`reason=night_budget_exhausted`).

---

## 6. Producer / consumer map — every new value

### D1 — recurrence window count

- **Producer arithmetic:** SQL count over `ac_ramp_events` WHERE
  `event_type='nudge_started' AND zone_id=? AND timestamp >
  now() - W`. Depends on: the existing `nudge_started` writes on
  the soft-nudge producer (verified live, 47 rows/night on 08-20).
- **Consumers:**
  - `_perform_hard_reset_escalation` (trust) — only when
    `recurrence_mode='live'`, and always with
    `engage_lockout_on_cap=False`.
  - `sensor.ac_recurrence_window_count_<zone>` (display).
  - `ac_ramp_events` `recurrence_would_fire` rows (audit — edge
    triggered).

### D2 — day/night reset counts

- **Producer:** `_perform_hard_reset_escalation` at `:3960` — the
  increment of the correct partition counter based on
  `_is_night_now(now, ...)`, keyed on `night_session_date` when
  in night.
- **Consumers:**
  - Partition check inside `_perform_hard_reset_escalation` at
    `:3938` (trust).
  - Day-rollover reset in `ac_reset_state` DAO.
  - `sensor.ac_reset_day_count_<zone>`,
    `sensor.ac_reset_night_count_<zone>` (display).
  - `_send_nm_alert` message at `:2911-2919` (display, per D8
    correction).

### D3 — soft-nudge daily count

- **Producer:** `state["soft_nudge_count"]` (already exists).
- **Consumers:** new Gate 5b in `check_ac_reset`; existing daily
  counter sensor.

### D4 — durable / durable_minutes

- **Producer:** `_write_durable` callback scheduled from the
  `nudge_evaluated` `log_ac_ramp_event` return `event_id`. Fires
  at D minutes OR early on re-nudge (truncated).
- **Consumers:** `sensor.ac_ramp_durability_rate_<zone>` (display).
  No trust consumer.

### D5 — hard-reset row enrichment

- **Producers:** enriched `log_ac_ramp_event` calls at
  `hvac_override.py:3967-3972` (started) and `:3050-3055`
  (completed). `restore_ok` back-filled from `_verify_restore` at
  `:3005/3016/3022`.
- **Consumers:** D6 (`_write_reset_outcome` reads `current_temp`
  from the started row via `event_id`); operator diagnostics.

### D6 — reset_outcome

- **Producer:** `_write_reset_outcome` at
  `restore + AC_RESET_OUTCOME_SETTLE_S`. Closes over
  `event_id`.
- **Consumers:** `sensor.ac_reset_last_outcome_<zone>` (display).

### D7 — off-duration

- **Producer:** operator (Number entity) → coordinator setter →
  `self._ac_reset_off_duration_s`.
- **Consumer:** `_perform_ac_reset` at `hvac_override.py:2906` and
  `:2915`.

### D8 — hard_reset_declined rows

- **Producer:** every gate-fail path in
  `_perform_hard_reset_escalation` writes one row (edge-triggered
  per §12-19). Recurrence-mode=`shadow` decline writes one row per
  window crossing.
- **Consumers:** operator diagnostics; NM message counts.

---

## 7. Measure-before-build probe — calibrating N and W

One-shot read-only probe, cheap. Runs on the HA host via SSH
against `ac_ramp_events`. Output feeds §7.1 BEFORE build dispatch.

For each of zone_1/zone_2/zone_3, compute:

1. Inter-`nudge_started` intervals per zone since 2026-07-22 —
   median, p25, p75, count < 30/60/90 min.
2. For candidate (N, W) ∈ {(2, 60), (2, 90), (2, 120), (3, 90),
   (3, 120)}: how many times/day would the trigger have fired
   (edge-triggered, no double-fires within W).
3. Cross-reference with the 11 historical `hard_reset_started`
   rows: does at least one candidate fire ≥ 1x on each of those
   dates?

**Decision rule:** pick the largest (N, W) that fires ≥ 1x on the
08-20 overnight case AND ≤ 4x/day/zone on the median historical
day. Provisional §5 defaults (N=2, W=90) are the working
hypothesis; §7.1 supersedes.

**§7.1 — populated by the orchestrator BEFORE build dispatch.**
Placeholder retained here; no builder starts D1 until §7.1 is
filled.

---

## 8. Acceptance criteria — DISCRIMINATING

Each criterion states what the fix looks like AND a plausible
different failure that produces a different observation.

### AC1 (D1 recurrence — shadow AND live positive control)

- **Positive control (in-suite):** with mode=`live`, hand-craft
  N+1 `nudge_started` rows within W for zone_1 (bypass the
  detection ladder). Trigger the recurrence gate site. Assert
  EXACTLY ONE new row exists WHERE
  `event_type='hard_reset_started' AND triggered_by='recurrence'`.
  **Failure shape:** `triggered_by='auto'` (parameter not
  threaded through `log_ac_ramp_event`) — the row exists but
  attribution is wrong; test discriminates because it asserts
  BOTH type and triggered_by.
- **Shadow absence (in-suite):** repeat with mode=`shadow`. Assert
  ZERO rows with `event_type='hard_reset_started' AND
  triggered_by='recurrence'` AND at least one row with
  `event_type='recurrence_would_fire'`. **Failure shape:** a
  `hard_reset_started/recurrence` row appears despite shadow
  mode — the kill switch leaked.
- **Off (in-suite):** mode=`off`. Assert ZERO rows of either
  type. **Failure shape:** shadow rows still appear — the Select
  is not disabling shadow, only live (which was the whole point of
  the 3-state Select over a boolean).
- **No-lockout-on-recurrence-cap (in-suite):** mode=`live`,
  `day_budget=0`, day-time now. Trigger recurrence. Assert:
  (a) one `hard_reset_declined` row with
  `notes="reason=day_budget_exhausted"`; (b) `lockout_flag` in
  `ac_reset_state` is UNCHANGED (still 0); (c) no persistent
  "controller may be broken" NM notification was fired.
  **Failure shape:** `lockout_flag=1` AND NM notification fired
  — the recurrence caller wrongly triggered lockout, disabling
  the ineffective-nudge escalation path for the rest of the day.
- **Live (post-deploy):** after the operator flips to `live`,
  within 7 days at least one `ac_ramp_events` row exists with
  `event_type='hard_reset_started' AND triggered_by='recurrence'`.

### AC2 (D2 partitioned budgets)

- **Save-round-trip discrimination (in-suite):** save an
  `ac_reset_state` dict with
  `day_reset_count=1, night_reset_count=2`, read back via
  `get_ac_reset_state`, assert both values persist. **Failure
  shape:** returned dict has 0/0 — the `INSERT OR REPLACE` tuple
  at `database.py:7314-7322` was not extended. This test fails
  deterministically if D2's DAO discipline is skipped.
- **Partition denial with reason (in-suite):** hand-craft
  `day_reset_count=1, night_reset_count=0` for zone_1, wall-clock
  = 15:00. Call `_perform_hard_reset_escalation` with the
  ineffective-nudge triggered_by. Assert: one
  `hard_reset_declined` row with
  `notes="reason=day_budget_exhausted"`; `_engage_lockout` called
  (this IS the ineffective-nudge path where lockout is
  appropriate). Then wall-clock = 23:30, repeat: assert one
  `hard_reset_started` row is written and reset actuates.
  **Failure shape:** daytime request succeeds (partition
  membership computed wrongly, or fell back to combined counter);
  discriminates because the criterion asserts BOTH the reason
  string AND the counter comparison.
- **Night wrap-around date-key (in-suite):** wall-clock = 23:30,
  night_budget=1. Trigger a reset — assert
  `night_reset_count=1` on the row `date=D`. Advance wall-clock
  to 00:30 (date=D+1). Trigger another reset — assert one
  `hard_reset_declined` row with `night_budget_exhausted`. Assert
  the state row read at 00:30 has
  `date=D+1 AND night_reset_count=1` (because
  `night_session_date=D` still), NOT `date=D+1 AND
  night_reset_count=0`. **Failure shape:** second reset succeeds
  — the night bucket keyed on `now.date()` reset over midnight.
- **HHMM wrap-around helper (in-suite):** for
  `start="22:00", end="06:00"`, assert
  `_is_night_now(23:30)=True`, `_is_night_now(02:00)=True`,
  `_is_night_now(12:00)=False`, `_is_night_now(06:00)=False`
  (right-open). Unparseable input → returns False (fail closed to
  day).

### AC3 (D3 soft-nudge cap)

- **In-suite auto path:** set
  `state["soft_nudge_count"]=50` for zone_1. Trigger `check_ac_reset`
  with all other gates passing. Assert: no `_perform_soft_nudge`
  call; log line `soft_nudge_daily_limit_reached zone=zone_1
  count=50`; `zone.ramp_state=AC_RAMP_STATE_LOCKED_OUT`. **Failure
  shape:** the 50th nudge fires (off-by-one, or the gate is
  placed AFTER `_perform_soft_nudge`).
- **In-suite manual bypass:** with `state["soft_nudge_count"]=50`,
  call `force_nudge`. Assert: `_perform_soft_nudge` IS called with
  `triggered_by="manual"`; a `nudge_started` row is written.
  **Failure shape:** manual is blocked — the D3 gate wrongly
  applies to manual.
- **Live (post-deploy):** across 7 days no `soft_nudge_count`
  value in `ac_reset_state` exceeds 50 for any zone.

### AC4 (D4 durable + delayed write)

- **Full-window in-suite:** simulate `nudge_evaluated` with
  `kwh_rate_before=2.5, post_min=0.2`, advance simulated clock 30
  min with kW≈0.3 the whole time. Assert the row's `durable=1,
  durable_minutes=30, effective=1` (BOTH assertions on the same
  row — this is what discriminates the non-mutation invariant).
  **Failure shape:** the row's `effective` has been overwritten
  to 0 by `_write_durable`.
- **Truncated in-suite:** same setup, but at simulated t+15 min
  fire a fresh `_perform_soft_nudge` on the SAME zone. Assert
  the original row (identified by `event_id` captured on
  scheduling) is UPDATED with `durable=0, durable_minutes=15`
  (early fire, truncated), AND the new nudge's row is UNTOUCHED
  by this callback. **Failure shape:** the callback writes to the
  latest row on that zone (ORDER BY timestamp DESC LIMIT 1
  antipattern) — the new nudge's row gets the truncated
  measurement. Discriminates by asserting on TWO row IDs, not
  one.
- **Cancel-on-teardown in-suite:** schedule a durable write,
  invoke the coordinator's teardown at
  `hvac_override.py:1439-1459`. Assert: no UPDATE fires; the row
  keeps `durable=NULL`.
- **Live (24h post-deploy):** at least one `ac_ramp_events` row
  per active zone carries non-NULL `durable`.

### AC5 (D5/D6 reset telemetry + drift)

- **Started row enrichment in-suite:** trigger a hard reset with
  `zone.current_temperature=76.0, target_high=76.0`. Assert the
  new `hard_reset_started` row has `current_temp=76.0,
  target_high=76.0, preset_before=<known>, mode_before=<known>,
  triggered_by=<caller>`. **Failure shape:** any of those fields
  is NULL — the enrichment kwargs were not threaded.
- **Completed row + restore_ok back-fill in-suite:** after
  `_restore_after_reset` runs successfully, assert the
  `hard_reset_completed` row has non-NULL `preset_after`,
  `mode_after`, `current_temp`, AND `restore_ok=1` (back-filled
  by `_verify_restore`'s success branch at `:3022-3027`). Then
  re-run with a verify that hits the failure branch at
  `:3005-3021` — assert `restore_ok=0`. **Failure shape:** row
  has `restore_ok=NULL` post-verify — the event_id back-fill
  from `_verify_restore` was not wired.
- **Drift discriminator in-suite:** two runs, both temp_start=76,
  target=76:
  - Run A: temp_settle=76.1 → `reset_outcome='floor_survived'`.
  - Run B: temp_settle=77.5 → `reset_outcome='justified_ramp'`.
  Assert two DIFFERENT `reset_outcome` values. **Failure shape:**
  both = `floor_survived` (temp_settle captured at the wrong
  moment — before drift could develop) OR both = `inconclusive`
  (event_id not threaded, temp read fails). Discriminates
  because it requires two temperatures to produce two outcomes.
- **Setter-abort exclusion in-suite:** flip
  `ac_reset_enabled=False` while a reset is mid-flight. Assert
  the resulting `hard_reset_completed` row has
  `triggered_by='abort_reason=feature_disabled'`, `reset_outcome
  IS NULL`, no `_write_reset_outcome` callback was scheduled.
  **Failure shape:** row has `reset_outcome='floor_survived'` —
  the abort path fabricated a verdict for an operator kill-switch
  flip.

### AC6 (D7 off-duration knob)

- **In-suite:** set `hvac_ac_reset_off_duration=90` via the
  coordinator setter. Trigger a reset. Assert the
  `async_call_later` delay = 90s AND the NM alert message
  interpolates `"90s"`. **Failure shape:** delay=60s or alert
  says `"60s"` — the setter is missing or the consumption site
  still reads the module constant.

### AC7 (Invariant I — non-negotiable)

- **Simulated day loop, 100 iterations, randomised nudge cadence:**
  for each iteration assert (a) total `hard_reset_started` per
  zone ≤ `day_budget + night_budget`; (b) every consecutive pair
  on the same zone is ≥ 120 min apart; (c) if
  `recurrence_mode ∈ {off, shadow}` throughout, ZERO rows have
  `triggered_by='recurrence'`. All three sub-assertions must
  hold on every iteration.

### AC8 (Invariant III — aggregators unpolluted)

- **In-suite:** snapshot the shipped savings aggregator
  (`database.py:7806-7830`) and FP aggregator (`:7896-7906`)
  return values. Insert one `recurrence_would_fire` and one
  `hard_reset_declined` row, both with `effective IS NULL` and
  `notes` free of `kwh_avoided=`. Re-run the aggregators. Assert
  outputs UNCHANGED. **Failure shape:** aggregator sums changed
  — a new event type polluted the ledger.

---

## 9. Restart-safety declaration

| New state | Category | Mechanism |
|---|---|---|
| `day_reset_count` / `night_reset_count` / `night_session_date` | **PERSIST** | Columns on `ac_reset_state`; loaded by existing DAO on boot; MUST be added to `save_ac_reset_state` INSERT OR REPLACE tuple per §3-D2. |
| Rolling `nudge_started` window (D1) | **REBUILD** | Computed on demand from `ac_ramp_events` (`idx_ac_ramp_events_zone_ts`); no in-memory state to survive. |
| `_last_shadow_fire_ts` per zone (D1 edge trigger) | **REBUILD** | Recomputed on boot from the most recent `recurrence_would_fire` row per zone; stale/absent → next tick may fire (correct behaviour — worst case is one duplicate shadow row across a restart). |
| `_write_durable` in-flight | **PERSIST via `in_flight_durable_started_ts`** | Sibling column on `ac_reset_state` (in D2's ALTER block AND the save tuple). Startup audit adds `_resume_in_flight_durable_evaluations` mirroring the existing `_resume_in_flight_nudges` pattern; elapsed-time arithmetic; remaining ≤ 0 fires immediately post-boot; missing kW history → `durable=NULL`. |
| `_write_reset_outcome` in-flight | **REBUILD (drop)** | 60s window; not worth persisting. Restart inside window leaves `reset_outcome=NULL` on the completed row — correctly reflects "measurement lost". |
| `hvac_ac_reset_off_duration` (Number) | **PERSIST** | URA Number-persistence (existing). |
| `hvac_ac_recurrence_mode` (Select) | **PERSIST** | HA Select entity persistence — on boot, mode is restored. A restart never re-arms a disabled trigger. |
| Config/options flow knobs (night HHMM, durability window) | **PERSIST** | HA config-entry storage. |
| `recurrence_would_fire` and `hard_reset_declined` rows | **PERSIST** | `ac_ramp_events` is the ledger. Both edge-triggered per §12-19. |

No state category is RESET beyond the existing day-rollover on
`ac_reset_state` (which now zeros the two new partition counters
as well).

---

## 10. Ship order with HVAC-GOVERNED-EXCURSION-1

Both cycles touch the reset producer sites (`_perform_ac_reset`,
`_restore_after_reset`). Ship order:

- **This cycle first.** D5 enriches the EXISTING
  `log_ac_ramp_event` calls at `:3967` and `:3050` directly. No
  dependency on the excursion primitive.
- **Excursion cycle D2/D3 later.** Re-plumbs reset through the
  excursion API. D5's writes become consumers of the primitive
  rather than direct writers. Compatible because the column set
  is identical.

Do NOT block this cycle on excursion D2/D3.

---

## 11. Tier 3 test-authority — real per-site source mutation

For Reviewer C and the mandatory orchestrator pre-ship verification.
Each site names its enclosing method AND the neuter drill AND the
specific test that MUST fail. A site whose neutering leaves the
suite green is untested — unacceptable.

- **Site 1 (D2 partition gate):** in
  `_perform_hard_reset_escalation` at `:3938`, neuter the
  partition check to always return `budget_ok=True`. Expected:
  AC2's partition-denial test fails.
- **Site 2 (D1 no-lockout-on-recurrence-cap):** remove the
  `engage_lockout_on_cap=False` short-circuit; always call
  `_engage_lockout` on cap fail. Expected: AC1's no-lockout test
  fails (lockout_flag=1 appears).
- **Site 3 (D1 mode gate):** at the recurrence gate site, force
  the code past the mode check regardless of Select value.
  Expected: AC1's shadow-absence test fails (a
  `hard_reset_started/recurrence` row appears in shadow mode).
- **Site 4 (D4 non-mutation):** mutate `_write_durable` to also
  set `effective` in its UPDATE. Expected: AC4's
  same-row-both-columns assertion fails.
- **Site 5 (D4 event_id identity):** replace the
  `WHERE event_id=?` clause in `_write_durable` with
  `ORDER BY timestamp DESC LIMIT 1`. Expected: AC4's
  truncated-vs-fresh-nudge test fails (the fresh nudge's row
  gets the old measurement).
- **Site 6 (D3 cap):** neuter the Gate 5b check (always
  `budget_ok=True`). Expected: AC3's auto-path assertion fails at
  N=51. Also confirm neutering does NOT affect manual — AC3's
  manual bypass test must still pass.
- **Site 7 (D5 restore_ok back-fill):** remove the
  `UPDATE ... SET restore_ok=? WHERE event_id=?` in
  `_verify_restore`'s success branch. Expected: AC5's
  completed-row back-fill test fails (row keeps `restore_ok=NULL`
  post-verify).
- **Site 8 (D5 setter-abort separation):** default the
  `completed` kwarg to `True` unconditionally in
  `_restore_after_reset`. Expected: AC5's setter-abort test
  fails (`reset_outcome` is set instead of NULL).
- **Site 9 (D6 temp-settle):** in `_write_reset_outcome`, read
  temp at scheduling time instead of at fire time. Expected:
  AC5's two-outcome-two-temps test fails (both outcomes collapse).
- **Site 10 (D7 knob):** in `_perform_ac_reset` consumption at
  `:2906`, hard-code `AC_RESET_OFF_DURATION_SECONDS` instead of
  `self._ac_reset_off_duration_s`. Expected: AC6 fails at knob=90.
- **Site 11 (D2 save-tuple):** remove
  `day_reset_count`/`night_reset_count` from the INSERT OR
  REPLACE column list in `save_ac_reset_state`. Expected: AC2's
  save-round-trip test fails (returned dict has 0/0).
- **Site 12 (Invariant III):** in the `hard_reset_declined`
  emit, include a fake `kwh_avoided=0.5` in `notes`. Expected:
  AC8 fails (savings aggregator sum changes).

Orchestrator personally re-runs sites 1, 2, 4, and 11 before ship
(highest blast radius: budget correctness, lockout non-regression,
ledger non-mutation, silent persist failure).

---

## 12. Findings the reviewers/brief were right about, and what changed

Each item corresponds to a numbered finding from the coordinator's
message. Documented so future rounds can audit that each was
addressed.

1. **`_hard_reset_eligible` does not exist.** Every reference
   corrected to `_perform_hard_reset_escalation` at
   `hvac_override.py:3874`. The eligibility check is inside that
   actuator, not a predicate. §3-D1 adds the
   `engage_lockout_on_cap=False` parameter and states the
   rationale in code-comment form (lockout is a controller
   pathology verdict, not a budget-spent verdict). §3-D2's
   enforcement site is `:3938`, inside the actuator.
2. **`_evaluate_ac_ramp_zone` and `AC_NUDGE_MIN_INTERVAL_S` do
   not exist.** Detection entry corrected everywhere to
   `check_ac_reset` at `hvac_override.py:2684` with the Gate 0a→9
   ladder at `:2720-2860`. D3's gate lives as a new Gate 5b in
   `check_ac_reset`. Card body error (the "30-min interval IS
   being honoured / interval knob shipped and cap did not"
   claim) flagged §12-2 for downstream correction — the
   ~2/hour cadence is EMERGENT from Gates 8 + 5-min hold + 600s
   eval + Gate 9, not enforced.
3. **`CREATE TABLE IF NOT EXISTS` fails silently against the
   live 1.18 GB DB.** §3-D2 mandates a new guarded ALTER block
   for `ac_reset_state`, modelled exactly on the
   `ac_ramp_events` block at `database.py:1681-1712`. §0 lists
   the precedent explicitly.
4. **D5 producer sites already emit — double-emit risk.** §3-D5
   entirely rewritten to enrich the EXISTING
   `log_ac_ramp_event` calls at `:3967-3972` and `:3050-3055`,
   not to add new rows. `_track_zone_action` explicitly called
   out as IN-MEMORY-ONLY per its docstring at `:1250`.
5. **`save_ac_reset_state` INSERT OR REPLACE tuple.** §3-D2
   documents the tuple as the highest-probability silent
   failure. AC2 adds a save-round-trip test that fails
   deterministically if columns are added to DDL but not to the
   tuple. Site 11 in §11 mutation drills the same.
6. **Delayed writes and row identity.** `log_ac_ramp_event`
   extended to return `cursor.lastrowid`. Both D4 and D5-B
   callbacks close over `event_id` and UPDATE by that key. Site 5
   in §11 mutation-drills the alternative and confirms it fails.
7. **Night wrap-around date-key.** §3-D2 defines
   `night_session_date` and the `_night_session_date` helper.
   AC2 includes a 23:30 + 00:30 test asserting the second is
   denied.
8. **Setter-abort caller into `_restore_after_reset`.** §3-D5-B
   threads `completed: bool` and `abort_reason: str` kwargs; the
   setter caller at `:2000` passes
   `completed=False, abort_reason="feature_disabled"`.
   `_write_reset_outcome` is NOT scheduled for aborts.
   `reset_outcome=NULL`.
9. **`restore_ok` unknowable at write time.** §3-D5-B writes it
   NULL and back-fills from the three terminal branches of
   `_verify_restore` at `:3005/3016/3022`. Invariant II
   re-stated so absent rows (no write at all) cannot make it
   vacuously true — the invariant is stated over rows that ARE
   written on the automatic path.
10. **`triggered_by='recurrence'` not plumbed.** §3-D1 threads
    the kwarg through both `_track_zone_action` at `:3963-3966`
    AND `log_ac_ramp_event` at `:3967-3972`. AC1 begins with
    a POSITIVE CONTROL test that asserts existence of the
    correctly-labelled row BEFORE the shadow-absence assertion.
11. **D4 cancel vs truncate contradiction.** §3-D4 asserts the
    rule: re-nudge FIRES the pending callback early with
    truncated interval; cancellation applies to teardown only.
    AC4 tests both branches; Site 4/5 in §11 mutation drill the
    non-mutation and event_id-identity requirements.
12. **1/1 defaults propagated into every consuming section.**
    §3-D2, §5, §6-D2, §9. Total daily cap remains 2, matching
    today. Any raise from 2 is a separate future policy call.
13. **3-state Select instead of boolean kill switch.** §3-D1,
    §5 knob table, §12-3 handling. `select.py` added to §13
    files-touched.
14. **Partition increment ordering.** §3-D2 states "in the
    same read-modify-write block as `hard_reset_count`, BEFORE
    `_perform_ac_reset`", and includes the in-source comment
    forbidding movement.
15. **Aggregator non-pollution.** Invariant III + AC8. §3-D8
    calls it out on the new event types.
16. **D3 vs manual button.** §3-D3 and non-goal 9 assert the
    manual button bypasses the cap; AC3 tests the bypass.
17. **HHMM wrap-around.** §3-D2's `_is_night_now` helper
    specifies `if start > end: night = now >= start OR now <
    end`; unparseable input fails closed to day. AC2 covers the
    helper and the failure mode explicitly.
18. **Teardown for delayed writes.** §3-D4 and §3-D6 register
    handles at `hvac_override.py:1439-1459` following the
    `_nudge_settled_timers` pattern.
19. **Edge-triggered shadow + declined writes.** §3-D8 states
    the rule (write on reason-change OR ≥ 15 min since last
    same-reason). Cites the write-flood rollback precedent
    (v4.7.33 optimizer DB write-flood incident 2026-06-09).
20. **D6 60s settle knob.** `AC_RESET_OUTCOME_SETTLE_S = 60`
    added at rung 1 to §5, sibling of
    `AC_NUDGE_RESTORE_SETTLE_DELAY_S = 12`. Named "temp at
    restore + settle", not "temp at reset-end", to survive a
    future change to `hvac_ac_reset_off_duration`.
21. **Duplicate heading + missing §7.1.** Duplicate removed;
    §7 placeholder remains until §7.1 is populated. Build
    dispatch blocks on §7.1 (see §7).
22. **`AC_RESET_MAX_PER_DAY` KEEP + WIRE.** §3-D8 rewires the
    NM alert string; the constant is retained and re-purposed as
    a "total daily reference".
23. **D7 coordinator write-through.** §3-D7 mandates
    `set_ac_reset_off_duration` on the coordinator, modelled on
    `set_hard_reset_daily_limit` at `hvac_override.py:1276+`.

### What I still believe may be wrong in the brief

- **The card claim that the 30-minute nudge interval "IS being
  honoured" (finding block, defect (2)) is factually wrong.** No
  such enforcement exists. The observed cadence is emergent.
  The card should be corrected downstream; this plan does NOT
  rely on the (nonexistent) enforcement and does NOT introduce
  it.

---

## 13. Files touched — for the builder

- `custom_components/universal_room_automation/domain_coordinators/hvac_const.py`
  — new CONF_/DEFAULT_ constants per §5; new event-type constants
  `AC_RAMP_EVENT_HARD_RESET_DECLINED`,
  `AC_RAMP_EVENT_RECURRENCE_WOULD_FIRE`; new module constant
  `AC_RESET_OUTCOME_SETTLE_S = 60`.
- `custom_components/universal_room_automation/domain_coordinators/hvac_override.py`
  — recurrence gate site + shadow/live/off dispatch (D1); Gate 5b
  soft-nudge cap in `check_ac_reset` (D3); partition-aware Gate A
  + `engage_lockout_on_cap` parameter in
  `_perform_hard_reset_escalation` (D2 + D1); partition increment
  at `:3960` with the `_is_night_now` / `_night_session_date`
  helpers; enrichment kwargs on `log_ac_ramp_event` at `:3967`
  (started) and `:3050` (completed) (D5); `completed` +
  `abort_reason` kwargs on `_restore_after_reset` and the two
  caller sites (`:3037` completion, `:2000` abort); `_write_durable`
  + `_write_reset_outcome` delayed callbacks (D4/D6); handle
  registries + teardown at `:1439-1459`;
  `_resume_in_flight_durable_evaluations` added to
  `async_startup_ramp_audit` at `:3925`; restore_ok back-fill in
  `_verify_restore`'s three terminal branches (`:3005/3016/3022`);
  D7 consumption at `:2906` + `:2915` reads coordinator attr;
  coordinator setters (`set_soft_nudge_daily_limit`,
  `set_reset_day_budget`, `set_reset_night_budget`,
  `set_recurrence_count_n`, `set_recurrence_window_min`,
  `set_ac_reset_off_duration`) modelled on
  `set_hard_reset_daily_limit` at `:1276+`; recurrence-mode
  Select accessor.
- `custom_components/universal_room_automation/database.py`
  — NEW guarded ALTER block for `ac_reset_state` (§3-D2)
  modelled on the `ac_ramp_events` block at `:1681-1712`, adding
  `day_reset_count`, `night_reset_count`, `night_session_date`,
  `in_flight_durable_started_ts`; EXTEND
  `save_ac_reset_state` INSERT OR REPLACE column list AND
  parameter tuple at `:7314-7335` for the four new columns;
  EXTEND `get_ac_reset_state` default dict to include new keys;
  guarded ALTER on `ac_ramp_events` adding `durable`,
  `durable_minutes`, `reset_outcome` in the existing block at
  `:1681-1712`; extend `log_ac_ramp_event` to return
  `cursor.lastrowid`; NEW DAO method
  `update_ac_ramp_event_fields(event_id, **fields)` used by
  D4/D5/D6 back-fills.
- `custom_components/universal_room_automation/number.py`
  — new Number entities: `hvac_ac_reset_off_duration`,
  `hvac_ac_recurrence_count_n`, `hvac_ac_recurrence_window_min`,
  `hvac_ac_reset_day_budget`, `hvac_ac_reset_night_budget`,
  `hvac_ac_soft_nudge_daily_limit`. Each calls its coordinator
  setter on `async_set_native_value`.
- `custom_components/universal_room_automation/select.py`
  — NEW: `hvac_ac_recurrence_mode` Select (`off`/`shadow`/`live`,
  default `shadow`). Calls a coordinator
  `set_ac_recurrence_mode` setter.
- `custom_components/universal_room_automation/config_flow.py` +
  `options_flow.py`
  — `hvac_ac_night_start_hhmm`, `hvac_ac_night_end_hhmm`
  string fields; `hvac_ac_durability_window` integer field
  (minutes).
- `custom_components/universal_room_automation/sensor.py`
  — D8 live sensors:
  `sensor.ac_recurrence_window_count_<zone>`,
  `sensor.ac_reset_day_count_<zone>`,
  `sensor.ac_reset_night_count_<zone>`,
  `sensor.ac_reset_last_outcome_<zone>`.
- `quality/tests/` — one test file per deliverable covering
  every acceptance criterion in §8 plus the mutation-drill
  fixtures in §11.

Builder: apply Institutional Context First to your edits. Any
anchor that "should exist" here MUST be grep-verified before use.
