# PLANNING — Behavioral Write-Verification (Energy Coordinator)

**Status:** DRAFT (planner output; not built)
**Author:** ura-planner
**Date:** 2026-07-16
**Base:** develop @ ~ceed6c51 (v5.18.0 live)
**Target:** v5.19.0 (proposed)
**Tier recommendation:** **Tier 3** (see § Tier classification below)

## Executive summary

Today's `WriteVerifier` (`energy_write_verify.py`) is an **echo verifier**: it
compares the commanded value against a cloud-oracle *setting* (the reserve %
the Enphase cloud reports as the current profile). Three live incidents in
the last 36h prove echo is insufficient:

- **Incident #1 — 2026-07-15 (echo lied):** cloud oracle returned the
  commanded reserve (80) and `WriteVerifier` logged OK, while the Enphase
  app showed 50 and the battery physically discharged from 80% → 66%,
  *below the echoed floor*. ~5 kWh lost. The setting was ratcheted correctly
  in the cloud API's view; the hardware was not enforcing it.
- **Incident #2 — 2026-07-16 ~18:31 (self-heal against operator):** the
  reversion sweep read a stale `_desired_*` ledger (blind-hold branches
  return before `_result()` restamps) and treated the operator's manual
  de-escalation (reserve 10, CFG off) as a revert of the frozen 15:06
  attain intent (reserve 80, CFG on) — NM fired and the strategy
  re-dispatched reserve=80, forcing an operator disable. Fixed in v5.17.5
  via `_desired_stamped_at` freshness gate (`energy_write_verify.py:703-725`).
  **Any new re-dispatcher this cycle inherits this contract.**
- **Incident #3 — 2026-07-16 21:00 (pending never applies):** URA commanded
  reserve 10 at 21:00:07 (off_peak drain). Enphase integration health
  showed `battery_pending_reserve: 10`, `battery_profile_pending: true`,
  `battery_pending_age_s: 4061` vs `battery_pending_timeout_s: 900` —
  accepted, stuck pending 67+ min, never applied. Hardware kept enforcing
  the last-applied ratcheted reserve (~63). Battery held ~60 all night
  instead of draining. **No URA alarm fired.** This is the D2 acceptance
  fixture.

The gap: URA verifies **what the cloud API says the setting is**, not
**what the hardware does about it** and not **whether the write ever left
the pending queue**. This cycle adds two behavioral tripwires and one
observability surface.

---

## Institutional context verified

### Greps + prior-art enumeration

**Existing write-verify surface (REUSED verbatim — new work extends, does
not duplicate):**

- `energy_write_verify.py:115` `WriteVerifier` class — schedule + delayed
  compare + reversion sweep + NM latch. Constructor takes verify window
  seconds; RAM records per surface; per-surface NM trip-date latch keyed
  by `(surface, alert_type)` (`:981-1013`).
- `energy_write_verify.py:557` `reversion_sweep()` — the outer loop that
  will host D1 conduct verification (same "walk each surface once per
  decision cycle, never actuate" shape).
- `energy_write_verify.py:678-725` v5.17.5 D3 desire-freshness gate on
  `_desired_stamped_at` (600s threshold). **REUSED** — the D2 re-dispatch
  path this cycle proposes MUST route through this gate; a re-dispatch
  from a stale desire is exactly incident #2.
- `energy_write_verify.py:868-893` `_read_oracle_raw` / `_read_oracle_unit`
  — reused for reading the SOC/discharge witnesses in D1.
- `energy_write_verify.py:895-945` `_compare` — reused for reserve
  numeric compare (percent normalization, ±2 tolerance, unit-mismatch
  branch).
- `energy_write_verify.py:950-979` `_emit_anomaly` — reused; anomaly bus
  is `AnomalyEvent` via `database.save_anomaly_event`. Severity is
  `AnomalySeverity.WARNING` today for all write-verify emits — D1/D2 will
  likely need `ALERT` or `CRITICAL` (planner recommendation below;
  operator judgment call).
- `energy_write_verify.py:981-1013` `_maybe_fire_nm` — reused; per-day
  latch keyed on `(surface, alert_type)`. **NEW `alert_type` strings**
  proposed: `hardware_noncompliance` (D1) and `pending_write_stuck` (D2).
- `energy_write_verify.py:1102-1138` `get_status_attrs()` — reused; D3
  observability adds two new keys here.

**Battery strategy hooks (REUSED):**

- `energy_battery.py:263-282` `_last_reserve_level_desired` +
  `_desired_stamped_at` stamp block. **REUSED** for the desire-freshness
  gate on D2 re-dispatch.
- `energy_battery.py:4596-4632` `_result()` — writes desire ledger AND is
  the single-writer for dispatch. **D2 re-dispatch MUST re-enter this
  path** (not a side-channel write). Rationale: single-writer + fresh
  desired-stamp preserves I-D3.
- `energy_battery.py:861-895` `battery_power_w` — SIGNED W (positive =
  discharging). **REUSED as the discharging witness for D1.** Sign
  convention documented; do NOT re-implement.
- `energy_battery.py:~636-737` 3-tier SOC resolver + v5.17.5 A1 cloud
  fallback staleness gate. **REUSED via existing `soc` property (whatever
  its final name — planner did not read the full block).** D1 SOC reads
  MUST route through the resolver — a stale cloud SOC that already
  survived A1 is trustworthy for below-floor detection; a fully-blind
  (soc=None) branch means **abstain**, never alert.

**Config knob prior art (REUSED patterns):**

- `energy_const.py:301` `DEFAULT_WRITE_VERIFY_WINDOW_S: Final = 900` —
  same file/pattern for all new constants below.
- `energy_const.py:326` `WRITE_VERIFY_NM_SURFACES` tuple — new anomaly
  types added to `AnomalyType` enum are consumed via string; no new
  entries needed in the tuple.
- `energy_const.py:358-386` `CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR`
  — reserve floor pattern; D1 legal-exceptions list interoperates with
  this floor.

**Anomaly bus (REUSED):**

- `anomaly_event.py:39-113` `AnomalyType.POINT_IN_TIME`, `AnomalySeverity`
  enum. **PROPOSED NEW anomaly type strings** (passed as `type_str` on
  `AnomalyEvent`, not enum members — `WriteVerifier` already uses free
  strings like `"write_verification_failed"`, `"write_reverted"`,
  `"cloud_write_leg_unavailable"`, `"self_heal_starvation"`,
  `"write_verification_unit_mismatch"`, `"write_local_witness_divergence"`
  — new strings follow the same pattern):
  - `"hardware_noncompliance"` (D1)
  - `"pending_write_stuck"` (D2)

**Enphase pending-state exposure to HA — VERIFIED ABSENT:**

- Grep of `custom_components/universal_room_automation` for
  `battery_pending`, `pending_reserve`, `pending_timeout`,
  `profile_pending` returned **zero matches**. URA has no existing
  reader for the integration's health/pending attributes.
- The 2026-07-16 21:00 evidence (`battery_pending_reserve: 10`,
  `battery_profile_pending: true`, `battery_pending_age_s: 4061`) came
  from the Enphase/enphase_ev integration's **health/diagnostic attribute
  set**, not from any HA sensor entity that URA already consumes. Whether
  those fields are exposed as an `attributes` dict on some entity
  (e.g., a diagnostic sensor) vs only inside the integration's diagnostic
  dump is **UNCONFIRMED** and must be resolved as **B0-D2** (see § Measure
  Before You Build). If not exposed as HA state, D2 falls back to the
  inference path defined below (desired-vs-observed divergence age).

**Prior planning docs consulted:**

- `docs/planning/PLANNING_envoy_write_verification_and_redundancy.md` —
  the founding write-verify spec. Skimmed for invariant W-6 ("NEVER
  actuates"). **This cycle deliberately relaxes W-6 for D2 only** by
  adding a *single, deduplicated* re-dispatch via the existing single-
  writer path — see § Tier classification for why that relaxation is
  the tier-3 crux.
- v5.17.5 review record (`docs/reviews/code-review/v5_17_5_blind_hold_tier3.md`)
  — I-D3 contract fully absorbed; the D2 re-dispatcher MUST inherit the
  desire-freshness gate at `energy_write_verify.py:703-725`.
- v5.17.2 stale-retirement review — `STATUS_STALE` semantics for
  desire-matches-oracle records. D2 must respect this branch (don't
  re-dispatch a stale-retired command).

**Memory bodies pulled:**

- Battery SOC directive (2026-06-16): SOC must read from Envoy, not SPAN.
  D1 SOC reads MUST route through the existing 3-tier resolver — do NOT
  add a fourth SOC source.
- v5.17.5 pickup (blind-hold Tier 3): I-D3 invariant + `_desired_stamped_at`
  freshness are load-bearing across this whole cycle.
- Inclement arbitrage-WAIT floor gap (resolved v5.5.3): inclement
  `partial_hold_reserve_floor` is a legal below-floor state — see D1
  exception enumeration.

**Design docs read:**

- Battery strategy coordinator design doc (`docs/Coordinator/*.md` for
  Energy) — planner did **NOT** read end-to-end. **Judgment call flagged:**
  a builder must read it before implementing D2, because the "who owns
  the re-dispatch trigger" question (Verifier vs Strategy) may already
  be resolved there.

**Code locations surveyed end-to-end during scoping:**

- `energy_write_verify.py` (all 1139 lines)
- `energy_battery.py` (targeted reads: 700-750 SOC A1 gate; 861-895
  battery_power_w; 3934, 4596-4632 desired-stamp + `_result` single-
  writer; 861-870 discharge sign convention)
- `energy_const.py` (targeted reads: 216-386 CONF/DEFAULT block + surface
  tuple + reserve floor)
- `anomaly_event.py` (39-187 AnomalyType + AnomalySeverity enums)
- `QUALITY_CONTEXT.md` bug classes (read #1-#31 in this session; #38
  timer leaks, #48 flapping, #53 computed-but-not-consumed, #50 substrate
  clobber referenced from memory)

---

## Falsifiable invariant (Tier-3 style)

**I-BWV (Behavioral Write-Verify) — stated so D can try to break it:**

> For any surface s and window W:
>
> 1. **Conduct (I-BWV-1):** if URA's commanded floor for s at time t is F,
>    and for N consecutive decision ticks starting at t+W the resolver-
>    provided SOC is below F AND `battery_power_w > +ε` (discharging)
>    AND none of the legal-exception predicates hold, then EXACTLY ONE
>    `hardware_noncompliance` anomaly is emitted per standing episode and
>    at most one NM alert per (surface, "hardware_noncompliance") per
>    calendar day.
> 2. **Pending (I-BWV-2):** if URA commanded s=V at t and the divergence
>    between commanded=V and observed=oracle for s has age > P seconds
>    (`DEFAULT_PENDING_WRITE_STUCK_AGE_S`, planner-proposed 1200s = Enphase
>    900s timeout + 5-min tick margin), then EXACTLY ONE
>    `pending_write_stuck` anomaly is emitted per standing episode AND
>    AT MOST ONE re-dispatch occurs per episode, AND the re-dispatch
>    occurs only if `_desired_stamped_at` is fresh (< 600s, v5.17.5
>    contract) AND the strategy's current desire still equals V.
> 3. **Never fight the operator (I-BWV-3):** no code path in this cycle
>    re-dispatches when `_desired_stamped_at` is stale, when the record
>    is `STATUS_STALE`, or when `_current_desire(surface) != commanded`
>    (desire has moved on — could be operator or strategy re-decision).
>    This is a *hard* precondition on the D2 re-dispatch.

D's job (framing D below) is to enumerate every existing reserve/CFG/mode
emission and every existing sweep path — including pre-existing paths not
in the diff — and construct a legal-config repro that violates any clause
of I-BWV.

---

## Tier classification

**Recommendation: Tier 3** (four framing-disjoint reviews + orchestrator
mutation-anchored verification + operator checkpoint before deploy).

**Reasoning against splitting D1 out as detection-only Tier 2-DB:**

- D1 shares the outer sweep loop and the anomaly/NM emission machinery
  with D2 and with the pre-existing reverted/self-heal paths. A D1
  false-positive during a legitimate below-floor exception (blind-hold,
  Enphase backup discharge, inclement partial_hold_reserve_floor) fires
  a CRITICAL/HIGH NM. That is cost-and-safety-impacting (operator
  disables coordinator like 07-15 = ~5 kWh lost; grid-import into peak
  possible during disable).
- D2 relaxes the founding invariant W-6 ("NEVER actuates") by allowing
  exactly one re-dispatch. Re-dispatch is a **new write into the seam
  that fought the operator on 07-15**. Failure mode = one missed
  precondition = the coordinator is disabled by the operator again. This
  is the classic "one missed path = silent financial or comfort/safety
  loss" trigger.
- D2 threads `_desired_stamped_at` and `STATUS_STALE` — a shared
  primitive already consumed by the reversion sweep, the arbitrage
  reserve emitters, the attain path, the EVSE force-charge path, and
  the blind-hold entry guard. Same primitive, more consumers = classic
  Tier-3 shared-primitive shape.
- Operator standing policy (2026-06-08): use Tier 2-DB / three-framing
  as default for regression-prone work; escalate to Tier 3 when "one
  missed path" can silently break a sibling coordinator. Both apply.

**Framings (one MUST be adversarial-completeness):**

1. **A — Local correctness.** Per-site: SOC-below-floor arithmetic,
   discharge sign, ε deadband, N-tick counter, legal-exception evaluation.
   Percent normalization and unit-mismatch guard reused from `_compare`.
2. **B — State machine + cross-coordinator integration.** D2 re-dispatch
   routed through single-writer `_result()`; `_desired_stamped_at`
   freshness re-checked at the *re-dispatch site*, not just at
   scheduling; `STATUS_STALE` respected; interaction with reverted-sweep
   coalesce; interaction with self-heal N=3 latch (both fire? mutually
   exclusive? — planner recommends mutually exclusive: pending_write_stuck
   is a distinct alert_type and suppresses self_heal_starvation for the
   same commanded value).
3. **C — Test authority via real per-site source mutation.** Reviewer
   neuters ONE load-bearing site at a time (e.g., delete the
   `_desired_stamped_at` freshness re-check in the D2 re-dispatcher),
   runs suite, confirms a specific test fails, restores. A site whose
   bypass leaves suite green is untested = unacceptable.
4. **D — Adversarial completeness / diff-blind.** States I-BWV in
   falsifiable form. Enumerates ALL existing sites that (a) can dispatch
   reserve/CFG/storage_mode, (b) can cause SOC to legitimately fall below
   the commanded floor, (c) can cause `battery_power_w > 0` at
   below-floor SOC (backup discharge during grid outage, Enphase
   force-discharge for calibration, etc.), (d) can leave a pending write
   stuck (Enphase profile change queue, network gap, integration reload).
   D re-runs enumeration against pre-existing code, not just the diff.
   Every leak must come with a legal-config repro (values + state that
   trigger it).

**Standing operator-elevated policy applies** (2026-06-08): mark cycle
Tier 3 in the planning doc header (done); document reasoning in this
section (done).

---

## Measure Before You Build (B0 probes — mandatory before D1/D2 build)

Both deliverables are empirically gated. Cheap read-only probes must run
against the HA recorder + integration health before build. Findings
committed to this doc.

### B0-D1 — Below-floor conduct frequency probe

**Question:** How often does the battery legitimately sit below the
commanded reserve floor while discharging, and how long do those episodes
last? This sizes the N-tick threshold and the ε deadband.

**Method:** one-shot recorder query, ~24-72h window:

```
ssh ha "python3 -" < probe_below_floor.py
```

Reads `sensor.envoy_*_battery` (SOC), `sensor.envoy_*_current_battery_discharge`
(or `battery_power_w` equivalent), and the URA-side commanded reserve
history (from `_last_reserve_level` if persisted, else from the anomaly_log
`write_reverted`/`write_verification_failed` payloads, else from the
strategy sensor's attributes over time via the recorder).

**Output table:** for each episode where SOC < commanded_floor AND
discharge > 0:
- start time, end time, duration
- min SOC observed, max discharge W observed
- concurrent house_state / rate tier / storage_mode
- concurrent inclement partial_hold flag
- concurrent grid-outage / backup mode flag (if readable)

**Decision gates:**
- If duration histogram shows a mode < 5 min → N=3 ticks (15 min at
  default 5-min decision cadence) is too aggressive; raise to N=5 or add
  a magnitude gate (SOC below floor by ≥ M points).
- If episodes cluster on inclement `partial_hold_reserve_floor` days →
  the legal-exception list must include that predicate.
- If any episode shows discharge > 0 while SOC below floor AND no
  legal exception → this is exactly incident #1, and its duration sizes
  the alarm reasonableness.

### B0-D2 — Pending-state exposure + resolution probe

**Question A (existence):** does the Enphase / enphase_ev integration
expose `battery_pending_*` as HA state (entity attributes) that URA can
read, or only via the integration's diagnostic dump?

**Method:** `ha-mcp` state-attribute enumeration on the two candidate
entities (`sensor.envoy_*_battery`, `select.enpower_*_storage_mode`,
plus `number.enpower_*_reserve` and any `binary_sensor.*_pending`).
Alternatively: `state.attributes` dump of every entity in the
enphase_envoy device.

**Fallback if not exposed:** D2 uses **inference** — divergence between
commanded (from `_last_reserve_level_at` ledger) and observed oracle,
aged past a threshold, is the trigger. Inference is strictly weaker
than reading pending state (an inferred-stuck pending can be confused
with a real reversion), so B-framing MUST spec how the two coexist:
planner recommendation is *pending_write_stuck fires first if the
divergence is under the pending-timeout budget; write_reverted only
after the pending budget elapses and would suppress pending_write_stuck
for that episode*.

**Question B (steady state):** among recent commanded writes (48h), what
fraction resolved within the Enphase 900s pending timeout, and what was
the age distribution of stuck-pendings that did *not* resolve? This
sizes `DEFAULT_PENDING_WRITE_STUCK_AGE_S`.

**Method:** if pending attrs are exposed, recorder query on
`battery_pending_age_s` peaks. If not, recorder query on
divergence-age (commanded_at vs first oracle-tick where oracle==commanded).

**Decision gates:**
- If ≥95% of writes resolve within 900s → set the trigger at 1200s
  (planner default). If tail resolves within 30 min → 1800s.
- If Question A returns "not exposed" → document explicitly and proceed
  with inference path; D-framing enumerates the false-positive risks.

---

## Deliverables

### D1 — Hardware conduct verification (headline)

**What:** in `WriteVerifier.reversion_sweep()` (or a new sibling
`conduct_sweep()`), after the existing per-surface sweep completes, add
a **reserve-surface conduct check**:

Trigger condition (all must hold for N consecutive ticks):
- `commanded_floor = _last_reserve_level` (existing ledger)
- `soc = _resolve_soc()` (existing 3-tier resolver; abstain if None)
- `discharge_w = battery_power_w` (existing signed prop; abstain if None)
- `soc < commanded_floor - CONF_CONDUCT_SOC_DEADBAND_PCT` (default 2%)
- `discharge_w > CONF_CONDUCT_DISCHARGE_EPSILON_W` (default 100 W)
- NO legal exception holds (see enumeration below)

Response (D1 detection-only in this cycle; auto-remediation deferred
per Marginal-Benefit Decomposition — see § Non-goals):
- Emit `hardware_noncompliance` anomaly (POINT_IN_TIME, severity
  **ALERT** — planner recommendation; operator judgment: CRITICAL is
  reserved for true emergencies per QC #16, and this is a
  detection-serious-but-not-emergency case, so ALERT is the right
  rung; if operator disagrees, one-line change).
- NM alert once per day per `(surface, "hardware_noncompliance")`.
- Update `get_status_attrs()` D3 keys.
- Reset N counter on any tick where trigger condition fails.

**Legal exceptions to enumerate (D1 must NOT fire when any hold):**

1. **Inclement partial_hold:** `CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR`
   in effect (v5.5.3 lesson) — the actual floor URA is enforcing is
   lower than the commanded reserve number.
2. **Enphase backup mode:** grid-outage discharge is expected below any
   floor. Read via `binary_sensor.envoy_*_grid_status` (or equivalent —
   B0-D1 probe confirms entity id).
3. **Enphase self-consumption / manual override:** if `storage_mode`
   commanded is `self_consumption` and the strategy is intentionally
   allowing drain (arbitrage_wait etc.), floor-below is legal.
   Planner note: this exception is broad and may swallow real defects;
   B-framing must scrutinize.
4. **Blind-hold branch:** SOC resolver returned None on all tiers (v5.17.5
   BH1). Abstain, do not alert. This is automatic (soc is None → early
   return).
5. **Recently commanded (within verify window):** `now - commanded_at <
   verify_window_s` (900s). Prevents racing the initial write.
6. **STATUS_STALE record:** desire has moved on — commanded_floor is no
   longer authoritative.
7. **Recorder / entity unavailable transient:** if either SOC or
   discharge reads unavailable/unknown for the tick, treat as abstain
   (do not reset counter, do not increment).

**Numbers Get Knobs (D1):**

| Knob | Rung (per Numbers Get Knobs ladder) | Default | Why |
|---|---|---|---|
| `CONF_CONDUCT_SOC_DEADBAND_PCT` | Module constant (`energy_const.py`) | 2.0 % | Aligns with existing ±2 dispatch deadband (`_compare`, energy_write_verify.py:929). Safety bound; change should require review. |
| `CONF_CONDUCT_DISCHARGE_EPSILON_W` | Module constant | 100 W | Same threshold class as v4.3.4 battery-drain (< -100 W was the historic threshold). Change requires review. |
| `CONF_CONDUCT_N_TICKS` | Module constant | 3 | Sized by B0-D1 probe. Change requires review because too-low = false positives; too-high = late alarm. |
| `CONF_CONDUCT_ENABLED` | Options flow (feature enable) | True | Kill switch. Operator-settable; disable feature without code change. |

Rationale for placement: no live-tuning entities (Number/Select) here —
the operator does not observe below-floor conduct often enough to warrant
a dashboard slider. Options flow enable is enough; adjust in code if the
probe shows deadband needs revising.

### D2 — Pending-write watchdog

**What:** in `WriteVerifier.reversion_sweep()`, for each surface, after
the divergence tests but before the reverted branch, add a
**pending-stuck check**:

Trigger condition (all must hold):
- Divergence age (`now - commanded_at`) > `DEFAULT_PENDING_WRITE_STUCK_AGE_S`
- Divergence age < `DEFAULT_PENDING_WRITE_STUCK_ABANDON_AGE_S` (upper
  bound; past this we're in reverted territory, not stuck-pending)
- `_desired_stamped_at` fresh (< 600s; **REUSED gate** from v5.17.5)
- `_current_desire(surface) == commanded` (strategy still wants what
  URA commanded — not stale, not moved on)
- Record is not `STATUS_STALE`
- Pending-state signal (if B0-D2A returns exposed): `pending == True`
  AND `pending_age_s > pending_timeout_s`. If not exposed: divergence
  age alone.
- No re-dispatch has occurred for this episode (per-surface latch keyed
  on `commanded_at`)

Response:
- Emit `pending_write_stuck` anomaly (POINT_IN_TIME, severity ALERT).
- Trigger EXACTLY ONE re-dispatch by **calling `_result()` with a flag
  that forces a fresh dispatch of the current desire on this surface**.
  Do NOT write directly from `WriteVerifier`. Do NOT bypass the single-
  writer path. Do NOT restamp `_desired_stamped_at` from the Verifier
  side. The re-dispatch is a "please try again" nudge to the existing
  single-writer, not a shadow write. Builder + B-framing: this is the
  load-bearing seam of the entire cycle.
- NM alert once per day per `(surface, "pending_write_stuck")`.
- Set per-episode re-dispatch latch; clear on episode close (oracle
  matches OR divergence age passes ABANDON threshold → hand off to
  reverted branch OR `commanded_at` changes → new episode).
- Suppress `self_heal_starvation` counter for the same commanded value
  during a pending_write_stuck episode (planner recommendation; the two
  represent overlapping conditions; the more specific alarm wins).

**Numbers Get Knobs (D2):**

| Knob | Rung | Default | Why |
|---|---|---|---|
| `DEFAULT_PENDING_WRITE_STUCK_AGE_S` | Module constant | 1200 s | Enphase pending timeout (900s) + one 5-min decision tick of slack. Sized by B0-D2B probe. |
| `DEFAULT_PENDING_WRITE_STUCK_ABANDON_AGE_S` | Module constant | 3600 s | Upper bound before handoff to reverted-sweep. Change requires review — sets the seam between two alarm classes. |
| `DEFAULT_PENDING_WRITE_STUCK_REDISPATCH_MAX` | Module constant | 1 per episode | Hard cap. Change requires review — increasing this reopens the incident-#2 shape. |
| `CONF_PENDING_WATCHDOG_ENABLED` | Options flow | True | Kill switch. |

Rationale: no live-tuning entities. The re-dispatch cap is a safety
number (change = review). The timeout aligns with Enphase's own timeout
(change = review, because it depends on integration behavior).

### D3 — Observability

**What:** extend `get_status_attrs()` return dict with:

- `hardware_noncompliance_state`: per surface:
  - `active: bool` (currently in noncompliant episode)
  - `consecutive_ticks: int` (progress toward N)
  - `soc_observed`, `commanded_floor`, `discharge_w_observed`
  - `episode_started_at`, `last_evaluated_at`
  - `abstain_reason` (None if evaluated; else one of: soc_none,
    discharge_none, within_verify_window, exception_backup,
    exception_partial_hold, stale_record, ...)
- `pending_write_stuck_state`: per surface:
  - `active: bool`
  - `commanded_at`, `commanded_value`, `oracle_value`
  - `divergence_age_s`
  - `redispatch_fired: bool`
  - `desire_stamp_age_s`

Consumed on the existing battery strategy sensor
(`sensor.ura_energy_coordinator_battery_strategy`) attributes via
whatever plumbing already surfaces `last_verified_write_*` from
`get_status_attrs()`.

### Non-goals (explicit; per Marginal-Benefit Decomposition)

- **No D1 auto-remediation.** Detect + alert only. The simplest version
  captures the incident-#1 value (visibility + alarm = operator response
  time drops from "hours or never" to "one NM ping"). Auto-remediation
  (e.g., trip storage_mode → self_consumption; force-cycle the reserve;
  power-cycle the Envoy) introduces categorically new writes into the
  same seam that fought the operator on 07-15, and its marginal benefit
  (minutes vs one-NM-cycle response) does not clearly pay for the
  ingredient risk. Park the idea with the trigger: "if D3 attrs show
  ≥3 hardware_noncompliance episodes/month AND operator response was
  the bottleneck each time, revisit."
- **No new persistence.** D1/D2 state is RAM; no new DB write path
  (the incident-#0 v5.0.0-v5.2.1 rollback wound is deep). Anomaly emits
  and NM alerts are per-day-latched, matching existing pattern.
- **No new schema migration.** New anomaly type strings are free-form
  in `AnomalyEvent.type`; no `AnomalyType` enum changes required.

---

## Acceptance criteria

### D1 acceptance

- **Verify (unit):** given commanded_floor=15, soc=10, discharge_w=+200,
  no legal exception, for N=3 ticks → exactly one anomaly emitted +
  NM fired once. Test: `test_conduct_below_floor_fires_once`.
- **Verify (unit):** same setup but tick 2 shows discharge_w=-500
  (charging) → counter resets, no anomaly. Test:
  `test_conduct_counter_resets_on_charge`.
- **Verify (unit):** legal exception `partial_hold_reserve_floor` in
  effect → no anomaly regardless of tick count. Test:
  `test_conduct_partial_hold_exempt`.
- **Verify (unit):** soc=None (blind) → abstain, no anomaly, counter not
  advanced. Test: `test_conduct_blind_abstains`.
- **Sensor:** `sensor.ura_energy_coordinator_battery_strategy` attributes
  include `hardware_noncompliance_state` with per-surface dict.
- **Test:** test suite covers each of the 7 legal-exception predicates
  with a mutation-anchored assertion (removing the predicate check makes
  a specific test fail — C-framing verifies).
- **Live:** post-deploy, force a synthetic scenario if operator wants
  (temporarily raise commanded floor via arbitrage attain and observe
  the D3 attr populate without alarm — expected: legal exception #5
  within-window suppresses). Real hardware-noncompliance is not
  reproducible on demand; D1 rides organic incidents.

### D2 acceptance

- **Verify (unit) — 21:00 fixture replay:** commanded=10 at t=21:00:07,
  oracle=63, `now - commanded_at = 4061s`, `_desired_stamped_at` fresh,
  `_current_desire == 10`, no prior re-dispatch → exactly one
  `pending_write_stuck` anomaly + one NM + one re-dispatch call to
  `_result()`. Test: `test_pending_stuck_2026_07_16_21_00_replay`.
- **Verify (unit):** same fixture but `_desired_stamped_at` stale
  (blind-hold) → no anomaly, no NM, no re-dispatch (I-D3 preserved).
  Test: `test_pending_stuck_stale_desire_stands_down`.
- **Verify (unit):** re-dispatch fires; on the next tick, if oracle still
  disagrees, no second re-dispatch (episode latch). Test:
  `test_pending_stuck_max_one_redispatch_per_episode`.
- **Verify (unit):** if `_current_desire` differs from commanded (operator
  changed reserve; desire has moved) → no anomaly, no re-dispatch;
  record retires to STATUS_STALE per v5.17.2 path. Test:
  `test_pending_stuck_desire_moved_retires`.
- **Verify (mutation, C-framing):** remove the `_desired_stamped_at`
  freshness check from D2 → `test_pending_stuck_stale_desire_stands_down`
  MUST fail. If any test still passes with that check removed, the site
  is untested. Deliverable-blocking.
- **Sensor:** `pending_write_stuck_state` attr populated during episode.
- **Live:** post-deploy, on the next 21:00 off_peak drain command,
  D3 attr `pending_write_stuck_state.commanded_at` matches the dispatch
  timestamp and `divergence_age_s` grows tick-over-tick if pending
  actually stalls. If pending resolves (normal path), attr stays
  `active: false`.

### D3 acceptance

- **Verify:** `get_status_attrs()` returns both new keys with correct
  shapes even when no episode is active.
- **Live:** attributes visible on
  `sensor.ura_energy_coordinator_battery_strategy` post-restart.

---

## Open judgment calls for the operator

1. **D1 severity — ALERT or CRITICAL?** Planner recommends ALERT per QC
   #16 (CRITICAL reserved for true emergencies). Below-floor discharge
   is money-loss, not safety. Operator call: if you want the CRITICAL
   NM bypass-quiet-hours behavior, mark it CRITICAL — but then D-framing
   MUST specifically scrutinize the legal-exception list, because any
   false positive during quiet hours is a bigger cost.
2. **Legal exception #3 (self_consumption + intentional-drain) — how
   broad?** Planner flagged this exception as potentially swallowing
   real defects. Operator call: (a) keep broad (all self_consumption
   with strategy state ∈ {arbitrage_wait, off_peak_drain} is exempt), or
   (b) narrow (only exempt when the intentional-drain strategy explicitly
   sets a lower floor via `partial_hold_reserve_floor`)? B-framing will
   scrutinize regardless; but planner needs the choice before writing
   the exception predicate.
3. **B0-D2A result unknown until probe runs.** If Enphase pending attrs
   are NOT exposed to HA, D2 uses inference (divergence-age). This is
   weaker than reading pending state. Operator confirm: proceed with
   inference-only D2 (planner recommendation: yes — incident #3 is
   detectable purely from divergence age; pending attrs would be a
   confidence boost, not a requirement).
4. **D2 re-dispatch — via `_result()` call or via a new
   `force_redispatch(surface)` method on `BatteryStrategy`?** Planner
   recommends the latter: a narrow, single-purpose entrypoint on
   `BatteryStrategy` that (a) checks the same preconditions, (b) calls
   the existing dispatch code path with the current desire, (c)
   restamps `_desired_stamped_at`. This is architecturally cleaner than
   piggybacking on `_result()`, but it is one more site consuming the
   `_desired_stamped_at` primitive — Tier-3 shared-primitive risk.
   Operator call at build time.
5. **Coordinator design doc not read end-to-end by planner.** Builder
   MUST read the Energy coordinator design doc before implementing D2's
   re-dispatch trigger. If the design doc already specifies how external
   triggers can request a re-dispatch, use that mechanism.

---

## References

- `custom_components/universal_room_automation/domain_coordinators/energy_write_verify.py`
- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py:263-282, 700-750, 861-895, 3934, 4596-4632`
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py:216-386`
- `custom_components/universal_room_automation/domain_coordinators/anomaly_event.py:39-187`
- `docs/reviews/code-review/v5_17_5_blind_hold_tier3.md`
- `docs/planning/PLANNING_envoy_write_verification_and_redundancy.md` (founding spec)
- `docs/QUALITY_CONTEXT.md` — bug classes #16 (CRITICAL bypass), #38 (timer leaks), #48 (flapping), #53 (computed-not-consumed)
- `CLAUDE.md` — Tier 3 protocol, Measure Before You Build, Marginal-Benefit Decomposition, Numbers Get Knobs

## CORRECTION ADDENDUM (2026-07-16 ~22:45, orchestrator)

Incident #3 as originally described ("reserve 10 commanded at 21:00, stuck
pending 67+ min, hardware on stale ratchet ~63") is PARTIALLY DISCREDITED
after tracing the full commanding trail:

- URA's actual command at 21:06 was **61** via `evse_battery_hold`
  (freeze-at-SOC while EV charges off-peak — correct, deliberate,
  philosophy-compliant). `current_commanded_reserve: 61`,
  `last_verified_write_reserve_soc: {commanded: 61, status: ok}`.
  Hardware compliant (envoy-reported reserve 61). No stuck write proven.
- The `battery_pending_reserve: 10 / pending_age 4061s` artifact in the
  enphase_ev integration health dump remains UNEXPLAINED — B0-D2 must
  determine what that pending state actually tracks before it is used as
  a watchdog signal. Do NOT treat the 21:00 timeline as the D2 acceptance
  fixture until the probe explains the artifact.
- The Enphase APP showed 15% while hardware enforced 61 — the app lag /
  app-vs-hardware divergence is real and remains motivating evidence for
  D1/D3 (three-way divergence surfacing), but tonight's hardware conduct
  was compliant with URA's command.
- NEW D3 requirement from tonight's operator confusion: surface the
  three-way trail as one attr block — commanded (URA desire + hold owner),
  hardware-enforced (envoy-reported), cloud/app view — with divergence ages,
  so the commanding trail is legible without recorder archaeology.
- Incidents #1 (07-15 below-floor discharge) and the app-vs-API divergence
  stand unmodified as D1 motivation.
