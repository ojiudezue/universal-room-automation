# PLANNING — AC-RAMP-PIPELINE-HARDENING-1

**Tier:** 3.
**Revision:** 2 (2026-08-22). Both Tier-3 plan reviews (Framing A + Framing B)
returned REVISE — DO-NOT-DISPATCH on Rev 1. This revision addresses every
CRITICAL and HIGH from both framings. See §15 change log for the mapping
finding → resolution.
**Supersedes:** `PLANNING_ac_ramp_recurrence_escalation.md`. The blanket "read
that document's §7.1/§12/§13" instruction is retired (Reviewer B-C1: it sent
builders AWAY from D2-D8 spec they needed). Every carry-forward from the
superseded plan is stated in §1's per-deliverable map with explicit section
pointers.

**Governing frame:** ONE pipeline, THREE compounding leaks (Gate 4 detect;
scoring classify; escalation act). Fixing any in isolation is throwing money
away because the next leak eats the gain.

**Central argument — repeat to reviewers:** once scoring can honestly say
"this nudge did not hold", the EXISTING `if escalate:` branch at
`hvac_override.py:3891` fires on its own. No recurrence counter, no N/W to
calibrate. Deleting the need is the deliverable. **Caveat added Rev 2 in
response to Reviewer B-C4:** whether that claim survives the 25-min inter-nudge
cadence is settled quantitatively in §3-D-ESC-CONSUME with a re-derivation
against measured rates. If the re-derivation lands D-ESC-CONSUME inside the
§7.1-rejected (N,W) region, D-ESC-CONSUME fails the same test its predecessor
did and must be reworked or dropped, not shipped.

---

## 0. Verified pipeline — re-grepped 2026-08-22

Every anchor `grep -n`ed 2026-08-22 against
`custom_components/universal_room_automation/`.

- **STAGE 1 — DETECT.** `check_ac_reset` at
  `domain_coordinators/hvac_override.py:2684`. Gate ladder at `:2720-2860`
  includes (in order): EgressManager pause `:2757` (A-M3), `_override_active`
  `:2763` (A-M3), Gate 2 zone enable `:2769`, Gate 3 `ac_load_sensor`
  configured `:2774`, **Gate 4 (the LEAK) at `:2779`**
  (`if zone.hvac_action != "cooling"`), Gate 5 lockout `:2789`, Gate 6
  overshoot at-or-below setpoint `:2795`, Gate 7 kWh rate threshold
  (`_read_kwh_rate` called at `:3113` and internal Gate-7 site at `:2814`
  per operator-side re-grep), Gate 8 sustained-time, Gate 9 re-entry
  guard.
- **STAGE 2 — NUDGE.** `_perform_soft_nudge` at `:3210`; helper
  `_read_kwh_rate` at `:3113` (returns kW after W→kW conversion, with
  `AC_KWH_SENSOR_STALENESS_S = 10 min` staleness guard, and
  unknown/unavailable/parse safety). Mechanically effective ~99%.
- **STAGE 3 — SCORE.** Classifier at `hvac_override.py:3802-3823`. Four
  branches with classification-assignment lines at 3806, 3812, 3817, 3821
  (L1 correction) and their escalate assignments at 3808/3814/3819/3823:
  `inconclusive` (escalate=False, `:3808`); `ineffective_no_samples`
  (escalate=True, `:3814`); **`effective` (escalate=False, `:3819`) — the
  LEAK: 307/308 rows land here**; `ineffective` (escalate=True, `:3823`).
  Keys off `post_min` in the trailing window. Row write immediately follows
  at `log_ac_ramp_event(...)` at `:3880`. `escalate` is then consumed at
  `:3891`.
- **STAGE 4 — ESCALATE.** `if escalate:` at `:3891`, calling
  `_perform_hard_reset_escalation` at `:3901`; definition at `:3925`.
  **Fires RARELY — not never.** MEASURED: 9 hard resets 2026-08-06 →
  2026-08-15, including overnight (04:53, 00:40), ~0.30/day house-wide.
  Rate-starved because Stage 3 almost never says `ineffective`, not because
  the path is unreachable. **Wording discipline:** do NOT write "never
  fires", "structurally unreachable", or "turns resets on for the first
  time". D-SCORE + D-ESC-CONSUME RAISES the reset rate from ~0.30/day to
  potentially several per day — a RATE CHANGE to an existing capability,
  not activation of a dormant one.

  Between `if escalate:` (`:3891`) and actuation, FIVE ADDITIONAL SHORT-
  CIRCUITS exist (A-H2 enumeration, MUST be verified live pre-ship):
  1. `_ac_reset_enabled` early-return at `:3962` — if the operator toggled
     AC Reset OFF, D-SCORE lands `escalate=True`, calls
     `_perform_hard_reset_escalation`, and the function returns silently.
     Ship-time check: read the live boolean.
  2. `_corrective_writes_suppressed(zone_id)` at `:3975` — plausibly active
     exactly when the operator is home overnight (its whole purpose is
     "don't fight an operator override"). Ship-time check: read for each
     zone.
  3. `self._db is None` — early boot / degraded persistence path; treat as
     "escalation lost silently" and log at INFO.
  4. Gate A — daily cap. See A-C2 fix in §3-D-PARTITION.
  5. Gate B — global min-interval `get_global_last_hard_reset_ts` (already
     accounted for). Skips with log, no lockout.
- **STAGE 5 — RESET.** `_perform_ac_reset` at `:2871`
  (`AC_RESET_OFF_DURATION_SECONDS = 60` at `hvac_const.py:493`);
  `_restore_after_reset` at `:2938`; `_verify_restore` at `:2985`. Preset
  restore fixed in v5.88.1. 9 executions ever, all mechanically fine.

**STRUCTURAL FACT — restate in every review round:** `check_ac_reset` is
named for RESET but is the SOFT-NUDGE entry point (comment at `:2728-2741`:
"`check_ac_reset` is the soft-nudge entry point; with nudges disabled it
has no work"). **The ONLY automatic route to a hard reset runs through a
nudge.** Gate 4 gates the ENTIRE ladder — detect, nudge, score, escalate,
reset — not just nudging.

### 0.5 One CRITICAL from Rev-1-review already resolved — record the evidence

**A-C1 (Rev-1 concern: draw-based D-GATE4 could authorise a cooling nudge
during heating in `hvac_mode=heat_cool`) is MOOT.** Heating in this house is
gas-fired, not heat-pump. Cross-check over 2026-01-10 → 2026-01-25 (360
heating-season hours): **ZERO hours had furnace draw > 150 W AND ac1 draw
> 800 W simultaneously**. AC-circuit averages in heating season: 43 / 36 /
22 W across the three zones — below `AC_ACTIVELY_COOLING_KW_MIN = 0.5 kW`
by an order of magnitude. **The C1 chain (D-GATE4 True while heating)
cannot physically occur** because the AC circuits do not carry heating
load. One-line justification embedded in the helper's docstring: *"safe
under `heat_cool` in this deployment because heating is gas-fired; the AC
circuit draw cannot rise during a heating cycle."*

Recording this measurement here so a future reviewer does not re-raise the
concern from first principles; a change to heat-pump heating in this house
would REOPEN the concern and REQUIRE this section to be re-run.

---

## 1. Institutional context verified

### Greps run 2026-08-22

| Proposed | Grep | Result | Disposition |
|---|---|---|---|
| Draw-based Gate-4 predicate helper | `grep -n "def _read_kwh_rate\|def .*compressor_active" hvac_override.py` | `_read_kwh_rate` at `:3113` — kW conversion, staleness (`AC_KWH_SENSOR_STALENESS_S`), None on unknown/unavailable/parse-fail. NO existing `_zone_is_actively_cooling`. | **REUSE `_read_kwh_rate`** (A-H3/B-H2 fix); **NEW helper** `_zone_is_actively_cooling(zone, now)` that calls it. |
| SPAN circuit draw per zone | `zone.ac_load_sensor` wired at Gate 3 (`:2774`). Config-flow field documented as "AC Load Sensor (kW or kWh)" — accepts BOTH kW and kWh sensors. | See §3-D-GATE4 ruling on kWh-configured sensors. | **REUSED** with kWh-sensor rule. |
| `hvac_mode` / `hvac_action` producer | `hvac_zones.py:433-454` `update_zone_climate_state`. `hvac_mode = state.state` (line 443); `hvac_action = state.attributes.get("hvac_action", "")` (line 444). Returns early on `None`/`unavailable`, LEAVING the previous value FROZEN. Initial value `""` before first poll. | Both derive from the SAME `hass.states.get(zone.climate_entity)` call (A-M2 correction). See §3-D-GATE4 for the corrected reasoning. | **REUSED** with corrected trust-basis. |
| `blower_rpm` availability | Not in URA today. | Operator observation only. | **NEW read** as corroboration only; treated as absent when the attribute is missing. |
| `async_track_time_interval` in HVAC coordinator | `grep -n "async_track_time_interval" domain_coordinators/hvac_override.py` → 0 hits. Elsewhere: `sensor.py`, `__init__.py`, `energy.py`, `hvac.py`, `security.py`. `hvac_override.py:1439-1459` is the TEARDOWN block, NOT a scheduler prior-art site (A-M1 correction). | If D9 were built (see §11 for the drop decision), the correct prior-art site is `domain_coordinators/hvac.py`. | **N/A** — D9 dropped this cycle. |
| Actuation-lag columns on `ac_ramp_events` | grep | None. | **NEW columns** IF Probe B justifies build; see §3-D10. |
| `log_ac_ramp_event` return value | `grep -n "def log_ac_ramp_event\|return.*lastrowid" database.py` | Today returns `None`. | **SIGNATURE CHANGE** — must return `cursor.lastrowid: int`. Shared primitive with many callers; enumerated in §13 (B-M2). |
| `update_ac_ramp_event_fields` DAO | grep | **Does NOT exist** (B-M1 correction). Superseded plan §13 mentioned it as if extant. | **NEW DAO** — enumerated in §13. |

### Per-deliverable carry-forward map (replaces the blanket read-order)

Reviewer B-C1: a builder never sees the wrap-around `_is_night_now` rule,
the `night_session_date` key rule, the `save_ac_reset_state` INSERT-OR-
REPLACE trap, Gate 5b placement, or charge-before-actuate ordering under a
"read §7.1/§12/§13" instruction. Below is the explicit map. **Also amend
the superseded doc's own supersession-header READ-ORDER line — it
contradicts this map. That amendment is a §13 deliverable of this plan.**

| This-plan deliverable | Superseded sections a builder MUST read |
|---|---|
| D-SCORE (was superseded D4) | superseded §3-D4 (full-window/truncate/cancel rules; `event_id` requirement; `in_flight_durable_started_ts`), §5 D4 rows, AC4, §9 D4 row, §11 sites 4 & 5 |
| D2 partitioned budgets | superseded §3-D2 (guarded-ALTER pattern; `_is_night_now` wrap-around; `night_session_date` key; `save_ac_reset_state` tuple; Gate-A partition-aware check; charge-before-actuate), §5 D2 rows (BUT default row overridden here — §5), AC2, §9 D2 row, §11 sites 1 & 11. **§3-D-PARTITION below adds the lockout-carve fix (A-C2).** |
| D3 soft-nudge daily cap | superseded §3-D3 (Gate 5b placement between real Gate 5 and Gate 6; manual bypass), §5 D3 row, AC3, §11 site 6 |
| D5 hard-reset row enrichment | superseded §3-D5 (enrich EXISTING `log_ac_ramp_event` at `:3967` and `:3050`; `restore_ok` back-fill from `_verify_restore` terminal branches; setter-abort `completed=False` path from `_restore_after_reset`'s second caller at `:2000`), AC5, §11 sites 7 & 8 |
| D6 reset-outcome drift | superseded §3-D6 (`AC_RESET_OUTCOME_SETTLE_S`; delayed callback registry; setter-abort exclusion; REBUILD restart), §5 D6 rows, AC5 drift block, §11 site 9 |
| D7 `AC_RESET_OFF_DURATION_SECONDS` promotion | superseded §3-D7 (coordinator setter modelled on `set_hard_reset_daily_limit` at `:1276`; consumption sites at `:2906` and `:2915`), AC6, §11 site 10 |
| D8 observability + declined trail | superseded §3-D8 (edge-triggered writes with 15-min same-reason floor; Invariant III non-pollution; NM alert repair to say "N/day+M/night"), §11 site 12 |

**Superseded §7.1 (measured rejection of the count trigger) is CANONICAL
and must not be overridden by any downstream section of this plan.** If a
Rev-2 deliverable's re-derivation lands inside the §7.1 rejection region,
that deliverable is rejected on the same grounds.

### Prior planning docs consulted

- `PLANNING_ac_ramp_recurrence_escalation.md` — full read (§0-§13, §7.1).
- `PLANNING_v4.5.11_ac_energy_aware_ramp_down.md` — objective doc drives
  Invariant I.
- `PLANNING_hvac_governed_excursion.md` — v5.86.0 shipped the preset/mode/
  restore telemetry columns.

### Memories pulled

- `feedback_measure_before_build.md` — Probe A (D-GATE4 sizing) and Probe B
  (D10 go/no-go) both run BEFORE build dispatch.
- `feedback_marginal_benefit_pushback.md` — applied to D9 (dropped, §11)
  and D10 (probe-gated).
- `feedback_falsify_before_asserting.md` — every invariant stated in
  breakable form; every acceptance criterion carries a negative control per
  the §14 meta-finding.
- `feedback_wire_in_anchor_mandatory.md` — §12 pairs every deliverable with
  a mutation-drill site that MUST fail.
- `feedback_parent_reload_watchdog_hazard.md` — informed the D9 drop.
- `feedback_no_fabrication.md` — `ha_carrier` internals cited from operator
  report; not re-fabricated.
- `project_optimizer_db_write_flood_incident_2026_06_09.md` — informs the
  edge-triggered/latched write discipline throughout.

### Design docs

- `docs/Coordinator/HVAC.md` if present — read end-to-end. Source wins on
  any discrepancy.

### Code read end-to-end during Rev-2 scoping

- `hvac_override.py`: 460-475 (`_corrective_writes_suppressed`); 1990-2005
  (`ac_reset_enabled` setter abort into `_restore_after_reset`);
  2720-2860 (`check_ac_reset` ladder including EgressManager and
  `_override_active` short-circuits at 2757/2763); 2871-3055
  (`_perform_ac_reset` / `_restore_after_reset` / `_verify_restore`);
  3113-3151 (`_read_kwh_rate`); 3210-3260 (soft nudge perform);
  3414-3540 (restore-after-nudge + settled telemetry);
  3802-3891 (classifier + row write + escalate branch);
  3925-4030 (`_perform_hard_reset_escalation` and `_engage_lockout`).
- `hvac_zones.py`: 433-454 (`update_zone_climate_state`).
- `hvac_const.py`: 480-540; 570-590.
- Superseded plan §0-§13 (full).

---

## 2. Falsifiable invariants — the whole pipeline

**Invariant P — Pipeline Blindness Ceiling (leak 1).** Over any rolling
7-day window, the duration-weighted fraction of time in which BOTH (a) the
zone's SPAN `ac_load_sensor` reads above the per-zone Gate-7 threshold
(the SAME threshold Gate 7 uses to decide "worth nudging"; NOT
`AC_ACTIVELY_COOLING_KW_MIN`, which is the lower "the compressor is on at
all" bound — B-M4 correction), AND (b) `check_ac_reset` short-circuits at
Gate 4, is bounded by `GATE4_MAX_BLIND_FRACTION` (§5, default 0.01).
Fix observation: near zero. Different-failure observation: pre-fix 7-13%
persists (predicate still cloud-derived).

**Invariant S — Scoring Honesty (leak 2).** Every `nudge_evaluated` row
classified `effective=True` whose zone's `ac_load_sensor` returns above the
Gate-7 threshold within `CONF_HVAC_AC_DURABILITY_WINDOW` minutes (default
30, §5) MUST land in `ac_ramp_events` with `durable=0` and non-NULL
`durable_minutes`. Different-failure observation: `durable=1` on rows that
demonstrably re-ramped after (event_id closure race). Discriminates
because the passive SPAN series and the row's `durable` are independently
authored.

**Invariant E — Escalation is Reachable (leak 3).** For every zone, if the
consecutive-run of preceding `nudge_evaluated` rows in the durability
window carrying `durable=1` (a FULL-WINDOW, non-truncated, non-NULL
zero-durable measurement — see §3-D-ESC-CONSUME for the count and
carry-forward rules) reaches **`N_ESC` events total including the current
one** (default `N_ESC = 2` → 1 prior with `durable=1` PLUS the current
evaluation whose classifier would otherwise say `effective` and whose
retro-check flips it to `durable_fail`), AND none of the FIVE
short-circuits enumerated in §0 (`_ac_reset_enabled`,
`_corrective_writes_suppressed`, `_db is None`, Gate A cap, Gate B
interval) is engaged, then the classifier MUST produce `escalate=True` and
route through the EXISTING `if escalate:` branch at
`hvac_override.py:3891`. NO new escalation predicate outside that branch
is introduced. Different-failure observation: a `hard_reset_started` row
appears without that branch having executed (call-graph assertion in
suite).

**Semantic disambiguation (B-C3 fix).** `N_ESC` is the TOTAL count of
qualifying events required to escalate, INCLUSIVE of the current one.
Default `N_ESC = 2` therefore means: 1 prior qualifying event + the
current event. **Delete the "N_ESC - 1 priors" phrasing** — retire it
everywhere. §8 AC-E adds a NEGATIVE CONTROL: **`N_ESC - 1 = 1` total
qualifying event MUST produce `escalate=False`** (i.e. no prior + current
does not escalate). A test that passes under BOTH semantics is the exact
failure this meta-finding forbids.

**Invariant I** (Bounded Compressor Cycling) and **Invariant III**
(Aggregator Non-Pollution) — REUSED from superseded plan §2 with the
lockout carve of §3-D-PARTITION taken into account.

---

## 3. Deliverables

### D-GATE4 — Replace cloud-reported veto with a draw-based predicate (**status on ship: SHADOW on first boot; LIVE on operator flip**)

**Site:** `hvac_override.py:2779` (Gate 4). BEFORE (verified 2026-08-22):

```
2778            # Gate 4: cooling action + valid temps
2779            if zone.hvac_action != "cooling":
2780                zone.last_overshoot_started = ""
2781                zone.kwh_samples_above_threshold = 0
2782                if zone_id not in self._nudge_in_flight:
2783                    zone.ramp_state = AC_RAMP_STATE_IDLE
2784                continue
2785            if zone.target_temp_high is None or zone.current_temperature is None:
```

**AFTER (literal, B-H1 fix):**

```
2778            # Gate 4 (v-this-cycle): draw-based predicate replaces
2779            # cloud-reported hvac_action veto. Wall time passed in for
2780            # staleness check; helper returns True iff hvac_mode is a
2781            # cooling-capable config AND kW rate is above the "compressor
2782            # is actually on" floor. See D-GATE4 in the planning doc for
2783            # the trust-basis argument (hvac_mode is downstream of the
2784            # same poll as hvac_action, but its underlying VALUE changes
2785            # only on seasonal operator action, so a frozen last-known
2786            # value is overwhelmingly likely to be correct; SPAN is polled
2787            # locally and independently).
2788            if not self._zone_is_actively_cooling(zone, now):
2789                zone.last_overshoot_started = ""
2790                zone.kwh_samples_above_threshold = 0
2791                if zone_id not in self._nudge_in_flight:
2792                    zone.ramp_state = AC_RAMP_STATE_IDLE
2793                continue
2794            if zone.target_temp_high is None or zone.current_temperature is None:
```

The three state-clearing statements MUST move into the new False branch
(as shown), unchanged. Removing them collapses Gate 7's consecutive-sample
counter and Gate 8's sustained-time guard on the next cooling cycle
(B-H1). Under `hvac_ac_gate4_predicate_mode = legacy`, the pre-cycle body
is restored verbatim (kill-switch semantics preserved). Line numbers here
are illustrative; the builder re-greps.

**Predicate trust ladder — `_zone_is_actively_cooling(zone, now)`:**

1. **CONFIG guard.** `zone.hvac_mode` must be in
   `{"cool", "heat_cool", "auto"}`. If in `{"heat", "off", "unknown",
   "unavailable", "", None}`, return False (fail-closed against pre-first-
   poll `""` and against frozen-`unavailable` — A-M2). Basis: `hvac_mode`
   is downstream of the same `hass.states.get(...)` call as `hvac_action`
   (`hvac_zones.py:443-444`) — the reviewer's A-M2 correction. The
   trust-basis is NOT "independent poll"; it is that `hvac_mode`'s
   underlying value changes ONLY on seasonal operator action, so even a
   frozen last-known value is overwhelmingly likely to be correct, whereas
   `hvac_action` changes tick-to-tick and its frozen value is a lie about
   present reality. **Frozen `""` before first poll is treated as
   non-cooling.** Note the correction explicitly in the helper docstring.
2. **GROUND-TRUTH draw — routes THROUGH `_read_kwh_rate`, not raw
   `float(state)` (A-H3/B-H2 fix).** Call `kw = self._read_kwh_rate(zone,
   now)`. If `kw is None` (staleness > 10 min per `AC_KWH_SENSOR_STALENESS_S`,
   OR unknown/unavailable, OR parse failure), return False (fail-closed;
   NOT True). Else require `kw >= AC_ACTIVELY_COOLING_KW_MIN` (default
   0.5 kW). SPAN's local poll is trusted; treating stale as "cooling" would
   silently keep a dead sensor's last reading firing detection (Risk R3
   from the helper's own docstring).
3. **kWh-CONFIGURED SENSOR RULE (this cycle's ruling; brief flag).** The
   config-flow field `strings.json:570` reads "AC Load Sensor (kW or
   kWh)". Against a cumulative-kWh sensor `_read_kwh_rate` today does NOT
   compute a rate (it returns the raw counter value which grows without
   bound); the predicate would be permanently True after the first
   half-kWh. **The plan requires:** `_read_kwh_rate` MUST reject a sensor
   whose `unit_of_measurement` is `kWh` (a cumulative counter is not a
   rate) by returning `None`, AND log a WARN once per zone/boot naming
   the sensor. Effect: a kWh-configured sensor causes D-GATE4 to
   fail-closed (True predicate never fires), which is correct — the
   feature never worked for those sensors and now the operator is told
   why. Add to §11 as a Rev-2 in-cycle fix (small).
4. **CORROBORATION (optional).** If
   `hass.states.get(zone.climate_entity).attributes.get("blower_rpm")` is
   present AND > `AC_ACTIVELY_COOLING_BLOWER_RPM_MIN` (default 100),
   corroborates step 2. If step 2 passes, step 3 corroboration is not
   required. If step 2 fails, blower CANNOT rescue.
5. **`hvac_action` corroboration only, never veto.** When step 1 and step
   2 pass and `hvac_action != "cooling"`, log one INFO with a
   per-zone-per-hour rate-limit key.

Helper returns True iff steps 1 AND 2 pass.

**Safety note (§0.5 evidence):** the C1 chain (cooling-nudge during
heating) cannot physically occur in this deployment because heating is
gas-fired. Cited in the helper docstring. A future change to heat-pump
heating REOPENS this concern.

**Producer / consumer.**
- Producer: helper reads `zone.hvac_mode` (config-source), `_read_kwh_rate`
  (with its own staleness gate), optional `blower_rpm`. Dependencies:
  SPAN integration health; climate entity resolvable.
- Consumers: ONE trust — `check_ac_reset` at `:2779` (the replaced body).
  ONE display — `sensor.ac_gate4_blind_fraction_7d_<zone>`.

**Rollout guard.** `hvac_ac_gate4_predicate_mode` Select values
`legacy` / `shadow` / `live`, default `shadow` on first boot. `shadow`:
legacy Gate 4 body still decides; helper's decision is computed and, on
disagreement, a LATCHED `gate4_divergence_shadow` row is written (see
next paragraph — B-H7 fix). `live`: helper decides. `legacy`: kill
switch, restores pre-cycle body verbatim.

**Divergence writes are LATCHED, not per-tick (B-H7).** Coordinator holds
`_last_gate4_divergence_state[zone_id] ∈ {None, "agree", "diverge"}`
REBUILT on restart (no persistence). Write one row on transition
`agree → diverge` and one on `diverge → agree`, tagged with the direction
(`legacy_veto_new_proceed` vs `legacy_proceed_new_veto`). Blind episode of
19 diverging ticks × 3 zones × 8 days would otherwise burn ~50-100
rows/day into `ac_ramp_events` — unacceptable per the v4.7.33
optimizer write-flood incident. §8 adds a multi-tick test asserting ONE
row across N contiguous diverging ticks.

**Restart safety:** REBUILD (helper stateless; divergence latch REBUILD
per B-H7).

### D-SCORE — `durable`/`durable_minutes` delayed classifier (**status on ship: LIVE additive; no trust consumer flip yet**)

Carry forward per §1 map (superseded §3-D4). Do not re-litigate. One
Rev-2 correction (B-M3): the SUPERSEDED plan is internally inconsistent
about truncated-`durable` semantics (§3-D4 conditional on kW; AC4
unconditional 0). **Ruling for this cycle:** `_write_durable` on early
fire due to re-nudge sets `durable = 0 if kW at fire-time is above
threshold else 1`; `durable_minutes = elapsed`. This is the §3-D4 rule;
AC4 is superseded by AC-S in §8 which restates it correctly. The AC-4
row in the superseded plan is retired for this cycle. Note: even under
this ruling, D-ESC-CONSUME (below) IGNORES truncated rows for its count.

### D-PARTITION — Partition-aware Gate A that does NOT engage lockout on partition-only denial (**status on ship: LIVE; carries the D2 ruling**)

**A-C2 fix.** In `_perform_hard_reset_escalation` (`hvac_override.py:3925`
today), Gate A's cap check calls `_engage_lockout` on failure. Under the
DAY 2 / NIGHT 2 partitioned budget (§5, operator-locked), that means:
burn the day budget → cap hit → `_engage_lockout` → `lockout_flag=1` →
Gate 5 short-circuits the ENTIRE zone (nudge AND reset) until midnight.
**The night reserve is unreachable.** The D2 promise ("night ALWAYS has
its full allowance") is currently false.

**Fix (assert one, do not offer options — B-C1 discipline):** the
partition gate PRECEDES Gate A. Concretely:
1. New method `_gate_partition_check(zone_id, now, state) -> tuple[bool,
   str]` runs BEFORE Gate A. Returns `(True, "")` if the current
   partition (day/night per `_is_night_now`) has remaining budget on the
   correct `night_session_date`-keyed row; else `(False,
   f"{partition}_budget_exhausted")`.
2. If partition denies: write ONE `hard_reset_declined` row with
   `notes="reason=<partition>_budget_exhausted"`, set
   `zone.ramp_state = AC_RAMP_STATE_IDLE`, return. **`_engage_lockout`
   NOT called.** Lockout is reserved for the ineffective-nudge classifier
   verdict, per superseded §3-D1 / §12-1 ("lockout means the controller
   is broken; a budget-spent denial is not a pathology").
3. Only if partition allows AND Gate A's ORIGINAL total-cap check would
   ALSO deny — the "we've done 4 in the day+night combined, don't try
   again in an emergency" backstop — does `_engage_lockout` fire, matching
   today's behaviour when someone hits the true global cap.

Equivalent alternative (do NOT offer to builder; picked here):
`engage_lockout_on_cap` is a new keyword-only param on
`_perform_hard_reset_escalation` (see D-ESC-SIG below), and the
partition-check path passes `False`. Semantics identical.

**Consumer of the partitioned counters.** `_gate_partition_check` (trust);
`sensor.ac_reset_day_count_<zone>` and `sensor.ac_reset_night_count_<zone>`
(display). D8's NM alert message repair per superseded §3-D8 stands.

**Restart safety:** PERSIST via `ac_reset_state` (superseded §3-D2 columns
via guarded ALTER + INSERT-OR-REPLACE tuple extension — the "highest-
probability silent failure" the superseded plan flagged).

### D-ESC-SIG — Extend `_perform_hard_reset_escalation` signature (**status on ship: LIVE, load-bearing for D-ESC-CONSUME and D-PARTITION**)

**B-H5 fix.** Both `triggered_by` and `engage_lockout_on_cap` originated
in the deleted D1; nothing in Rev-1 instructs the builder to add them.
Explicit sub-deliverable:

- **Signature change** from
  `_perform_hard_reset_escalation(self, zone, kwh_rate_now)` to
  `_perform_hard_reset_escalation(self, zone, kwh_rate_now, *,
  triggered_by: str = "auto", engage_lockout_on_cap: bool = True)`.
  Defaults preserve today's behaviour for the only current caller.
- **Update call site at `:3901`** to pass
  `triggered_by="auto"` (explicit for readability).
- **Thread `triggered_by` into the `hard_reset_started` write** at
  `:3967-3972` (superseded §3-D5-A already did this for D5; both cycles
  agree). Also thread into the `_track_zone_action` call at `:3963-3966`.
- **D-ESC-CONSUME caller** passes `triggered_by="durability_fail"`,
  `engage_lockout_on_cap=False`.
- **D-PARTITION caller** — actually not a NEW caller; it lives inside
  `_perform_hard_reset_escalation` (the partition-check precedes Gate A).
  So `engage_lockout_on_cap` is honoured by Gate A specifically: when
  False, Gate A skips `_engage_lockout` and instead writes a
  `hard_reset_declined` row.
- **Signature is a shared-primitive change (B-M2):** while
  `_perform_hard_reset_escalation` has one caller today (`:3901`), the
  `log_ac_ramp_event` return-type change (None → int lastrowid) affects
  every caller of that DAO. §13 enumerates every caller.

### D-ESC-CONSUME — Teach the classifier to use `durable` (**status on ship: SHADOW → LIVE via a Select; may be REWORKED per §3.1 re-derivation**)

**Site:** `hvac_override.py:3802-3891`. The new branch is inserted
**STRICTLY BEFORE `log_ac_ramp_event` at `:3880` (B-H4 fix).** "After the
existing four" is not enough — a post-write insertion would log
`effective=1, classification="effective"` and then hard-reset, leaving the
ledger and the action in disagreement.

**Insertion point (literal):** after the existing 4-way classifier at
`:3821-3823` and BEFORE the notes-string build at `:3872`. So: classify
→ (this branch may promote) → build notes → `log_ac_ramp_event` at
`:3880` → `if escalate:` at `:3891`. On promotion `notes` includes
`classification="ineffective_durable_fail"`, `effective=False`,
`kwh_avoided=0.000` (matches non-goal 1 — see A-H4 consumer analysis).

**Promotion rule (B-C4 fix + B-H6 fix):**

The rule is a strict AND of four:

1. Legacy classifier just produced `classification == "effective"`.
2. Configured mode is `hvac_ac_escalation_source == "live"` (in `shadow`
   the branch computes but writes only a shadow row; in `legacy` the
   branch is not evaluated).
3. The consecutive-run of `nudge_evaluated` rows for this zone whose
   timestamp is within the last `CONF_HVAC_AC_DURABILITY_WINDOW` minutes
   AND whose `durable` is a QUALIFYING FAILURE reaches `N_ESC - 1`
   priors (i.e. `N_ESC` events total including the current one), where
   **qualifying failure** is defined below.
4. None of the five short-circuits from §0 will suppress the resulting
   escalation on this tick (best-effort check; the actual short-circuits
   still run and may deny — this AND is only to avoid gratuitous
   promotion when a partition denial is guaranteed; SEE §11 for the
   marginal-benefit call on whether to bother).

**QUALIFYING FAILURE, definition (B-C4 + B-H6):**
- A prior row qualifies iff **`durable = 0` AND the row is FULL-WINDOW
  (i.e. `durable_minutes >= CONF_HVAC_AC_DURABILITY_WINDOW`, NOT
  truncated by re-nudge)**. Truncated rows are almost always `durable=0`
  because a re-nudge only fires when draw came back above threshold; using
  them collapses the deliverable into the count-trigger §7.1 rejected.
- **`durable IS NULL` DOES NOT QUALIFY AS FAILURE and BREAKS THE
  STREAK** (fail-safe). NULL sources include: never-scheduled (first 30
  min post-deploy); restart-dropped in-flight timer (post-boot window);
  teardown-cancelled; DB update failure. In a repo with a boot-actuation-
  storm incident on record, an interpretation of `if not row["durable"]`
  that counts NULL as failure would silently escalate on first boot.
  Ruling: NULL is unknown, unknown breaks the streak.
- **Same rule for `restore_ok` where D-ESC-CONSUME reads it** — never
  read today, so this is a forward-guard for anyone adding a consumer.

### 3.1 — Re-derivation against the 25-min cadence (B-C4 quantitative gate)

Superseded §7.1 measured: inter-nudge median is EXACTLY 25.0 min in every
zone; §7.1 rejected `N=2/W=90` on the ground that it fires on 68-96% of
active nights and does not discriminate.

**Under this cycle's QUALIFYING-FAILURE definition** (FULL-WINDOW rows
only), the calculus changes materially:

- A full-window `durable=0` row requires the durability callback to fire
  at t+30 min AND observe kW still above threshold. It CANNOT be produced
  by a fresh re-nudge inside 30 min (that path produces a truncated row
  which does NOT qualify).
- So `N_ESC=2` requires: one prior nudge whose FULL 30-min follow-up
  observed the compressor drop and RE-RAMP, followed by a next nudge on
  the same zone. Given the 25-min inter-nudge median, most re-nudges will
  occur BEFORE the durability window closes, producing truncated rows that
  do NOT qualify. The predecessor's failure mode ("3 nudges in ~55
  minutes = fire") does NOT reduce to `N_ESC=2` under this definition
  because the middle event's durability row would be truncated.
- The rows that DO qualify are those where the compressor genuinely drops
  and holds for ~30 min AND then re-ramps. That is precisely the
  operator's ~10 kW / 49 kWh overnight pattern.

**Expected fire rate — PROBE A extension (§7.1 of this plan) MUST measure
before build dispatch.** The recorder join is:
```
count per zone-day of (durable=0 events whose row is FULL-WINDOW AND
whose next nudge on same zone within W min is also FULL-WINDOW durable=0)
```
run over the same 30-day window §7.1 used. Decision rule (asserted, not
offered):
- If the expected fire rate is **≤ 0.5/zone-day** on median nights AND
  ≥ 1 on the 2026-08-20 patho-night, ship D-ESC-CONSUME as specified.
- If **> 1/zone-day on medians** OR ~zero on patho-night, the deliverable
  fails the same discrimination test as §7.1's count trigger and is
  REWORKED (candidates: raise `N_ESC` to 3; add a magnitude conjunction
  requiring `kwh_rate_before >= 2×AC_NUDGE_KWH_RATE_BEFORE_FLOOR` on the
  qualifying rows; or DROP D-ESC-CONSUME and leave the ~0.30/day rate
  in place). Rework is a NEW planning revision, not a builder call.

**Section 7.1 of THIS plan holds the probe result before build.**

**Rollout guard (three-state Select).** `hvac_ac_escalation_source` in
`legacy` / `shadow` / `live`, default `shadow`. Kill-switch: `legacy`.

**Byte-identical shadow (B-H3 fix).** In `shadow` mode, ALL of the
following must be UNCHANGED relative to a legacy tick, verified in-suite:
- `zone.ramp_state` value at end-of-tick.
- `zone.nudge_kwh_rate_before` value at end-of-tick (the `None` reset in
  the `else` branch at `:3906` must still run).
- `nudge_evaluated` row's `effective`, `classification`, `kwh_avoided`,
  `notes` fields.
- Whether `_perform_hard_reset_escalation` was called.
- Whether the `else` branch's INFO log line was emitted.

The shadow-mode implementation writes at most ONE ADDITIONAL row
(`escalation_would_promote`, edge-triggered per §3-D8 with a 15-min
same-zone floor). Nothing else changes.

**A-H4 consumer analysis — `effective` and `kwh_avoided`.** Grep
2026-08-22 identifies consumers of `ac_ramp_events.effective` /
`kwh_avoided` derived from `notes`:
- `database.py:7806-7830` — savings aggregator (SUM of `kwh_avoided`
  parsed from `notes` where `effective`).
- `database.py:7896-7906` — false-positive aggregator.
- `sensor.py` — savings/FP display sensors.
- `energy_billing.py` — feeds cost accounting.

D-ESC-CONSUME flips rows from `effective=True → False` and forces
`kwh_avoided=0.000` in `notes`. Direction and magnitude:
- Savings AGGREGATE decreases (fewer effective rows, and each promoted
  row contributes 0 instead of its projected kWh — historically ≤ ~0.1
  kWh per row at the projection cap). At the expected fire rate
  (§3.1 ≤ 0.5/zone-day), the direction is a small DECREASE in reported
  savings and a small INCREASE in reported hard-reset activity.
- **Acceptance criterion (AC-CONSUMER):** after D-ESC-CONSUME flips
  live, the `ac_ramp_savings_today` sensor's 7-day trailing average
  decreases by ≤ 5% and does NOT flip sign. **Discriminating failure:**
  the aggregator throws (parse error on the new `classification` string)
  or reports negative savings — either indicates a shape defect.
- **Decision on inclusion:** promoted rows STAY in the savings
  denominator (their `kwh_avoided=0` contribution is correct — the nudge
  did not save anything). Do NOT exclude them.

**Consumer count on `durable`:** TWO — this classifier branch (trust) and
the display sensor from D-SCORE. No third consumer.

**Restart safety:** REBUILD. Classifier reads DB on entry; no in-memory
state to persist beyond the shadow's edge-latch (also REBUILD).

### D9 — DROPPED THIS CYCLE

Reviewer B-C5 identified that the Rev-1 `update_entity` withdrawal only
edited §3-D9, leaving five other sections still prescribing it. Rather
than propagate PENDING-PROBE-C markers across §5/§10/§11/§12/§13/AC-D9,
the simpler resolution is to **cut D9 entirely from this cycle** and
pursue the Carrier staleness defect either upstream or in a dedicated
follow-up planning doc. Marginal-benefit rationale in §11.

The Rev-1 evidence still stands (documented for the follow-up): scheduled
polls run every 30 min per `ha_carrier`'s `DEFAULT_UPDATE_INTERVAL_MINUTES =
30`; measured blind episodes of 96/108/68 min spanned 3-4 polls without
clearing; a reload clears the staleness. Points at a stale
client/session, not a stale poll. `update_entity` calls the same fetch
path as the periodic poll and is therefore unlikely to help. A future
cycle takes this up.

**D-GATE4 is UNAFFECTED by the D9 drop** — it never depended on refresh
(non-goal 3 of Rev 1, retained as non-goal 3 below).

### D10 — Actuation-lag canary (**probe first, then LIVE telemetry, or CANCEL**)

Unchanged from Rev 1. Three timestamps per nudge:
- **(a) `commanded_ts`** — existing `timestamp` on `nudge_started`.
- **(b) `reported_at_ts`** — first HA state change on
  `climate.<zone>.target_temp_high` matching the nudged value within a
  60s window. NEW column IF built.
- **(c) `physical_at_ts`** — first SPAN sample dropping below
  `AC_ACTIVELY_COOLING_KW_MIN` within the same 60s window. NEW column IF
  built.

Probe B (§7.2) runs BEFORE build; cancels the build if the retrospective
recorder join answers the question (p50 < 2s, p95 < 5s).

**Producer:** `_perform_soft_nudge` records (a) implicitly; two per-nudge
`async_track_state_change_event` listeners, hard 60s timeout, unregistered
on fire OR timeout OR teardown; both call the NEW
`update_ac_ramp_event_fields(event_id, **fields)` DAO. **Consumer:** two
display sensors, no trust consumer.

**Restart safety:** columns PERSIST; in-flight listeners REBUILD (drop).
Bounded write rate per §3-D3 cap.

---

## 4. Non-goals — explicit

1. Do NOT redefine `effective` on already-written rows (D-ESC-CONSUME
   writes its verdict onto the row it is currently evaluating; it never
   updates a past row's `effective`).
2. Do NOT introduce a count-based recurrence trigger against arbitrary
   `nudge_started` rows. Superseded §7.1 rejected it. D-ESC-CONSUME's
   qualifying-failure definition is disjoint (see §3.1).
3. Do NOT make D-GATE4 depend on any refresh mechanism. Ships
   independent of D9 (which is dropped this cycle anyway).
4. Do NOT use `config_entry.async_reload` or
   `homeassistant.reload_config_entry` from URA code for periodic refresh.
5. Do NOT let `hvac_action` veto D-GATE4. Corroboration only.
6. Do NOT rebuild working machinery: soft-nudge perform/restore,
   `_perform_hard_reset_escalation` internals, `_perform_ac_reset`,
   `_restore_after_reset`, `_verify_restore`, `async_startup_ramp_audit`,
   the `ac_reset_state` / `ac_ramp_events` DDL. Deltas only.
7. Do NOT couple D-GATE4 or D-ESC-CONSUME to house-state, occupancy, or
   preset. Pure HVAC-domain signals only.
8. Do NOT create a new escalation code path outside `if escalate:` at
   `hvac_override.py:3891`. All promotions route through it.
9. Do NOT delete `AC_RESET_MAX_PER_DAY` — KEEP + WIRE per superseded §3-D8
   / §12-22 with the D8 NM alert repair to "N/day + M/night".
10. Do NOT extend the D3 soft-nudge cap to the manual `force_nudge` button.
11. Do NOT ship D-ESC-CONSUME if §3.1's re-derivation lands its expected
    fire rate inside the §7.1 rejection region. Rework or drop.
12. Do NOT count truncated durable rows toward the D-ESC-CONSUME streak.
13. Do NOT count NULL durable rows as failure (they break the streak).
14. Do NOT read `hvac_action` inside `_zone_is_actively_cooling` except
    for the corroboration INFO log at trust-ladder step 5 (which does not
    influence the return value).

---

## 5. Knob ladder — every new number, placed and justified

| Knob | Default | Rung | Why here |
|---|---|---|---|
| `hvac_ac_gate4_predicate_mode` (Select) | `shadow` on first boot | 3 (Select) | 3-state kill-switch + shadow observation. |
| `hvac_ac_escalation_source` (Select) | `shadow` on first boot | 3 (Select) | Same discipline; trust decision. |
| `AC_ACTIVELY_COOLING_KW_MIN` (module const, kW) | `0.5` | 1 | Safety-adjacent primitive; not operator-tunable. |
| `AC_ACTIVELY_COOLING_BLOWER_RPM_MIN` (module const, rpm) | `100` | 1 | Corroboration threshold. |
| `GATE4_MAX_BLIND_FRACTION` (module const, ratio) | `0.01` | 1 | Invariant P bound. |
| `CONF_HVAC_AC_DURABILITY_WINDOW` (options int, minutes) | `30` | 2 | Set once; retroactive re-classification hazard. Silently ALSO the escalation lookback window (B-M5). Documented as such in the options-flow description. |
| `hvac_ac_esc_consume_n` (Number int) | `2` | 3 | `N_ESC` in Invariant E. Live-tunable. |
| `hvac_ac_reset_day_budget` (Number int, 0-4) | **`2`** | 3 | **DAY 2** per operator ruling 2026-08-22. Reserve semantics: NIGHT budget is not consumable by day. Superseded §5 says 1; **this row supersedes it for this cycle**. |
| `hvac_ac_reset_night_budget` (Number int, 0-4) | **`2`** | 3 | **NIGHT 2** per same ruling. Per-zone theoretical daily max rises from 2 to 4. Global 120-min min-interval still bounds cycling rate. |
| `hvac_ac_night_start_hhmm` (options string) | `"22:00"` | 2 | Superseded §3-D2 wrap-around helper. |
| `hvac_ac_night_end_hhmm` (options string) | `"06:00"` | 2 | Same. |
| `hvac_ac_soft_nudge_daily_limit` (Number int) | `50` | 3 | Runaway guard (D3 carry). |
| `hvac_ac_reset_off_duration` (Number int, seconds, 30-300) | `60` | 3 | D7 carry. |
| `AC_RESET_OUTCOME_SETTLE_S` (module const, s) | `60` | 1 | D6 measurement primitive. |

**Three constants named "2" (A-L3 clarification).** `AC_RESET_MAX_PER_DAY
= 2` (`hvac_const.py:491`) is retained as the "total daily reference" for
the NM alert message per superseded §3-D8; `_hard_reset_daily_limit`
(coordinator attribute) is the runtime cap; the partition defaults are
2/2. Their relation: `day_budget + night_budget = 4` is the new
theoretical per-zone maximum; `AC_RESET_MAX_PER_DAY` is a display constant
in the alert string, rewritten to say
`"Reset #{used_in_partition}/{partition_budget} ({partition}). Total
today: {day + night} across {day_budget + night_budget}."`;
`_hard_reset_daily_limit` is deprecated in this cycle in favour of
partition-aware checks and reads as `day_budget + night_budget` for
back-compat.

**Kill-switch semantics.** `hvac_ac_gate4_predicate_mode = legacy`
restores the pre-fix Gate 4 body verbatim.
`hvac_ac_escalation_source = legacy` restores today's classifier verbatim.
`day_budget = 0` OR `night_budget = 0` disables the corresponding
partition entirely (partition-check denies with the specific reason).

---

## 6. Producer / consumer map — every new value

### `_zone_is_actively_cooling` predicate (D-GATE4)

- Producer: helper. Reads `zone.hvac_mode` (config-source, frozen-tolerant
  because underlying value changes rarely), `_read_kwh_rate(zone, now)`
  (which handles W→kW, staleness, unknown/None, and now the
  kWh-cumulative rejection), optional `blower_rpm`.
- Consumers: `check_ac_reset` at `:2779` (trust — ONLY consumer);
  `sensor.ac_gate4_blind_fraction_7d_<zone>` (display).

### `durable` / `durable_minutes` (D-SCORE)

- Producer: `_write_durable` (superseded §3-D4).
- Consumers: (1) D-ESC-CONSUME classifier branch (trust; reads only
  full-window rows with non-NULL `durable`); (2)
  `sensor.ac_ramp_durability_rate_<zone>` (display).

### `escalation_would_promote` shadow rows (D-ESC-CONSUME shadow mode)

- Producer: classifier when mode=`shadow` AND promotion rule hits.
  Edge-triggered: one row per triggering `nudge_evaluated` `event_id`,
  min 15 minutes between same-zone same-reason writes.
- Consumers: operator diagnostics; NOT read by any trust path;
  Invariant III protected (§8 AC-III).

### `gate4_divergence_shadow` rows (D-GATE4 shadow mode)

- Producer: LATCHED per-zone `agree↔diverge` transition writer.
- Consumers: operator diagnostics.

### Partition counters (D-PARTITION / superseded §3-D2)

- Producer: `_perform_hard_reset_escalation` increment (charged BEFORE
  actuation per superseded §3-D2 ordering rule).
- Consumers: `_gate_partition_check` (trust); day/night display sensors;
  D8 NM alert message.

### `_perform_hard_reset_escalation` signature (D-ESC-SIG)

- Producer: N/A (function definition).
- Consumers: `:3901` call site (existing, passes `triggered_by="auto"`);
  D-ESC-CONSUME's future call passes `"durability_fail"` +
  `engage_lockout_on_cap=False`. `_gate_partition_check` (indirect) —
  partition-check runs BEFORE Gate A regardless of
  `engage_lockout_on_cap`.

### D10 lag columns

- Producer: per-nudge listeners; write via `update_ac_ramp_event_fields`.
- Consumers: two display sensors.

### `effective` / `kwh_avoided` — CONSUMERS ENUMERATED (A-H4)

- `database.py:7806-7830` (savings aggregator, trust — feeds cost);
- `database.py:7896-7906` (FP aggregator, trust);
- `sensor.py` savings/FP display;
- `energy_billing.py` cost accounting.
Direction under D-ESC-CONSUME live: small DECREASE in reported savings;
small INCREASE in reported hard-resets. Bounded and non-sign-flipping;
AC-CONSUMER discriminates.

---

## 7. Measure-before-build probes

Two probes BEFORE build dispatch. Build blocks on both.

### §7.1 — Probe A: D-GATE4 sizing + D-ESC-CONSUME re-derivation

Read-only join over `ac_ramp_events` and the HA recorder / SPAN history,
7-30 days. Per zone:

1. Duration-weighted fraction of time where SPAN `ac_load_sensor` >
   Gate-7 threshold AND `climate.<zone>.hvac_action != "cooling"`
   (**B-L3 correction — NOT `== "idle"`; Gate 4 vetoes on ANY value
   other than `"cooling"`, including `fan`/`drying`/`off`/`heating`/
   `unavailable`**). Reproduce the 12.2 / 7.1 / 12.9% figures.
2. Same, restricted to `hvac_mode ∈ {cool, heat_cool, auto}`.
3. Blower_rpm distribution when SPAN reads > threshold AND
   `hvac_action != "cooling"`.
4. **D-ESC-CONSUME re-derivation (§3.1):** expected fire rate per
   zone-day of the qualifying-failure streak reaching `N_ESC=2` under
   full-window-only semantics. Median-night rate AND patho-night rate.

**Go/no-go.** Steps 1-3 as before. Step 4: if median > 1/zone-day OR
patho ≈ 0, D-ESC-CONSUME is REWORKED (§3.1 asserts this, not the probe).
Probe output goes into §7.1 as a data block.

---

### §7.1 RESULTS — RUN 2026-08-22. **VERDICT: D-ESC-CONSUME IS REWORKED.**

**Steps 1-3 — D-GATE4 CONFIRMED, ship it.**

| zone | blind % of time-above-threshold | blind hours |
|---|---|---|
| zone_1 | **12.2%** | 11.35 h |
| zone_2 | **7.1%** | 4.58 h |
| zone_3 | **12.9%** | 6.80 h |

Reproduces the earlier run to within rounding (11.05 / 4.58 / 6.49 h). **NOTE FOR ANY
FUTURE READER: the probe agent reported these as 6.33 / 2.57 / 3.79% and inferred a "2x
divergence" caused by the threshold retune. THAT INFERENCE IS WRONG — it used a different
DENOMINATOR (fraction of the WHOLE window rather than of time-above-threshold). Dividing by
the time-above-threshold fractions (51.4 / 36.4 / 28.9%) recovers 12.3 / 7.1 / 13.1%. The
figures agree; there is no divergence and no threshold-retune effect to chase.**

Supporting: `hvac_mode` gating removes essentially nothing (all three thermostats sit in
`heat_cool` ~99.6% of the window) — so the mode check earns its place as a HEATING guard, not
as a discriminator. `blower_rpm` EXISTS on all three entities and reads >=500 rpm during
**93-96%** of blind time, corroborating that the air handler genuinely runs while the cloud
says idle. Blind time is `idle` 98.9-99.5% — a confident wrong answer, not `unknown`.

**Step 4 — D-ESC-CONSUME IS NOT MERELY MIS-CALIBRATED. IT IS ARITHMETICALLY IMPOSSIBLE.**

MEASURED over the full 30-day event history, independent of any SPAN simulation:

| zone | eval->eval pairs within the 30-min lookback | of those, prior row FULL-WINDOW |
|---|---|---|
| zone_1 | 286 | **0** |
| zone_2 | 163 | **0** |
| zone_3 | 73 | **0** |
| **total** | **522** | **0** |

The proof: `nudge_started -> nudge_evaluated` is a hard **6.00 minutes** (measured p50 = min,
n=912). For a prior row to be FULL-WINDOW the next nudge must land **> t+30 min**; the next
EVALUATION therefore lands **> t+36 min**; but the streak lookback is **30 min**. **The two
conditions are mutually exclusive by exactly the nudge duration, always.** AC-E's positive
control is constructible only as a hand-crafted fixture — no production path can generate it,
so the deliverable would have shipped green and never fired once.

**No tuning escape exists.** Full-window-only fires **exactly 0**. Counting truncated rows
fires **5.9 / 8.7 / 17.1 per zone-day** — roughly one per nudge, i.e. the count trigger §7.1's
predecessor already rejected. There is no middle at W=30. Sensitivity sweep (full-window-only,
N_ESC=2), per zone-day with patho-night fires in brackets:

| lookback | zone_1 | zone_2 | zone_3 |
|---|---|---|---|
| 30 (spec) | 0.00 (0) | 0.00 (0) | 0.00 (0) |
| 60 | 0.40 (0) | 0.13 (0) | 0.54 (0) |
| 90 | 1.47 (1) | 0.27 (0) | 0.54 (0) |
| 120 | 2.28 (2) | 0.67 (1) | 0.94 (0) |

**No (N, W) satisfies both halves of the §3.1 decision rule.** W=60 meets the median bound but
fires 0 on the pathological night in every zone. W=120 catches it in z1/z2 but breaches the
median in z1 and still misses z3.

**ROOT CAUSE — and it was flagged and not fixed.** `CONF_HVAC_AC_DURABILITY_WINDOW` is doing
TWO jobs: the durability MEASUREMENT window and the escalation LOOKBACK window. Reviewer B
raised exactly this as B-M5; the revision DISCLOSED the double duty on the knob row instead of
DECOUPLING it. The two jobs are incompatible by precisely the 6-minute nudge duration.
Decoupling them into two knobs is a PRECONDITION for any rework — and note the sensitivity
table above already contains no passing cell, so decoupling alone does not rescue it.

**PROCESS NOTE, recorded because it is the second occurrence.** Measurement has now killed the
escalation deliverable TWICE, on two different mechanisms (count trigger; durability streak).
That is a signal about the APPROACH, not about the knob values: we have twice designed an
escalation trigger and then measured it, rather than measuring first to find what actually
separates a bad night from an ordinary one. §7.1's predecessor established that NO tested
signal discriminates the pathological night — energy, duration, continuity, floor persistence,
recovery. Until something does, any trigger built on per-zone nightly pattern is a guess with a
test attached.

**RULING: the cycle ships WITHOUT escalation.** D-GATE4 plus carried-forward D2-D8 are all
measured and motivated and are unaffected by this. "When should a reset fire" returns to being
an open question requiring its own discovery probe — NOT a third design-then-test attempt.

### §7.2 — Probe B: D10 retrospective lag

Join `nudge_started` rows to `climate.<zone>.target_temp_high` state
history. If p50 < 2s and p95 < 5s → CANCEL D10 build.

---

## 8. Acceptance criteria — DISCRIMINATING

**Meta-rule (§14):** every decision the plan asserts (semantics, defaults,
carve-outs) MUST have at least one test that FAILS under the wrong
choice — a negative control. A criterion that passes under both the
correct and incorrect implementation is decoration and must be replaced.

### AC-P (Invariant P — D-GATE4)

- **In-suite three-outcome discrimination:**
  (a) `hvac_mode=cool`, kW=1.2, `hvac_action="idle"` → helper True.
  (b) `hvac_mode=heat`, kW=1.2, `hvac_action="cooling"` → helper False
      (config-guard negative control — a builder who dropped the mode
      check passes (a) but fails this).
  (c) `hvac_mode=cool`, kW=0.1, `hvac_action="cooling"` → helper False
      (SPAN gate negative control).
  (d) `hvac_mode=cool`, kW=None (sensor stale > 10 min) → helper False
      (fail-closed negative control — a builder who treated `None` as
      True would pass (a) but fail this).
  (e) `hvac_mode=""` (pre-first-poll frozen), kW=1.2 → helper False
      (A-M2 pre-first-poll negative control).
  (f) `hvac_mode=cool`, sensor unit=kWh (cumulative) → helper False AND
      one WARN logged for this zone (kWh-sensor rule negative control).
- **Shadow LATCHED divergence (B-H7 negative control):** 20 contiguous
  ticks with (legacy=veto, new=proceed), then 20 with agreement, then 20
  with (legacy=proceed, new=veto). Assert exactly TWO
  `gate4_divergence_shadow` rows total: one at tick 1
  (`legacy_veto_new_proceed`) and one at tick 41
  (`legacy_proceed_new_veto`). A per-tick implementation writes 40 rows
  and fails.
- **Live (7 days after `live` flip):**
  `sensor.ac_gate4_blind_fraction_7d_<zone>` ≤ 0.01 for all three zones.

### AC-S (Invariant S — D-SCORE)

Reuse superseded AC4's full-window and cancel-on-teardown cases with the
Rev-2 clarification (D-SCORE §3 above): truncated rows have `durable = 0
if kW-at-fire above threshold else 1`. Retire the superseded AC4 clause
that says truncated is unconditionally 0 (B-M3).

### AC-E (Invariant E — D-ESC-CONSUME)

- **Positive control (live):** 1 prior FULL-WINDOW `durable=0` row within
  30 min for zone_1, current nudge would classify `effective` under
  legacy. Assert:
  (a) new row's classification is `"ineffective_durable_fail"`,
      `effective=False`, `kwh_avoided` in notes = 0.000;
  (b) `_perform_hard_reset_escalation` called once with
      `triggered_by="durability_fail"`, `engage_lockout_on_cap=False`;
  (c) exactly one `hard_reset_started` row with
      `triggered_by="durability_fail"`.
- **Negative control — `N_ESC - 1` = 1 total (B-C3):** 0 priors, current
  is the first event. Assert `escalate=False`, no promotion, no hard
  reset. Under the wrong semantics ("N_ESC priors + current") the plan
  would ALSO produce False here, so the ambiguity is retired only if
  positive-control-with-1-prior and negative-control-with-0-priors BOTH
  pass. Both are asserted.
- **Truncated-row negative control (B-C4):** 1 prior TRUNCATED
  `durable=0` (`durable_minutes=12`), current nudge would classify
  `effective`. Assert `escalate=False`, no promotion. A builder counting
  truncated rows fails.
- **NULL-breaks-streak negative control (B-H6):** 1 prior FULL-WINDOW
  `durable=0`, second-most-recent prior `durable=NULL`, current nudge.
  Assert `escalate=False` (NULL breaks the run). A builder counting
  NULL as failure fails.
- **Byte-identical shadow (B-H3):** same setup as positive control, mode
  = `shadow`. Assert:
  (a) new row's `effective=True`, `classification="effective"`,
      `kwh_avoided` matches legacy computation exactly;
  (b) `zone.ramp_state` at end-of-tick equals the legacy value;
  (c) `zone.nudge_kwh_rate_before` equals the legacy value (`None`);
  (d) `_perform_hard_reset_escalation` NOT called;
  (e) exactly ONE `escalation_would_promote` shadow row.
  A builder who forgets to run the `else` branch's `None` reset fails
  (c). A builder who writes the promoted row instead of the shadow row
  fails (a).
- **Legacy-mode absence:** mode=`legacy`, same setup. Assert ZERO rows
  of either shadow or `hard_reset_started/durability_fail` type. Kill-
  switch negative control (a boolean can't guard this).
- **Live (14 days after flip):** at least one row with
  `triggered_by="durability_fail"` OR operator confirms the ~10 kW / 49
  kWh overnight has not recurred.

### AC-PARTITION (A-C2 fix)

- **Day-only cap denial preserves night reserve:** hand-craft
  `day_reset_count=2, night_reset_count=0` for zone_1, wall-clock=15:00,
  `day_budget=2, night_budget=2`. Invoke escalation from the
  ineffective-nudge caller. Assert:
  (a) one `hard_reset_declined` row with
      `notes="reason=day_budget_exhausted"`;
  (b) `lockout_flag` UNCHANGED (still 0);
  (c) no "controller may be broken" NM notification;
  (d) NO call to `_engage_lockout`. Then advance wall-clock to 22:30
      and invoke again. Assert one `hard_reset_started` row is written
      (the night reserve was preserved). Failure shape: 22:30 denial
      means the day-time lockout ate the night reserve.
- **True-cap lockout still fires:** engineer `day_reset_count=2,
  night_reset_count=2`, invoke at 23:59. Assert Gate A's true-cap
  fallback fires `_engage_lockout` (or the equivalent behaviour) —
  the ORIGINAL "we've exhausted BOTH partitions" invariant is
  preserved. A builder who dropped Gate A entirely fails this.
- **Recurrence-caller no-lockout (D-ESC-SIG):** invoke with
  `engage_lockout_on_cap=False` at cap. Assert decline row, no lockout,
  no NM. As superseded plan AC1 no-lockout-on-cap, adapted.

### AC-D10 — Actuation lag

- Probe-gated. If Probe B cancelled the build, this block is vacuous.

### AC-CONSUMER (A-H4)

- 7 days after D-ESC-CONSUME live: `ac_ramp_savings_today` 7-day trailing
  average has decreased by ≤ 5% relative to the 7-day pre-flip average
  AND remains positive.
- Failure shape: sign flip OR aggregator exception in logs = shape
  defect; roll back.

### AC-I / AC-III

Reuse superseded AC7 (bounded cycling, now with per-partition budgets)
and AC8 (aggregator non-pollution — insert one
`escalation_would_promote`, one `gate4_divergence_shadow`, one
`hard_reset_declined` row; savings/FP aggregators unchanged).

---

## 9. Restart-safety declaration

| New state | Category | Mechanism |
|---|---|---|
| `_zone_is_actively_cooling` (D-GATE4) | REBUILD | Stateless. |
| `_last_gate4_divergence_state[zone]` (B-H7 latch) | REBUILD | Recomputed on boot; worst case one extra transition row post-restart. |
| `hvac_ac_gate4_predicate_mode` (Select) | PERSIST | HA Select persistence. |
| `hvac_ac_escalation_source` (Select) | PERSIST | Same. |
| `hvac_ac_esc_consume_n` (Number) | PERSIST | URA Number-persistence. |
| Partition counters + `night_session_date` (D-PARTITION / superseded §3-D2) | PERSIST | Columns on `ac_reset_state` via guarded ALTER; must be added to `save_ac_reset_state` INSERT-OR-REPLACE tuple. |
| `_perform_hard_reset_escalation` new params | N/A | Function definition; default preserves today's behaviour. |
| D10 lag columns | PERSIST as columns; in-flight listener REBUILD (drop) | Row keeps NULL on restart, visible + attributable. |
| `escalation_would_promote` / `gate4_divergence_shadow` / `hard_reset_declined` rows | PERSIST | `ac_ramp_events` ledger, edge-triggered. |
| D2-D8 carry-forward state | Per superseded §9 | Not repeated. |

---

## 10. Ship order

1. Build (single deploy): D-GATE4 (shadow default) + D-SCORE columns
   (LIVE additive) + D-PARTITION (LIVE) + D-ESC-SIG (LIVE, defaults
   preserve behaviour) + D-ESC-CONSUME (shadow default) + D2/D3/D5/D6/D7/D8
   carry-forward (LIVE).
2. Operator flips D-GATE4 to `live` after ≥ 24 h of shadow observation.
3. Operator flips D-ESC-CONSUME to `live` after ≥ 3 shadow hits look
   right AND AC-CONSUMER's 7-day baseline is captured.
4. D10 ships iff Probe B justifies.

Independent-of-excursion-cycle claim from superseded §10 stands.

---

## 11. Marginal-benefit decomposition

- **D9 (Rev-1 refresh workaround) — DROPPED this cycle.** Simplest
  version: the manual reload the operator already does. Marginal benefit
  of an automated `update_entity` call: probably zero (Rev-1 evidence:
  three scheduled polls did not clear the staleness during blind
  episodes; refresh reuses the same client). Marginal ingredient risk:
  new writer of service calls on a periodic timer; false confidence in a
  refresh that doesn't refresh. **Verdict: cut.** Pursue the defect in a
  follow-up planning doc with an experimental probe FIRST
  (measure-before-build), or upstream in `ha_carrier`.
- **D10 (per-nudge lag columns) — probe-gated.** Simplest version: the
  retrospective probe. Marginal benefit of columns: continuous rolling
  telemetry vs one-shot. Ship only if Probe B says the (a)→(b) gap
  matters.
- **D-ESC-CONSUME rework option (§3.1).** If Probe A step 4 lands the
  expected fire rate in the §7.1 rejection region, DO NOT ship as
  specified. Rework or drop; a rework is a new planning revision.

Parked-with-trigger discipline applies to any dropped item: record it
with the evidence trigger that would revisit.

---

## 12. Tier 3 test-authority — real per-site source mutation

| # | Site | Enclosing method | Neuter drill | Test that MUST fail |
|---|---|---|---|---|
| 1 | D-GATE4 config guard | `_zone_is_actively_cooling` | Delete the `hvac_mode` check | AC-P (b) heat + draw |
| 2 | D-GATE4 SPAN gate | same | Return True when `hvac_mode=cool` regardless of kW | AC-P (c) low draw |
| 3 | D-GATE4 fail-closed on None | same | Treat `_read_kwh_rate` returning `None` as True | AC-P (d) stale |
| 4 | D-GATE4 pre-first-poll | same | Skip the `""` check in the mode set | AC-P (e) frozen `""` |
| 5 | D-GATE4 kWh-sensor rule | `_read_kwh_rate` | Do NOT reject `unit=kWh` | AC-P (f) kWh |
| 6 | D-GATE4 state-clearing (B-H1) | `check_ac_reset` at Gate 4 body | Drop the three state-reset statements from the False branch | Gate-8 sustained-time false-positive test (new; see §12.a) |
| 7 | D-GATE4 shadow decides live | `check_ac_reset` at `:2779` | In shadow, use NEW helper for the decision | AC-P shadow latched-divergence |
| 8 | D-GATE4 divergence latch (B-H7) | shadow writer | Write per-tick instead of on transition | AC-P latched test asserts 2 rows |
| 9 | D-SCORE non-mutation | `_write_durable` | Also SET `effective=?` | Superseded AC4 same-row-both-columns |
| 10 | D-SCORE event_id identity | `_write_durable` | Replace `WHERE event_id=?` with `ORDER BY timestamp DESC LIMIT 1` | Superseded AC4 truncated-vs-fresh |
| 11 | D-ESC-CONSUME full-window only (B-C4) | classifier branch | Count truncated rows | AC-E truncated-row negative control |
| 12 | D-ESC-CONSUME NULL breaks streak (B-H6) | same | Count NULL as failure | AC-E NULL-breaks-streak |
| 13 | D-ESC-CONSUME N_ESC semantics (B-C3) | same | Fire on `N_ESC=1` (0 priors + current) | AC-E N-1 negative control |
| 14 | D-ESC-CONSUME insertion order (B-H4) | classifier | Insert branch AFTER `log_ac_ramp_event` at `:3880` | New test: assert the row's `classification == "ineffective_durable_fail"` at time of write, not post-hoc |
| 15 | D-ESC-CONSUME byte-identical shadow (B-H3) | classifier mode dispatch | Skip only the `_perform_hard_reset_escalation` call; leave `ramp_state = ESCALATING` set | AC-E byte-identical shadow (c) or (a) |
| 16 | D-ESC-CONSUME shadow gate | classifier mode dispatch | Force live path regardless of Select | AC-E legacy-mode absence |
| 17 | D-ESC-SIG signature | `_perform_hard_reset_escalation` | Ignore `engage_lockout_on_cap`; always call `_engage_lockout` | AC-PARTITION day-only-cap |
| 18 | D-PARTITION preserve-night (A-C2) | `_gate_partition_check` OR Gate A body | Run Gate A first without partition-check | AC-PARTITION 22:30 reserve preserved |
| 19 | D-PARTITION true-cap fallback | Gate A body | Delete the true-cap `_engage_lockout` call | AC-PARTITION true-cap lockout |
| 20 | D2 save-tuple (carried) | `save_ac_reset_state` | Remove partition columns from INSERT-OR-REPLACE tuple | Superseded AC2 save-round-trip |
| 21 | AC-CONSUMER shape (A-H4) | classifier notes builder | Emit `kwh_avoided=1.234` on promoted row | AC-III non-pollution + AC-CONSUMER magnitude |

**§12.a NEW test — Gate-8 sustained-time FP guard (B-H1 negative
control):** simulate a heating cycle followed by a cooling cycle;
without the state-reset statements in the D-GATE4 False branch, Gate 8's
counter carries from heating into cooling and fires immediately. Assert
the counter is 0 at cooling-cycle start.

**Orchestrator personally re-runs sites 1, 2, 3, 6, 11, 12, 15, 17, 18
before ship.** Blast radius: config guard, SPAN gate, staleness handling,
state-clearing, D-ESC-CONSUME's three semantic ambiguities, byte-identical
shadow, signature carve, partition-preserve-night.

**Reviewer D (adversarial completeness)** re-enumerates every emission
site of `_perform_hard_reset_escalation` INCLUDING pre-existing code (the
`if escalate:` at `:3891` AND the manual `force_ac_reset` caller at
`:4338`), confirming no new escalation path outside `if escalate:`
(non-goal 8). Every flagged leak needs a legal-config reachable repro.

---

## 13. Files touched — for the builder

**Amend the supersession header on `PLANNING_ac_ramp_recurrence_escalation.md`**
to state "read this document's §7.1 (canonical); every other carry-
forward is spelled out per-deliverable in the successor plan §1's map."
This retires the READ-ORDER line that conflicted with §1 (B-C1).

- `custom_components/universal_room_automation/domain_coordinators/hvac_override.py`
  — new `_zone_is_actively_cooling(zone, now)` helper; replace Gate 4
  body at `:2779` per §3-D-GATE4 literal block; new
  `_last_gate4_divergence_state` latch + writer; new classifier branch
  inserted BEFORE `log_ac_ramp_event` at `:3880`; new
  `_gate_partition_check` method preceding Gate A in
  `_perform_hard_reset_escalation`; signature extension of
  `_perform_hard_reset_escalation` (adds `triggered_by`,
  `engage_lockout_on_cap` kwargs) plus call-site update at `:3901`;
  thread `triggered_by` into `hard_reset_started` write at `:3967`; new
  per-nudge lag listeners for D10 (if built); coordinator setters for
  new Selects and Numbers. Cancellation registry for D10 listeners lives
  in the existing teardown block at `:1439-1459`.
- `custom_components/universal_room_automation/domain_coordinators/hvac_const.py`
  — new module constants `AC_ACTIVELY_COOLING_KW_MIN`,
  `AC_ACTIVELY_COOLING_BLOWER_RPM_MIN`, `GATE4_MAX_BLIND_FRACTION`;
  new event-type constants `AC_RAMP_EVENT_GATE4_DIVERGENCE_SHADOW`,
  `AC_RAMP_EVENT_ESCALATION_WOULD_PROMOTE`,
  `AC_RAMP_EVENT_HARD_RESET_DECLINED` (carried from superseded plan);
  `AC_RESET_OUTCOME_SETTLE_S = 60` (D6 carry).
- `custom_components/universal_room_automation/select.py`
  — `hvac_ac_gate4_predicate_mode`, `hvac_ac_escalation_source`. NOT
  `hvac_ac_recurrence_mode` (superseded §7.1 killed it).
- `custom_components/universal_room_automation/number.py`
  — `hvac_ac_esc_consume_n`, `hvac_ac_reset_day_budget`,
  `hvac_ac_reset_night_budget`, `hvac_ac_soft_nudge_daily_limit`,
  `hvac_ac_reset_off_duration`. Each calls its coordinator setter.
- `custom_components/universal_room_automation/config_flow.py` +
  `options_flow.py`
  — `hvac_ac_night_start_hhmm`, `hvac_ac_night_end_hhmm`,
  `hvac_ac_durability_window`. D9's `hvac_ac_carrier_refresh_interval_s`
  is DROPPED with D9.
- `custom_components/universal_room_automation/database.py`
  — extend `ac_ramp_events` guarded ALTER block at `:1681-1712` with
  `durable INTEGER NULL`, `durable_minutes INTEGER NULL`,
  `reset_outcome TEXT NULL` (D5/D6/D-SCORE carry); IF D10 built also
  `reported_at_ts TEXT NULL`, `physical_at_ts TEXT NULL`.
  **NEW guarded ALTER block for `ac_reset_state`** (superseded §3-D2)
  adding `day_reset_count`, `night_reset_count`, `night_session_date`,
  `in_flight_durable_started_ts` — model exactly on the
  `ac_ramp_events` block. **EXTEND `save_ac_reset_state` INSERT-OR-
  REPLACE column list AND parameter tuple at `:7314-7335`** — the
  "highest-probability silent failure" per superseded §12-5.
  **CHANGE `log_ac_ramp_event` return from None to `cursor.lastrowid:
  int`** (B-M2). Callers in the tree that ignore the return still work;
  new callers (D4 `_write_durable`, D5 back-fill, D6
  `_write_reset_outcome`, D10 lag writers) rely on it. Enumerate
  callers below and verify none pattern-matches on `is None`.
  **NEW DAO `update_ac_ramp_event_fields(event_id: int, **fields)`**
  (B-M1) used by D4/D5/D6/D10 back-fills. UPDATE by `event_id`; fields
  validated against a whitelist.
  **Callers of `log_ac_ramp_event` today** (verify pre-ship via
  `grep -n "log_ac_ramp_event" custom_components/universal_room_automation/`):
  the soft-nudge start/evaluated/settled writes in `hvac_override.py`
  and the hard-reset started/completed writes in the same file. All
  discard the return value today — safe.
- `custom_components/universal_room_automation/sensor.py`
  — `sensor.ac_gate4_blind_fraction_7d_<zone>`,
  `sensor.ac_reset_day_count_<zone>`,
  `sensor.ac_reset_night_count_<zone>`,
  `sensor.ac_reset_last_outcome_<zone>` (D6 carry),
  `sensor.ac_ramp_durability_rate_<zone>` (D-SCORE display), plus D10
  sensors if built. DROP D9 refresh sensor.
- `quality/tests/` — one file per deliverable covering §8 ACs, the §12
  mutation-drill fixtures, and every negative control listed above.

Builder: re-grep every anchor before edit.

---

## 14. Response to the meta-finding

Reviewer B: *"the plan's own §12 mutation drills and §8 acceptance
criteria pass under BOTH the correct and incorrect implementation for
B-C3, B-C4, B-H3 and B-H6."* That was the failure Tier 3 is designed to
prevent. Rev 2 addresses each with a NEGATIVE CONTROL that fails under
the WRONG choice:

- **B-C3 (N_ESC off-by-one):** AC-E adds "0 priors + current → no
  escalate". The wrong semantics (N_ESC priors + current) ALSO passes
  this — so §12 site 13 pairs it with a mutation drill that fires on
  `N_ESC=1` and asserts AC-E's positive control FAILS. Both together
  discriminate.
- **B-C4 (truncated rows):** AC-E adds "1 prior TRUNCATED → no escalate".
  §12 site 11 mutates the qualifier to count truncated rows and confirms
  this test fails. The re-derivation in §3.1 is the plan-level
  discrimination (rework-or-drop if fire rate is in §7.1 region).
- **B-H3 (byte-identical shadow):** AC-E's byte-identical shadow test
  asserts `zone.ramp_state`, `zone.nudge_kwh_rate_before`, row fields,
  presence/absence of the `else` branch's INFO log, and the promoted-
  row-vs-shadow-row identity. §12 site 15 mutates to leave
  `ramp_state = ESCALATING` set in shadow and confirms the test fails.
- **B-H6 (NULL semantics):** AC-E's NULL-breaks-streak test with a NULL
  between two full-window `durable=0` rows. §12 site 12 mutates to
  count NULL and confirms the test fails.

**Rule for this cycle going forward:** every assertion in the plan (any
"MUST", "ASSERTED", or default value) MUST be traceable to at least one
in-suite test that fails under the wrong choice. §8 and §12 pair up.
Reviewer B is right — a criterion that passes under both correct and
incorrect implementations is decoration. Rev 2 assumes that as a plan-
level invariant, not just a review outcome.

---

## 15. Change log (Rev 1 → Rev 2)

Mapping of reviewer findings to resolutions.

**CRITICAL from Framing A**

- A-C1 (cooling nudge during heating in `heat_cool`): **MOOT** —
  measurement recorded §0.5. Gas heating, AC circuits show <200 W in
  heating season. Helper docstring cites this and the re-open condition
  (change to heat-pump heating).
- A-C2 (`_engage_lockout` on cap-hit destroys the night reserve):
  **FIXED** — new D-PARTITION deliverable §3; partition-check precedes
  Gate A and does not engage lockout on partition-only denial. AC-
  PARTITION discriminates. §12 sites 17-19 mutation-drill.

**CRITICAL from Framing B**

- B-C1 (read-order sends builder AWAY from D2-D8 spec): **FIXED** — §1
  per-deliverable carry-forward map; superseded doc's header amended per
  §13.
- B-C2 (2/2 ruling in §3 but §5 carries 1/1 by reference): **FIXED** —
  §5 has explicit `hvac_ac_reset_day_budget=2` and
  `hvac_ac_reset_night_budget=2` rows; AC-PARTITION's fixture is
  `day=2, night=0` (not `1`).
- B-C3 (N_ESC off-by-one; AC passes under both): **FIXED** — Invariant
  E disambiguated to "total events including current"; §3-D-ESC-CONSUME
  retires the "N_ESC - 1 priors" phrasing; AC-E adds 0-prior negative
  control; §12 site 13 mutation.
- B-C4 (as-specified D-ESC-CONSUME IS the count trigger §7.1 rejected):
  **FIXED** — §3-D-ESC-CONSUME qualifying-failure requires FULL-WINDOW
  rows; truncated excluded. §3.1 forces a re-derivation as Probe A step
  4; if in rejection region, rework or drop, not ship. §12 site 11
  mutation. AC-E truncated negative control.
- B-C5 (D9 withdrawal only in §3-D9; five other sections still
  prescribed it): **FIXED** — D9 CUT entirely; §11 records the
  rationale; sections 5/6/8/9/10/12/13 D9 references all removed.

**HIGH from Framing A**

- A-H2 (five more gates between `if escalate:` and actuation): §0 STAGE
  4 enumerates all five; Invariant E includes the "none of the five
  engaged" precondition.
- A-H3 / B-H2 (predicate must call `_read_kwh_rate`): §3-D-GATE4 trust
  ladder step 2 routes through it; kWh-cumulative sensor rule added as
  step 3.
- A-H4 (`effective` / `kwh_avoided` consumer map): §3-D-ESC-CONSUME
  A-H4 analysis; AC-CONSUMER; §6 enumeration; §12 site 21.
- A-M1 (D9 scheduler prior-art was TEARDOWN not `async_track_time_interval`):
  §1 grep table corrects; D9 cut so N/A now.
- A-M2 (`hvac_mode` not independent of stale poll): §3-D-GATE4 trust
  ladder step 1 restates the trust-basis correctly (frozen-tolerant
  because underlying value changes rarely, not "independent poll");
  frozen `""` handled; AC-P (e) negative control.
- A-M3 (§0 gate enumeration omits EgressManager and `_override_active`):
  §0 STAGE 1 now enumerates both.
- A-M4 (Gate 4 state-reset side effects): §3-D-GATE4 literal AFTER block
  keeps them in the False branch; §12.a Gate-8 FP test.
- A-L1 (classifier line numbers off by 2): §0 STAGE 3 corrected —
  classification lines 3806/3812/3817/3821; escalate lines
  3808/3814/3819/3823.
- A-L2 (D9 stall count 6 inline): moot with D9 cut.
- A-L3 (three "2"s): §5 KILL-SWITCH block explains the three constants
  and their relation.

**HIGH from Framing B**

- B-H1 (paste the literal Gate 4 before/after): §3-D-GATE4 literal block
  with the state-reset statements shown in the False branch.
- B-H3 (shadow byte-identical, not "don't call actuator"): §3-D-ESC-
  CONSUME enumerates the fields; AC-E byte-identical shadow; §12 site 15.
- B-H4 (pin branch STRICTLY BEFORE `:3880`): §3-D-ESC-CONSUME insertion
  point; §12 site 14.
- B-H5 (signature has NEITHER `triggered_by` NOR `engage_lockout_on_cap`):
  new D-ESC-SIG sub-deliverable §3; §13 files-touched.
- B-H6 (`durable` three-valued; NULL breaks streak): §3-D-ESC-CONSUME
  qualifying-failure definition; AC-E NULL negative control; §12 site 12.
  Same treatment for `restore_ok`.
- B-H7 (define divergence edge): LATCHED writer per §3-D-GATE4; AC-P
  latched divergence test; §12 site 8.

**MEDIUM from Framing B**

- B-M1 (`update_ac_ramp_event_fields` does not exist): NEW DAO in §1
  grep table and §13.
- B-M2 (`log_ac_ramp_event` returns None today, must return int): §13
  enumerates the change and confirms current callers safe.
- B-M3 (superseded plan internal inconsistency truncated-durable): §3
  D-SCORE Rev-2 ruling.
- B-M4 (Invariant P threshold mismatch): §2 P clarified — Gate-7
  threshold, NOT `AC_ACTIVELY_COOLING_KW_MIN`.
- B-M5 (`CONF_HVAC_AC_DURABILITY_WINDOW` two jobs): §5 row notes both.
- B-M6 ("no reset fires until D-SCORE live" is FALSE): §0 STAGE 4
  wording-discipline block corrects; D2 note in §3 updated (retire the
  false sentence).
- B-L3 (Probe A `== "idle"` vs `!= "cooling"`): §7.1 corrected.

**META-FINDING:** §14 addresses; every assertion carries a negative
control.

---

## 16. Flags on the Rev-2 brief

Two items:

1. **§0 STAGE 4 line number.** The Rev-2 brief cites the `if escalate:`
   at `:3891` and `_perform_hard_reset_escalation` definition at `:3925`
   — both are correct in the current tree (re-grepped 2026-08-22). No
   correction needed.
2. **`_perform_hard_reset_escalation` signature.** Today the function is
   `(self, zone, kwh_rate_now)`. The Rev-2 brief's H5 note that the
   signature has NEITHER new parameter is precisely correct; D-ESC-SIG
   adds them as keyword-only with defaults preserving current behaviour.

No other errors identified in the Rev-2 brief. Every finding taken as
correct; §15 records the resolutions.
