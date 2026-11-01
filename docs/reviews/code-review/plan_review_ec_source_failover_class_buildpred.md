# Plan review #2 (adversarial build-prediction): PLANNING_ec_source_failover_class.md

**Plan commit:** cdf67a490. **Reviewer framing:** "what will the builder get wrong reading this?" (Tier 3 plan review 2 of 2; completeness re-enumeration is reviewer #1's lane and is not repeated here).
**Code read:** `energy_battery.py` 89-111, 119, 636, 1060-1188, 1307-1354, 1773-1945, 8011; `energy_const.py` 335-365, 638-641; `energy.py` 1180-1190; `config_flow.py` stream/cloud-last-success fields; `quality/tests/test_ec_degraded_data_p1.py` constant patching.
**HVAC / presence docs:** not read; no HVAC or presence code is in scope.

**Verdict: FIX-REQUIRED (plan edits only; no design change to D1a).**

## Findings

### BP-1 HIGH: D0's go criterion for D1b is inverted. `last_reported` advancing is the hazard, not the go
Plan §6 D0: "if cloud last_reported advances while the value is unchanged, D1b converts the 12.5 min blind tail into `cloud_fallback`." `last_reported` moves whenever the HACS integration re-writes its state on a poll. It says the integration polled, not that the Enphase cloud has new data. The nightly native outage (23:06) is the Envoy going quiet locally. If the Envoy is also not uploading during that window, the cloud value is frozen upstream while the HACS poll keeps refreshing `last_reported`. D1b then serves a stale-equal cloud SOC as `cloud_fallback`. That is the same "stale-equal cloud trusted while local is down" defect behind the 10-29 false REVERTED page (§3.1 reserve-witness row), moved into the SOC resolver.
- **Repro (legal config, plausible physics):** native unavailable 23:07-23:30; Envoy upload paused; HACS polls every 60 s returning the cached 42%. Today the resolver rejects at 600 s after the last change. Under D1b it serves 42% for the whole window, and D1b's own "Live" criterion ("`cloud_soc_age_s` stays below 600") reads PASS.
- **Mitigation already in the measurements:** M0b shows the cloud value changed at 23:07:49 inside the outage, so the cloud was getting data that night. One night is not a measurement, though.
- **Plan fix:** D0 must measure cloud **data** freshness during native outages, not report cadence: (a) over all 7 outage windows, the interval between cloud **value changes** compared with daytime cadence at a similar SOC slope, and (b) whether the integration exposes a data-age stamp. Prior art the plan missed: `CONF_ENERGY_CLOUD_LAST_SUCCESS_ENTITY` (`energy_const.py:641`, config_flow.py:1067, "when the battery cloud last refreshed successfully"). Decide whether D1b's gate becomes `min(last_reported age, last_success age)` or stays on `last_updated`. Answer open question 1 as: if D0 cannot show the cloud has fresh data during outages, ship only the fail-closed unknown-age half of D1b and keep `last_updated`.

### BP-2 HIGH: the same question applies to `battery_2` and is unanswered
INV-SF2 and D1a treat `battery_2` `last_reported` ≤ 120 s as alive. That holds only if `enphase_realtime` marks entities `unavailable` when its poll fails rather than re-writing the cached value. M3's evidence ("3 reconnects resumed at prior value") fits both behaviours. A builder will take mode "a" as sufficient.
- **Repro:** realtime loses the Envoy meter endpoint while its coordinator keeps calling `async_write_ha_state` on cached data, or a custom poller writes on a timer. `battery_2` stays fresh at a frozen %, it is trusted (`stream` ∈ `SOC_TRUSTED_TIERS`), the LKG re-anchors on every tick (`energy_battery.py:1099`), and the blind hold never engages.
- **Plan fix:** D0 adds a read of the `enphase_realtime` source (or one forced-failure observation) to establish what it writes on poll failure. Add a falsifier: a native outage in which `battery_2` value changes stop while `last_reported` keeps advancing and `load_power` / `current_battery_discharge_2` are also flat, so the frozen stream is visible.

### BP-3 HIGH: first-deploy trust is not "earned while native is up"
§4 says trust is earned while native is up and carried into the outage. In code, `_soc_stream_trust` initialises to `"trusted"` (`energy_battery.py:636`), and quarantine needs 2 divergent compared samples ≥60 s apart (`:1866-1910`). If HA restarts (or first deploys) while native is down, the stream is served as trusted with zero comparisons, and the persisted-trust restore (`energy.py:1846`) has nothing to restore on first boot. The builder will implement exactly what the plan says, and no test in the D1a list catches it.
- **Repro:** deploy restart at 23:10 during the nightly outage (the sleep rule pushes restarts later, but the watchdog/restart-storm history makes an unplanned restart in that window legal). `battery_2` reads 55% while true SOC is 40% (realtime misconfigured to the wrong Envoy). It goes straight to `local_stream`, trusted, with no quarantine possible until native returns.
- **Plan fix:** either (a) state explicitly that unproven-at-boot trust is accepted (and why), or (b) add an `unproven` state: the stream is served only after ≥N agreeing samples since boot or since the last restore. Option (b) changes state-machine semantics, so the plan should choose, and option (b) needs its own restore test.

### BP-4 MEDIUM: D1b's lock-step change to `_read_cloud_soc_snapshot` breaks its injected-`now` contract
`_read_cloud_soc_snapshot(now)` computes age against an injected `now` (fix-up A-HIGH-2, single time snapshot per evaluator, `:1319-1350`). `_state_age_s` calls `dt_util.utcnow()` internally (`:110`). A builder told to "use `_state_age_s`, in lock-step" will either drop `now` (regressing A-HIGH-2 and making existing frozen-`now` divergence tests wall-clock-coupled) or call it and ignore `now`.
- **Plan fix:** specify that `_state_age_s` gains an optional `now=` parameter (default utcnow, byte-identical), or that the snapshot keeps its inline arithmetic and only swaps the attribute to `last_reported` with a `last_updated` fallback. Name the existing divergence tests that must stay green unmodified.

### BP-5 MEDIUM: `unknown_age="fail"` is under-specified against the helper's existing fallback
`_state_age_s` already falls back from `last_reported` to `last_updated` when the attribute is missing (`:103-104`). "Unknown" under `"fail"` therefore only means no state, both stamps missing, a naive stamp, or an exception. The plan also says "returns `math.inf` instead of None". A builder may return inf for `state is None` too, and some callers treat None as "missing" for D-OBS classification. Ambiguous points: does `"fail"` change the `state is None` branch? Does inf leak into attributes (`cloud_soc_age_s` = inf serialises as a non-JSON float in the DB/attribute surface)?
- **Plan fix:** pin the exact return table per branch. Require that the cloud path never writes an inf age into `soc_resolution` attributes (clamp or None for display). Add `test_state_age_s_unknown_age_fail_branches` covering all four branches.

### BP-6 MEDIUM: D1c's co-witness becomes non-independent and its job is undefined
With D1c, the co-witness `load_power` is judged on `last_reported`, from the same integration and poll loop as `battery_2`. It then proves only what `battery_2`'s own `last_reported` already proves, and it adds a refusal path: M2 measured 3-5 `load_power` blips of 0.2-0.5 min, each one drops the stream to LKG. That is harmless (LKG covers 300 s), but the plan claims a liveness value it does not deliver. The co-witness is also optional in mode "a" (`:1812`).
- **Plan fix:** state the co-witness's job in mode "a". If it is "a value-moving sibling detects a frozen-but-reporting producer" (the BP-2 hazard), D1c should NOT switch to `last_reported`: `last_updated` on a value-moving sibling is the only frozen-poller detector the tier has. Keep the 120 s and choose a sibling that always moves (`load_power` qualifies; `grid_power` near zero may not). Otherwise leave the co-witness unset in mode "a" and drop D1c. As written, D1c and BP-2 pull in opposite directions, and the builder will ship the weaker one.

### BP-7 MEDIUM: test-authority traps
- Existing tests flip behaviour with `_setc(monkeypatch, "SOC_STREAM_TIER_ENABLED", ...)` and `"DEFAULT_SOC_STREAM_MAX_AGE_S", 90` (`test_ec_degraded_data_p1.py:237,288,348,380`). New D1a tests written the same way pass whether or not the shipped constants change, so reverting `True`/`120` stays green. **Fix:** require one test that asserts the shipped values (`SOC_STREAM_TIER_ENABLED is True`, `DEFAULT_SOC_STREAM_MAX_AGE_S == 120`) with no monkeypatch, and run the D1a acceptance tests once against unpatched module constants.
- INV-SF4 ("`SOC_STREAM_TIER_ENABLED=False` → byte-identical") now needs a monkeypatch to False, so it proves the kill switch works but not that develop's default path is unchanged. The real byte-identical claim after this cycle is "**stream entity unset** → identical", since that is how a second install sees it. Add that test.
- Wall-clock: `_state_age_s` uses real `utcnow()`. Tests at 119 s / 121 s against a 120 s gate are wall-clock-coupled and flaky under a slow suite. Require `freezer` or margins of ≥10 s (e.g. 60 s / 180 s).
- The mutation anchor "neutralise `age > max_age` at `:1810`" also has to cover the `age is None` half (`:1810` is `if age is None or age > max_age`). Mutating only `> max_age` leaves the naive-stamp fail-closed path untested. Name both drills.

### BP-8 MEDIUM: the live acceptance depends on an operator config step the deploy flow does not enforce
D1a's tier activates only when the operator sets `energy_stream_battery_soc_entity` in the options flow. If the cycle deploys before that is done, `stream_trust_state()` = `disabled` (`:1838`), and the night's recorder rows show `lkg` then None exactly as on 10-28, which is the plan's "misconfigured" signature. That reads as FAIL with no code defect, or the configuration gets skipped and nobody notices. The operator is travelling (memory: away 10-14→10-18, now back, but the rule stands).
- **Plan fix:** add a pre-live gate that reads `sensor.ura_energy_coordinator_battery_strategy` `stream_trust` = `trusted` (not `disabled`) the same day, before 23:00, and put the option write in the deploy checklist. Options-flow writes reload the CM entry; note the parent-entry reload hazard (memory: parent reload, then a watchdog restart) and do the write in daytime.

### BP-9 LOW: native-fresh-but-disagreeing quarantine latency vs outage onset
Quarantine needs 2 compared samples ≥60 s apart. Native drops at 23:06-23:09. If the stream started diverging shortly before then (for example realtime partially reconnecting), fewer than 2 spaced samples exist and the divergent stream is served trusted all night. This is inherent in the design, but INV-SF2/"Verify: stream quarantined before native drops" tests only the already-quarantined case. **Fix:** add a config-extreme test with 1 divergent sample, then native down, and record the accepted residual (bounded by 1 sample ≤ 3 pp + 60 s).

### BP-10 LOW: knob ladder
`SOC_STREAM_TIER_ENABLED` at rung 1 is correct: it is a trust-tier entry, and the per-house enable already lives at rung 2 through entity wiring. `DEFAULT_SOC_STREAM_MAX_AGE_S` at rung 1 is also right, but it is now global across installs. A second install wired to an MQTT stream that relies on `expire_after` (mode "b") is silently switched to mode "a" by this change. **Fix:** one line in §7 and the `energy_const.py` comment noting that 120 assumes a per-report-stamping producer.

### Cleared
- **Tier order (stream before LKG):** holds. A fresh independent read beats memory, and LKG re-anchoring on a stream read (`:1097-1100`) gives INV-SF5's one-miss tolerance. Open question 3 needs no change.
- **Native fresh vs stream disagreeing:** native always wins because it is checked first (`:1082`). The stream is only compared, never served, while native is fresh.
- **`envoy_available` / INV-SF3:** no slice-1 edit touches `:3618-3650` or `SOC_TRUSTED_TIERS`. Holds if the builder respects §9.
- **max_age 0 vs 120:** mode switch semantics are clear in code (`:1806-1817`). Cowitness unset in mode "a" means it is skipped (`:1812`), in mode "b" the tier refuses. Correct.
- **HA restart stamps:** a non-restored entity's first write after boot sets `last_reported` to boot time. That is a problem only through BP-2 (the poller writes cached data) and BP-3 (unproven trust), both above. An entity that comes up `unavailable` is rejected (`:1789`).

## Must-fix before build dispatch
BP-1, BP-2, BP-3 (choose and document), BP-4, BP-5, BP-6, BP-7, BP-8. BP-9/BP-10 are small plan text additions.

## Addendum: operator requirements (2026-10-29)

### OR-1 MEDIUM: recommended changes and production behaviour are mixed together
§3.1 and §3.3 put live behaviour, dormant code and proposals in the same tables. The builder can misread them in three places:
- **(a) "Stream tier ... REUSE, enable"** (§1.2, §3.3 "BUILT, never live"). The code exists, but nothing in it has run in production: the trust init at `:636`, quarantine, and the restore at `energy.py:1846`. A builder reading "REUSE" will treat it as proven, skip the BP-3 review, and skip its tests.
- **(b) §3.1 "Stream co-witness ... last_updated 120 s"** is production code that is never reached. D1c's change to it is a proposal.
- **(c) The §5 invariants mix states that hold today (INV-SF3) with states that hold only after the change (INV-SF2).**

**Fix:** add a "Today (develop @cdf67a490) / After slice 1" column pair to §3.1, and tag each invariant [holds today] or [new].

### OR-2 MEDIUM: pieces whose benefit is not yet shown
- **D1b** has no proven benefit until D0 measures data freshness (BP-1). The way D0 is written now, it could approve a regression.
- **D1c** has no correctness benefit in mode "a", where the co-witness is optional. Its only effect is to weaken the frozen-poller detector (BP-6). Drop it, or justify it.
- **The `unknown_age` keyword** is justified only by D1b. If D1b is dropped, the keyword goes with it. Do not ship it alone as "harmonization".
- **The text rename in D1a** is harmless and can stay.
- **D2** is listed as a separate cycle. Keep it out of this build, and say so in the builder brief.

### OR-3 MEDIUM: configurability for other houses
Code today is clean here. The SOC entity, cloud fallback (`DEFAULT_CLOUD_BATTERY_SOC_FALLBACK_ENTITY = None`, `energy_const.py:323`), stream entity and co-witness are all options-flow fields (`config_flow.py:6068-6069,7464-7477`), and all of them default to unset. The risk is that the builder hard-codes values the plan gives as concrete examples:
- **Values the builder may copy in:** `sensor.envoy_482543015950_battery_2`, `load_power`, the `_2` suffix, and the 23:06 window. These appear in D1a's "Config (operator action)", in the tests, and in the Live criteria.
- **Forbid:** any entity ID, serial, `_2` suffix or time window in `custom_components/`, including defaults, migrations, auto-population and NM text. Tests must use synthetic entity IDs.
- **Units and sign:** the stream guard already requires unit `%` and a value in 0-100 (`:1797-1801`). No sign question arises for SOC. Keep power out of scope (M6).

**Second-house matrix (behaviour after slice 1 with nothing configured):**

| House sources | Configuration | Result |
|---|---|---|
| No `enphase_realtime` | stream unset | `_stream_tier_configured()` returns False and the tier is skipped; behaviour is identical to today (this is the real INV-SF4; see BP-7) |
| Cloud only | cloud fallback set | D1b semantics apply. BP-1 matters more here, because cloud is the only fallback |
| MQTT stream with `expire_after` and no per-message stamp | stream set | `DEFAULT_SOC_STREAM_MAX_AGE_S=120` forces mode "a" for every house (BP-10). A per-house stream max-age at rung 2, with 0 meaning mode "b", would serve both kinds of producer. That is a new config field, so the plan should either justify it or record the limitation |
| Native integration unset | SOC unset | unchanged from today |

**Fix:** add this matrix and the forbid-list to §6 D1a and to the builder brief.

---

## Re-review rev 2 (de891642d): changed sections only, build-prediction framing plus R1-R3

**Verdict: FIX-REQUIRED (small).** Rev 2 resolves every finding from my first pass. It introduces four new gaps (RB-1 to RB-4) inside the new pieces. All of them can be fixed in the plan text before build dispatch.

### Status of the first-pass findings
| Finding | Status |
|---|---|
| BP-1 cloud `last_reported` | **Resolved.** D1b dropped and parked with a replay trigger; A4 records the prior NO-GO |
| BP-2 frozen republish | **Resolved** for this producer by the D0-a source read (`FastCoordinator`, unavailable on a failed poll). The Envoy-side freeze is covered by the co-witness kept on `last_updated` |
| BP-3 boot trust | **Resolved in design** (D2 `unproven`). See RB-2 for an ordering gap |
| BP-4 injected `now` | **Resolved** (moot; helper unchanged) |
| BP-5 `unknown_age` | **Resolved** (dropped) |
| BP-6 co-witness | **Resolved** (D1c dropped; D0-c sizes the window) |
| BP-7 test authority | **Resolved** (unpatched-constant test, unset-entity identity, config-driven max age, both mutation halves, ≥10 s margins) |
| BP-8 operator config | **Resolved** (daytime step plus pre-23:00 `unproven`→`trusted` gate, which also proves the earn path) |
| BP-9 one-sample residual | **Resolved** (test plus accepted residual) |
| BP-10 global max age | **Resolved** (per-house field; constant stays 0) |
| OR-1 production vs proposed | **Resolved.** The Part A / Part B split is clear, and the invariants are tagged |
| OR-2 unproven benefit | **Resolved**, except RB-1: the slew guard's benefit as specified is partly unproven |
| OR-3 configurability | **Partly resolved.** Entity wiring is clean, but RB-1 brings in this house's battery physics |

### RB-1 HIGH: the slew guard reuses house-specific constants and, as specified, rejects legitimate steps
`soc_envelope` (`energy_battery.py:3384-3433`) builds its bounds from `BATTERY_CAPACITY_KWH=40.0` and `BATTERY_MAX_DISCHARGE_KW=30.72` (`energy_const.py:2383-2385`). These are rung-1 module constants holding this house's values, not per-house config. That breaks R3: in a second house with a different battery, the slew guard uses the wrong physics. Two concrete failures follow:
- **(a) Legitimate integer steps get rejected (this house).** 30.72/40 gives 76.8 pp/h, which is 0.64 pp per 30 s tick. Because every served stream read re-anchors the LKG (`:1097-1100`), the envelope around the next read is ±0.64 pp, and the producer reports integer %. **Repro:** native down, stream 41 → 40 at the next tick. 1 pp is more than 0.64, so the read is rejected and the tick falls to `lkg`. On the next tick (60 s from the anchor, ±1.28 pp) it is accepted. The tier label flaps `local_stream`↔`lkg` once per pp step. Holds are unaffected because LKG is trusted, but D1's live criterion ("tier = `local_stream` for every row") reads FAIL on a correct build. The predictable response is for the builder to widen the envelope by hand.
- **(b) The plan's partial-fleet claim does not hold after a gap.** "95 → 87 rejected" is true only within about 6 min of the LKG anchor (8 pp at 1.28 pp/min). **Repro:** stream unavailable for 7 min inside the native outage (LKG, then cloud, which does not re-anchor), then the stream reconnects partial-fleet at 87 for longer than the 60 s settle. The envelope is about ±10 pp, so 87 is served as trusted.
- **Plan fix:**
  - The slew check rejects only when `|Δ| > envelope + quantization`, with quantization at least 1 pp (a rung-1 constant). Test a legitimate 1 pp step at a 30 s tick.
  - State that the slew guard is a coarse backstop. It catches the 0-class and gross junk, not an 8 pp partial fleet after a gap. Revise the INV-SF7 wording and the `95 → 87` test to use timing that the physics actually supports.
  - Record the R3 limitation: the battery physics constants are this house's values. Either move them to the options flow (separate card) or note in the R3 table that other houses get envelope bounds sized for 40 kWh / 30.72 kW.

### RB-2 MEDIUM: the earn, recovery and lapse ordering is ambiguous
- The existing quarantine recovery moves `quarantined`→`trusted` after `DEFAULT_SOC_STREAM_QUARANTINE_TICKS=2` agreements (`:1920-1926`). The plan does not say whether recovery now goes `quarantined`→`unproven`→`trusted` (needing N=3) or keeps the 2-tick shortcut. A builder will keep the existing code, and recovery from a proven-bad state is then easier (2) than first earn (3). **Fix:** quarantine recovery lands in `unproven`, then needs N fresh agreements. Add a test for this.
- The plan does not say which counter the earn path uses: the existing `_stream_agree_count` (reset by `_stream_div_count` logic) or a new one. **Fix:** name it.
- The lapse ("last agreeing comparison older than `TRUST_MAX_AGE_S`") needs a new timestamp field. It is not persisted, which is fine because restore yields `unproven`. The plan should name the field and the tick where the lapse is evaluated: in `_read_stream_soc` before serving, not only in `_evaluate_stream_divergence`, which returns early while native is down (`:1880-1883`). If the builder puts the lapse check inside `_evaluate_stream_divergence`, it never fires during the very outage it bounds.
- `restore_stream_trust_snapshot` whitelists only `("trusted","quarantined")` (`:1942`). The plan's test `test_restore_trusted_becomes_unproven` covers the mapping. Also say explicitly that a persisted `unproven` restores as `unproven`, not that it is ignored. Today an unknown state returns early and keeps the init value, which is correct only if the init also changes to `unproven`. Make sure the builder changes the init at `:636`.

### RB-3 MEDIUM: where the settle tracking lives, and blips shorter than a tick
- The plan says "when the **resolver** reads the stream entity as unavailable". The resolver reads the stream only while native is down (native returns first, `:1082-1090`). Settle state therefore is not recorded for drops that happen while native is up. In that case `_evaluate_stream_divergence` (`_read_stream_soc(check_trust=False)`) compares the reconnect 0 against native 95. That is one divergent sample, which resets the earn count (and counts toward quarantine). **Fix:** the settle check lives in `_read_stream_soc`, so both callers honour it and junk never enters a comparison.
- EC ticks are about 30 s apart (M0b row spacing). M2 measured realtime blips of 0.2-0.5 min, so a blip shorter than a tick is never observed as unavailable, and settle never arms. **Repro:** stream unavailable from 23:10:05 to 23:10:17, and the 23:10:19 tick reads first value 0. Settle has not armed, so only the envelope stands between that 0 and service, which RB-1 shows is fine for a 0 within minutes of the anchor. **Fix:** either arm settle from the entity's own `last_changed` (if `last_changed` is newer than the previous tick's read and the previous value differed by more than the envelope, treat it as a reconnect), or a state-change listener (that brings in listener lifecycle and unsub, which is heavier). Or document that the settle covers only drops longer than a tick and that the envelope covers the rest.

### RB-4 MEDIUM: wiring and validation of the per-house max-age field
- `self._entities` maps CONF keys to entity IDs (`energy.py:1182-1187`). A builder adding the numeric field to that mapping makes `_get_entity` return an int. **Fix:** say where the value lives (a typed attribute on BatteryStrategy, read from options), name all three config_flow sites (`6068`, `6165`, `7464-7477` pattern), and add strings.json label and help text.
- **Silent never-serve config.** **Repro:** max age 10 s on a producer that polls every 30 s. Every read is stale, and `_evaluate_stream_divergence` also reads through freshness, so trust never earns, `stream_trust` stays `unproven` forever, and nothing pages. **Fix:** set a selector minimum (for example 30 s). The pre-23:00 gate already detects this in this house; for other houses, add an NM or a diagnostic when the state is `unproven` for more than 1 h while native is fresh and the stream is configured. The trigger lives in code, per the no-soak rule.

### RB-5 LOW: the EVSE blind-guard ruling rests on an unverified claim
B4 says reserve verifiability is "still false in the outage", but A2 lists `is_reserve_verifiable` as keyed on "write record age, not SOC" (`energy_write_verify.py:274-281`). Those two statements do not follow from each other. **Fix:** cite the line that makes verifiability false while native is down, or change the ruling text to rest on SOC being known alone. The recommendation (accept) does not depend on it.

### RB-6 LOW (R1 wording)
A1.8 says "unreadable restores to `trusted`". The code actually returns early and keeps the init `"trusted"` (`:1942-1943`). The effect is the same and the mechanism is different. A builder fixing "restore" without changing the init at `:636` leaves boot-trusted in place. RB-2's last bullet covers this.

### R2 check (nothing without a clear benefit)
D1 and D2 each fix a measured wrong behaviour. The D3 settle guards a behaviour measured on this Envoy, although not yet on this producer; D0-b gates it. The slew guard is justified, provided RB-1 is fixed. No other additions.

### Must-fix before operator checkpoint
RB-1, RB-2, RB-3, RB-4. RB-5 and RB-6 are text.

---

## Rev 3 check (4acd21a80)

**Verdict: SHIP-PLAN.** RB-1 to RB-6 are resolved. Rev 3 introduces two new LOW ambiguities. A builder brief note is enough for both; no plan change is needed.

| Finding | Status |
|---|---|
| RB-1 slew physics, quantisation, gap | **Resolved.** The reference is now the last trusted native value, so LKG re-anchoring no longer narrows the bound. A +3 pp margin covers the 1 pp step (test `test_stream_one_pp_step_served`). The guard is described as a coarse backstop, with the 87-after-10-min limit documented by a test. Capacity reuses `_battery_capacity_kwh()` (A1.11b). The rate limitation is recorded with a trigger, and the direction is safe: a slower battery gets a wider bound |
| RB-2 earn, recovery, lapse | **Resolved.** The init at `:636`, the restore table, the reused `_stream_agree_count`, recovery to `unproven` with the same N, and the lapse in the read path are all specified, and each has a test and a drill |
| RB-3 settle placement, sub-tick blips | **Resolved.** Settle lives in `_read_stream_soc`. Arm (a) fires on an observed unavailable; arm (b) fires on `last_changed` plus a jump above the margin |
| RB-4 max-age wiring | **Resolved.** Typed attribute outside the entity map, three config_flow sites, min 30, stuck-unproven attribute |
| RB-5 EVSE ruling | **Resolved.** It now rests on SOC being known |
| RB-6 restore wording | **Resolved.** A1.8 corrected |

### New in rev 3 (LOW)
- **RC-1 LOW: arm (b)'s "previous read value" is undefined when the previous read returned None.** A read can return None because of a stale stamp, the slew check, quarantine, or settle. **Repro:** the stream is slew-rejected for 3 ticks, then a legitimate value arrives that is more than 3 pp from the last served value. What counts as "previous" decides whether settle re-arms. Either reading is safe: it costs at most 60 s on LKG, and it can never admit junk, because the slew check still applies. **Brief note:** say that "previous" means the last numeric state value the read saw before any guard ran, stored on every numeric read.
- **RC-2 LOW: the stuck-unproven signal is an attribute, not a trip-wire.** It is accepted under R2: there is no measured instance, and the trigger is to add an NM if the attribute is ever seen above 1 h. Something must actually check that attribute; this house's pre-23:00 live gate does. Note it on the card as the revival trigger so it is not lost.

No other regressions. INV-SF4 (unset entity gives identical behaviour) is untouched by the rev 3 edits: every new field and guard sits behind `_stream_tier_configured()`.
