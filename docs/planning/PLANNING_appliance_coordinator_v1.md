# PLANNING — Appliance coordinator, v1 (APPLIANCE-MGMT-REFINE-1)

**Card:** APPLIANCE-MGMT-REFINE-1 · **Date:** 2026-09-14 · **Status:** DRAFT for operator go/no-go on build
**Tier:** 3 (new coordinator, cross-coordinator energy/cost reads, control actuation in a later phase) —
plan-review (2 framing-disjoint) before any build dispatch.
**Basis:** operator two-layer reframe (2026-09-14) + 4 residual answers + anomaly prior-art scan (this session).

---

## The operator's model (absorbed verbatim, not paraphrased)

Appliances are **two things at once**, and the coordinator must hold both:

- **(a) MEASURABLE** — things that draw energy whether or not we can command them (examples: warming
  drawer, kettle). Sources: **SPAN** (per-circuit) + **Emporia** (per-channel). Emporia is
  measurement-only *except EVSEs*; SPAN can toggle a breaker but only for large appliances.
- **(b) CONTROLLABLE** — things we can command (examples: LG dishwasher, fridge, TVs). Control paths
  are **per-device, heterogeneous**: Samsung integration, Amazon Fire TV, EPSON projector, Denon AVR,
  and **power-measuring smart plugs** that are *both* a measure source AND an on/off actuator for
  otherwise-dumb loads.

An appliance can be in both layers. The dual objective is **visibility** (measure everything) and
**control** (command the subset we can). Examples above are EXAMPLES — v1 needs a **categorization
scheme**, not a hardcoded appliance enum.

### The four residual answers that shape the plan
- **Q1 breaker control = NOT a controller lever.** SPAN breaker on/off is an architectural fact we may
  *choose* to use; it is **off the table** for automated actuation (a wrong breaker-off = spoiled food
  / frozen pipe). Instead the coordinator **wires into the anomaly subsystem like every coordinator**
  (§D3) — SPAN breaker *state* is an input/anomaly signal, never an output.
- **Q2 lists = examples** → categorization scheme (§D1), not an enum.
- **Q3 control = heterogeneous per device** → control primitive is a per-appliance property (§D4, later phase).
- **Q4 cost = yes but careful** → separate **energy-used (kWh)** from **cost-attribution** (§D2), because
  solar/battery-served energy is not priced at the import rate.

---

## Institutional context verified (prior-art scan — Tier 2+ mandate)

**REUSE, not build**, for every mechanism v1 needs:

| Piece v1 needs | Verdict | Existing symbol (file:line) |
|---|---|---|
| Appliance power/energy inputs | **REUSE** | 74 existing appliance power/energy entities (SPAN circuits + Emporia channels); enumerate, don't create |
| Anomaly emit (domain) | **REUSE** | `AnomalyEvent` (anomaly_event.py:154), `build_context_json` (:292), `database.save_anomaly_event` (database.py:6956), `AnomalyDetector.store_event` (coordinator_diagnostics.py:1205) |
| Anomaly emit (rule-engine) | **REUSE** | `OptimizationFinding` + evaluator tuple (optimization.py:919); `_persist_findings_batch` (:3969) |
| Loud operator alert | **REUSE** | `fire_stuck_signal` (_stuck_signal_nm.py:165) — per-day latch, fail-open, auto-persists anomaly row |
| Anomaly status sensor pattern | **REUSE** | `sensor.ura_<domain>_anomaly` family (e.g. presence sensor.py:6160) reading `coord.anomaly_detector.get_worst_severity()` |
| TOU rate for cost | **REUSE** | `TOURateEngine` / `sensor.ura_energy_coordinator_tou_period` `import_rate` (shipped v5.101.2) |
| Solar/battery/grid mix | **REUSE (read)** | Envoy grid/solar/battery power entities (see `battery_soc_envoy_not_span` memory) |
| Dedup / once-per-episode latch | **REUSE pattern** | camera_stuck in-memory `set` latch (optimization.py:589/1905/1915) |

**No new anomaly registry exists or is needed** — there is no cross-coordinator registry; a coordinator
either adds an evaluator to `optimization.py:919` (rule-engine findings) or constructs `AnomalyEvent`
and calls `save_anomaly_event` (domain anomalies). v1 uses the **domain-anomaly path** (§D3).

**Prior planning consulted:** `CRITIQUE_appliance_management_v3.md` (this session — ranked opportunity
table: #1 delay-start BUILD-FIRST, #5 interrupt PARK Tier-3). **Memory:** `battery_soc_envoy_not_span`
(cost math source of truth), `EC config surface` (export sign inverted — matters for §D2 mix math).

---

## v1 SCOPE — read-only appliance-energy census + categorization + anomaly wiring

**v1 is deliberately measure-only. No control actuation ships in v1** (control = §D4, a later phase gated
on this census proving out). This follows Measure-Before-Build and Marginal-Benefit: the census de-risks
control because *power draw is itself the "materially started" signal* control would need.

### Falsifiable invariant
v1 adds **only** read-only sensors + anomaly findings. It commands **nothing** — no `turn_on`/`turn_off`,
no breaker call, no `number.set_value` on any appliance. Any actuation in the v1 diff is a defect.

---

## D0 (MEASURE FIRST) — appliance DISCOVERY probe across THREE sources
**Operator correction (2026-09-14): power meters alone miss most appliances — "not enough breakers to
cover a house."** So discovery is NOT just the 74 power/energy entities. It draws from three sources and
unions them:

1. **Power meters** — SPAN circuits + Emporia channels (the 74 power/energy entities). Measures draw;
   covers only what happens to be on a metered circuit.
2. **HA native appliance integrations** — the appliance *devices* HA already knows about independent of
   any meter: LG ThinQ (washer/dryer/dishwasher/fridge), Samsung TV, Amazon Fire TV, Denon AVR, EPSON
   projector, smart plugs, etc. D0 must **enumerate these live** (by integration/domain — `media_player`,
   `vacuum`, `humidifier`, ThinQ device classes, …) — do NOT hand-assume the list.
3. **Existing URA room + coordinator config** — entities URA already manages (see the onboarding rule
   in D0a). These are surfaced, never re-added.

- **Acceptance:** a live table unioning all three sources; per entity: source, current state, freshness,
  unit, energy-vs-power, and which source(s) cover it (a device may be BOTH metered and integration-known).
  Dead/stale flagged (a sparse producer caps the census — measure real production first). Committed as the
  hand-built fixture (Measure-Before-Build corollary).

## D0a — Onboarding model: URA-owned = SHOW UP, net-new = ADD (operator-coined 2026-09-14)
The appliance universe is **"basically anything not already in URA room and coordinator config."** The
governing rule:
- **If an entity is already in URA** (a room's fan, light, climate entity, or a coordinator-managed
  device), it **SHOWS UP in the appliance view automatically — it is NOT re-configured.** Fans must not be
  re-added; they surface. The appliance coordinator READS existing config as a discovery source, it does
  not ask the operator to re-enter anything URA already knows.
- **If an entity is net-new** (a TV, an AV receiver, a projector, a standalone smart-plug load URA has
  never seen), it can be **ADDED** through an onboarding path (config/options flow) — that is the only
  place the operator does manual work.
- **De-dup across sources is mandatory:** the same physical appliance can appear as a SPAN circuit AND a
  ThinQ device AND (if in a room) a URA entity — it must resolve to ONE appliance record, not three.
- **Acceptance:** an entity already in a URA room (e.g. a room fan) appears in the appliance census with
  `source_includes: [ura_config]` and requires NO onboarding step (the discriminating test that
  URA-owned ≠ re-config); a net-new TV requires an explicit add; a triple-covered appliance yields one record.

## D1 — Appliance categorization scheme (the operator's correction, refined 2026-09-14)
A declarative categorization — NOT a hardcoded enum — on **FOUR ORTHOGONAL axes**. The load-bearing one
is the **functional domain** — *what the appliance does*, **independent of how it was added or how it is
controlled** (operator 2026-09-14: "not just categorization by how added but what the appliance does…
Media, Kitchen Appliance etc."). A Samsung TV on a native API and a dumb speaker on a smart plug are
BOTH `media`; the add-vector is a separate axis.

1. **Functional domain (PRIMARY — what it does):** `media_av` | `kitchen` | `laundry` | `climate` |
   `cold_chain` | `water` | `cleaning` | `other` (extensible). This is the axis anomaly thresholds and
   operator-facing grouping key off — a `cold_chain` appliance is exempt from "left-on"; a `media_av`
   one is the phantom-draw candidate. Domain is NOT derivable from source or control — it is declared.
2. **Control axis (can we command it):** `measure_only` | `controllable` (an appliance may be both-layer:
   controllable AND measured).
3. **Add-vector / source (how it reaches us):** `span_circuit` | `emporia_channel` | `smart_plug` |
   `native_integration`. Orthogonal to domain — the same domain spans multiple vectors.
4. **Energy behaviour (derived, for anomaly logic):** e.g. `always_on` (fridge) vs `session` (dishwasher)
   vs `standby_prone` (AV). Derived from observed draw in D0, not declared.
- **Numbers-get-knobs:** the appliance→{domain, control, source} mapping is per-deployment structure →
  **config/options flow** (rung 2), not module constants. Kill switch: an appliance with no mapping =
  measured, `other`/`measure_only` — visible but ungrouped, never silently dropped.
- **Acceptance:** the D0 fixture round-trips; each of the 74 entities gets **exactly one functional
  domain** + exactly one source + a control tag; two appliances of the same domain on *different*
  add-vectors (e.g. a native-API TV and a smart-plug speaker → both `media_av`) is the discriminating
  test that domain is independent of vector; scheme is additive (a new appliance needs config, not code).

## D2 — Energy-used vs cost-attribution (Q4, carefully)
Two SEPARATE per-appliance values:
- **`energy_used_kwh`** — unambiguous, straight from the energy entity (or ∫power dt where only W exists).
- **`cost_attributed`** — energy × the *effective* rate at time-of-draw, where effective rate accounts
  for the **grid/solar/battery mix**. v1 uses a documented, conservative apportionment (candidate:
  marginal-grid model — appliance kWh priced at TOU `import_rate` only for the fraction of house load
  that was grid-served in that interval; solar/battery-served fraction priced at 0 or a battery-cycle
  cost). The exact model is a **plan-review decision** — the invariant is that the two numbers are
  distinct and cost is never a naive `kwh × import_rate`.
- **Acceptance:** a test where the house is 100% solar-served shows `energy_used_kwh > 0` AND
  `cost_attributed ≈ 0` (the discriminating test — proves the mix is respected, per acceptance-must-discriminate).

## D3 — Anomaly-subsystem wiring (Q1 — the "like every coordinator" requirement)
The appliance coordinator holds an `AnomalyDetector` and emits **domain anomalies** via
`AnomalyEvent`/`save_anomaly_event`, exposed as `sensor.ura_appliance_anomaly` (mirroring the
presence/safety/security status-sensor family). Candidate v1 anomalies (all measure-derived, no control):
- **appliance-left-on** — a controllable/high-draw appliance drawing above idle for longer than a
  per-category threshold (cold-chain exempt — it's *supposed* to run).
- **cold-chain-power-loss** — a fridge/freezer circuit that drops to ~0 W unexpectedly (this is where
  SPAN breaker *state* is an input signal, not an output).
- **phantom-draw** — an entertainment-AV load drawing standby power beyond a category threshold.
- **Numbers-get-knobs:** each threshold is a named constant (rung 1, review-gated) or entity-knob if the
  operator will tune it by observation; documented on the knob.
- **Latch:** in-memory once-per-episode set (camera_stuck pattern), cleared on return-to-normal.
- **Loud path (optional per anomaly):** `fire_stuck_signal` with a new `kind="appliance"` for the ones
  that warrant an operator page (cold-chain-power-loss yes; phantom-draw no).
- **Acceptance:** WIRE-IN ANCHOR — the detector must be constructed AND the sensor registered (a
  helper-only test stays green if not wired); mutation — neuter the emit call, an anomaly test goes RED;
  cold-chain-power-loss fires on a simulated fridge-circuit drop and pages via NM.

## D4 — Control (LATER PHASE, NOT v1) — parked with trigger
Per-device control (LG dishwasher delay-start, AV off, smart-plug toggle) is the #1 opportunity from
`CRITIQUE_appliance_management_v3.md` but is **out of v1 scope**. Parked with the revival trigger: "D0
census shows the controllable-layer appliances produce a reliable materially-started signal." When
revived it is its own Tier-3 cycle (control actuation on cost/comfort). Breaker actuation stays
permanently out per Q1.

---

## Non-goals (explicit)
- **NO control actuation in v1** (measure-only). **NO breaker on/off ever** (Q1).
- **NOT** a hardcoded appliance enum (Q2 → categorization scheme).
- **NOT** a naive `kwh × import_rate` cost (Q4 → mix-aware).
- **NOT** a new anomaly registry (none exists; reuse the two established paths).

## Plan-review checklist (Tier 3, 2 framing-disjoint before build)
- **Completeness:** re-run D0 census independently; confirm the 74-entity count and that each has a live,
  fresh producer (a sparse producer changes the plan).
- **Build-prediction:** the D2 cost model is the highest-ambiguity area — a reviewer must confirm the
  apportionment is fully specified before a builder inherits it (avoid the "two options where a third is
  correct" failure). Confirm the anomaly-path choice (domain vs rule-engine) against the prior-art scan.
- **Institutional:** verify the anomaly prior-art file:line citations (the scan is a hypothesis) and the
  Envoy mix-entity ids (export-sign inverted per EC memory).
