# Plan review #1 (COMPLETENESS) — PLANNING_ec_source_failover_class.md @ cdf67a490

**Reviewer:** ura-reviewer, framing = completeness (independent re-enumeration). **Date:** 2026-10-29.
**Verdict: FIX-REQUIRED.** 1 CRITICAL, 3 HIGH, 4 MEDIUM, 2 LOW.
HVAC/presence state-of-play docs not read: the plan touches neither domain and neither does this review.

## File:line verification (item 4)

All energy_battery.py citations checked and they match: 89, 119, 1099-1100, 1156-1175, 1340-1353, 1486-1497, 1773-1821,
1809-1810, 1832, 2167, 2227, 2257, 2284, 2322, 3618, 6245. Also energy_const.py:345/348/352/357 and energy.py:1186/1846/2356/4322/4382/5286.
Small drift that does not matter: the solar-follow fail-closed block is `energy_pool.py:5028-5039`, not 5025-5035.

## Findings

### CRITICAL-1: D1b re-proposes a measured NO-GO, and the D0 gate cannot tell the two cases apart
`docs/planning/DESIGN_ec_degraded_data_policy.md:325` already closed **P1-1 "cloud SOC freshness by last_reported" as NO-GO**:
the cloud integration re-reports a cached value. On 10-02 the cloud read 10.0 % "fresh" while true SOC climbed to 29 %, and admitting by
`last_reported` "turns 86 % of blind minutes into confidently-wrong SOC (p95 up to 25 pp)". `PLANNING_ec_degraded_data_phase1.md:18,97`
says this NO-GO "stands". The plan's §1.3 does not cite either. Its D0 asks only "does cloud `last_reported` advance while the
value is unchanged?". A YES answer is the harmful case (re-reporting a frozen value), yet the plan treats YES as GO.
The plan also says "cloud stays untrusted, D2a/D3/D4 unchanged" (§4, INV-SF3). That is not enough, because `blind_hold_active`
(`energy.py:4360` `return (not env_ok) and soc is None`), the DP `_tick_is_blind_hold` (`energy.py:5286`) and the strategy blind
gate (`energy_battery.py:6245`) all key on **soc is None, not on tier**. A cloud value that D1b admits therefore releases the blind hold, the EVSE blind
guard and DP `is_blind_hold` on an untrusted, possibly frozen reading.
**Fix:** drop D1b's timestamp swap, or re-gate it on a divergence-vs-truth replay like the original Q2/P3 rather than on stamp advancement. Keep only the
fail-closed handling of unknown ages if you want it (that answers open Q1: drop the swap). Add DESIGN_ec_degraded_data_policy §9.3 to §1.3.

### HIGH-1: The origin card's binding constraints are not carried into the plan
`kanban.data.yaml` card ENVOY-STREAM-SOC-TIER-1 has these binding items:
(a) `binding_constraint_3_8`: never accept a 0 that directly follows `unavailable`, and add a settle or device-count gate, with a test that feeds `unavailable, 0, 36`.
(b) the DEVICE-COMPLETENESS GUARD.
(c) the invariant "age from the payload timestamp, NOT the HA entity timestamp; a frozen republish must NOT read as fresh".
`_read_stream_soc` (`energy_battery.py:1797-1802`) accepts 0.0 (range is 0-100) and has no reconnect gate. Quarantine cannot catch a
reconnect-zero, because divergence only compares while native is fresh (`:1879-1883`), and native is down at exactly that moment. M3 (n=3
reconnects) is not a guard. The nightly 23:06 outages also look like Envoy-side events, and that is the case where 3.8 occurred.
**Fix:** add a deliverable for the 3.8 gate plus its test, and either satisfy (c) or record an explicit operator waiver of (c) with reasons.

### HIGH-2: D1c turns the co-witness from a frozen-producer detector into a liveness ping
The co-witness exists to show that the *value is moving*. It currently uses `last_updated` (`:1824,1832`; `energy_const.py:358`: "must have CHANGED").
The proposed co-witness `load_power` comes from the **same `enphase_realtime` poller on the same Envoy**. If the Envoy serves frozen data, that poller
republishes both values, so `last_reported` stays fresh on both and nothing detects the freeze. D1c removes the only same-device guard against card
constraint (c). This is the same shape as CRITICAL-1. **Fix:** keep `last_updated` for the co-witness and pick a co-witness whose value
always moves (load_power usually does), or replace it with an Envoy data-timestamp entity if realtime exposes one (the phase-1 plan
F8 proposed `Data Timestamp`).

### HIGH-3: The plan claims trust is "earned while native is up", but the code starts every boot trusted
`energy_battery.py:636` initialises `_soc_stream_trust = "trusted"`, and `restore_stream_trust_snapshot` (`:1936-1944`) defaults to trusted. On first enable,
or on a restart inside the 23:06 window, the stream is served with **zero** native comparisons. §4 and INV-SF5 assert otherwise. **Fix:**
either require N agreeing compares before the first use (a new rung-1 count), or state plainly in §4 that trust is default-on and add a config-extreme
test for "boot during native outage".

### MEDIUM-1: Missed freshness site on `last_updated` — `energy_pool.py:5322-5333`
The per-EVSE solar-follow power freshness check (`SOLAR_POWER_FRESH_S`, `energy_const.py:1612`, which says "uses last_updated") marks a bay that is charging
at a steady current as `STALE_POWER` once its power value stops changing for 180 s. This is the same defect as the cloud SOC case, and it is missing from §3.1, §3.4 #1 and #4, and D2.
**Fix:** add it to the member table (slice 2 or park, with a trigger).

### MEDIUM-2: The consumer enumeration in §3.2 is incomplete
The following consumers are not listed. Each needs a stated "behaviour change when stream/cloud serves":
- `energy.py:2848-2857`: the boot envoy-cache save is gated on `== "envoy"`, so a stream tier is not cached. That is correct but should be stated.
- `energy_write_verify.py:274-281` `is_reserve_verifiable` together with the EVSE blind guard (`PLANNING_ec_blind_window_evse_guard.md:166`): D1a makes `blind_hold_active`
  False during outages, so the guard can no longer engage during the very window it was built for, even though reserve writes are still unverifiable. This may be intended, but it must be stated and ruled on.
- `energy_drain_precedence.py:642` (`is_blind_hold`), plus the DP shadow `energy.py:5052`.
- `soc_tier_trusted` consumers: the EV start-SOC verdict (`energy.py:7800-7806`), the untrusted dwell NM (`energy_battery.py:2021`), and the decision attr (`:8223`).
- the cloud divergence `tier_ok` (`energy_battery.py:1600`). It abstains under stream, which is fine but should be stated.

### MEDIUM-3: D1b routing through `_state_age_s` breaks the injected-`now` contract
`_read_cloud_soc_snapshot(now=)` (`:1314-1351`) ages against the injected `now`. Fix-up A-HIGH-2 at `:7996` requires one `now` across evaluators.
`_state_age_s` (`:89-111`) uses `dt_util.utcnow()`. Routing the snapshot through it drops the contract and its frozen-time tests. If D1b
survives, the helper needs a `now=` kwarg. Returning `math.inf` would also flow into the `cloud_soc_age_s` attribute and the DB.
Specify display as None.

### MEDIUM-4: "Live" criterion for D1b is unobservable as written
§6 D1b Live is checkable "only if D1a is absent or quarantined; otherwise check the attribute in the daytime". In daytime, native is fresh and the
resolver never reaches the cloud branch. `cloud_soc_age_s` comes from the snapshot, so it is observable, but it does not
discriminate admission. Give the criterion a discriminating observation or move it in-suite.

### LOW-1: Knob ladder
120 s for `DEFAULT_SOC_STREAM_MAX_AGE_S` is on rung 1 with a reason given. The phase-1 plan proposed 90 s for mode "a" (`PLANNING_ec_degraded_data_phase1.md:454`).
Reconcile the two or cite why 120 s wins. The knob comment at `energy_const.py:354-357` ("MQTT expire_after") must be rewritten along with D1a.
Every other number is accounted for.

### LOW-2: The adjacent plan is mislabelled "to be planned separately"
§8's reserve-witness item does not mention the existing `PLANNING_ec_reserve_witness_fix.md` or
`PLANNING_ec_enphase_resilience_and_p1_adjust.md` R3 (a stream reserve witness extending `_local_reserve_witness_state`). Link them, so the separate card
extends that work instead of re-planning it.

## Parked-plan triggers this cycle would fire (item 3)
- `DESIGN_ec_degraded_data_policy.md` P1-1 NO-GO: re-fired by D1b (CRITICAL-1).
- ENVOY-STREAM-SOC-TIER-1 binding constraints 3.8, device-completeness and payload-timestamp: not carried (HIGH-1).
- `PLANNING_ec_blind_window_evse_guard.md`: the guard's entry predicate is weakened by D1a (MEDIUM-2).
- `PLANNING_ec_reserve_oracle_phase2.md` rev 2.2 stream witness is parked with a trigger tied to the MQTT add-on. That trigger does not fire, because realtime is not the add-on, but `reserve_battery_level_2` is the obvious revival. The plan correctly keeps it out of scope.
- EC-ATTAIN-HOLD-WHEN-ENVOY-BLIND-1: under D1b, a cloud SOC now reaches attain where it previously got None. This is the exact shape that card ruled on. It must be listed as affected, not "not addressed".

## Invariant falsifiability (item 5)
INV-SF1-SF4 are falsifiable as written. INV-SF2 is weakened by HIGH-3 and INV-SF5 by HIGH-1 (a 0 reading is not a "failure", so LKG never engages).
INV-SF3 does not cover the blind-hold path (CRITICAL-1). A missing invariant should be added: "a stream or cloud value never produces a trusted tier while the producer's value is frozen". The D1a Live criterion is discriminating. The D1b Live criterion is not (MEDIUM-4).

## Must-fix before build dispatch
CRITICAL-1, HIGH-1, HIGH-2, HIGH-3, MEDIUM-1, MEDIUM-2, MEDIUM-3. Fix the LOWs in the same revision.

## Operator requirements (added 2026-10-29)

**R1, production versus recommended, is a PARTIAL gap (MEDIUM-5).** §3.3 labels each mechanism by proof class and §6 shows what each deliverable changes, so those two sections are clear. §3.1's member table does not do this. In the "Stamp" and "Selection" columns, live code (cloud `last_updated` at `:1158`) sits beside dormant code ("stream mode a", which is not live because `SOC_STREAM_TIER_ENABLED=False` and `MAX_AGE_S=0`) and beside proposals, and no column says LIVE, DORMANT or PROPOSED. §0.4 also says "enable the dormant stream tier" without naming the version that shipped it. **Fix:** add a "Live today (version, file:line)" column and a "Proposed" column to §3.1, and say which version shipped the stream tier (EC-DEGRADED-DATA-POLICY-1 phase 1).

**R2, clear correctness benefit, fails for D1b.** CRITICAL-1 shows that D1b's benefit is negative on the evidence we have: 86 % of the minutes it would admit carry confidently wrong SOC. D1c's benefit is also unmeasured, and HIGH-2 shows it removes the guard against a frozen producer. D1a's benefit is measured (M0 and M2, about 130 min/week of blind window) and passes. D2 should be justified per site; `_dp_house_load_kw` has the "masked under the live default" problem the plan admits, so its benefit is marginal.

**R3, configurable fallbacks:**
- The fallback entities are configurable. The cloud entry is `CONF_ENERGY_CLOUD_BATTERY_SOC_FALLBACK_ENTITY` (`energy.py:1182`), and its default `DEFAULT_CLOUD_BATTERY_SOC_FALLBACK_ENTITY=None` (`energy_const.py:323`). The stream and co-witness entries are in `config_flow.py:6068-6069,6165-6166`. No entity ID, serial or `_2` suffix is hard-coded in the proposed code. PASS.
- **MEDIUM-6: the freshness window is fitted to this house.** `DEFAULT_SOC_STREAM_MAX_AGE_S=120` is a rung-1 global sized to *this* house's `enphase_realtime` 10 s polling (§6 D1a). Another house could use a different producer, such as the MQTT add-on (the 5-6 s cadence plus `expire_after` that mode "b" was designed for) or a slower poller. With a fixed global, that house would either get a wrong window or need a code change. **Fix:** move the window to rung 2, either as an options-flow field next to the stream entity or as a value derived from the selected producer, and keep 0 as "mode b".
- **LOW-3: correlated-fallback protection relies on per-house measurement.** §4 says only measurement and config prevent a correlated fallback, so another house has no protection beyond the "%" unit guard. At minimum, the options-flow help text must warn about it. Better, make the quarantine compare a precondition of first use (ties to HIGH-3), so a correlated producer is never trusted without at least one live comparison.
- The plan names specific entities (§6 D1a config: `sensor.envoy_482543015950_battery_2`, `load_power`). That is acceptable because they are operator config values, not code. The README and the knob comments must say so explicitly.

---

## Re-review rev 2 (de891642d), changed sections only

**Verdict: SHIP-PLAN with two must-fix plan edits (MEDIUM-R2-1 and R2-2).** These are small text changes. A third round of plan review is not needed if the orchestrator checks them.

### Prior findings
| Finding | Status | Evidence |
|---|---|---|
| CRITICAL-1 cloud `last_reported` | RESOLVED | B3 drops D1b and parks it with a replay trigger. A4 cites the NO-GO. |
| HIGH-1 card constraints | RESOLVED, with an operator waiver for (c) | D3 adds the settle (the `unavailable,0,36` test) and the envelope slew. D0-a read the source: the battery entity goes unavailable on a failed poll, so the integration does not republish a frozen value. The (c) substitution goes to the checkpoint. |
| HIGH-2 co-witness | RESOLVED | D1c is dropped and the co-witness stays on `last_updated`. D0-c sizes the window. |
| HIGH-3 trust at boot | RESOLVED | D2 adds the `unproven` state. A restored `quarantined` stays quarantined. Trust lapses after 6 h. INV-SF6 and its tests are added. |
| MEDIUM-1 per-EVSE `last_updated` | RESOLVED (parked) | B6 parks it with a measurable trigger. |
| MEDIUM-2 consumers | RESOLVED | The B4 table rows match my enumeration (energy.py:2848, 5052, 7800; drain_precedence:642; battery:1600, 2021, 8223). The EVSE guard ruling goes to the checkpoint. |
| MEDIUM-3, MEDIUM-4, LOW-1 | RESOLVED | MEDIUM-3 and MEDIUM-4 are moot because D1b is gone. LOW-1 becomes a per-house field. |
| MEDIUM-5 (R1) | RESOLVED | Part A (live/dormant/unconfigured, with version and file:line) is now split from Part B. I spot-checked the A1 rows against the code and they match. |
| MEDIUM-6 (R3 window) | RESOLVED | The new rung-2 field. The constant stays 0, so mode "b" houses see no change. |
| LOW-2, LOW-3 | RESOLVED | A4 links the related plans. D2 plus the help text cover the correlated-fallback case. |

### New findings
- **MEDIUM-R2-1 (R3): the slew guard reuses envelope physics that is hard-coded for this house.** `soc_envelope` (`energy_battery.py:3384-3433`) builds `SOCEnvelope` from the module constants `BATTERY_CAPACITY_KWH=40.0`, `BATTERY_MAX_CHARGE_KW=30.72` and `BATTERY_MAX_DISCHARGE_KW=30.72` (`energy_const.py:2383-2385`). No options field exists for them. That is 76.8 pp/h. In a house with a smaller or slower battery (for example 13.5 kWh at 5 kW, which is about 37 pp/h), the envelope is twice as wide, so the D3 guard against partial-fleet junk becomes weaker. A house with a faster battery than these constants gets false rejections. B0 marks the envelope "REUSE" and D3 calls it "generic", but it is not generic for another house. **Fix:** in D3, either read capacity and power from config, or state that the slew guard is house-calibrated and that the settle plus earned trust are the generic protection. Either way, list it in the B6 second-house table.
- **MEDIUM-R2-2 (D3 build-prediction gap): there is no quantisation margin when the stream is first served.** The envelope is anchored on the last native value, and its width grows at about 1.28 pp/min. M3 measures a stream-vs-native difference of up to 1 pp (integer %). A stream read 30 s after native drops can sit 1 pp outside a roughly 0.64 pp envelope and be rejected. That falls back to LKG, which covers it, but it also spends the first minute or so of the outage on LKG, and with a tight per-house max age it can churn. **Fix:** D3 should specify that the envelope check uses a margin of at least the 3 pp divergence threshold, add a test for "native 40 to stream 41 at 30 s, served", and give the margin a knob row.
- **LOW-R2-3 (R2): D3's benefit on this producer is unmeasured.** M3 saw no zero across 3 reconnects. The guard is justified by the card's binding constraint and by observations on the same Envoy, and D0-b will check the full history. I accept it as a safety guard, but B2 should name it a guard rather than a measured fix, so R2 is applied honestly.
- **LOW-R2-4:** the `DEFAULT_SOC_STREAM_TRUST_MAX_AGE_S` reason quotes "232 min longest dropout". That number is not tied to a D0 or M row in this plan. Cite where it comes from (DESIGN §9).

### Operator requirements
R1: PASS. R2: PASS for D1 and D2 (measured, M0b). D3 is acceptable as a guard (LOW-R2-3). R3: PASS, apart from MEDIUM-R2-1. The D4 forbid list and the second-house table are good.

---

## Rev 3 check (4acd21a80)

**Verdict: SHIP-PLAN with one must-fix plan edit (MEDIUM-R3-1).**

Prior items: MEDIUM-R2-1 is resolved. D3.3 reuses `_battery_capacity_kwh` (`energy_battery.py:4820-4842`, which handles both Wh and kWh). The rate constants are recorded as an R3 limitation with a trigger, and the "weaker, never tighter" claim is correct. MEDIUM-R2-2 is resolved. The reference is now the last native value, the bound is rate × elapsed + 3 pp, the 1 pp test is added, and the backstop is labelled coarse. LOW-R2-3 is resolved because D3 is now labelled a guard. LOW-R2-4 is resolved because the figure is cited to DESIGN §9.

### New, introduced by rev 3
- **MEDIUM-R3-1: if the slew check sits inside `_read_stream_soc`, it disables quarantine.** D3.1 puts settle inside `_read_stream_soc` so both callers honour it, but D3.2 does not say where slew goes, and a builder will naturally put it in the same place. `_evaluate_stream_divergence` reads through `_read_stream_soc(check_trust=False)` (`:1880`). While native is fresh, the native reference is seconds old, so the bound is about 3 pp. Any stream value more than about 3 pp from native would then be rejected before it is compared. No divergent sample is ever counted, quarantine (> 3 pp) can never fire, and the earn count is never reset by it. A persistently offset producer just sits unproven or trusted with no signal. **Fix:** state that slew applies only on the serve path (`check_trust=True`) or only when native is stale. Add the test "native fresh, stream +5 pp for 2 samples → quarantined" and a matching mutation row.
- **LOW-R3-2:** `_battery_capacity_kwh` can return 0. With 0, `rate` divides by zero, or becomes inf, which silently turns the backstop off. D3.3 should say: capacity ≤ 0 or None → use `BATTERY_CAPACITY_KWH`.
- **LOW-R3-3:** the D2 lapse step changes trust state inside a read. The plan should say the lapse runs only on `check_trust=True` reads, so that a compare-path read cannot demote trust while native is fresh. This matters little, because compares refresh `_stream_last_agree_at` anyway.

Nothing else new. R1, R2 and R3 still pass. The D0 results are cited, and the knob rows are complete, including the new margin knob, whose kill value of 100 is documented.
