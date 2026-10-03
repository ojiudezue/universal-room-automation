# DESIGN REVIEW — Energy coordinator behaviour when the Envoy reading drops out (REV 2)

**Card:** EC-DEGRADED-DATA-POLICY-1 (parent). Children on hold: EV-ARBITRAGE-BREAKER-FLAP-ON-SOC-DROPOUT-1,
EC-ATTAIN-HOLD-WHEN-ENVOY-BLIND-1.
**REV 1:** 2026-10-03, ura-planner. **REV 2:** 2026-10-03, ura-planner, after operator decisions + pushback.
Decision doc, not a build plan. No code edited.

**Operator decisions recorded (2026-10-03):**
- Q-A: **Option B, phased — YES.**
- Q-B: **Attain may keep grid-charging on a fresh cloud SOC while the Envoy is blind — YES, bounded.**
- Pushback: *"We already have fallback machinery in EC. Find it and see how it connects."* REV 1 proposed a new
  `SocReading` dataclass and a new hold TTL. REV 2 throws both out of Phase 1 and builds on the machinery that
  already exists.

---

## 0. What changed vs REV 1

| REV 1 said | REV 2 says | Why |
|---|---|---|
| Build a new `SocReading(value, source, age, quality)` dataclass in Phase 1 | **Not in Phase 1.** Extend the existing per-tick blind snapshot (`energy.py:3817-3840`) to carry the resolver tier. Full dataclass only if Phase 2 needs it. | The resolver (`energy_battery.py:870-989`), the tier tag (`_soc_source_last`) and the B7 per-tick snapshot already exist. |
| New module constant `DEFAULT_SOC_HOLD_TTL_S` (~30 min) | **Dropped from Phase 1.** The EV pause hold reuses the guard's existing discharge (`CONF_BLIND_WINDOW_MAX_DEFER_MIN`=60 + must-start-by liveness release). For held *battery* decisions (Phase 2) the bound is the **existing SOC envelope**, not a TTL (§4). | Operator asked for the envelope alternative. Evaluated in §4: envelope is better for the strategy; neither is the right bound for the EV pause. |
| "Reuse the blind-window guard's debounce for the hold" | **The debounce is the reason the 10-01 release got through** (§3). A refusal to *loosen* must not be debounced. | Traced in code this revision. |
| Stamp fix = hypothesis | **Mostly confirmed** by operator's 48 h measurement: cloud SOC had 98 gaps > 600 s in `last_updated` (max 6.4 h) while `last_reported` kept advancing. D0 still checks this *during Envoy outages*. | New evidence. |
| Q-B open | Decided YES-bounded; bounds specified in §5 P1-4. | Operator. |
| Phase 3 = "Option C, telemetry" | Phase 3 = the never-built `TelemetryPair` map (`PLANNING_envoy_telemetry_failover_map.md` D1/D2) for net import, plus the MQTT `sensor.envoy_stream_*` local witness as a candidate import source. | Prior art; REV 1 only skimmed the filename. |
| D0 = 7 one-off questions | D0 = those questions **plus a one-week replay** of each candidate policy as the go/no-go gate (§6). | Operator. |

---

## 1. The existing fallback machinery, and how it connects

```
Envoy SOC ──fresh by last_reported (≤ PRIMARY_MAX_AGE)──┐
                                                          ├─► battery_soc (energy_battery.py:870)  ─► strategy
LKG (stamped ONLY from Envoy reads, :896-897) ≤300 s ────┤        │ side effect: _soc_source_last
Cloud SOC  ──fresh by last_updated (≤600 s)  :958-962 ───┘        │
                                                                   ▼
                        blind_hold_active = Envoy down AND battery_soc is None   (energy.py:3767-3806)
                        per-tick snapshot  _record_blind_hold_snapshot / _snapshot (energy.py:3817-3840)
                                                                   │
         ┌─────────────────────────────────────────────────────────┤
         ▼                                                         ▼
 Strategy blind branch (energy_battery.py:5086-5215)     Blind-window EVSE guard (energy_pool.py:654-1530)
  - holds battery, no commands                             entry = snapshot blind AND NOT reserve_write_verifiable (:654-688)
  - de-escalates CFG into peak (:5142-5189)                debounce 120 s (:690-790, CONF_..._ENTRY_DEBOUNCE_S energy_const:1710)
  - publishes charge_from_grid=False,                      max-defer 60 min (:970-993, energy_const:1702) → must-start-by
    arbitrage_active=False  (:5095, :5209-5214)            ride permission: mains_export_active() OR soc_envelope().lower ≥ drain (:995-1025)
                                                           adds EVSE to _paused_by_blind_window (:1383)

 SOC envelope  SOCEnvelope (energy_battery.py:124-200) → soc_envelope() (:2407-2457) → coord.soc_envelope() (energy.py:3895)
   LKG ± 30.72 kW × Δt / 40 kWh  (= ±1.28 pp/min, energy_const:1754-1756), max age 6 h (:1762)
   returns None while Envoy is fresh; ONLY consumer today = the EVSE guard ride check.
 Solar envelope  solar_production_w_envelope (energy_battery.py:2484) — upper bound only; consumer = excess-solar.
 Write verifier  is_reserve_verifiable (energy_write_verify.py:219-300) — cloud oracle readable + OK record ≤600 s.
```

**Three disconnections matter:**
1. **Cloud never re-anchors the LKG.** The LKG is stamped only from an Envoy read (`energy_battery.py:896-897`).
   After 1 h of Envoy outage the envelope is ±77 pp (useless) even if the cloud SOC was fresh the whole time.
2. **The cloud tier's freshness stamp is `last_updated`** (`:959`), while the Envoy tier (`:893`), the envelope
   (`:2438`) and the cloud *oracle* lag check (`:1202-1211`, NM Cycle A A6 — the exact same bug, already fixed
   there in July) all use `last_reported`. A flat cloud value (battery idle at reserve) is rejected as stale.
3. **The guard and the arbitrage release are separate owners**, joined only by set membership (§3).

---

## 2. Evidence

| Source | Fact |
|---|---|
| Operator measurement (48 h, 2026-10-03) | Cloud SOC `sensor.iq_battery_hacs_battery_overall_charge`: 98 gaps > 600 s in `last_updated`, max 6.4 h; `last_reported` kept advancing. |
| Card EV-ARBITRAGE-BREAKER-FLAP (10-01) | garage_a ON/OFF pairs ~every 5 min 06:09-07:25Z while Envoy SOC continuously unavailable 05:50-06:39Z. Local CFG switch unavailable; breaker breach not confirmed. |
| Card EC-ATTAIN-HOLD (10-02) | 14:00-15:48 CDT "Envoy unavailable — holding (no commands issued)"; operator grid-charged by hand. |
| `PROBE_envoy_outage_frequency.md` (July) | 7-29 outages/day; 66 % < 2 min, 11 % 2-10, 6 % 10-30, 17 % > 30 min (restart-inflated). Measured on the production sensor, not SOC. |
| `DEFAULT_DECISION_INTERVAL_MINUTES = 5` (`energy_const.py:183`) | Decision tick is 5 min. The 120 s guard debounce therefore means "two consecutive blind ticks". |

---

## 3. Why the 10-01 arbitrage pause released despite the blind-window guard

Trace of one blind tick (file:line, all read this revision):

1. Strategy blind branch returns `charge_from_grid=False`, `arbitrage_active=False` (`energy_battery.py:5095`,
   `:5209-5214`). "No information" is published as "no grid charge".
2. `_execute_breaker_safe_dispatch`: `grid_charge_intent = decision_grid_charge OR live_grid_charge_on`
   (`energy.py:6764`). The live leg reads the write-role CFG switch; `unavailable` counts as ON **only if the
   LKG latch `_last_known_grid_charge_on` is True** (`:6747-6759`). It does **not** consult
   `_last_charge_from_grid_command` (`energy_battery.py:452`), which the peak de-escalation path does
   (`:5152`). Result on 10-01: intent False, `pause_reason=None` (`:6781`).
3. Step 3, `EVChargerController.determine_actions` (`energy.py:6856`) runs the guard (Row 2.5,
   `energy_pool.py:1311-1530`).
   - `_blind_window_guard_engaged` needs the raw predicate True for ≥120 s (`:773-776`). On the **first** blind
     tick, `_blind_window_entry_first_at` is set to now and the guard returns **not engaged**.
   - A sighted tick resets the debounce (`:709`) and drains `_paused_by_blind_window` (`:1520-1522`).
   - The raw predicate also needs `not reserve_write_verifiable()` (`:685`). With the cloud oracle readable and
     a reserve verify OK inside 600 s (`energy_write_verify.py:249-300`), the guard **cannot** engage at all.
     Whether that was true on 10-01 is unmeasured (D0 Q8).
4. Step 4, `determine_arbitrage_actions(arbitrage_charging=False, …)` (`energy.py:6881-6886` →
   `energy_pool.py:2940-2990`). Its only blind-data protections are `grid_charge_on` (`:2947`, False per step 2)
   and peer membership in `_paused_by_blind_window` (`:2974`, empty per step 3). It **discards the EVSE from
   `_paused_by_arbitrage` immediately** (`:2956`) and turns it on (off-peak, no other owner).
5. Next tick: cloud tier passes its 600 s gate (or Envoy blips back), strategy wants grid charge, breaker pause
   (`energy.py:6790-6797`) turns the EV off.

**Answer to "why":** all three of the operator's candidates, in this order of weight:
- **Guard does not cover the arbitrage owner.** The guard's invariant is *reserve protection*
  (`is_reserve_verifiable` is "battery-reserve-specific", `energy_write_verify.py:245-247`). The arbitrage
  release's risk is *breaker compound load*. The release only borrows the guard's set as a peer veto.
- **Debounce + alternation.** Debounce is designed to stop *tightening* (pausing) on blips. Applied to a
  *loosening* path it is backwards: with a 5-min tick and blind/sighted alternating each tick (the cloud
  `last_updated` gate flipping), every blind tick is a "first" blind tick and the guard never engages.
- **Ordering is not the cause.** The guard (step 3) runs before the release (step 4). Ordering is correct.

**Proposed routing (reuse, no new owner):** in the release loop at `energy_pool.py:2940`, before discarding,
refuse release when `coord.blind_hold_active_snapshot()` is True (the guard's own per-tick truth,
`energy_pool.py:672-679`), **with no debounce** and **without** the `reserve_write_verifiable` leg (wrong
invariant for breaker). Keep the EVSE in `_paused_by_arbitrage` with label `"breaker"`, exactly like the existing
`grid_charge_on` refusal at `:2947-2954`. Discharge: the existing max-defer constant
(`CONF_BLIND_WINDOW_MAX_DEFER_MIN`) and the must-start-by liveness release (`blind_window_liveness_release`,
`energy_pool.py:1458`, `_dp_must_start_by_min` `:1649`). No new knob.

---

## 4. Envelope as the hold bound vs a fixed TTL

**Envelope rule:** a held decision stays valid while the whole envelope `[lo, hi]` still supports it; stand down
when it crosses. Each held decision states a predicate, e.g. "keep holding at reserve" valid while `lo ≥ floor`;
"keep charging toward target T" valid while `hi < T`.

| | Fixed TTL | Envelope (existing `soc_envelope()`) |
|---|---|---|
| New ingredient | New constant, a guessed number | None (primitive shipped, already load-bearing in the guard) |
| Near a threshold (2-5 pp bands) | Holds the full TTL, may hold a wrong decision | Crosses in 2-4 min at 1.28 pp/min → stands down within one tick. Conservative, which is correct near a threshold |
| Far from a threshold (e.g. 30 pp below target) | Stands down at TTL even though nothing could have changed | Holds ~23 min, physically justified |
| Discharge | Time | Monotonic widening; hard ceiling = `DEFAULT_SOC_LKG_ENVELOPE_MAX_AGE_S` (6 h) |
| Weakness | Arbitrary | Uses worst-case 30.72 kW both ways; LKG not re-anchored by cloud (§1 point 1) |
| Fits the EV arbitrage pause? | No | **No** — that hold is about *is grid charge possibly on*, not SOC. Bound it by CFG evidence + max-defer (§3). |

**Verdict:** envelope for *battery-strategy* held decisions (Phase 2), with two reuse extensions: (a) re-anchor the
LKG from a FRESH cloud read (`LkgValue` already carries a `source` field, `energy_battery.py:2470-2475`), gated
on D0 Q3 divergence; (b) keep the 6 h max-age as the ceiling. No TTL constant. Not needed for Phase 1 at all,
because Phase 1's only hold is the EV pause, which has its own discharge.

Caveat to verify in the Phase-2 plan: the envelope is consumed today by the guard's ride check (`:1019`).
Re-anchoring on cloud widens what that ride check permits. D0 Q3 must show cloud-vs-Envoy divergence well under
the drain-target margin before (a) ships.

---

## 5. Phased plan (Option B, reuse-first)

### Phase 1 — smallest scope that closes both cards (Tier 3: breaker safety + shared state machine)

| # | Change | Site | Reuse |
|---|---|---|---|
| P1-1 | Cloud SOC freshness by `last_reported` (fallback `last_updated` on older cores) | `energy_battery.py:957-962` | `_state_age_s(stamp="last_reported")` `:85-107`; same fix as `:1202-1211` |
| P1-2 | Blind branch stops asserting "no grid charge": publish last commanded CFG instead of False | `energy_battery.py:5095`, `:5209-5214` | `_last_charge_from_grid_command` `:452` |
| P1-3 | Breaker intent ORs `_last_charge_from_grid_command` | `energy.py:6764` | same attribute; LKG latch `:6739-6759` unchanged |
| P1-4 | Arbitrage release refused on blind snapshot, no debounce; discharged by max-defer / must-start-by | `energy_pool.py:2940` | `blind_hold_active_snapshot` `energy.py:3827`; `CONF_BLIND_WINDOW_MAX_DEFER_MIN`; liveness release `energy_pool.py:1458` |
| P1-5 | Attain continuation may keep CHARGE with `net_power_w` unreadable **only when bounded** (below) | `energy_battery.py:4730-4760` | resolver tier, envelope, breaker pause |

**P1-5 bounds (all must hold, else today's fail-closed HOLD):**
1. SOC tier is `cloud_fallback` and fresh by `last_reported` (after P1-1). Not LKG-only, not envelope-only.
2. EV breaker pause is in force this tick (`grid_charge_intent` True ⇒ `pause_reason="breaker"`, `energy.py:6773`).
   This removes the EV half of the compound load the import guard exists for.
3. Cloud SOC < attain target (stop on reaching target, as today).
4. Inside the existing attain window; never into peak (peak de-escalation `:5142-5189` still wins).
5. A blind-charge time cap. **NEW** rung-1 module constant `DEFAULT_ATTAIN_BLIND_CHARGE_MAX_MIN`, value sized from
   D0 replay (start point: 60, matching `CONF_BLIND_WINDOW_MAX_DEFER_MIN`). Rung 1 because it bounds breaker
   exposure; changes should be reviewed. 0 = kill switch (today's behaviour).
6. If D0 Q6 finds a fresh non-Envoy import source, a later cycle may swap bound 5 for a real import check.

Not in Phase 1: `SocReading` dataclass, envelope holds for the strategy, HVAC `or 0`, DP-tick exception direction.

**Falsifiable invariants (Tier 3, D-reviewer breaks these):**
- **I-1:** No change in SOC availability (any tier transition, either direction) produces an EVSE `switch.turn_on`
  from the arbitrage release path. Repro to test: off-peak, EVSE in `_paused_by_arbitrage`, alternate sighted
  (CFG intent True) and blind ticks 10 times → zero turn_on.
- **I-2:** Under the P1-5 bounds, attain emits the same CFG/reserve commands on a fresh cloud SOC as on an Envoy
  SOC of the same value, and stops within one tick of any bound failing.
- **I-3:** Nothing in a blind tick loosens a protective posture; peak de-escalation is unchanged byte-for-byte.
- Config extremes: `CONF_BLIND_WINDOW_MAX_DEFER_MIN` 0 and large; `DEFAULT_ATTAIN_BLIND_CHARGE_MAX_MIN` 0 and large;
  cloud age at bound and bound+1; `_last_charge_from_grid_command` None/True/False.

### Phase 2 — Tier 2-DB elevated
Envelope-bounded holds for strategy decisions (§4), cloud re-anchoring of the LKG (gated on Q3), HVAC constraint
off `soc or 0` (`energy.py:7397, 7513, 10159`), DP-tick exception direction (`energy.py:4697-4709`), EVSE
battery-hold None capture (`energy.py:5939-5948`, `:6635-6643`), route remaining SOC readers to the snapshot.

### Phase 3 — only if measured to matter
`TelemetryPair` + debounced trip/hysteretic return (`PLANNING_envoy_telemetry_failover_map.md` D1/D2, never built;
its D3/D4 were rejected on measured staleness and stay rejected) applied to net import + solar, merged with
EC-SOLAR-ENTITY-OVERRIDE-1. Candidate import source: the MQTT local witness `sensor.envoy_stream_*` (memory note,
~5-6 s cadence, ~20 s clock skew; not verified in code this session). Cloud **write** route stays as designed in
`PLANNING_envoy_write_verification_and_redundancy.md` D3 (dormant); not reopened here.

**Sequencing:** D0 → Phase 1. Not in parallel with EC-SOC-LADDER-FULL-WIRING-1 (same `determine_mode` surface).

---

## 6. D0 — measurement + one-week replay (go/no-go gate). Spec only, NOT RUN.

Read-only: `ssh ha "python3 -" < probe_ec_degraded_replay.py`, opening the recorder DB with `mode=ro` URI and the
URA DB read-only. No HA service calls. Output: one markdown report appended to this doc + a per-minute CSV in the
scratchpad.

### 6.1 Step 0 — schema and entity discovery (fail loudly, don't guess)
- Confirm `states` has `last_reported_ts`; if absent, Q2/P1-1 replay uses `last_updated_ts` and the report says so.
- Resolve `states_meta.metadata_id` for: `sensor.envoy_482543015950_battery`,
  `sensor.iq_battery_hacs_battery_overall_charge`, `switch.iq_battery_hacs_charge_battery_from_grid`, the local
  `switch.enpower_*_charge_from_grid`, both garage EVSE switches (read from the EC config entry, not assumed),
  SPAN/mains import entities (`CONF_ENERGY_MAINS_*` from the config entry), `sensor.envoy_stream_*`.
- Identify the URA entity that records the strategy decision (reason/phase/`charge_from_grid` attributes) by
  scanning `states_meta` for URA energy sensors whose `state_attributes` contain `arbitrage_phase`. Print it; if none
  found, the replay falls back to `ura_activity_log` rows.

### 6.2 Questions (REV 1 Q1-Q7 kept, plus)
- **Q8:** for each blind minute on 10-01 05:50-07:30Z, was `reserve_write_verifiable` plausibly True (cloud reserve
  oracle state fresh + a URA reserve write within 600 s)? Explains whether the guard could ever engage.
- **Q9:** empirical max |dSOC/dt| (pp/min) from Envoy SOC, p99 and max, vs the 1.28 pp/min envelope rate.

### 6.3 Replay model
Window: 7 days ending 2026-10-03 (must include 10-01 night and 10-02 afternoon). Clock: 5-min ticks aligned to the
real EC tick times (taken from decision-sensor `last_updated`), with per-minute availability state in between.

Per tick, reconstruct inputs: Envoy SOC value/age, cloud SOC value with age by **both** stamps, LKG, envelope
`[lo, hi]` (same formula, constants from `energy_const.py`), local + cloud CFG state, EVSE switch states, TOU period,
recorded strategy decision (sighted ticks only).

Policies replayed (pure functions in the script, mirroring the cited code, no imports from the integration):
| ID | Policy |
|---|---|
| P0 | As coded today: cloud by `last_updated`, blind-branch publishes False, guard debounce 120 s, release as `:2940` |
| P1 | P0 + cloud by `last_reported` |
| P2 | P1 + P1-2/P1-3 (intent carries last command) + P1-4 (release refused on blind, max-defer 60) |
| P3 | P2 + P1-5 attain-on-cloud, cap ∈ {30, 60, 90} |
| P4 | P3 + envelope hold for strategy decisions (Phase 2 preview), with and without cloud re-anchoring |
| P5 | P3 + fixed TTL hold ∈ {15, 30, 60} (comparison arm for §4) |

Per tick per policy emit: quality (`fresh_envoy` / `fresh_cloud` / `lkg` / `blind`), action class
(`act` / `hold` / `stand_down`), predicted battery commands (CFG on/off, reserve), predicted EVSE commands; and
alongside, the **actual** recorded commands/states.

### 6.4 Report
- Per policy: EVSE toggles/day (and on 10-01 night), blind ticks, minutes of attain grid-charge in-window vs
  missed, minutes of predicted EV-on while any CFG reading was on/unknown (breaker exposure), minutes held past
  the point the envelope crossed.
- P0 vs actual agreement rate (model fidelity). **If P0 does not reproduce the 10-01 toggle pattern and the 10-02
  hold within ±1 tick, stop: the model is wrong, results are not usable.**

### 6.5 Go / no-go
- **Go Phase 1** if: P0 fidelity holds; P2 has **zero** predicted EV turn-on during blind ticks across the week;
  P2/P3 EV toggles on 10-01 ≤ normal (2-4/h); P3 recovers ≥ most of the 10-02 14:00-15:48 window; P3 breaker-exposure
  minutes = 0.
- **Drop P1-5 (keep P1-1..4)** if P3 shows any breaker-exposure minute or cloud SOC diverges from Envoy by more
  than the attain target margin at p95 (Q3).
- **Drop P1-1** if Q2 shows `last_reported` gaps also exceed 600 s during outages (then the cloud integration
  itself is stalling and the stamp is not the cause).
- **Envelope vs TTL (Phase 2 input):** prefer P4 unless P5 at some TTL has strictly fewer missed-charge minutes
  with equal breaker exposure.

---

## 7. Decisions still needed
- **Q-C (new):** accept `DEFAULT_ATTAIN_BLIND_CHARGE_MAX_MIN` as a rung-1 constant sized by D0 (start 60)?
- **Q-D:** order relative to EC-SOC-LADDER-FULL-WIRING-1.
- **Q-E (new):** Phase 2 envelope re-anchoring on cloud — approve in principle, gated on D0 Q3?

**Config-first:** no setting fixes this. `CONF_RESERVE_VERIFIABLE_MAX_AGE_S`=0 (backout knob) would not help: it
only affects the guard's engagement, and the guard is not the owner that released (§3).

---

## 9. D0 results (2026-10-03)

Probe: `scratchpad/d0_replay.py` (+ raw dump `d0_dump.py`), run `ssh ha "python3 -" < …` against the recorder
(`mode=ro`, both `last_updated_ts` and `last_reported_ts`) and the URA DB (`mode=ro`, `ura_activity_log`). No writes.
Window 2026-09-26 00:00Z → 2026-10-03 06:30Z (7.3 d, 10 469 min). Decision source = `sensor.ura_energy_coordinator_battery_strategy`
attributes (`reason`, `soc_source`, `soc_resolution`, `last_verified_write_reserve_soc`, `evse_paused_by_arbitrage`).
EVSEs `switch.garage_a` / `switch.garage_b`.

**Recorder caveat:** HA keeps only the *last* `last_reported_ts` per state row. Inside `[last_updated, last_reported]`
the report cadence is unknown, so "fresh by last_reported" is optimistic inside a row; gaps after `last_reported` are real.

### 9.1 Model fidelity — STOP condition hit (partially)

| Check | Result | Verdict |
|---|---|---|
| P0 data tier (resolver mirrored per minute) vs actual "Envoy unavailable — holding" | 91.0 % minute agreement (1563 TP / 7965 TN / 669 FP / 272 FN) | OK |
| 10-02 19:00-20:48Z (14:00-15:48 CDT) attain hold | actual blind-branch 99 min, P0 predicted 100 min | **Reproduced** |
| 10-01 06:09-08:05Z charger toggles | 31 EV turn-ons on 10-01. garage_a turn-ons 06-12Z by deciding tick: **13 of 14 on non-blind ticks** (envoy 6, lkg 4, cloud_fallback 3), 1 on a blind tick | **NOT reproduced** |

**The 10-01 flap is a different mechanism from §3.** The strategy alternates every 5-min tick between
`Off-peak hold … (rung_1: EV pause redirects solar; projected 100% ≥ target by boundary)` (`arbitrage_intent=redirect`,
EVs paused) and `Arbitrage WAIT — charge window not yet open` (`intent=breaker`, `arbitrage_active=False` → release →
EVs on). It is driven by EV load, not SOC availability:

| Phase entry (week) | garage_a draw at entry |
|---|---|
| rung_1 (R1) | 13 / 13 with EV ≥ 11.6 kW |
| WAIT | 34 / 34 with EV off |

It continued on Envoy-sighted ticks (10-01 08:04 R1/envoy → 08:10 WAIT → 08:15 R1/envoy; 10:30 R1/envoy → 10:35 WAIT/envoy).
R1 appears only on 10-01 (06-11Z) in the week. The Envoy dropout was co-incident, not causal. Per §6.4 the P1-P5 policy
replay was **not run**; its outputs would describe a mechanism that did not produce the 10-01 event.

### 9.2 Measurements (model-independent)

| Q | Result |
|---|---|
| Q8 reserve verifiable, 10-01 05:50-07:30Z | Record status `ok` all 100 min, **but `verified_at` older than 600 s (or missing) in all 100 min**; cloud reserve oracle readable. ⇒ `is_reserve_verifiable()` was False; the guard's verifiable leg did not block it. (Only 30 of the 100 min were blind-tier anyway.) |
| Q2 cloud SOC gaps > 600 s | by `last_updated`: n=362, max 6.4 h. By `last_reported`: n=16, max 1.4 h (10 overlap an Envoy outage, max 83 min) |
| Q2 during Envoy+LKG-blind minutes (2 951) | cloud fresh by `last_updated` 24 %; by `last_reported` 86 % |
| **Q2/Q3 the 10-02 window** | Cloud SOC row: value **10.0**, `last_updated` 14:28Z, `last_reported` **20:49Z**. Envoy at 20:48Z = **29 %** (operator grid-charged by hand during the window). The cloud kept re-reporting a frozen 10.0 for ~2 h while the battery rose ~19 pp. |
| Q3 \|cloud − Envoy\| (both fresh, cloud by `last_reported`, n=6 876 min) | p50 0.9, p95 11.5, p99 47.0, max 74.9 pp; 250 min > 20 pp. Split by cloud `last_updated` age: ≤10 min p95 8.7; 10-30 min p95 25.2; 30-60 min p95 7.9; > 60 min p95 3.0 (max 74.9). Live attr `tier_disagreement_pp`: p95 9.9, max 74.9 |
| Q9 Envoy \|dSOC/dt\| (pairs 4-30 min apart, n=7 385) | p99 0.76, max 1.20 pp/min vs envelope 1.28 ⇒ envelope rate is tight but not violated |
| Dropout histogram (Envoy SOC not fresh by `last_reported` ≤ 300 s) | 165 runs, 22.7/day, 59.4 h total (34 % of the week). 0-2 min 28; 2-10 min 71; 10-30 min 43; 30-60 min 5; 60-120 min 9; > 120 min 9. Longest 232, 224, 188, 184, 152, 150 min |
| MQTT witness `sensor.envoy_stream_battery_soc` | `unavailable` since 2026-09-30; no usable data in either incident window |

### 9.3 Go / no-go per Phase-1 item

| Item | Verdict | Evidence |
|---|---|---|
| P1-1 cloud freshness by `last_reported` | **NO-GO** | The cloud integration re-reports a cached value: 10-02 cloud said 10.0 % "fresh" through 20:49Z while true SOC reached 29 %. Admitting by `last_reported` turns 86 % of blind minutes into confidently-wrong SOC (p95 up to 25 pp). Matches the §6.5 drop rule in spirit (the integration is stalling, the stamp is not the cause). |
| P1-2 / P1-3 intent carries last CFG command | **HOLD, re-scope** | Not the trigger of 10-01 (releases came on resolved-SOC WAIT ticks). **But:** local `switch.enpower_482348004678_charge_from_grid` read `on` every time it was available in 06:39-08:00Z (else `unavailable`), and EVs were still turned on, e.g. 06:45:02 on an Envoy-sighted WAIT tick with the switch `on` since 06:39:18. Either the `grid_charge_on` refusal (`energy_pool.py:2947`) reads a different entity or it did not fire — unresolved, possible breaker exposure. Carry into the re-scoped card as a must-answer. |
| P1-4 refuse arbitrage release on blind snapshot | **NO-GO as a fix for 10-01** | Would have blocked at most 1 of 14 turn-ons. Cheap and harmless; may ride along with the real fix, not stand alone. |
| P1-5 attain on cloud SOC | **NO-GO** | Bound 1 depends on P1-1; the cloud was frozen at 10 % over exactly the target window, so bound 3 (stop at target) can never fire on that reading. No fresh non-Envoy SOC witness exists today (MQTT stream down). |
| **New: rung_1 ⇄ WAIT load-feedback oscillation** | **Card needed (Tier 2+)** | Rung_1 pause is entered when the EV draws, and WAIT releases it the next tick; period 10 min, Envoy-independent. Belongs with the arbitrage/rung machinery, not the degraded-data policy. |

### 9.4 Sizing `DEFAULT_ATTAIN_BLIND_CHARGE_MAX_MIN`

Recommend **do not add it now** (P1-5 is no-go; equivalent to the kill-switch value 0). If P1-5 is revived on a
trustworthy witness (Envoy MQTT stream restored, or a cloud reading proven to move), start at **30 min**, not 60:
at the measured max 1.20 pp/min a 30-min blind charge carries up to ~36 pp of SOC uncertainty, already larger than the
2-5 pp threshold bands in §4; 60 min (~72 pp) is unbounded in practice. 30 min would cover 142 of 165 dropouts
(86 %) this week; the 18 runs > 60 min are where it would cut out.

### 9.5 Consequences for this doc

- §3's trace is real code behaviour but was not what flapped on 10-01; the incident card should be re-pointed at the
  rung_1/WAIT oscillation.
- §2 row 1 ("cloud `last_reported` kept advancing") is true but not evidence of freshness — the reported value can be frozen.
- Phase 2 cloud re-anchoring of the LKG (Q-E) inherits the P1-1 problem: **not approvable** on this data.
