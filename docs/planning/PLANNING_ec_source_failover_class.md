# PLANNING: EC source failover as a class (multi-producer values, freshness stamps, untrusted fallbacks)

**Revision:** rev 2, 2026-10-29 (rev 1 = cdf67a490). **Status:** revised after two plan reviews; the changed sections go back to a re-review before the operator checkpoint. **Tier:** 3 (section B7).
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
| A1.8 | Stream trust persistence; unreadable restores to `trusted` | same | `restore_stream_trust_snapshot` `energy_battery.py:1936-1945`; `energy.py:1846,2356` | **Dormant** |
| A1.9 | Trusted-tier set (native, stream) | degraded-data phase 1 | `SOC_TRUSTED_TIERS` `energy_battery.py:119` | **Live** |
| A1.10 | LKG, re-anchored only by trusted tiers | D2 envelope work | `energy_battery.py:1085, 1099-1100` | **Live** |
| A1.11 | SOC envelope from LKG + battery physics (capacity, max charge and discharge kW) | D1 blind-window guard | `soc_envelope` `energy_battery.py:3384-3433` | **Live** |
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

### D0-b to D0-d: recorder probes to run before build (read-only, ura-prober, about 15 min)

| # | Probe | Go/no-go use |
|---|---|---|
| D0-b | For every unavailable→numeric transition of the realtime battery entity and its `battery_capacity` sibling in the recorder: the first 3 values and their spacing | Sizes the settle window. If any first value is 0 or the capacity sibling dips, the slew guard and settle are confirmed necessary on this producer, and the capacity check (parked in B6) is revived |
| D0-c | `load_power` gaps between value changes (`last_updated`), p99 and max over 7 days | The co-witness window (120 s) must exceed the p99 gap. If not, the window moves up or another value-moving sibling is chosen |
| D0-d | Realtime battery entity `last_reported` gap p99 and max over 7 days, outside the blips | Sets this house's stream max age value (expected 30 s poll, so 120 s gives 4 polls) |

## B2. Changes (each names the Part-A item it modifies)

### D1: Enable the stream tier with configurable freshness (modifies A1.5, A1.13)

- **Wrong behaviour it fixes:** SOC None for 8-17 min every night (M0b), which engages the blind hold, the EVSE blind guard and DP blind hold although an independent local reading is available (M2).
- **Change:**
  1. `SOC_STREAM_TIER_ENABLED` → `True` (rung 1, `energy_const.py:345`). This is safe for every house because `_stream_tier_configured()` (`energy_battery.py:1766-1771`) also needs the stream entity set. Recommendation on the master switch: **keep it a module constant, do not add a config toggle.** The per-house switch already exists as the stream entity field (unset = off), so a second toggle would duplicate it and add a config combination (toggle on, entity unset) with no meaning. The constant stays as the reviewed code-level kill switch.
  2. New options-flow field `energy_stream_battery_soc_max_age_s` next to the stream entity. Unset means `DEFAULT_SOC_STREAM_MAX_AGE_S`, which **stays 0** (mode "b", unchanged). A value > 0 selects mode "a". This keeps an MQTT `expire_after` producer working (mode "b") and lets a polled producer use mode "a" without a code change.
  3. Comment and NM text: replace the MQTT-specific wording (`energy_const.py:350-361`, `energy_battery.py:1912`) with "local second-source battery level". Text only.
- **Operator action (config, not code), daytime only:** set stream entity = this house's realtime battery entity, co-witness = this house's realtime `load_power`, max age = 120 s (or the D0-d value). An options write reloads the CM entry, so do it in the daytime and not while the house sleeps (parent-reload hazard).

### D2: Earned trust (modifies A1.7, A1.8)

- **Wrong behaviour it fixes:** today the stream starts `trusted` at boot and on an unreadable restore. A restart during the 23:06 window, or the first enable, serves the stream with zero comparisons against native. The legal repro from review: a realtime entry pointed at the wrong Envoy reads 55 % against a true 40 % and is served as trusted all night.
- **Change:** add a state `unproven`. Boot and every restore start at `unproven`, except a restored `quarantined`, which stays quarantined. `_read_stream_soc` serves only when the state is `trusted`. The existing comparison loop (`_evaluate_stream_divergence`, which runs only while native is fresh) moves `unproven` to `trusted` after `DEFAULT_SOC_STREAM_TRUST_EARN_SAMPLES` consecutive agreeing compared samples (≤ 3 pp, ≥ 60 s apart, both reused). A divergent sample resets the count. Earned trust lapses back to `unproven` when the last agreeing comparison is older than `DEFAULT_SOC_STREAM_TRUST_MAX_AGE_S`.
- **Consequence:** a restart during an outage is blind until native returns, which is today's behaviour, not a regression. A correlated or mis-wired producer in another house is never served without live agreement (answers the review's LOW-3 for every house).

### D3: Reconnect settle and slew guard (modifies A1.5; card binding constraint 3.8 and the device-completeness constraint)

- **Wrong behaviour it guards against (measured on this Envoy):** 09-26 23:14:11, after a re-enumeration, the Envoy's data said SOC 0 then the true 36 for about 36 s; 09-25 a partial fleet produced 0 → 87 → 20 while the battery sat near 95 %. Quarantine cannot catch either, because it only compares while native is fresh, and native is down at that moment. M3 (3 clean reconnects) shows it has not happened on the realtime battery entity yet; D0-b checks the full history.
- **Change:**
  1. **Settle:** when the resolver reads the stream entity as unavailable or unknown, it records the time. The first numeric value after that is not served until `DEFAULT_SOC_STREAM_RECONNECT_SETTLE_S` has passed with the entity numeric. A 0 that directly follows unavailable is therefore never served.
  2. **Slew:** when an LKG envelope exists (`soc_envelope` physics, A1.11), a stream value outside it is rejected for that tick. The envelope bounds how far SOC can move given the battery's charge and discharge rates since the LKG, so a partial-fleet 0 or 87 against a 95 % LKG is rejected without any device count. This is generic: it needs no microinverter count, serial or MQTT field.
- **Card constraint (c), "age from the payload timestamp":** cannot be met literally for this producer, because `secctrl` has no timestamp (D0-a). Rev 2 meets its intent instead: the integration marks the entity unavailable on a failed poll (no integration-side frozen republish), and an Envoy-side freeze stops `load_power` changing, which kills the co-witness (A1.6, kept on `last_updated`). The operator is asked at checkpoint to accept this substitution in writing. A producer that does expose a payload timestamp is a later option (B6).

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
| EVSE blind guard `energy_pool.py:745-761` | engages | does not engage | **ruling needed at checkpoint.** The guard exists for "SOC unknown". Reserve-write verifiability is a separate check (`is_reserve_verifiable`, `energy_write_verify.py:274-281`) that is unchanged and still false in the outage. Recommendation: accept, because SOC is known and the reserve check still guards writes |
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
| INV-SF7 | A stream value is never served within the settle window after the resolver saw it unavailable, and never outside the LKG envelope when one exists. Falsified by the sequence unavailable, 0, 36 serving 0 | new |
| INV-SF8 | No served stream value comes from a producer whose value-moving co-witness has not changed within its window (when configured) | holds in code, dormant |

Config extremes for build reviewer D: house max age < native 300 s and > LKG 300 s; max age unset with entity set (mode "b", co-witness required); co-witness unset in mode "a"; trust earn samples = 1 and very large; trust max age 0; settle 0; stream quarantined or unproven at the moment native drops; one divergent sample then native down (accepted residual: at most one sample ≤ 3 pp apart); boot during the outage; stream wired to a %-unit correlated entity (rejected by D2, never earns trust while native is down).

## B6. Knobs

| Name | Rung | Value | Why this rung | Kill-switch semantics |
|---|---|---|---|---|
| `SOC_STREAM_TIER_ENABLED` | 1 | True | trust-tier entry is a reviewed decision; per-house enable is the entity field | False = tier off everywhere, identical to today |
| `energy_stream_battery_soc_entity` (existing) | 2 | operator sets | per-house wiring | unset = tier off |
| `energy_stream_cowitness_entity` (existing) | 2 | operator sets | per-house | unset = skipped in mode "a"; tier refuses in mode "b" |
| `energy_stream_battery_soc_max_age_s` (**new**) | 2 | unset; this house 120 (D0-d) | depends on the producer's cadence and stamping | unset or 0 = mode "b" |
| `DEFAULT_SOC_STREAM_MAX_AGE_S` (existing) | 1 | 0 (unchanged) | default for unset field | — |
| `DEFAULT_SOC_STREAM_COWITNESS_MAX_AGE_S` (existing) | 1 | 120 (D0-c may raise it) | protocol window | — |
| `DEFAULT_SOC_STREAM_TRUST_EARN_SAMPLES` (**new**) | 1 | 3 | safety bound on trust; should need review to change | 1 = trust after one agreement (weakest); not a disable |
| `DEFAULT_SOC_STREAM_TRUST_MAX_AGE_S` (**new**) | 1 | 21600 (6 h, same span as the LKG envelope `energy_const.py:2391`) | bounds how long the stream serves without a native cross-check; the longest measured native dropout in the 7-day DESIGN §9 sample was 232 min | 0 = no lapse |
| `DEFAULT_SOC_STREAM_RECONNECT_SETTLE_S` (**new**) | 1 | 60 (observed junk lasted 36 s; D0-b may adjust) | safety window; cost to any house is at most 60 s on LKG, which covers 300 s | 0 = no settle |
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
| Battery-capacity completeness check | D0-b shows a capacity dip or first-value 0 on reconnect |
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
- `test_stream_outside_lkg_envelope_rejected` (partial-fleet 95 → 0 and 95 → 87).
- `test_one_divergent_sample_then_native_down_residual`.
- `test_cowitness_frozen_value_refuses_stream` (co-witness `last_updated` stays the stamp).
- `test_envoy_available_ignores_stream` (INV-SF3).

**Mutation drills (build review C):** remove the `age is None` half and the `age > max_age` half at `energy_battery.py:1810` separately; bypass the `unproven` check; bypass settle; bypass the envelope check; read max age from the constant instead of the field. Each must turn a named test red.

**Live validation (no timing luck):**

1. **Operator action, daytime, same day as deploy:** set the three fields (D1). The CM entry reloads.
2. **Gate before 23:00, any time native is up:** `sensor.ura_energy_coordinator_battery_strategy` shows `stream_trust` = `unproven` right after the reload, then `trusted` within about 5 min (3 samples 60 s apart), while `soc_resolution.tier` stays `primary_envoy`. This proves the earn path and that the stream is never served while native is fresh. Under "not configured" the attribute reads `disabled`, which tells the two cases apart.
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
| MEDIUM-5 / OR-1 production vs proposed | Part A / Part B split; invariants tagged |
| OR-2 unproven benefit | each B2 change states the wrong behaviour and its measurement; unmeasured items parked |
| OR-3 hard-coding | D4 forbid list; second-house table |
