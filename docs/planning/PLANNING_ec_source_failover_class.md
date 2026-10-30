# PLANNING: EC source failover as a class (multi-producer values, freshness stamps, untrusted fallbacks)

**Filed:** 2026-10-29 by ura-planner. **Status:** plan, not reviewed. **Tier:** 3 (see section 10). Two framing-disjoint plan reviews are required before any build dispatch.
**Origin card:** ENVOY-STREAM-SOC-TIER-1 (`revival_2026_10_29`, `measured_2026_10_29`). Operator ask, 2026-10-29: treat the nightly blind window as one instance of a class of failure, and harmonize with the EC code that already checks several similar sources, reusing patterns that are proven.
**Scope:** cross-cutting (Energy Coordinator, house scope). No HVAC or presence code is touched. The HVAC and presence state-of-play docs were not read; nothing from those domains is reused here (section 3.3 says why).

---

## 0. Answer first

1. **The class:** an EC value has two or more candidate producers. When the primary drops or goes quiet, the consumer either (a) goes blind or holds, (b) silently uses a worse source, or (c) rejects a healthy fallback because freshness is measured with the wrong timestamp. Untrusted fallbacks and fallbacks that fail together with the primary are part of the same class.
2. **The root cause of the instance is the timestamp, not a missing source.** On 10-28 the SOC resolver went from `primary_envoy` to `lkg` to `cloud_fallback`, then to `None` from 23:17:49 to 23:30:19 (12.5 min). The cloud SOC was healthy but was rejected because the gate at `energy_battery.py:1158` reads `last_updated`, which only moves when the value changes. A live template read (21:40 CDT 10-29) shows the difference plainly: `battery_2` last_reported age 5 s against last_updated age 219 s, and `pv_power` 6 s against 9091 s.
3. **The smallest design that covers the class:** one convention plus one small extension of an existing proven helper. Every producer freshness gate in EC measures `last_reported` through `_state_age_s` (`energy_battery.py:89`), and declares what it does when the age is unknown. No new resolver framework is built. The generic telemetry failover map (PLANNING_envoy_telemetry_failover_map.md) stays parked; nothing in the measurements justifies it.
4. **Slice 1 (this cycle):** SOC only. Fix the cloud-fallback timestamp, and enable the dormant stream tier pointed at `enphase_realtime`'s `battery_2` in freshness mode "a". That closes the measured ~1.5 h/week blind window. Every other member is either already correct, gets a timestamp-only change in slice 2, or is parked with a trigger.
5. **A new finding that limits reuse:** not every `enphase_realtime` `_2` entity is independent of the native integration. `current_power_production_2` and the `*_consumption_*_2` family drop at 23:07-23:08 every night together with native (overlap 120.8 of 130.6 native-down minutes). Only the meter/stream family (`battery_2`, `grid_power`, `load_power`, `pv_power`, `current_battery_discharge_2`, `reserve_battery_level_2`) stayed up. Pairing sources by name would pick a fallback that fails at the same time as the primary.

---

## 1. Institutional context verified

### 1.1 Greps run (paths under `custom_components/universal_room_automation/`)

`grep -nE 'last_reported|_state_age_s|stale_sources|SOC_STREAM|STREAM_MAX_AGE|COWITNESS|max_age'` over `domain_coordinators/energy*.py`, plus `grep last_updated` across the same files, `grep blind_hold|_dp_house_load_kw|grid_fallback|_read_fresh`, `grep map_hash|failover_map|stale_sources` across the package, and `grep SOC_STREAM_TIER_ENABLED|_read_stream_soc` across `quality/tests`. Results are cited inline below.

### 1.2 REUSE-or-BUILD verdict per proposed piece

| Piece | Verdict | Existing symbol |
|---|---|---|
| Age primitive | **REUSE** | `_state_age_s(state, stamp=)` `energy_battery.py:89-111`. Already shared by battery, billing (`energy_billing.py:234,289,317`) and the D-OBS sensor |
| Fresh-read wrappers | **REUSE** | `_read_fresh_float` `:2257`, `_read_fresh_power_w` `:2227` |
| Stream SOC tier (guards, quarantine, trust persistence, observability) | **REUSE, enable** | `_read_stream_soc` `:1773-1821`, divergence/quarantine `:1871-1920`, `stream_trust_state` `:1837`, tier label `local_stream` `:1491`, trust restore/persist `energy.py:1846,2356` |
| Stream config fields | **REUSE** | `CONF_ENERGY_STREAM_BATTERY_SOC_ENTITY` / `CONF_ENERGY_STREAM_COWITNESS_ENTITY` `energy_const.py:348,352`, wired `energy.py:1186-1187` |
| Trusted-tier set | **REUSE unchanged** | `SOC_TRUSTED_TIERS` `energy_battery.py:119` |
| `last_reported` preference with `last_updated` fallback | **REUSE pattern** | NM Cycle A A6, `energy_battery.py:1401-1410` |
| Fail-closed handling of a missing or naive stamp | **REUSE pattern** | solar-follow `energy_pool.py:5025-5035` (CF-8), stream mode "a" `energy_battery.py:1807-1811` |
| Fail-closed age variant of `_state_age_s` | **NEW, small**: an `unknown_age="pass"|"fail"` keyword on the existing helper, default `"pass"` (byte-identical for current callers). Needed because two proven sites hand-roll fail-closed and the cloud fallback swallows errors as pass (`:1172-1175`) | none found; the two hand-rolled copies are the duplication this removes |
| Generic pair map / auto-pairer | **NOT BUILT (parked)** | PLANNING_envoy_telemetry_failover_map.md; no `map_hash` anywhere in code |

No new CONF_*, sensor, or signal is proposed. New constants are listed in section 7.

### 1.3 Plans, audits, cards and READMEs read

- `AUDIT_envoy_stream_fallback_resolver_validity_2026_10_29.md` (read in full). It is the code inventory this plan builds on. Its section 6 "proper path" is slice 1 here, with one correction: its claim that realtime reconnect junk is unmeasured is now partly answered (3 reconnects, no zeros; card `measured_2026_10_29`).
- `PLANNING_envoy_telemetry_failover_map.md`, sections 0-1 (operator invariants: telemetry is local-primary and control is cloud-primary permanently; debounced trip; I-F4 freshness-per-consumer; I-F7 a wrong pair never serves). Those invariants are adopted in section 4. The auto-pair machinery is not built (no `map_hash` in code).
- `PLANNING_ec_reserve_oracle_phase2.md` via the audit summary (rev 2.2: local witness primary, cloud corroborator; stream witness dropped; C4 residual "native down plus cloud stale-equal" accepted at line 384). That accepted residual is what fired the false page on 10-29 (README_v5.103.89:63).
- Cards: ENPHASE-REALTIME-TRIAL-1 (parked; SOC p99 1.0 pp PASS; net-power sign and battery-power plausibility unresolved), ENVOY-STREAM-SOC-TIER-1 (parked, revived 10-29), EC-ATTAIN-HOLD-WHEN-ENVOY-BLIND-1 (parked, Tier 3), SOLAR-FOLLOW-LOCAL-GRID-SOURCE-1 (done), ENVOY-PRODUCTION-STALE-1 and FROZEN-POWER-READ-STALENESS-CLASS-1 (done), ENVOY-DRAIN-ARM-STALE-CT-1 (parked), EC-DEGRADED-DATA-POLICY-1 (done, validated in README_v5.103.39), EC-DB-RESTORE-TIMEOUT-1 (planned, Tier 2), FRESHNESS-FALSE-AWAY-DOWNSTREAM-1 (done; presence domain, not reused).
- README validated tables used as proof: v5.103.39 (degraded-data policy), v5.103.89 (reserve oracle phase 2, including the VIOLATED false-page row).

### 1.4 Code read end-to-end for scoping

`energy_battery.py` 60-125, 1060-1188 (resolver), 1300-1420, 1765-1840, 2136-2340, 3618-3650, 6235-6255; `energy.py` 4318-4395 (blind hold), 4907-4960 (`_dp_house_load_kw`); `energy_pool.py` 4980-5040 (solar-follow grid read); `energy_billing.py` 218-325; `energy_write_verify.py` 518-575, 1195-1235, 2895-2925; `sensor.py` 14600-14730 (envoy_status, `stale_sources`).

---

## 2. Measurements (read-only, 2026-10-29)

Script: recorder DB `/config/home-assistant_v2.db`, read-only, 7-day window, unavailable/unknown minutes per entity and overlap with native SOC outages. Live stamps came from an `ha_eval_template` read.

| # | Question | Result | Status |
|---|---|---|---|
| M0 | Native outage pattern | `sensor.envoy_482543015950_battery` down 7 times in 7 days, every night at 23:06-23:09, lasting 12.6/14.4/20.6/22.7/20.7/19.0/20.7 min (130.6 min total) | measured |
| M0b | EC tiers through one outage (10-28) | `primary_envoy` until 23:09:19, `lkg` 23:09:49-23:14:19, `cloud_fallback` 23:14:49-23:17:19, then `None` (`fallback_stale_reject`) 23:17:49-23:30:19, then `primary_envoy`. `cloud_soc_age_s` counts up from the last value change (reset to 0.5 s at 23:07:49 when the value changed) | measured |
| M1 | Does `last_reported` advance on unchanged reports? | YES for realtime and native: `battery_2` lr 5 s / lu 219 s; `pv_power` lr 6 s / lu 9091 s; native `battery` lr 53 s / lu 184 s. Cloud `iq_battery_hacs_battery_overall_charge` had just changed (lr = lu = 11 s), so its unchanged-report behaviour is **NOT yet measured** | partly measured |
| M2 | Realtime independence from native | Meter/stream family (`battery_2`, `grid_power`, `load_power`, `pv_power`, `current_battery_discharge_2`, `reserve_battery_level_2`): 0 down minutes during native outages since its history begins (10-24 13:28); 3-5 blips of 0.2-0.5 min. **Production/consumption `_2` family fails together with native** (`current_power_production_2` down 23:07-23:08 nightly, overlap 120.8 min) | measured |
| M3 | realtime SOC quality | card `measured_2026_10_29`: unit %, 983 rows, no zero or negative values, no jumps >5 pp, 3 reconnects resumed at prior value, max diff vs native 1 pp | measured (n = 3 reconnects) |
| M4 | Emporia mains (solar-follow primary) | 8 outages of about 1 min in 7 days, none overlapping native outages | measured |
| M5 | Cloud SOC availability | 8 short drops (≤1.1 min), none in the native window | measured |
| M6 | `grid_power` unit/sign | live state `0.539` with unit `W` while `load_power` = 2982.6 W and `current_battery_discharge_2` = 2.98 kW. A W-labelled value of 0.539 suggests kW mislabelled as W or a near-zero net; **unit and sign unresolved** (also open on ENPHASE-REALTIME-TRIAL-1) | needed before any power slice |
| M7 | Tool trap | `ha_get_state` (ha-mcp) returned `last_reported == last_updated` for every entity; the template read shows they differ. Diagnose stamps with a template or the recorder, never `ha_get_state` | measured |

M1-cloud is the go/no-go gate for D1b (section 6).

---

## 3. The class: members, producers, selection, stamps

### 3.1 Member table

"Stamp" means the timestamp the freshness gate reads. "All fail" means what the consumer does when no producer qualifies.

| Value | Producers (independent ones in bold) | Selection logic | Stamp / max age | Unknown-age handling | All fail | Class defect | Verdict |
|---|---|---|---|---|---|---|---|
| **Battery SOC** | **native `battery`**, **realtime `battery_2`**, cloud `iq_battery_hacs_battery_overall_charge`, LKG | `battery_soc` `energy_battery.py:1060-1188`: native, stream (dormant), LKG 300 s, cloud 600 s | native `last_reported` 300 s; stream mode "a" `last_reported` (unset, `DEFAULT_SOC_STREAM_MAX_AGE_S=0`); cloud **`last_updated`** 600 s (`:1158`) | native pass; stream fail; cloud swallow-and-pass (`:1172`) | blind hold `:6245`; `blind_hold_active` `energy.py:4322` drives the EVSE guard and DP `is_blind_hold` | wrong stamp on cloud; independent second local source dormant | **Slice 1** |
| SOC envelope / `envoy_available` | native SOC only | `envoy_available` `:3618-3650`, deliberately local-only | `last_reported` 300 s | pass | `envoy_available=False` | none (by design it must not be masked by a fallback, docstring `:3621-3624`) | keep as is; slice 1 must not change it |
| Solar production | **native `current_power_production`**, **realtime `pv_power`**; realtime `current_power_production_2` is correlated (M2) | `solar_production_w` `:2284` plus LKG envelope 15 min (`energy_const.py:2489`) | `last_reported` 180 s | pass | envelope, then None | no second source; nightly outages happen when solar = 0 | **park** (trigger T2) |
| Battery power | **native `current_battery_discharge`**, **realtime `current_battery_discharge_2`** | `battery_power_w` `:2167` | `last_reported` 180 s | pass | None, then drain path holds existing pauses (docstring `:2176-2181`); ENVOY-DRAIN-ARM-STALE-CT-1 parked | no second source | **park** (T3) |
| Net power (EC) | native `current_net_power_consumption`; realtime `grid_power` (unit/sign M6); Emporia mains | `net_power_w` `:2322` **ungated by design** (Tier-3 MED-2, comment `:69-71`) | none | n/a | None | deliberately ungated; a frozen read is trusted on the breaker/arbitrage path | **park** (T4); do not change without its own Tier-3 |
| Net power (billing) | Emporia import/export pair, native net | `_get_net_power` `energy_billing.py:218-325` | `last_reported` 180 s; counter mode 1200 s (`energy_const.py:1593`) | pass | tick skipped (fail-closed, no dollars accrued) | none material | **compliant** |
| Solar-follow grid | **Emporia mains** primary, **native net** fallback | `_read_grid_watts` `energy_pool.py:4985-5000` | `last_reported` 180 s (`SOLAR_FOLLOW_GRID_FRESH_S`) | **fail** (CF-8) | `blind`, so the controller does not size | none; independent pair, proven (card done, soak-exit 10-05) | **compliant, the reference pattern** |
| House load (DP) | SPAN r1+r2, R1 model | `_dp_house_load_kw` `energy.py:4907-4960`, select `max_span_r1` | **no freshness gate** (`_get_state_float`) | n/a | 0.0, so DP abstains | frozen SPAN is accepted; masked by `max(model)` under the live default | **slice 2 candidate** (timestamp gate only) |
| Reserve readback witness | native reserve sensor (primary), cloud oracle (corroborator); realtime `reserve_battery_level_2` independent but unused | `trusted_local_reserve` `energy_write_verify.py:521-570`; sweep `:1190-1235` | local: **no stamp gate**; cloud age `last_updated` (`:2906-2918`, diagnostics) | n/a | sweep compares against stale cloud, producing a **false REVERTED page** (10-29 04:12Z, README_v5.103.89:63) | stale-equal cloud trusted when local is down; this is the accepted C4 residual | **separate Tier-3 card** (section 8); reuses the convention |
| Cloud settings lag | 3 cloud oracle entities | `_read_cloud_settings_max_age_s` `:1356-1419` | `last_reported` with `last_updated` fallback (A6) | skip | None | none | **compliant, proven** (NM Cycle A) |
| Cloud SOC divergence detector | native vs cloud | `_read_cloud_soc_snapshot` `:1307-1354` | **`last_updated`** (`:1346`); the docstring at `:1300-1302` says it shares one freshness contract with the resolver | n/a | abstains | same wrong stamp as the resolver, so it must change in lock-step with D1b (Bug Class #53) | **Slice 1** (same site group) |
| Stream co-witness | any sensor | `_stream_cowitness_live` `:1823-1835` | **`last_updated`** 120 s | fail | stream refused | a steady co-witness reads as dead | **Slice 1** (D1c) |
| Energy import counters at midnight | Envoy lifetime counters, Emporia daily counters | billing counter-gap (`COUNTER_OUTAGE_FALLBACK_HRS` `energy_const.py:1585`) | own | n/a | `billing_source='counter_gap'` | measured outages end by about 23:31 and never cross midnight; the 10-26 zero day was the boot-restore timeout, a different mechanism | **out of class**; tracked on EC-DB-RESTORE-TIMEOUT-1 |
| EV/EVSE status | Emporia EVSE plus charger entities | EVSE restore and status paths (not traced) | not traced | not traced | not traced | not measured this cycle | **park** (T5) |

### 3.2 Producer and consumer checks for slice-1 values

**SOC, producer side.** Native SOC (integer %, reported each poll, last_reported advances, M1). Realtime `battery_2` (%, last_reported advances every few seconds while the value changes every few minutes; independent of native at night, M2; within 1 pp of native, M3). Cloud SOC (% with unit checked at `:1128`; changes on cloud update; whether last_reported advances without a value change is not yet known, M1). LKG is EC's own memory, re-anchored only by trusted tiers (`:1085`, `:1099`). The three are compared against each other only through the existing divergence detector (native vs cloud, `:1190`) and stream quarantine (native vs stream, `:1871`). The external check is the trial's 1 pp p99 against native.

**SOC, consumer side.** These must all see the same `_soc_source_last` and tier label:
- strategy blind hold at `:6245` (trust decision);
- `blind_hold_active` at `energy.py:4322` and its DP snapshot at `:4382`, which feed the EVSE blind guard (`energy_pool.py:745-761`) and DP `is_blind_hold` (`energy.py:5286`) (trust decisions);
- `SOC_TRUSTED_TIERS` consumers D2a/D3/D4 (trust decisions);
- `_evaluate_soc_resolution` tier map at `:1486-1497` (display and DB);
- the `envoy_status.fallback_active` attribute at `sensor.py:14731` (display);
- `soc_envelope` (LKG anchor).

`stream` is already in `SOC_TRUSTED_TIERS`, so a stream read loosens holds exactly as native does. That is a trust decision, and it is why this plan is Tier 3.

### 3.3 Existing multi-source mechanisms (harmonization inventory)

| Mechanism | file:line | Proves | Proof class | Reusable piece |
|---|---|---|---|---|
| `_state_age_s` + `_read_fresh_*` | `energy_battery.py:89, 2227, 2257` | one age primitive across battery, billing and observability | **PROVEN** (ENVOY-PRODUCTION-STALE-1 / FROZEN-POWER done; README v5.91.x/v5.100.7 tables; 13 test files reference it) | the primitive itself |
| A6 `last_reported` preference | `:1401-1410` | killed false cloud-lag pages caused by a steady value | **PROVEN** (NM Cycle A) | the timestamp choice |
| Solar-follow primary/fallback pair | `energy_pool.py:4985-5035` | independent pair, `last_reported`, fail-closed stamp, reason labels (`primary_stale->fallback`) | **PROVEN** (card done, soak exit 10-05) | fail-closed unknown age; reason-label vocabulary |
| SOC resolver tiers + trusted set | `:1060-1188`, `:119` | ordered fallback with trust semantics | **PROVEN** (README_v5.103.39 validated) | tier order and trust set |
| Stream tier guards + quarantine | `:1773-1920` | unit/range/freshness/co-witness/divergence fail-closed | **BUILT, never live** (tests in `test_ec_degraded_data_p1.py`; constant False) | entire tier |
| Reserve local witness | `energy_write_verify.py:521-570` | local primary, cloud corroborator for writes | **PROVEN with a known residual** (v5.103.89 VIOLATED row) | trust semantics only |
| Billing fail-closed tick skip | `energy_billing.py:289-317` | stale input produces no accrual | **PROVEN** (FROZEN-POWER done) | — |
| LKG envelopes (SOC 6 h, solar 15 min) | `energy_const.py:2391, 2489` | bounded-staleness value instead of blind | PROVEN for SOC (D2) | none here |
| Telemetry failover map | PLANNING doc only | — | **DESIGN only, not built** | invariants I-F1/I-F4/I-F7 only |
| Presence fleet-liveness / person trust | presence domain | — | not checked against presence docs | **not reused**; EC needs per-entity report freshness, not fleet liveness |

### 3.4 Inconsistencies (these are class members in their own right)

1. **Timestamps differ for the same question ("is the producer alive?").** `last_reported` is used for native SOC, power, billing, solar-follow and A6. `last_updated` is used for cloud SOC fallback (`:1158`), cloud divergence (`:1346`), stream co-witness (`:1832`), and write-verify diagnostics (`energy_write_verify.py:2906-2918`).
2. **Unknown age is handled three ways:** pass-through (`_state_age_s` callers, `:73-79`), fail-closed (solar-follow, stream mode "a"), and swallow-and-pass on an exception (cloud fallback `:1172-1175`).
3. **Max ages are not related to producer cadence in any single place:** 300 s (native SOC), 300 s (LKG), 600 s (cloud), 180 s (power, solar-follow), 1200 s (counters), 120 s (co-witness). Each is justified locally. This plan leaves them alone except where a timestamp change alters their meaning (D1b).
4. **Duplicate age arithmetic:** `:1158-1161`, `:1346-1351`, `energy_pool.py:5031-5033`, and `energy_write_verify.py:2906-2918` compute ages inline instead of through `_state_age_s`.
5. **Stale MQTT vocabulary** in stream constants and NM text (`energy_const.py:350-360`, `energy_battery.py:1912` "Local stream battery level"), per the audit.
6. **No unknown-unit trust guard for realtime power**: `grid_power` labelled W carries a value that looks like kW (M6). Any power slice must fail closed on unit plausibility, which `_read_one_grid` already does for unexpected units but not for a mislabelled one.

---

## 4. Trust semantics (stated explicitly)

The BLE-style rule "the primary decides, the others assist" fits **control** (reserve writes stay cloud-primary per failover-map invariant 1) and does **not** fit telemetry consumers that must act during a primary outage. For telemetry this plan adopts:

- **Ordered substitution, not voting.** The first producer that passes every guard is used. There is no averaging or fusion.
- **Independent local producers are trusted.** A realtime meter-family entity passing unit, range and freshness guards, and not quarantined by native divergence, is a trusted tier (`stream` is already in `SOC_TRUSTED_TIERS`). Trust is earned while native is up (quarantine compares the two) and carried into the outage. If the stream was quarantined before native dropped, it is not used.
- **Cloud stays untrusted** even when fresh. D2a/D3/D4 behaviour is unchanged. Fixing its timestamp only means EC uses a fresh cloud value instead of none, under the existing untrusted rules.
- **A correlated producer is never a fallback.** A producer that fails together with the primary (M2's production/consumption `_2` family) must not be configured as one. This is enforced by measurement and config, not by runtime auto-pairing.
- **`envoy_available` stays native-only.** A fallback must never make the Envoy look healthy.

---

## 5. Falsifiable invariants

- **INV-SF1 (freshness):** For any EC trust decision on a class-member value, EC never accepts a reading from a source whose `last_reported` age (or `last_updated` only where `last_reported` is absent) exceeds that source's max age; and for every slice-1 site an unknown age is rejected. *Falsified by:* any slice-1 site that accepts a state with a naive or missing stamp, or computes age from `last_updated` while `last_reported` exists.
- **INV-SF2 (no needless blindness):** `battery_soc` returns None (and therefore `blind_hold_active` can be True) only when every configured SOC producer is missing, unavailable, out of unit or range, stale by INV-SF1, or (stream) quarantined. *Falsified by:* a tick with `soc_resolution.tier == None` while `battery_2` has unit %, value 0-100, last_reported age ≤ `DEFAULT_SOC_STREAM_MAX_AGE_S`, and trust ≠ quarantined.
- **INV-SF3 (no trust inflation):** A cloud-sourced SOC never produces a tier in `SOC_TRUSTED_TIERS`, and `envoy_available` is never True while native SOC is stale. *Falsified by:* `cloud_fallback` mapped into a trusted tier, or `envoy_available` reading any fallback.
- **INV-SF4 (byte-identical no-op):** With `SOC_STREAM_TIER_ENABLED=False` and native fresh, every resolver output, tier label and `_soc_source_last` value is identical to develop.
- **INV-SF5 (no flap):** A single stream read failure while native is down drops to LKG (300 s) rather than straight to None. The LKG is re-anchored by every trusted stream read (`:1099-1100`), so the I-F1 "one miss never flips" property holds through the existing LKG.

Config-extreme combinations Reviewer D must test: stream max age < native max age; stream max age > LKG age; co-witness unset in mode "a"; stream configured to the correlated `current_power_production_2`-class entity (expected: the unit guard rejects non-% values; a %-unit correlated entity is a config hazard, documented); cloud entity with no unit; stream quarantined at the moment native drops.

---

## 6. Deliverables

### D0: Measurement gate (read-only, before build)

Sample `last_reported` of `sensor.iq_battery_hacs_battery_overall_charge` across at least 3 unchanged cloud polls (a template read every few minutes, or recorder `last_reported_ts` on the latest row), and do the same for `battery_2` through one native outage window, with ages logged from 23:00 to 23:40.
- **Verify:** a written table in this doc's section 2 with M1-cloud filled in.
- **Discriminates:** if cloud last_reported advances while the value is unchanged, D1b converts the 12.5 min blind tail into `cloud_fallback`. If it does not, D1b is a no-op for cloud and is dropped; slice 1 then relies on D1a alone.
- **Live:** none (pre-build).

### D1a: Enable the stream tier on realtime `battery_2` (mode "a")

- `SOC_STREAM_TIER_ENABLED = True` (`energy_const.py:345`).
- `DEFAULT_SOC_STREAM_MAX_AGE_S = 120` (`:357`). This switches to mode "a" (`last_reported`). 120 s is roughly 20 realtime 10 s reports and below the 300 s native gate.
- Config (operator action through the options flow, not code): `energy_stream_battery_soc_entity = sensor.envoy_482543015950_battery_2`, `energy_stream_cowitness_entity = sensor.envoy_482543015950_load_power` (same device, meter family, independent per M2, value-moving).
- Rename the MQTT-specific NM and comment text (`energy_battery.py:1912`, `energy_const.py:350-360`) to "local second-source battery level". Text only.

Acceptance:
- **Verify:** native unavailable with a fresh `battery_2` gives `soc_resolution.tier == "local_stream"`, `_soc_source_last == "stream"`, and `blind_hold_active False`.
- **Verify:** `battery_2` last_reported age 121 s with native down gives LKG, then None after 300 s. This must differ from the fixed case; a test that passes both ways is hollow.
- **Verify:** stream quarantined before native drops means stream is never used.
- **Test:** `test_stream_tier_realtime_mode_a_serves_when_native_down`, `test_stream_tier_stale_last_reported_rejected`, `test_stream_quarantined_not_used_in_outage`, `test_stream_disabled_byte_identical` (INV-SF4), `test_envoy_available_ignores_stream` (INV-SF3). Each must be mutation-anchored: neutralising the `age > max_age` check at `:1810` must turn the stale test red.
- **Live:** on the first night after deploy (23:06-23:31 CDT), the recorder rows of `sensor.ura_energy_coordinator_battery_strategy` show `soc_resolution.tier = local_stream` for the whole outage, zero rows with tier None, and `stream_trust` = `trusted`. Under the failure "stream misconfigured", the rows show `lkg` then None as on 10-28, so the observation discriminates. Also: zero `soc_stream_quarantine` NM pages in the first 24 h while native is up (divergence ≤1 pp per M3).

### D1b: Cloud fallback and divergence detector use `last_reported` (gated on D0)

- `energy_battery.py:1156-1175`: replace the inline `last_updated` age with `_state_age_s(st, stamp="last_reported", unknown_age="fail")`. An exception or unknown age becomes `fallback_stale_reject` (fail-closed), replacing the current silent pass.
- `energy_battery.py:1344-1353` (`_read_cloud_soc_snapshot`): same timestamp, in lock-step, because its docstring promises one freshness contract with the resolver.
- `_state_age_s` gains a keyword `unknown_age: str = "pass"`. Under `"fail"` it returns `math.inf` instead of None for a missing or naive stamp, so `age > max` rejects. All existing callers stay byte-identical.

Acceptance:
- **Verify:** cloud value unchanged for 30 min with last_reported 20 s old gives `cloud_fallback` (today it gives `fallback_stale_reject`).
- **Verify:** cloud last_reported 700 s old gives `fallback_stale_reject`, and a naive stamp gives a reject.
- **Test:** `test_cloud_fallback_steady_value_fresh_by_last_reported`, `test_cloud_fallback_stale_last_reported_rejected`, `test_cloud_fallback_naive_stamp_fails_closed`, `test_divergence_detector_uses_same_stamp_as_resolver`, `test_state_age_s_unknown_age_pass_default_unchanged`.
- **Live:** `soc_resolution.cloud_soc_age_s` stays below 600 during steady cloud values (today it reaches about 11 800). This is only observable if D1a is absent or quarantined; otherwise check the attribute in the daytime.

### D1c: Co-witness uses `last_reported`

`energy_battery.py:1832`: change the stamp to `last_reported`, fail-closed. The co-witness's job is to show the producer is alive, not that its value is moving.
- **Test:** `test_cowitness_steady_value_alive_by_last_reported`.
- **Verify:** a steady-valued co-witness no longer kills the stream tier.

### D2 (slice 2, separate cycle, Tier 2-DB): convention sweep

Route the remaining inline ages (`energy_pool.py:5031`, `energy_write_verify.py:2906-2918` diagnostics) through `_state_age_s`, and add a `last_reported` freshness gate to `_dp_house_load_kw` SPAN reads (new constant `DP_SPAN_MAX_AGE_S`). Under the live default `max_span_r1` the change is visible only when SPAN freezes high. Planned separately; listed here so the class is complete.

---

## 7. Knobs (on the ladder)

| Name | Rung | Value | Why this rung | Kill switch |
|---|---|---|---|---|
| `SOC_STREAM_TIER_ENABLED` | 1 (module const) | True | trust-tier entry is a reviewed decision | False = tier off, byte-identical |
| `DEFAULT_SOC_STREAM_MAX_AGE_S` | 1 | 120 | protocol window tied to the producer's report cadence | 0 = mode "b" (co-witness only); keep >0 for realtime |
| `DEFAULT_SOC_STREAM_COWITNESS_MAX_AGE_S` | 1 | 120 (unchanged) | same | n/a |
| `DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S` | 1 | 600 (unchanged; meaning becomes "time since the last cloud report") | safety-adjacent | none |
| `DEFAULT_SOC_DIVERGENCE_THRESHOLD_PCT`, quarantine ticks, spacing | 1 | unchanged (3 pp, 2, 60 s) | proven | n/a |
| `energy_stream_battery_soc_entity`, `energy_stream_cowitness_entity` | 2 (options flow) | realtime entities | per-house wiring | unset = tier off |
| `unknown_age` keyword | code parameter | `"pass"` default | not policy | n/a |
| `DP_SPAN_MAX_AGE_S` (slice 2) | 1 | 180 (proposed) | matches the power gates | 0 = no gate |

---

## 8. Marginal-benefit decomposition

| Option | Captures | Marginal ingredient risk |
|---|---|---|
| A: D1a only (enable stream on `battery_2`) | the whole measured blind window (stream up during 100% of observed native outages since 10-24), plus the LKG and cloud time | turns on a never-live trusted tier, so it carries the full Tier-3 review cost |
| B: A + D1b + D1c (this slice 1) | adds cloud as a real second fallback for nights when realtime also fails, and removes the wrong timestamp from three sites | small: a timestamp swap at three sites plus one keyword; no new state |
| C: generic resolver / failover map for all values | in theory covers power and house load too | new shared primitive, auto-pairing (M2 shows name-pairing picks a correlated source), cross-value state. **Measured benefit for non-SOC values today is about zero**: the native outages fall at night when solar is 0, the billing gate already fails closed, solar-follow has an independent pair, and net power is ungated on purpose |

**Recommendation:** B. C does not pay for itself yet; it stays parked under PLANNING_envoy_telemetry_failover_map.md with the triggers below. A alone leaves a known-wrong timestamp in the code that the operator explicitly asked to harmonize, at a marginal cost of three small edits inside the same review.

**Parked members and revival triggers:**
- T2, solar production: a native production outage measured during daylight (production > 0) longer than the 15 min envelope.
- T3, battery power: a drain decision held or mis-armed during a native outage (`dp` attributes show `battery_power_unknown` during a blind window), or ENVOY-DRAIN-ARM-STALE-CT-1 revives. Prerequisite: realtime discharge sign verified.
- T4, net power: any trust consumer of `net_power_w` found acting on a frozen value; M6 unit/sign resolved first.
- T5, EVSE status: a measured EVSE status outage that changes a decision.
- **Reserve witness (separate card, Tier 3):** the 10-29 false REVERTED page is this class (stale-equal cloud trusted while local is down). Proposed approach, to be planned separately: when the native witness is unavailable, the sweep consults `reserve_battery_level_2` as a second local witness, or treats a cloud value whose `last_reported` is older than the commanded write as stale. It is separate because it touches the write-verification invariant surface and the reserve-oracle plan's accepted C4 residual.

---

## 9. Non-goals

- Do not remove or disable the native `enphase_envoy` integration.
- Do not change the `enphase_realtime` configuration (stream off, 10 s / 30 s polling stays).
- No HA restarts beyond the normal deploy restart, which must respect the sleep rule.
- No change to `envoy_available`, the control/write path, `net_power_w`, `SOC_TRUSTED_TIERS` membership, or any max-age value other than `DEFAULT_SOC_STREAM_MAX_AGE_S`.
- No auto-pairing, no generic resolver, no new sensor or CONF key.
- EC-ATTAIN-HOLD-WHEN-ENVOY-BLIND-1 (acting on cloud SOC in attain) is not addressed. D1a makes it rarer by keeping a trusted tier present.

---

## 10. Tier classification

**Tier 3.** Triggers: it enables a trusted SOC tier that loosens protective holds (`SOC_TRUSTED_TIERS` consumers D2a/D3/D4, blind hold, EVSE blind guard, DP), which affects both cost and safety; and the value is threaded through a resolver consumed by about 8 decision sites (Bug Class #53). Process:

- **Two framing-disjoint plan reviews** before build: (1) completeness, an independent re-enumeration of SOC consumers and freshness sites; (2) adversarial build-prediction.
- Build by `ura-super-builder`.
- Four build reviews: A local, B integration/restart (trust persistence restore `energy.py:1846`), C per-site mutation, and D falsifying INV-SF1..5 with the config extremes in section 5.
- Orchestrator re-verification, then an operator checkpoint before deploy.

Live validation is the first nightly native outage after deploy (D1a Live criterion); the result is written back into the README.

---

## 11. Open questions for plan review

1. Should a failed D0 cloud measurement drop D1b entirely, or should D1b still ship for its fail-closed handling of unknown ages?
2. Co-witness choice: `load_power` or `grid_power`? M6 makes `grid_power` suspect, so `load_power` is proposed.
3. Should the stream tier sit before LKG (current code) or after it? Current order is kept: a fresh independent read beats a remembered one.
