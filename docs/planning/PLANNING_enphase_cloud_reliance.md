# PLANNING — Enphase Cloud-Reliance Hardening + enphase_ev v4.0.0 Upgrade

**Status:** DRAFT (planner output; not built)
**Author:** ura-planner
**Date:** 2026-07-16
**Base:** develop tip (v5.18.0 live)
**Target:** v5.20.0 (proposed — sequenced AFTER v5.19.0 behavioral write-verify)
**Tier classification:** **Tier 3 — operator-elevated** ("super high risk").
Review protocol: FOUR framing-disjoint reviews (A local correctness / B
integration + state / C test authority via real per-site source mutation /
D adversarial completeness) + **operator checkpoint before deploy**, per
CLAUDE.md Tier 3.

The elevation is justified independently of the trigger checklist:
- The cloud oracle is the WRITE authority for every battery control action
  (reserve, storage mode, charge_from_grid). A silently-broken read of a
  removed attribute, or a silently-missing entity after upgrade, does not
  just fail one decision — it poisons the entire hourly control loop for
  hours before the next telemetry-side alarm.
- The upgrade AND the reliance hardening both cross the exact
  cross-coordinator seam (energy_battery ↔ energy_pool ↔ energy_write_verify
  ↔ EVSE) that the Tier 3 protocol was designed for.
- Three live incidents this week (07-15 echo-lie, 07-16 15% vs 61 hardware,
  07-16 25-pp SOC divergence) each expose a different failure mode of the
  reliance. A cycle that touches ALL of them is by construction wide-blast.

---

## Executive summary

URA's battery control has been cloud-first by standing decision since
v5.16.x (local Envoy API on fw 8.3.x accepts writes and ignores them;
demoted to telemetry witness). The cloud path runs through the HACS
`barneyonline/ha-enphase-energy` (`enphase_ev`) integration. **v4.0.0 is
pending upgrade**, and staying behind carries a hard-fail risk — Enphase
has retired the Entrez token mint that older versions depend on, so the
write path can go silent at any time from an auth-side change URA cannot
detect.

Concurrently, three live incidents this week proved that URA's cloud
reliance is under-instrumented on the *read* side too:
- **07-15:** cloud reserve echo returned the commanded value while
  hardware discharged below floor.
- **07-16 ~15%vs61:** cloud app showed 15% reserve while hardware enforced
  61 (~70 min settings lag).
- **07-16:** cloud aggregate SOC 86.8% vs local 60-62% at the same
  instant — a **25-point divergence** on the 3-tier SOC resolver's
  fallback tier (`energy_battery.py:647` three-tier resolver comment).
- **07-16 21:50 / 22:46 / 23:04:** three local Envoy telemetry dropouts
  in one evening. During any dropout window, cloud is the ONLY SOC
  source — the upgrade must not overlap one.

This cycle has two halves:
1. **enphase_ev v4.0.0 upgrade** (D0 + D1) — measurement-first (per
   CLAUDE.md "Measure Before You Build"), gated on a hand-built manual
   fixture (per "hand-build the fixture before automating").
2. **Reliance hardening** (D2 + D3) — divergence detection, tier-disagreement
   observability, and a judged-scope decision on the local dropout posture.

The falsifiable invariant across the whole cycle is stated below and
functions as the D reviewer's target.

---

## Falsifiable invariant (Tier 3 requirement)

> **INV-CLOUD:** No URA decision path (battery strategy, write-verify,
> EVSE control, SOC resolver) reads an `enphase_ev` surface — entity or
> attribute — that is absent from the D0 fixture table. Post-upgrade,
> every fixture row's live value verifies within 1 hour of restart.
> Additionally, when cloud-aggregate SOC and local-primary SOC diverge
> by more than the configured threshold (default 10 percentage points)
> for more than the configured dwell (default 5 minutes), URA raises
> an NM alert AND surfaces a divergence attribute on
> `sensor.ura_energy_coordinator_battery_strategy` — regardless of which
> resolver tier is currently serving the decision loop.

The D reviewer's job is to falsify this invariant on **the entire
consumption surface** (not just the diff): find one code path that reads
an `enphase_ev` surface not in the D0 table, or one legal state where the
25-pp divergence goes silent.

---

## Institutional context verified

### Greps run + results

**Cloud oracle consumption surface (enumerated 2026-07-16):**

| Entity id / attribute | Consumer file:line | REUSED? |
|---|---|---|
| `number.iq_battery_hacs_battery_reserve` | `energy_const.py:291` `DEFAULT_CLOUD_RESERVE_ORACLE_ENTITY` — read by write-verify oracle + battery strategy | REUSED |
| `switch.iq_battery_hacs_charge_battery_from_grid` | `energy_const.py:293` `DEFAULT_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY` — read via `_get_entity("charge_from_grid", ...)` `energy_battery.py:3107,3493` | REUSED |
| `sensor.iq_battery_hacs_battery_overall_charge` | `energy_const.py:299` — 3-tier resolver cloud fallback tier (`energy_battery.py:647` comment) | REUSED |
| `select.iq_gateway_hacs_system_profile` | Storage-mode cloud oracle (per AUDIT_envoy_telemetry_pairing_manual.md §1); write-verify surface `WRITE_VERIFY_SURFACE_STORAGE_MODE` at `energy_const.py:325` | REUSED |
| `sensor.enphase_cloud_hacs_current_production_power` [W] | AUDIT §2 T2 — candidate solar failover (not yet wired) | REUSED (audit) |
| `sensor.enphase_cloud_hacs_current_battery_power` [W] | AUDIT §2 T3 — sign UNVERIFIED | REUSED (audit) |
| `sensor.enphase_cloud_hacs_current_grid_power` [W] | AUDIT §2 T4 — semantic mismatch (F1 EVSE exclusion) | REUSED (audit) |
| `sensor.iq_battery_hacs_battery_available_energy` | AUDIT §2 T6 — not consumed today | REUSED (audit) |
| lifetime `*_site_*` counters | AUDIT §2 T8–T12 — delta-only, not consumed today | REUSED (audit) |
| STATE-ATTRIBUTE reads on any `iq_battery_hacs_*` / `enphase_cloud_hacs_*` entity | **`energy_battery.py` `.attributes.get(...)` grep at lines 688, 775, 898, 924, 2536 all read `unit_of_measurement` only** — no other cloud-oracle attribute is consumed. Confirms D0 attribute-surface is trivially small: unit metadata only. | REUSED (verified NONE beyond unit_of_measurement) |
| `battery_pending_reserve` / `battery_profile_pending` / `battery_pending_age_s` / `battery_pending_timeout_s` (Enphase integration health attributes) | NOT consumed by URA today (grep `battery_pending\|profile_pending` returned no matches). Consumed by **write-verify v5.19.0** cycle only. Out of scope here. | N/A |
| Enpower-serial-scoped entities (`select.enpower_..._storage_mode`, `number.enpower_..._reserve_battery_level`, `switch.enpower_..._grid_enabled`, `switch.enpower_..._charge_from_grid`) | `energy_const.py:221-224` DEFAULT_*_ENTITY constants — LOCAL Enpower, not enphase_ev cloud. Cloud oracle overrides via `_cloud_first` map (`energy_battery.py:303,305`). Grid switch has NO cloud analogue per AUDIT §1 GAP row. | REUSED |

**Prior planning docs consulted:**
- `docs/planning/PLANNING_behavioral_write_verify.md` (v5.19.0) — full read.
  Owns conduct verification (D1), pending-write stuck detection (D2 of that
  cycle), three-way commanded/hardware/app trail (D3 of that cycle). This
  cycle does NOT duplicate; it interfaces at the read-surface layer.
- `docs/planning/AUDIT_envoy_telemetry_pairing_manual.md` — full read. It
  IS the D0 fixture starting point for the telemetry surface; this cycle
  extends it to the control surface (already covered in AUDIT §1) and
  admits the AUDIT verdicts as-is.
- `docs/planning/PLANNING_envoy_write_verification_and_redundancy.md`
  (referenced in `energy_battery.py:284`, `energy_write_verify.py:5`) —
  skim; canonical write-verify invariant W-6 lives there.

**Memory bodies pulled:**
- `project_battery_soc_envoy_not_span.md` — operator directive: SOC =
  Envoy, NOT SPAN. Relevant to D2 divergence detector: local is
  authoritative, cloud is the witness that must agree to a threshold.
- `project_v5_5_0_inclement_weather_shipped.md` — `sensor.ura_energy_coordinator_battery_strategy` is the canonical strategy attrs sensor; D2's new attributes belong there.

**Design docs read:**
- `docs/Coordinator/ENERGY.md` if it exists — planner assumes reader
  consults for coordinator invariants. (Not re-quoted here.)

**Code locations surveyed end-to-end during scoping:**
- `energy_const.py` (defaults, CONF constants, envoy validation) — full.
- `energy_battery.py` around `_cloud_first` dispatch (`:303-305`), the
  3-tier resolver (`:636-737` region indexed by comment `:647`), storage
  mode probe (`:952-996`), reserve/charge_from_grid actuation
  (`:3092-3230, 4410-4620`).
- `energy_write_verify.py` — behavior verified in the v5.19.0 planning
  doc; not re-read end-to-end here.
- `energy.py` around envoy availability tracking (`:2353-2470`, `:7332-7334`).

### Bug classes to guard against (from QUALITY_CONTEXT.md)

- **#7 Stale Data Source Driving Development Decisions.** Directly
  applicable. The 25-pp SOC divergence and the 70-min settings lag are
  BOTH stale-data-source symptoms where the stale source drives the
  decision. D2 exists to make the staleness observable + trippable.
- **#53 Computed-but-not-consumed** (implied by Tier 3 elevation) —
  the reviewer D pass must confirm every fixture-table entry is
  actually READ from at least one code path (dead cloud reads that we
  think we depend on but don't = latent removal-safety we don't know we
  have; more importantly, live cloud reads NOT in the fixture = the
  invariant-breaking case).
- **#58 Centralized subscription loses per-entry lifecycle hooks** —
  the upgrade may re-register entities under new unique_ids; if any
  subscription is keyed on entity_id, a reload could silently orphan it.
  D0 must verify entity_ids are preserved across the upgrade.

---

## Measure Before You Build

Trigger checklist:
- Does a deliverable consume data whose freshness/accuracy is assumed? **YES** (every cloud read).
- Would the design change if a divergence number were 10× worse? **YES** (D2 threshold).
- Is there ≥24h of relevant history already in the recorder? **YES** — 07-15/07-16 divergence + dropout events are in the recorder.
- Is the plan proposing runtime instrumentation to learn something a one-shot script could answer? **D0 IS the offline probe. D2 is runtime only because the divergence must be *acted on* live.**

Verdict: D0 (fixture) MUST run before D1/D2/D3 are scoped in detail.
D0 is a **read-only recorder + WebFetch probe**, not code.

---

## Deliverables

### D0 — Consumption-Surface Audit + Manual Fixture (FIRST, gates all others)

**What.** Produce a hand-built manual fixture table:
`docs/planning/AUDIT_enphase_ev_v4_consumption_surface.md`. One row per
consumed surface (entity_id OR attribute-on-entity), with columns:

| URA role | Consumed surface | Consumer file:line | Present in v3.x today? (live sample) | Present in v4.0.0? (from release notes + repo source) | Verdict | Notes |

Coverage requirement (exhaustive; use greps from Institutional Context §1
as the seed, plus the following surfaces to prove NEGATIVE coverage):

- All entity_ids listed in the Institutional Context table above.
- Any `.attributes.get(...)` call whose target entity resolves to an
  `enphase_ev`-domain entity. (Live grep already confirms `unit_of_measurement`
  is the only one today — the fixture must state this NEGATIVE explicitly.)
- Any service call to `enphase_ev.*` (grep for `service.*enphase_ev`). If
  any exist, they enter the fixture; if none, that NEGATIVE is stated.
- Battery Scheduler sensors CFG / DTG / RBD — v4.0.0 removes when
  scheduler disabled. If URA does NOT consume, state NEGATIVE explicitly
  (this row exists specifically to prove non-consumption).
- Grid Mode entities / `request_grid_toggle_otp` / `set_grid_mode` service.
  AUDIT §1 already notes URA has no working grid-disconnect control via
  cloud; row confirms.
- Any high-cardinality device-metadata attributes v4.0.0 removes from
  state attributes. State NEGATIVE explicitly.

**Method (per CLAUDE.md corollary — hand-build the fixture BY HAND).**

1. Grep the `custom_components/universal_room_automation/` tree for every
   `enphase_ev`-domain reference (entity_id fragments: `iq_battery_hacs`,
   `iq_gateway_hacs`, `enphase_cloud_hacs`, and every DEFAULT_CLOUD_*_ENTITY
   / DEFAULT_*_ENTITY constant defined in `energy_const.py:221-299`).
2. Cross-reference each hit against `enphase_ev` v3.x live registry via
   `ssh ha "python3 -" < script.py` reading `.storage/core.entity_registry`.
3. Cross-reference each hit against `enphase_ev` v4.0.0 by
   `WebFetch`ing the release notes and `gh api` reading the tag's
   `entity_description` / `select`/`number`/`switch`/`sensor` platform
   sources for the v4.0.0 tag. Cite line numbers.
4. For every "PRESENT / REMOVED / RENAMED" verdict, cite BOTH the URA
   consumer file:line AND the upstream file:line (or release-notes bullet).
5. Sign the fixture "audited by <planner> on <date> against v4.0.0 tag
   <sha>". The fixture is the acceptance oracle for D1.

**Acceptance criteria (D0):**
- **Verify:** the fixture has one row per URA consumer of an
  `enphase_ev`-domain surface. Every consumer file:line found by grep in
  Institutional Context §1 appears in the table.
- **Verify:** every row has a verdict of PRESENT / RENAMED / REMOVED /
  ATTRIBUTE-REMOVED / NEGATIVE-CONFIRMED, with an upstream citation.
- **Verify:** at least the following NEGATIVES are stated explicitly (not
  just omitted): Battery Scheduler CFG/DTG/RBD, Grid Mode entities,
  `request_grid_toggle_otp` service, `set_grid_mode` service, all
  high-cardinality device-metadata attributes v4.0.0 removes.
- **Live:** (D0 output is a doc, not code — no live criterion.)
- **Gate:** if ANY row's v4.0.0 verdict is REMOVED and its Consumer
  count > 0, the upgrade is HOLD until a D1.1 remediation is scoped
  (either replace the consumer with a supported surface, or accept
  degradation with explicit fallback).

---

### D1 — Upgrade Execution Runbook

**What.** A step-by-step deploy runbook, filed at
`docs/runbooks/RUNBOOK_enphase_ev_v4_upgrade.md`, executed by the operator
under Shipwatch coverage.

**Steps (contract):**

1. **Pre-upgrade snapshot.** For every fixture row with a live entity,
   record the current state + `unit_of_measurement` + `last_updated` into
   the runbook (paste block). This is the "before" side of the diff.
2. **Timing gate — NEVER during a local Envoy dropout.** Verify
   `sensor.ura_energy_envoy_status` is `ok` (not `degraded` / `OFFLINE`)
   AND `_envoy_unavailable_count == 0` (`energy.py:2364, 7333`) for at
   least 15 min before initiating the HACS update. Rationale: during a
   local dropout the cloud SOC (`sensor.iq_battery_hacs_battery_overall_charge`)
   is the ONLY input to the 3-tier resolver; a cloud restart on top of
   that would leave URA truly blind. Evidence: 3 dropouts on 2026-07-16
   evening (21:50 / 22:46 / 23:04).
3. **HACS update to v4.0.0.** No URA changes concurrent.
4. **Post-upgrade oracle-health pass (within 15 min):**
   - Every fixture-PRESENT row's entity resolves in HA (`hass.states.get`
     non-None + state not `unavailable`).
   - The 3-tier SOC resolver's canonical output attribute on
     `sensor.ura_energy_coordinator_battery_soc` (or equivalent) is
     non-None and within 3 pp of local Envoy SOC.
   - `WriteVerifier` oracle reads are readable: `_read_oracle_raw` for
     each of `reserve`, `storage_mode`, `charge_from_grid` returns a
     value (not None) for the cloud oracle entity.
5. **Benign write round-trip (one, on a no-op).** With hardware in a
   known state, command the SAME storage_mode + reserve + CFG that are
   already in effect (idempotent no-op from hardware's perspective; write
   still routes through the cloud actuation path). Verify write-verify
   OK within the configured window.
6. **Rollback path.** HACS Downgrade to the last-known-good version
   (recorded in step 0). No URA code rollback required. Rollback trigger:
   any fixture-PRESENT row that reads `unavailable` for > 15 min post-restart
   AND is on the write path.

**Acceptance criteria (D1):**
- **Verify (pre-deploy):** runbook contains a pre-upgrade snapshot block
  ready to fill.
- **Verify (post-deploy, LIVE):** operator + Shipwatch execute steps
  1-5; each step's PASS / FAIL is written into the README validation
  table per CLAUDE.md ("Record Live Validation Back Into the README").
- **Live:** within 60 min of upgrade, every D0 fixture-PRESENT row has
  a live value observed and recorded in the README.
- **Live:** one benign write round-trip observed as write-verify OK.

---

### D2 — Reliance Hardening (Divergence + Tier-Disagreement Observability)

**What.** Version-independent robustness. Two behaviors, one observability
surface. Owned by `energy_battery.py` (SOC-resolver / strategy path),
NOT by `energy_write_verify.py` (that lives in v5.19.0 write-verify).

**Overlap disclaimer.** The v5.19.0 write-verify cycle owns:
- Conduct verification (commanded vs hardware).
- Pending-write stuck detection (`battery_pending_*` attribute reads).
- Three-way commanded/hardware/app trail.

D2 here owns telemetry-side divergence between **the cloud SOC oracle
and the local Envoy SOC**, i.e. the read-side witness disagreement — a
different failure mode. The two cycles share no reads and no writes;
they interface only via `sensor.ura_energy_coordinator_battery_strategy`
attribute namespace (both add attributes; names must not collide).
Sequence: v5.19.0 ships first, this cycle follows.

**Sub-deliverables:**

**D2.1 — SOC divergence detector.** In the 3-tier SOC resolver
(`energy_battery.py:~647`), when both local Envoy SOC and cloud oracle
SOC are available in the same tick, compute `abs(local - cloud)`. If
the delta exceeds `soc_divergence_threshold_pp` (default 10, "Numbers
Get Knobs" — rung: **module constant** in `energy_const.py`, because
turning it is a safety trade-off that should require review) for more
than `soc_divergence_dwell_min` (default 5, rung: **module constant**)
continuous minutes, raise an NM alert (per-day latch keyed on
`("soc_divergence",)`, same pattern as `energy_write_verify._maybe_fire_nm`)
AND set a `soc_divergence_active: true` attribute on
`sensor.ura_energy_coordinator_battery_strategy` with the observed delta.
Alert clears when delta returns below `threshold - hysteresis_pp`
(default 2) for the same dwell.

**Acceptance:**
- **Verify:** planted divergence in unit test (local=60, cloud=87) held
  for `dwell + 1 min` → NM fired exactly once, attr set, alert clears
  when delta returns to 3.
- **Verify:** planted divergence that clears within `dwell - 1 min` →
  no NM.
- **Live:** attribute `soc_divergence_active` present on
  `sensor.ura_energy_coordinator_battery_strategy` post-restart. Cannot
  be actively demonstrated without organic divergence — record as
  in-suite-only if not observed in the validation window, per CLAUDE.md.

**D2.2 — Tier-disagreement observability.** In the 3-tier resolver,
add attributes:
- `soc_resolver_tier`: string, one of `primary_envoy` / `lkg` / `cloud_fallback`.
- `soc_resolver_tier_disagreement_pp`: float or None — the max
  pairwise pp gap between tiers whose values are non-None this tick.
- `soc_resolver_cloud_age_s`: int or None — the age of the last-updated
  timestamp on the cloud oracle SOC entity.
Rung: attributes only; no user-facing knob. Purely observability. These
enable the operator (and future automation) to see WHY a decision was made
without instrumenting the whole resolver at debug level.

**Acceptance:**
- **Verify (in-suite):** three attribute-population tests, one per tier
  configuration.
- **Live:** all three attributes present on the strategy sensor within
  5 min of restart. `soc_resolver_tier` reads `primary_envoy` under
  normal conditions.

**D2.3 — Cloud-lag surfacing.** Add attribute `cloud_settings_lag_s` on
the strategy sensor: max age (now − last_updated) across the three cloud
oracle write-target entities (reserve, storage_mode, charge_from_grid).
The 07-16 15%-vs-61 incident had this at ~70 min. NM alert if
`cloud_settings_lag_s > cloud_settings_lag_alert_s` (default 1800 = 30
min, rung: **module constant**) for `cloud_settings_lag_dwell_min`
(default 5, rung: **module constant**). Kill-switch: `cloud_settings_lag_alert_s = 0`
disables (documented on the constant).

**Acceptance:**
- **Verify:** attribute populated; alert fires at planted lag = 31 min
  held 6 min, clears when lag returns below 15.
- **Live:** attribute reads plausible value (< 300 s under normal cloud
  health).

---

### D3 — Local Envoy Dropout Posture (Judgment Call)

**What.** 3 dropouts in one evening on 2026-07-16 (21:50 / 22:46 /
23:04). Reliability dossier context: `AUDIT_envoy_telemetry_pairing_manual.md`
frames local as primary; the dropouts push URA to the fallback tier
where the D2 25-pp divergence lives. Question: does code need to change,
or is this an operational cable/network fix?

**Apply Marginal-Benefit Decomposition (CLAUDE.md):**
- **Simple version (no code):** operator physically re-terminates the
  dual-homed eth + wifi on the Envoy, or moves it to eth-only. Captures
  100% of dropouts caused by physical flakiness. Zero risk.
- **Fancy version (code):** LKG window tuning + dropout-rate anomaly to
  NM (already partially exists — `energy.py:2376` fires NM at
  `_envoy_unavailable_count == 3`). Marginal benefit: earlier alerting
  if physical fix DOESN'T hold, or if a different failure surfaces.
  Marginal risk: adds a new NM alert path; existing one already fires.
- **Verdict (planner recommendation):** **defer code changes.** The
  existing 3-strike NM alert (`energy.py:2376`) already covers the
  observable-to-operator surface. Propose: operator does the physical
  check first; if dropouts recur AFTER a physical fix, revisit with
  evidence and open a Tier-1 tuning cycle. Parked, not deleted, per
  CLAUDE.md ("Park the fancy design, don't delete it").

**Acceptance criteria (D3):**
- **Verify:** planning doc records the marginal-benefit decomposition
  and the deferral decision with the revisit trigger ("if dropout rate
  remains > N/week after physical fix, revisit").
- **Live:** (none — no code change.)

**Open judgment call for operator:** confirm the deferral, or request
D3 code work be scoped.

---

## Numbers Get Knobs — summary

| Number | Knob name | Rung | Default | Why this rung |
|---|---|---|---|---|
| SOC divergence threshold | `SOC_DIVERGENCE_THRESHOLD_PP` | Module constant (`energy_const.py`) | 10 | Safety trade-off; change requires review |
| SOC divergence dwell | `SOC_DIVERGENCE_DWELL_MIN` | Module constant | 5 | Anti-flap; not operator-tunable |
| SOC divergence hysteresis | `SOC_DIVERGENCE_HYSTERESIS_PP` | Module constant | 2 | Pairs with threshold |
| Cloud settings lag alert threshold | `CLOUD_SETTINGS_LAG_ALERT_S` | Module constant | 1800 | Kill-switch=0 |
| Cloud settings lag dwell | `CLOUD_SETTINGS_LAG_DWELL_MIN` | Module constant | 5 | Anti-flap |

Rationale for keeping ALL knobs on the module-constant rung: none of these
is a policy the operator legitimately turns by observation (per the
Numbers Get Knobs ladder). Any change is a review-worthy behavioral
adjustment.

---

## Sequencing

1. **v5.19.0 (write-verify) ships first.** It owns pending-write stuck
   detection and the `battery_pending_*` reads. Deferring this cycle
   avoids namespace collision on strategy-sensor attributes and lets D2
   build on a stable write-verify surface.
2. **D0 fixture run BEFORE D1/D2/D3 build starts.** D0 output is a
   gate: any REMOVED-with-consumers row halts D1 until remediated.
3. **D1 upgrade + D2 reliance hardening in the SAME cycle** (v5.20.0).
   Both share the review pass and the operator checkpoint. The upgrade
   without hardening leaves the 25-pp divergence undetected on the new
   integration; the hardening without the upgrade races the Entrez
   token retirement.
4. **D3 = doc-only in this cycle.** Physical operational fix is
   operator work.

---

## Tier 3 protocol summary (repeat for reviewers)

Four framing-disjoint reviews, run in parallel:
- **A — local correctness.** Divergence math, hysteresis, dwell timers.
- **B — integration / state.** 3-tier resolver interaction, attribute
  namespace vs v5.19.0, NM latch per-day-key correctness, restart, no
  suppression of the legitimate strategy action.
- **C — test authority via real per-site source mutation.** For each
  of the three divergence sites (D2.1, D2.2, D2.3), neuter the site in
  source and confirm a SPECIFIC test fails. Aggregate monkeypatch does
  NOT satisfy this pass.
- **D — adversarial completeness.** State INV-CLOUD in the falsifiable
  form above. Re-enumerate the ENTIRE cloud consumption surface
  (including pre-existing code, not just this diff). Find one path
  that reads an `enphase_ev` surface not in the D0 fixture, or one
  legal state where divergence goes silent. Repros must be concrete.

**Operator checkpoint before deploy.** After the four reviews and any
fix-ups, planner presents: (a) the invariant proof, (b) the D0 fixture
sign-off, (c) the four review verdicts, (d) the runbook timing gate
status. Operator gives explicit go.

**Live Validation (Review E).** Post-restart README write-back table
per CLAUDE.md.

---

## Not-doing / parked

- **D3 code work** — parked pending post-physical-fix evidence.
- **Failover-map auto-builder pairs T3 / T4 / T5** — remain blocked on
  sign convention (T3) + EVSE-exclusion semantics (T4); AUDIT already
  says "do not admit". Not in scope here.
- **Grid-disconnect control** — no working cloud analogue (AUDIT §1
  GAP). Not addressed this cycle.
