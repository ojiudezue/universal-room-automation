# PLANNING: EC source failover as a class (multi-producer values, freshness stamps, untrusted fallbacks)

**Revision:** rev 3.1 (small clarifications after rev 3 re-check), rev 3, 2026-10-29 (rev 1 = cdf67a490, rev 2 = de891642d). **Status:** rev 3 applies the two rev-2 re-reviews (completeness 6bf9983bd, build-prediction 858ee1bc5) and the D0 probe results (`AUDIT_ec_source_failover_d0_probes_2026_10_29.md`, 8663731a9). Orchestrator checks the rev-3 edits, then operator checkpoint. **Tier:** 3 (section B7).

**Operator checkpoint 2026-10-30 (pre-build): APPROVED.** (1) Build rev 3.1 + B2a as written. (2) Constraint (c) substitution accepted: 60 s settle + slew check in place of payload-timestamp age. (3) EVSE blind guard: stands down while a trusted stream tier supplies SOC (recommendation accepted). (4) Stream fields stay in the `cloud_verification` step. (5) Heartbeat help wording change taken: "(for example its grid power)" → "(for example its house load power)" — part of the build.
**Origin card:** ENVOY-STREAM-SOC-TIER-1 (`revival_2026_10_29`, `measured_2026_10_29`, `binding_constraint_3_8_2026_09_27`, `constraints`).
**Reviews answered:** `docs/reviews/code-review/plan_review_ec_source_failover_class_completeness.md` (816d691d0) and `plan_review_ec_source_failover_class_buildpred.md` (60cea4ec7 + addendum 65cdc0318). Section C maps every finding to its resolution.
**Operator requirements (2026-10-29, binding):** R1 separate production from proposals; R2 every change fixes a measured wrong behaviour; R3 fallbacks are configurable per house, unset means identical to today.
**Scope:** Energy Coordinator, house scope. No HVAC or presence code. The HVAC and presence state-of-play docs were not read because neither domain is touched.

---

## 0. Answer first

1. **What is wrong today (measured):** every night at about 23:06 the native Envoy SOC drops for 12-23 min (7 of 7 nights). EC falls through LKG (5 min) and the cloud tier (rejected as stale), then has no SOC at all for 8-17 min a night (about 1.5 h a week). With SOC None, the strategy blind hold, `blind_hold_active`, the EVSE blind guard and DP `is_blind_hold` all engage.
2. **What fixes it:** turn on the stream SOC tier that already exists in code (shipped dormant in EC degraded-data policy phase 1) and point it, by operator config, at a second local producer that stays up during those outages. In this house that is `enphase_realtime`'s battery entity, which never went down during a native outage in 7 days.
3. **What rev 2 changes from rev 1:** the cloud `last_reported` swap (old D1b) is dropped, because it re-admits a frozen cloud value that was already measured and rejected. The co-witness stamp change (old D1c) is dropped, because it removed the only frozen-producer check. The stream tier gains three guards the origin card requires: trust that is earned against native rather than assumed, a reconnect settle window, and a physics slew check. The stream max age becomes a per-house options-flow field.
4. **What stays out:** a generic failover framework, power values, house load, the reserve witness, and every other class member. Each is parked with a trigger (section B6).

---

# PART A: In production today

Develop at 816d691d0. "Live" means the code runs and acts in this house today. "Dormant" means the code ships but a switch keeps it off. "Unconfigured here" means the code is live but this house has not wired the entity.

## A1. SOC resolver and its mechanisms

| # | Mechanism | Shipped | file:line | Status here |
|---|---|---|---|---|
| A1.1 | SOC resolver tier order: native, stream, LKG (300 s), cloud (600 s) | resolver tiers v5.17.x (2026-07); degraded-data phase 1 (README_v5.103.39 validated) | `energy_battery.py:1060-1188` | **Live** (stream leg skipped) |
| A1.2 | Native SOC freshness on `last_reported`, 300 s | FROZEN-POWER-READ-STALENESS-CLASS-1 (README_v5.100.7) | `energy_battery.py:1082`, `_read_fresh_float` `:2257` | **Live** |
| A1.3 | Cloud SOC fallback, freshness on `last_updated`, 600 s, exception swallowed as pass | v5.17.5 (2026-07-15) | `energy_battery.py:1156-1175` | **Live** (cloud entity configured) |
| A1.4 | Cloud SOC divergence detector, `last_updated`, injected `now` | cloud-reliance build 2026-07-17 | `energy_battery.py:1307-1354`, `tier_ok` `:1600` | **Live** |
| A1.5 | Stream SOC tier: unit `%`, 0-100, freshness mode "a" (`last_reported` ≤ max age) or mode "b" (not unavailable + co-witness) | degraded-data phase 1, commit 651c72cfc (2026-10-04) | `_read_stream_soc` `energy_battery.py:1773-1821` | **Dormant**: `SOC_STREAM_TIER_ENABLED=False` (`energy_const.py:345`), `DEFAULT_SOC_STREAM_MAX_AGE_S=0` (`:357`). Also unconfigured here |
| A1.6 | Stream co-witness, `last_updated` ≤ 120 s ("must have CHANGED") | same | `energy_battery.py:1823-1835`, `energy_const.py:358-361` | **Dormant** (never reached) |
| A1.7 | Stream trust state machine: starts `trusted`; 2 divergent samples ≥ 60 s apart over 3 pp quarantine it; 2 agreeing restore it | same | init `energy_battery.py:636`; `_evaluate_stream_divergence` `:1866-1920` | **Dormant** |
| A1.8 | Stream trust persistence. Restore accepts only `trusted`/`quarantined` (`:1942`); anything else returns early and keeps the init value, which is `trusted` (`:636`) | same | `restore_stream_trust_snapshot` `energy_battery.py:1936-1945`; `energy.py:1846,2356` | **Dormant** |
| A1.9 | Trusted-tier set (native, stream) | degraded-data phase 1 | `SOC_TRUSTED_TIERS` `energy_battery.py:119` | **Live** |
| A1.10 | LKG, re-anchored only by trusted tiers | D2 envelope work | `energy_battery.py:1085, 1099-1100` | **Live** |
| A1.11 | SOC envelope from LKG + battery physics. Uses module constants `BATTERY_CAPACITY_KWH=40.0`, `BATTERY_MAX_CHARGE_KW=BATTERY_MAX_DISCHARGE_KW=30.72` (`energy_const.py:2383-2385`), i.e. this house's battery | D1 blind-window guard | `soc_envelope` `energy_battery.py:3384-3433` | **Live** |
| A1.11b | Battery capacity from config entity with in-session LKG, None if never read | arbitrage fix-up A-HIGH-2 | `_battery_capacity_kwh` `energy_battery.py:4820-4842`; `CONF_ENERGY_BATTERY_CAPACITY_ENTITY` `energy_const.py:1259` | **Live**, configured |
| A1.12 | `envoy_available`, native only by design | — | `energy_battery.py:3618-3650` | **Live** |
| A1.13 | Config fields: cloud fallback entity, stream entity, co-witness entity; all default unset | cloud v5.17.x; stream 651c72cfc | `energy_const.py:323,348,352`; `config_flow.py:6068-6069, 6165-6166, 7464-7477`; wired `energy.py:1182-1187` | Cloud **configured**; stream and co-witness **unconfigured here** |

## A2. SOC consumers (what reads the resolver today)

| Consumer | file:line | Keys on | Trust or display |
|---|---|---|---|
| Strategy blind hold | `energy_battery.py:6245` | SOC is None | trust |
| `blind_hold_active` (also DP snapshot `:4382`) | `energy.py:4322-4360` (`(not env_ok) and soc is None`) | SOC is None | trust |
| EVSE blind guard | `energy_pool.py:745-761` | `blind_hold_active` | trust |
| DP `is_blind_hold` and drain precedence | `energy.py:5286`, DP shadow `energy.py:5052`, `energy_drain_precedence.py:642` | `blind_hold_active` | trust |
| D2a/D3/D4 untrusted-tier holds | via `SOC_TRUSTED_TIERS` | tier | trust |
| EV start-SOC verdict | `energy.py:7800-7806` | `soc_tier_trusted` | trust |
| Untrusted-dwell NM | `energy_battery.py:2021` | tier | notification |
| Decision attribute | `energy_battery.py:8223` | tier | display |
| Boot Envoy-cache save | `energy.py:2848-2857` | tier == `envoy` | persistence |
| Attain paths (EC-ATTAIN-HOLD-WHEN-ENVOY-BLIND-1) | read `battery_soc` | SOC value | trust |
| Cloud divergence detector `tier_ok` | `energy_battery.py:1600` | tier | trust (abstain) |
| Reserve verifiability | `is_reserve_verifiable` `energy_write_verify.py:274-281` | write record age, not SOC | trust |
| `soc_resolution` tier map, `envoy_status.fallback_active` | `energy_battery.py:1486-1497`; `sensor.py:14731` | tier | display, DB |

## A3. Other multi-source values (the class, as it stands)

| Value | Producers | Freshness today | Status |
|---|---|---|---|
| Solar production | native; realtime `pv_power` | `last_reported` 180 s, LKG envelope 15 min | Live, single source |
| Battery power | native; realtime discharge | `last_reported` 180 s | Live, single source |
| Net power (EC) | native | **ungated by design** (`energy_battery.py:69-71, 2322`) | Live |
| Net power (billing) | Emporia pair, native | `last_reported` 180 s / counters 1200 s, fail-closed tick skip (`energy_billing.py:218-325`) | Live, proven |
| Solar-follow grid | Emporia primary, native fallback | `last_reported` 180 s, fail-closed unknown stamp (`energy_pool.py:4985-5000, 5028-5039`) | Live, proven reference pattern (SOLAR-FOLLOW-LOCAL-GRID-SOURCE-1, done 10-05) |
| Per-EVSE charging power | EVSE power entity | `last_updated` 180 s, fail-closed (`energy_pool.py:5322-5333`, `SOLAR_POWER_FRESH_S` `energy_const.py:1612`) | Live |
| House load (DP) | SPAN r1+r2, R1 model | no freshness gate (`energy.py:4907-4960`) | Live |
| Reserve readback witness | native reserve, cloud oracle | local unstamped, cloud `last_updated` (`energy_write_verify.py:521-570, 1190-1235, 2906-2918`) | Live, accepted C4 residual (false REVERTED page 10-29, README_v5.103.89:63) |
| Cloud settings lag | cloud oracle entities | `last_reported` with `last_updated` fallback (NM Cycle A A6, `energy_battery.py:1356-1419`) | Live, proven |

## A4. Prior decisions this plan must not reopen

- **Cloud SOC freshness by `last_reported` is NO-GO** (`DESIGN_ec_degraded_data_policy.md:325`, §9.3 P1-1; restated `PLANNING_ec_degraded_data_phase1.md:18,97`). On 10-02 the cloud kept re-reporting a frozen 10.0 % with a fresh `last_reported` while the battery rose to 29 %. Admitting by `last_reported` turned 86 % of blind minutes into confidently wrong SOC (p95 up to 25 pp).
- **Raising the cloud max age is rejected** (card `parked_alts`).
- **The reserve witness stays a separate plan** (`PLANNING_ec_reserve_witness_fix.md`, `PLANNING_ec_enphase_resilience_and_p1_adjust.md` R3).

---

# PART B: Recommended changes

## B0. Institutional context verified

**Greps (package `custom_components/universal_room_automation/`):** `last_reported|_state_age_s|SOC_STREAM|STREAM_MAX_AGE|COWITNESS|max_age` over `domain_coordinators/energy*.py`; `last_updated` over the same; `blind_hold|is_blind_hold|soc_tier_trusted` over the package; `CONF_ENERGY_STREAM|CONF_ENERGY_CLOUD` over `const.py`, `energy_const.py`, `config_flow.py`; `SOC_STREAM_TIER_ENABLED|_read_stream_soc|_setc` over `quality/tests`. Results are cited at each row.

| Proposed piece | Verdict | Existing symbol |
|---|---|---|
| Stream tier, its guards, quarantine, persistence | REUSE, enable (dormant, never live; reviewed as new) | A1.5-A1.8 |
| Earned-trust state `unproven` | NEW state value on the existing machine | extends `_soc_stream_trust` (`energy_battery.py:636`) and `_evaluate_stream_divergence` agree counter |
| Per-house stream max age field `energy_stream_battery_soc_max_age_s` | NEW CONF (rung 2). No equivalent: only the rung-1 `DEFAULT_SOC_STREAM_MAX_AGE_S` exists | sits beside `CONF_ENERGY_STREAM_BATTERY_SOC_ENTITY` (`energy_const.py:348`, `config_flow.py:7464-7477`) |
| Slew guard | REUSE | `SOCEnvelope` via `soc_envelope` physics (A1.11) |
| Reconnect settle | NEW small guard; no equivalent in EC SOC code | pattern matches the card's 3.8 constraint |
| Age helper | REUSE unchanged | `_state_age_s` (`energy_battery.py:89-111`). Rev 1's `unknown_age` keyword is dropped with D1b |

**Docs read:** the audit `AUDIT_envoy_stream_fallback_resolver_validity_2026_10_29.md`; `DESIGN_ec_degraded_data_policy.md` §9 (Q2/Q3, §9.3); `PLANNING_ec_degraded_data_phase1.md` (NO-GO note, 90 s mode-a proposal at :454); `PLANNING_envoy_telemetry_failover_map.md` §0-1; `PLANNING_ec_blind_window_evse_guard.md:166`; `PLANNING_ec_reserve_oracle_phase2.md` (rev 2.2 via audit); card ENVOY-STREAM-SOC-TIER-1 in full; `enphase_realtime` v1.0.5 source (read-only, D0-a).

## B1. Measurements

| # | Question | Result |
|---|---|---|
| M0 | Native outage pattern | `sensor.envoy_<serial>_battery` down 7 of 7 nights at 23:06-23:09 for 12.6-22.7 min (130.6 min/week) |
| M0b | EC tiers through the 10-28 outage | `primary_envoy` → `lkg` 23:09:49 → `cloud_fallback` 23:14:49 → **None** 23:17:49-23:30:19. None-tier minutes per night 10-22..10-28: 8, 9, 15, 16.5, 11.5, 14, 12.5 |
| M2 | Realtime independence | realtime battery, `load_power`, `grid_power`, `pv_power`, discharge, reserve: 0 down minutes during native outages since 10-24 13:28; 3-5 blips of 0.2-0.5 min. The production/consumption `_2` family fails with native (overlap 120.8 min), so it must never be the fallback |
| M3 | Realtime SOC quality | %, 983 rows, no zero or negative, no jump > 5 pp, 3 reconnects resumed at prior value, within 1 pp of native |
| M6 | `grid_power` unit/sign | unresolved; no power value is in scope |
| M7 | Tool trap | `ha_get_state` shows `last_reported == last_updated`; use a template or the recorder for stamps |
| Q2/Q3 (prior) | Cloud by `last_reported` | NO-GO (A4) |

### D0-a: what `enphase_realtime` writes when a poll fails (done in this revision, source read only)

Read from `/config/custom_components/enphase_realtime/` (v1.0.5, read-only):

- The battery SOC entity (`key="battery_soc"`, name "Battery") reads `/ivp/ensemble/secctrl` `agg_soc` (`sensor.py:328-333`, `envoy_client/models.py:566-589`) on the **FastCoordinator** (`coordinator.py:200-218`). That is a plain `DataUpdateCoordinator` with the default `always_update`. On a failed poll `last_update_success` goes False and the entity reports **unavailable at once** (`entity.py:94-101`, `super().available`). It does **not** re-write a cached value. A successful poll writes state every time, so `last_reported` advances even when the value is unchanged.
- The power entities (`load_power`, `grid_power`) are on the **LiveCoordinator** (`coordinator.py:92-125`). It keeps the last good values through 2 failed polls (`LIVE_FAILURES_BEFORE_UNAVAILABLE = 3`, `const.py:59`) and uses `always_update=False`, so an identical snapshot reaches no listener and `last_updated` stops moving when the Envoy's data stops moving.
- `secctrl` carries **no data timestamp**. `meters.last_update` exists only on the livedata path and is used for logging, not exposed as an entity.

**What this settles:** an integration-side frozen republish of the battery entity does not happen (BP-2's hazard is ruled out for this producer). An Envoy-side freeze (the Envoy keeps answering with stale `agg_soc`) cannot be seen from the battery entity's stamps. It can be seen from a value-moving sibling on the livedata path: if the Envoy's data stops, `load_power`'s value stops changing and its `last_updated` ages. That is exactly the current co-witness rule (A1.6), which rev 2 keeps.

### D0-b to D0-d: recorder probes (DONE 2026-10-29, `AUDIT_ec_source_failover_d0_probes_2026_10_29.md`, 8663731a9)

Window 10-24 13:28 to 10-29 21:49 (5.3 days; the realtime entities only exist from 10-24). Realtime polls: fast 30 s (SOC), live 10 s (`load_power`).

| # | Result | Decision |
|---|---|---|
| D0-b reconnects | 3 SOC reconnects (down 17-31 s); each resumed at the prior value ±1 pp; capacity sibling constant at 40000 Wh. No 0, no capacity dip | Junk not reproduced on this producer. Settle and slew stay as **safety guards** (not measured fixes); capacity check stays parked (its trigger did not fire). Settle stays 60 s |
| D0-c `load_power` change gaps | p99 11.1 s, max 261 s; only 2 gaps > 120 s, both during real disturbances (10-26 10:05, 10-28 23:05) | Co-witness window stays 120 s |
| D0-d SOC report gaps | p99 31.7 s; since 10-26 max 34.1 s | This house's max age = 120 s (4 polls) |
| Unit | battery entity `unit_of_measurement` = `%` (recorder attributes, verified 2026-10-29) | passes the stream unit guard |

**Known observation, unexplained:** three SOC report gaps of 198 s (10-24 21:20), 434 s (10-24 14:03) and 960 s (10-25 17:34), all in the first day of the trial, not bridging an unavailable state. Cause unverified (possibly integration or HA restarts). At 120 s they are rejected, fail-closed, which is the right outcome. If such gaps recur after 10-26 during a native outage, they show up as `lkg` rows in the live check; no action now.

## B2. Changes (each names the Part-A item it modifies)

### D1: Enable the stream tier with configurable freshness (modifies A1.5, A1.13)

- **Wrong behaviour it fixes:** SOC None for 8-17 min every night (M0b), which engages the blind hold, the EVSE blind guard and DP blind hold although an independent local reading is available (M2).
- **Change:**
  1. `SOC_STREAM_TIER_ENABLED` → `True` (rung 1, `energy_const.py:345`). This is safe for every house because `_stream_tier_configured()` (`energy_battery.py:1766-1771`) also needs the stream entity set. Recommendation on the master switch: **keep it a module constant, do not add a config toggle.** The per-house switch already exists as the stream entity field (unset = off), so a second toggle would duplicate it and add a config combination (toggle on, entity unset) with no meaning. The constant stays as the reviewed code-level kill switch.
  2. New options-flow field `energy_stream_battery_soc_max_age_s` next to the stream entity. Unset means `DEFAULT_SOC_STREAM_MAX_AGE_S`, which **stays 0** (mode "b", unchanged). A value > 0 selects mode "a". This keeps an MQTT `expire_after` producer working (mode "b") and lets a polled producer use mode "a" without a code change.
     - **Wiring:** a numeric option, **not** added to the `self._entities` map (`energy.py:1182-1187`), which holds entity IDs only. Read it from options into a typed attribute `BatteryStrategy._stream_max_age_s: int | None`, and have `_read_stream_soc` use it in place of `_ec.DEFAULT_SOC_STREAM_MAX_AGE_S` (fall back to the constant when None). Add it at all three config_flow sites that carry the stream entity (`config_flow.py:6068-6069`, `6165-6166`, `7464-7477` pattern) plus `strings.json` label and help text.
     - **Selector:** number selector, unit seconds, minimum 30, step 1, optional (empty = mode "b"). Help text says to use at least 3× the source's poll interval.
     - **Stuck-unproven diagnostic (other houses):** a too-small max age makes every read stale, so trust never earns and the tier never serves, silently. Add attributes on `sensor.ura_energy_coordinator_battery_strategy`: `stream_unproven_since` (ISO time) and `stream_unproven_native_fresh_s` (seconds the state has been `unproven` while native was fresh and the stream configured). No NM: there is no measured instance of this pattern, so per R2 the attribute is enough; an NM can be added if the attribute is ever seen above 1 h.
  3. Comment and NM text: replace the MQTT-specific wording (`energy_const.py:350-361`, `energy_battery.py:1912`) with "local second-source battery level". Text only.
- **Operator action (config, not code), daytime only:** set stream entity = this house's realtime battery entity, co-witness = this house's realtime `load_power`, max age = 120 s (or the D0-d value). An options write reloads the CM entry, so do it in the daytime and not while the house sleeps (parent-reload hazard).

### D2: Earned trust (modifies A1.7, A1.8)

- **Wrong behaviour it fixes:** today the stream starts `trusted` at boot and on an unreadable restore. A restart during the 23:06 window, or the first enable, serves the stream with zero comparisons against native. The legal repro from review: a realtime entry pointed at the wrong Envoy reads 55 % against a true 40 % and is served as trusted all night.
- **Change (exact):**
  1. **Init:** change `self._soc_stream_trust: str = "trusted"` at `energy_battery.py:636` to `"unproven"`. Changing only the restore is not enough, because an unknown persisted state returns early and keeps the init value.
  2. **Restore** (`restore_stream_trust_snapshot`, whitelist at `:1942`): persisted `trusted` → `unproven`; persisted `quarantined` → `quarantined`; persisted `unproven` → `unproven`; anything else → keep init (`unproven`).
  3. **Serve rule:** `_read_stream_soc(check_trust=True)` serves only when the state is `trusted`.
  4. **Earn:** in `_evaluate_stream_divergence` (runs only while native is fresh), reuse the existing counter `_stream_agree_count`. When state is `unproven` and `_stream_agree_count >= DEFAULT_SOC_STREAM_TRUST_EARN_SAMPLES` (agreeing = ≤ 3 pp, samples ≥ 60 s apart, both reused), set `trusted`. A divergent sample resets the count (existing behaviour).
  5. **Quarantine recovery:** the existing 2-tick shortcut (`:1920-1926`) changes to `quarantined` → `unproven` (counter reset), so leaving quarantine needs the same N fresh agreements as the first earn. Recovery is never easier than first earn.
  6. **Lapse:** new field `_stream_last_agree_at` (datetime, set on every agreeing compared sample, not persisted since restore yields `unproven`). The lapse check runs in `_read_stream_soc` before serving: if state is `trusted` and `now - _stream_last_agree_at > DEFAULT_SOC_STREAM_TRUST_MAX_AGE_S` (and the knob is > 0), set `unproven` and refuse. It must be in the read path, because `_evaluate_stream_divergence` returns early while native is down (`:1880-1883`) and would never fire during the outage it bounds.
- **Consequence:** a restart during an outage is blind until native returns, which is today's behaviour, not a regression. A correlated or mis-wired producer in another house is never served without live agreement (answers the review's LOW-3 for every house).

### D3: Reconnect settle and slew backstop (SAFETY GUARD, not a measured fix; modifies A1.5; card binding constraint 3.8 and the device-completeness constraint)

- **Why (R2, stated honestly):** this is a safety guard required by the origin card, not a fix for a measured fault on this producer. D0-b found no junk in 3 realtime reconnects. The hazard is measured on the same Envoy through another path: 09-26 23:14:11 the Envoy's data said SOC 0 then the true 36 for about 36 s; 09-25 a partial fleet produced 0 → 87 → 20 while the battery sat near 95 %. Quarantine cannot catch either, because it only compares while native is fresh, and native is down at that moment.
- **Change:**
  1. **Settle, inside `_read_stream_soc`** (so both callers, the resolver and `_evaluate_stream_divergence`, honour it and junk never enters a comparison or resets the earn count). New field `_stream_settle_until` (datetime, not persisted). It is armed in two ways:
     - (a) the read sees the entity `unavailable` or `unknown`: set `_stream_settle_until = None` and remember `_stream_seen_unavailable = True`; the next numeric read arms `_stream_settle_until = st.last_changed + SETTLE`.
     - (b) sub-tick drops that no read observed (blips of 17-31 s are shorter than a 30 s tick): on each numeric read, if `st.last_changed` is newer than the previous read's time (`_stream_last_read_at`, new field) **and** the value differs from the previous read value by more than `DEFAULT_SOC_STREAM_SLEW_MARGIN_PCT`, treat it as a possible reconnect and arm `_stream_settle_until = st.last_changed + SETTLE`. A normal 1 pp step does not arm it.
     While `now < _stream_settle_until`, the read returns None. A 0 that directly follows unavailable is therefore never served or compared.
  2. **Slew backstop.** Reference = the **last trusted native value** and its time (`_soc_native_last_value`, `_soc_native_last_at`, set where the native tier is served; not the LKG, which every served stream read re-anchors). A stream value is rejected when `|stream - native_ref| > rate_pp_per_s × (now - native_ref_at) + DEFAULT_SOC_STREAM_SLEW_MARGIN_PCT`, with `rate = max(charge, discharge kW) / capacity_kWh × 100 / 3600`. With no native reference this session, the check abstains (the stream cannot be `trusted` without native anyway, D2).
     - This is a **coarse backstop**. It catches the 0-class and gross junk. It does not catch an 8 pp partial-fleet error once more than a few minutes have passed since native's last value (at this house's 1.28 pp/min, 8 pp exceeds the bound only for about the first 4 min).
     - The margin (3 pp, same as the divergence threshold) absorbs integer-% steps: native 40 then stream 41 after 30 s gives |Δ| = 1 ≤ 0.64 + 3, so it is served.
  3. **Physics source (R3):** capacity comes from the existing configured capacity entity via `_battery_capacity_kwh()` (`energy_battery.py:4820`, REUSED, `CONF_ENERGY_BATTERY_CAPACITY_ENTITY`), falling back to `BATTERY_CAPACITY_KWH`. No configurable charge/discharge rate exists; the rates stay `BATTERY_MAX_CHARGE_KW` / `BATTERY_MAX_DISCHARGE_KW` (30.72 kW). **Recorded R3 limitation:** a house with a slower battery gets a wider (weaker) backstop, never a tighter one that would refuse good values, unless its battery is faster than 30.72 kW. Making the rates config is not proposed: no measured benefit (R2). Revival trigger: a second install whose battery rates differ.
- **Card constraint (c), "age from the payload timestamp":** cannot be met literally for this producer, because `secctrl` has no timestamp (D0-a). Rev 2 meets its intent instead: the integration marks the entity unavailable on a failed poll (no integration-side frozen republish), and an Envoy-side freeze stops `load_power` changing, which kills the co-witness (A1.6, kept on `last_updated`). The operator is asked at checkpoint to accept this substitution in writing. A producer that does expose a payload timestamp is a later option (B6).

### D3/D2 rev 3.1 clarifications (binding)

- **MEDIUM-R3-1:** the slew check runs only on serving reads (`check_trust=True`) or when native is stale. It never runs on the divergence-comparison read (`check_trust=False`), so a real divergence still reaches quarantine. Test: `test_native_fresh_stream_plus_5pp_quarantined`.
- **LOW-R3-2:** if `_battery_capacity_kwh()` returns None or ≤ 0, use `BATTERY_CAPACITY_KWH`.
- **LOW-R3-3:** the trust-lapse check runs only on serving reads (`check_trust=True`).
- **RC-1:** "previous read value" for settle arm (b): if the previous read returned None (unavailable, stale, settling), treat it as no jump. Settle was already armed by arm (a) on the unavailable read.
- **RC-2:** an NM for "stuck unproven" is parked. Revival trigger, recorded on card ENVOY-STREAM-SOC-TIER-1: `stream_unproven_native_fresh_s` seen above 3600 s in any house.
- **Native reference fields** (`_soc_native_last_value`, `_soc_native_last_at`) are written on the native path even when no stream is configured. They are internal only; resolver output, tier labels and attributes are unchanged, so INV-SF4 holds. The INV-SF4 test asserts this.

## B2a. Config surface (operator-visible)

Everything below appears in the options flow, step `cloud_verification` ("Battery cloud verification (advanced)", `strings.json:1163`). Labels follow the repo style: a short phrase for the label, a plain sentence for the help.

### 1. NEW field: `energy_stream_battery_soc_max_age_s`

| Item | Value |
|---|---|
| Placement | step `cloud_verification`, directly after `energy_stream_cowitness_entity`, same `vol.Optional` + `description={"suggested_value": ...}` pattern as `config_flow.py:7464-7477` |
| Selector | `NumberSelector`, mode box, unit `s`, min 0, max 3600, step 10. 0 = off. Validation: a non-zero value below 30 is rejected with a form error |
| Default | none (optional). Unset or 0 = mode "b", identical to today |
| Label | **Local battery stream max age (s)** |
| Help | Optional. Ignore the local battery stream when its last report is older than this. Use a few times the stream's update interval (for example 120 for a sensor that updates every 30 s). Leave blank or 0 for a stream that goes unavailable by itself when it stops (such as an MQTT sensor with expire_after); then the heartbeat sensor is used instead. |
| This house | 120 (operator action, daytime) |

### 2. CHANGED help text: `energy_stream_battery_soc_entity`

| Item | Value |
|---|---|
| Label | unchanged: **Local battery stream** |
| Help today (`strings.json:1182`) | Optional. A fast local battery-level sensor used when the battery gateway integration drops out. |
| Help after | Optional. A fast local battery-level sensor used when the battery gateway integration drops out. Pick one from a different integration that stays up when the gateway drops; a sensor that fails at the same time gives no protection. |

Note for the operator: the existing heartbeat help (`strings.json:1183`) gives "its grid power" as the example. This plan recommends a sensor whose value always moves (`load_power` here; `grid_power` can sit near zero). Optional text change, not required: replace "(for example its grid power)" with "(for example its house load power)".

### 3. CHANGED step description: `cloud_verification`

Append one sentence: "The local battery stream fields set a second local source for battery level."

Placement oddity (pre-existing): the stream fields live in a step named for cloud verification. Recommendation: do NOT move them. Moving fields between options steps risks breaking the options round-trip for saved values. The operator can override.

### 4. Code constants NOT shown in the UI (rung 1, review-gated)

| Constant | Value | Why it stays code |
|---|---|---|
| `SOC_STREAM_TIER_ENABLED` | True | master kill switch for a trusted SOC tier; the per-house on/off is the stream entity field |
| `DEFAULT_SOC_STREAM_TRUST_EARN_SAMPLES` | 3 | how much agreement with the main source earns trust; a safety bound |
| `DEFAULT_SOC_STREAM_TRUST_MAX_AGE_S` | 21600 (6 h) | how long the stream may serve without a cross-check; a safety bound |
| `DEFAULT_SOC_STREAM_SLEW_MARGIN_PCT` | 3.0 | tolerance of the physics backstop; loosening it weakens the junk guard |
| `DEFAULT_SOC_STREAM_RECONNECT_SETTLE_S` | 60 | wait after a reconnect before trusting a value; a safety window |
| `DEFAULT_SOC_STREAM_COWITNESS_MAX_AGE_S` | 120 | how long the heartbeat may stay unchanged; the frozen-source detector |

### 5. Diagnostic attributes on `sensor.ura_energy_coordinator_battery_strategy`

| Attribute | Meaning |
|---|---|
| `stream_trust` (existing) | `disabled`, `unproven`, `trusted` or `quarantined` (`unproven` is new) |
| `stream_unproven_since` (new) | when the stream last entered `unproven` |
| `stream_unproven_native_fresh_s` (new) | seconds the stream has stayed `unproven` while the main source was up, i.e. while it could have earned trust. A large value means the stream is misconfigured (for example max age too small) |
| `soc_resolution.tier` (existing) | `local_stream` when the stream is serving |


### D4: Builder brief rules (no Part-A change)

- No entity ID, serial, `_2` suffix, unit, sign or time window (23:06) anywhere in `custom_components/`: not in defaults, migrations, auto-population or NM text. Tests use synthetic entity IDs.
- `_state_age_s` is not modified. Rev 1's `unknown_age` keyword and its `now=` question go away with D1b.
- Slice 2 items (B6) are not in this build.

## B3. Dropped from rev 1

| Rev 1 item | Decision | Reason |
|---|---|---|
| D1b: cloud fallback and divergence detector on `last_reported` | **Dropped, parked** | A4 NO-GO. A fresh `last_reported` on the cloud entity shows the integration polled, not that Enphase has new data; 10-02 measured a frozen 10 % served as fresh. The blind hold, EVSE blind guard and DP blind hold key on SOC being None, not on tier, so an admitted cloud value would release them on an untrusted, possibly frozen reading. **Revival trigger:** a replay over ≥ 7 days showing cloud-vs-Envoy |diff| p95 ≤ 3 pp for cloud readings admitted only by `last_reported`, or a cloud data-age entity (`CONF_ENERGY_CLOUD_LAST_SUCCESS_ENTITY`, `energy_const.py:641`) proven to track Enphase data age |
| D1b fail-closed unknown age alone | **Dropped** | no measured wrong behaviour; the swallow-and-pass at `:1172-1175` has never been observed to fire |
| D1c: co-witness on `last_reported` | **Dropped** | it would turn the only Envoy-freeze detector into a liveness ping from the same poller. Co-witness stays on `last_updated` with a value-moving sibling |
| `unknown_age` keyword | **Dropped** | only consumer was D1b |
| `DEFAULT_SOC_STREAM_MAX_AGE_S = 120` as a global | **Replaced** by the per-house field (D1.2); the constant stays 0 |

## B4. Consumer behaviour when the stream tier serves SOC

The stream is a trusted tier, so consumers behave as they do with native SOC. Cloud behaviour is unchanged (D1b dropped).

| Consumer | Today in the outage | With stream serving | Intended? |
|---|---|---|---|
| Strategy blind hold `energy_battery.py:6245` | holds | does not hold | yes, the fix |
| `blind_hold_active` `energy.py:4322-4360` | True | False | yes |
| EVSE blind guard `energy_pool.py:745-761` | engages | does not engage | **ruling needed at checkpoint.** The guard exists for "SOC unknown". Recommendation: accept, resting only on SOC being known from a trusted tier. Reserve-write verifiability (`is_reserve_verifiable`, `energy_write_verify.py:274-281`) is keyed on the write record's age, not SOC, and this plan does not change it; no claim is made about its value during the outage |
| DP `is_blind_hold`, drain precedence `energy.py:5286, 5052`, `energy_drain_precedence.py:642` | blind | normal drain logic | yes |
| D2a/D3/D4 untrusted holds | LKG and cloud are untrusted | not engaged | yes (stream already in `SOC_TRUSTED_TIERS`) |
| EV start-SOC verdict `energy.py:7800-7806` | untrusted | trusted | yes |
| Untrusted-dwell NM `energy_battery.py:2021` | can fire | does not fire | yes |
| Attain paths | no SOC or LKG | stream SOC | yes; makes EC-ATTAIN-HOLD-WHEN-ENVOY-BLIND-1 rarer; that card is listed as affected |
| Cloud divergence `tier_ok` `:1600` | abstains on LKG | abstains on stream | yes, stated |
| Boot Envoy-cache save `energy.py:2848-2857` | not saved | not saved (only `envoy`) | yes; a stream value is not cached for boot |
| LKG re-anchor `:1099-1100` | — | re-anchored by each served stream read | yes; gives one-miss tolerance |
| `envoy_available`, reserve oracle | native only | unchanged | yes, must not change |
| Stream quarantine NM `:1912` | dormant | can fire while native is up | yes |

## B5. Falsifiable invariants

| ID | Invariant | Holds today? |
|---|---|---|
| INV-SF2 | `battery_soc` is None only when every configured producer is missing, unavailable, wrong unit or range, stale, or (stream) not `trusted`, settling, or outside the envelope. Falsified by: a tick with tier None while the stream entity is numeric, %, fresh by the house's max age, settled, inside the envelope and `trusted` | new |
| INV-SF3 | Cloud never yields a trusted tier; `envoy_available` never reads a fallback | holds today, must keep |
| INV-SF4 | Stream entity unset → every resolver output, tier label, `_soc_source_last` and trust attribute is identical to develop, with the shipped constants (not monkeypatched) | new (the real second-house test) |
| INV-SF5 | One stream miss while native is down drops to LKG, not None | new |
| INV-SF6 | The stream is never served unless it has agreed with native `N` times since boot or restore and within the trust max age | new |
| INV-SF7 | A stream value is never served or compared within the settle window after the entity was unavailable (observed by a read, or inferred from `last_changed` plus a jump above the margin), and never when it lies outside the native-referenced bound (rate × elapsed + margin). Falsified by: the sequence unavailable, 0, 36 serving or comparing 0; or a sub-tick blip followed by 0 being served. Not claimed: catching a partial-fleet error smaller than the bound | new |
| INV-SF8 | No served stream value comes from a producer whose value-moving co-witness has not changed within its window (when configured) | holds in code, dormant |

Config extremes for build reviewer D: house max age < native 300 s and > LKG 300 s; max age unset with entity set (mode "b", co-witness required); co-witness unset in mode "a"; trust earn samples = 1 and very large; trust max age 0; settle 0; stream quarantined or unproven at the moment native drops; one divergent sample then native down (accepted residual: at most one sample ≤ 3 pp apart); boot during the outage; stream wired to a %-unit correlated entity (rejected by D2, never earns trust while native is down).

## B6. Knobs

| Name | Rung | Value | Why this rung | Kill-switch semantics |
|---|---|---|---|---|
| `SOC_STREAM_TIER_ENABLED` | 1 | True | trust-tier entry is a reviewed decision; per-house enable is the entity field | False = tier off everywhere, identical to today |
| `energy_stream_battery_soc_entity` (existing) | 2 | operator sets | per-house wiring | unset = tier off |
| `energy_stream_cowitness_entity` (existing) | 2 | operator sets | per-house | unset = skipped in mode "a"; tier refuses in mode "b" |
| `energy_stream_battery_soc_max_age_s` (**new**) | 2 | unset; this house 120 (D0-d p99 31.7 s); selector min 30 | depends on the producer's cadence and stamping | unset or 0 = mode "b" |
| `DEFAULT_SOC_STREAM_MAX_AGE_S` (existing) | 1 | 0 (unchanged) | default for unset field | — |
| `DEFAULT_SOC_STREAM_COWITNESS_MAX_AGE_S` (existing) | 1 | 120 (kept; D0-c p99 11 s) | protocol window | — |
| `DEFAULT_SOC_STREAM_TRUST_EARN_SAMPLES` (**new**) | 1 | 3 | safety bound on trust; should need review to change | 1 = trust after one agreement (weakest); not a disable |
| `DEFAULT_SOC_STREAM_TRUST_MAX_AGE_S` (**new**) | 1 | 21600 (6 h, same span as the LKG envelope `energy_const.py:2391`) | bounds how long the stream serves without a native cross-check; the longest native SOC dropout in the 7-day sample in `DESIGN_ec_degraded_data_policy.md` §9 (dropout histogram row, "Longest 232, 224, 188 ... min") was 232 min, so 6 h covers it | 0 = no lapse |
| `DEFAULT_SOC_STREAM_SLEW_MARGIN_PCT` (**new**) | 1 | 3.0 (same as `DEFAULT_SOC_DIVERGENCE_THRESHOLD_PCT`) | absorbs integer-% quantisation and stream-vs-native offset (M3 ≤ 1 pp); also the jump size that arms settle on an unobserved reconnect | 100 = slew check off |
| `DEFAULT_SOC_STREAM_RECONNECT_SETTLE_S` (**new**) | 1 | 60 (observed native-path junk lasted 36 s; D0-b reconnects 17-31 s, no junk; kept) | safety window; cost to any house is at most 60 s on LKG, which covers 300 s | 0 = no settle |
| quarantine ticks, spacing, 3 pp threshold (existing) | 1 | 2, 60 s, 3 pp | proven | — |

**Options-flow help text (R3):** for the stream entity: "A second local battery level that keeps reporting when the main source drops. Do not pick an entity from the same integration path as the main source; if it fails at the same time, it gives no protection. URA uses it only after it has agreed with the main source several times." For the max age: "How old the reading may be, in seconds. Use a value a few times the source's poll interval. Leave empty for sources that go unavailable on their own when they stop reporting (for example MQTT with expire_after)."

**How other houses configure it:**

| House | Configuration | Result |
|---|---|---|
| No second local source | stream unset | identical to today (INV-SF4) |
| Cloud only | stream unset, cloud set | identical to today; cloud keeps the `last_updated` gate |
| `enphase_realtime` (polled) | stream = its battery entity, co-witness = a value-moving power entity from the same integration, max age ≈ 4× fast poll | mode "a" |
| MQTT stream with `expire_after` | stream = MQTT battery entity, co-witness = a value-moving MQTT entity, max age empty | mode "b" (as designed in phase 1) |
| Realtime-only (no native integration) | native SOC entity unset | the stream never earns trust (no native to compare), so it is never served. Recorded limitation: such a house should configure the realtime entity as the primary SOC entity instead |

**Parked (slice 2 or later), each with a trigger:**

| Item | Trigger |
|---|---|
| Cloud `last_reported` (old D1b) | see B3 |
| Solar production second source | a daytime native production outage longer than the 15-min envelope |
| Battery power second source | a drain decision held or mis-armed during a native outage; realtime discharge sign verified first |
| Net power (EC) | a trust consumer found acting on a frozen value; M6 resolved first |
| Per-EVSE power `energy_pool.py:5322-5333` (`last_updated`) | in class (same stamp question). No measured wrong behaviour yet: it fails closed to `STALE_POWER` and EVSE power at steady current may or may not hold a constant value. Trigger: a recorder count of `STALE_POWER` ticks while the EVSE was charging at steady current |
| House-load SPAN freshness | a SPAN freeze measured that changes a DP decision under the live `max_span_r1` default |
| Battery-capacity completeness check | a capacity dip or first-value 0 on reconnect (D0-b: did not fire) |
| Configurable battery charge/discharge rates | a second install whose rates differ from 30.72 kW (D3 R3 limitation) |
| Payload-timestamp stamping | a producer exposes a data timestamp entity |
| Reserve witness | own plan (A4) |
| EVSE status | a measured outage that changes a decision |

## B7. Tests and live validation

**Tests (synthetic entity IDs, config-driven, injected or frozen clock with ≥ 10 s margins):**

- `test_stream_entity_unset_byte_identical_shipped_constants` (INV-SF4; no monkeypatch of module constants).
- `test_shipped_stream_constants` asserts `SOC_STREAM_TIER_ENABLED is True` and `DEFAULT_SOC_STREAM_MAX_AGE_S == 0` without patching.
- `test_stream_serves_when_native_down_mode_a_via_config_max_age` (max age from the options field, not a patched constant).
- `test_stream_mode_b_when_max_age_unset`.
- `test_stream_stale_last_reported_rejected` (60 s fresh vs 180 s stale against a 120 s field).
- `test_stream_unproven_at_boot_not_served`, `test_stream_earns_trust_after_n_agreements`, `test_restore_trusted_becomes_unproven`, `test_restore_quarantined_stays`, `test_trust_lapses_after_max_age`.
- `test_boot_during_native_outage_stays_blind` (today's behaviour).
- `test_reconnect_sequence_unavailable_0_36_never_serves_0` (card 3.8 test).
- `test_stream_slew_backstop_rejects_zero_after_20_min` (native last 95, stream 0 at +20 min: bound 25.6 + 3 pp, rejected).
- `test_stream_slew_backstop_rejects_87_within_3_min` (native last 95, stream 87 at +3 min: bound 3.8 + 3 pp, rejected); `test_stream_slew_backstop_allows_87_after_10_min` documents the coarse limit.
- `test_stream_one_pp_step_served` (native 40, then stream 41 after 30 s: served).
- `test_stream_slew_uses_config_capacity_entity` (capacity entity 13.5 kWh narrows nothing it shouldn't: bound computed from config, fallback to constant when unset).
- `test_sub_tick_blip_then_zero_arms_settle` (`last_changed` newer than the last read, jump > 3 pp: not served, not compared).
- `test_settle_junk_never_reaches_comparison` (native fresh, stream reconnects at 0: no divergent sample counted).
- `test_quarantine_recovery_needs_n_agreements` (quarantined → unproven → trusted only after N).
- `test_trust_lapse_fires_in_read_path_while_native_down`.
- `test_restore_unproven_stays_unproven`, `test_init_state_is_unproven`.
- `test_max_age_option_not_in_entity_map` and `test_stream_unproven_native_fresh_attribute_counts`.
- `test_one_divergent_sample_then_native_down_residual`.
- `test_cowitness_frozen_value_refuses_stream` (co-witness `last_updated` stays the stamp).
- `test_envoy_available_ignores_stream` (INV-SF3).

**Mutation drills (build review C):** remove the `age is None` half and the `age > max_age` half at `energy_battery.py:1810` separately; bypass the `unproven` check; bypass settle arm (a) and arm (b) separately; bypass the slew check; replace the native reference with the LKG; restore the 2-tick quarantine shortcut; move the lapse check out of `_read_stream_soc`; revert the init at `:636`; read max age from the constant instead of the field. Each must turn a named test red.

**Live validation (no timing luck):**

1. **Operator action, daytime, same day as deploy:** set the three fields (D1). The CM entry reloads.
2. **Gate before 23:00, any time native is up:** `sensor.ura_energy_coordinator_battery_strategy` shows `stream_trust` = `unproven` right after the reload, then `trusted` within about 5 min (3 samples 60 s apart), `stream_unproven_native_fresh_s` back to 0, while `soc_resolution.tier` stays `primary_envoy`. This proves the earn path and that the stream is never served while native is fresh. Under "not configured" the attribute reads `disabled`, which tells the two cases apart.
3. **First native outage (7 of 7 nights measured, so expected the first night):** one recorder query the next morning over the window when native SOC was unavailable: tier = `local_stream` for every row after the first settle, zero rows with tier None, `blind_hold_active` False. Under "stream not serving" the rows show `lkg` then None as on 10-28. If no native outage occurs within 3 nights, the benefit claim is moot: record it and dispose of the card as met by absence, with the in-suite proof standing.
4. **First 24 h:** zero `soc_stream_divergence` NM pages while native is up (M3: within 1 pp).

Results are written back into the README as a validated table.

## B8. Tier

**Tier 3.** The change enables a trusted SOC tier that releases protective holds (blind hold, EVSE blind guard, DP, D2a/D3/D4) and is consumed at about a dozen decision sites (A2), so one missed site loses money or safety (Bug Class #53).

Process: the changed sections of this rev 2 (Part B, A4, C) go to a re-review by both plan reviewers before the operator checkpoint. Then build by `ura-super-builder`, four build reviews (A local, B integration and restart with trust restore, C per-site mutation, D falsifying INV-SF2..SF8 at the config extremes above), orchestrator re-verification, and an operator checkpoint before deploy covering: the EVSE blind guard ruling (B4), the constraint (c) substitution (D3), and the daytime config step.

## B9. Non-goals

- No change to the native integration, the `enphase_realtime` configuration, `envoy_available`, `SOC_TRUSTED_TIERS`, the cloud tier, `net_power_w`, the reserve witness, or any write path.
- No generic resolver, no auto-pairing.
- No restart beyond the deploy restart, which respects the sleep rule.

---

# PART C: Review findings and resolutions

| Finding | Resolution |
|---|---|
| CRITICAL-1 / BP-1 cloud `last_reported` re-admits a frozen value | D1b dropped and parked with a replay trigger (B3, A4) |
| HIGH-1 / BP-2 card constraints, frozen republish | D0-a source read: no integration-side republish; D3 settle + envelope slew; co-witness kept as Envoy-freeze detector; constraint (c) substitution goes to the operator |
| HIGH-2 / BP-6 co-witness | D1c dropped; co-witness stays on `last_updated` with a value-moving sibling; D0-c sizes its window |
| HIGH-3 / BP-3 trust at boot | D2 `unproven` state, N and max-age knobs |
| MEDIUM-1 per-EVSE `last_updated` | in class, parked with a measurable trigger (B6) |
| MEDIUM-2 consumers | B4 table |
| MEDIUM-3 / BP-4 injected `now` | moot: `_state_age_s` not modified |
| MEDIUM-4 D1b live criterion | moot (D1b dropped) |
| BP-5 `unknown_age` | dropped |
| BP-7 test authority | config-driven tests, unpatched-constant test, unset-entity identity test, frozen clock, both mutation halves |
| BP-8 live depends on config | operator step stated, daytime; pre-23:00 trust gate |
| BP-9 one-sample residual | config-extreme test + accepted residual (B5) |
| LOW-1 / BP-10 / MEDIUM-6 max age global | per-house field; constant stays 0 so mode "b" houses are unchanged; the phase-1 90 s proposal is replaced by the per-house value |
| LOW-2 reserve witness links | A4 |
| LOW-3 correlated fallback | D2 earned trust + help-text warning |
| MEDIUM-R2-1 / RB-1 house-specific physics | D3.3: capacity REUSES the configured capacity entity; rates stay constants, R3 limitation recorded with trigger |
| MEDIUM-R2-2 / RB-1 quantisation, re-anchor | D3.2: reference = last trusted native value + elapsed-time bound + 3 pp margin knob; called a coarse backstop; 1 pp step test |
| LOW-R2-3 | D3 labelled a safety guard, not a measured fix |
| LOW-R2-4 | 232 min cited to DESIGN §9 dropout histogram |
| RB-2 earn/recovery/lapse | D2 exact steps: init at :636, restore table, `_stream_agree_count`, recovery via `unproven` with same N, `_stream_last_agree_at`, lapse in read path |
| RB-3 settle placement, sub-tick blips | D3.1: in `_read_stream_soc`; arm by observed unavailable or `last_changed` + jump |
| RB-4 max-age wiring | D1.2: typed attribute, not entity map; 3 config_flow sites + strings; min 30; stuck-unproven attribute, no NM (R2) |
| RB-5 EVSE ruling | B4 rests on SOC known only |
| RB-6 restore wording | A1.8 corrected |
| D0 probes | B1: 120/120/60 kept; 3 early gaps recorded; capacity check parked; unit % verified |
| MEDIUM-5 / OR-1 production vs proposed | Part A / Part B split; invariants tagged |
| OR-2 unproven benefit | each B2 change states the wrong behaviour and its measurement; unmeasured items parked |
| OR-3 hard-coding | D4 forbid list; second-house table |
