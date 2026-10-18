# PLANNING: EC reserve write-verifier witness fix

**Card:** EC-SELFHEAL-UNEXPLAINED-RESENDS-1 (incl. `reconciled_2026_10_17`). **Date:** 2026-10-17.
**Evidence:** `docs/planning/AUDIT_envoy_reliability_recount_and_witness_reconcile.md` (the audit).
**Operator rulings (10-17):** no new setting; reconcile done; this fix ships separately from the Tier-3
resilience card (EC-ENPHASE-CONNECTIVITY-RESILIENCE-1).
**Code base read:** `integ/test-wave1-d4ac` worktree (develop lineage). Code wins over this doc.

---

## 0. Answer first

1. **The fix.** The reserve verifier's local witness (`_local_entity_for(RESERVE)`,
   `energy_write_verify.py:369-409`) resolves the Envoy's own reserve SENSOR
   (`sensor.envoy_<envoy_serial>_reserve_battery_level`, enphase_envoy unique_id
   `<envoy_serial>_reserve_soc`) through the entity registry, anchored on the already-configured
   SOC entity. If the sensor cannot be resolved (not registered, other hardware), it falls back to
   today's `reserve_soc_number` read. `energy_reserve_soc_entity` is not touched.
2. **Direction (2) as stated cannot pass, and the audit's §5.1 attribution is wrong.** The 10-17
   18:01 case is commanded 10 vs actual 9. `_compare` (`energy_write_verify.py:1136-1140`) matches
   reserve within **±2.0** points, which is deliberately aligned to the ±2 dispatch deadband
   (`energy_battery.py`, `_reserve_action`, `abs(current - target) >= 2`) to stop a
   forever-REVERTED band (fix-up A-HIGH-2 / B-MED-1). So 9 vs 10 is "converged" against ANY
   witness, frozen number or honest sensor. The cloud-oracle verifier also read 9 → within
   tolerance, which answers the audit's open question of why it stayed silent. The frozen witness did
   not hide this one; the tolerance did. **Operator decision needed (§9 Q1).** My recommendation is to
   keep ±2 and re-state acceptance (2) against the real masked episode that IS outside tolerance:
   10-12/13, commanded 10, battery and sensor at 14, frozen number at 10 → silent then, alerts after.
3. **out_of_range (commanded 3 < Enphase minimum 5) does NOT belong here.** It is a write-side clamp
   at the governor chokepoint, not a witness read. Card it separately (Tier 3). Evidence in §8.
4. **Tier:** 2, elevated to three framing-disjoint code reviews under the standing
   regression-prone-energy policy. One plan review before build.

---

## 1. Institutional context verified

### 1.1 Config-first

- `energy_reserve_soc_entity` could be set to the sensor. **Rejected:** it is also the write
  target for the local (dormant) write-failover leg and for every `role="write"` reserve read when
  the cloud key is blank (`energy_battery.py:865-883` `_get_entity`, `_cloud_write_target`).
  Pointing a write role at a read-only sensor would break the local fallback. Operator ruling
  matches.
- No existing witness setting: grep of `const.py`, `energy_const.py`, `config_flow.py` for
  `WITNESS` / `reserve_witness` → only the card's proposed `CONF_ENERGY_RESERVE_WITNESS_ENTITY`,
  which the operator declined. Code change required.

### 1.2 Prior-art scan (REUSE-or-BUILD per piece)

| Piece | Verdict | Evidence |
|---|---|---|
| Witness entry point | REUSED `_local_entity_for` `energy_write_verify.py:369-409`; change the RESERVE branch only | single resolver for all 3 reserve witness consumers (§3) |
| Envoy serial / anchor | REUSED the configured SOC entity `battery._get_entity("battery_soc")` (populated by `derive_envoy_config` `energy_const.py:1576-1600` from `CONF_ENERGY_ENVOY_ENTITY`, injected `__init__.py:3955-3960`) | no hard-coded serial; note Envoy serial (482543015950) != Enpower serial (482348004678), so the number's serial cannot be reused |
| Registry sibling lookup | REUSED pattern: `_nws_last_updated_entity` `energy_battery.py:3049-3075` (registry + unique_id sibling, warn-once on miss) | same shape, narrower key |
| Registry API | REUSED HA `EntityRegistry.async_get_entity_id(domain, platform, unique_id)` (`.venv-ha/.../helpers/entity_registry.py:902-906`) | indexed lookup, no scan |
| unique_id of the sensor | VERIFIED HA core `enphase_envoy/sensor.py:754-760` (`ENCHARGE_AGGREGATE_SENSORS` key `reserve_soc`, `value_fn=reserve_state_of_charge`) and `:999` (`EnvoySystemSensorEntity`, parent of `EnvoyEnchargeAggregateEntity` `:1256`: `f"{envoy_serial_num}_{key}"`) | entity_id is NOT derivable from the key (`battery_level` → `sensor.envoy_<s>_battery`), so match unique_id, not an entity_id string |
| The number's source | VERIFIED `enphase_envoy/number.py:63-70` (`STORAGE_RESERVE_SOC_ENTITY`, `value_fn=reserved_soc` from the Enpower storage settings) | a different Envoy field; it froze, the aggregate sensor did not |
| Fallback entity | REUSED `DEFAULT_RESERVE_SOC_ENTITY` / `reserve_soc_number` role read (today) | unchanged for homes without the sensor |
| Tolerance | REUSED `_compare` ±2.0 `energy_write_verify.py:1136-1140`; NOT changed (§9 Q1) | |
| New CONF / sensor / knob | NONE | operator ruling; §6 |
| New anomaly field `hw_witness_entity` | NEW (additive key in the existing `pending_write_stuck` extra dict, `:2268-2276`) | today `hw_witness` is a literal string that names an entity URA does not read; additive key avoids changing the meaning of an existing field |

### 1.3 Prior planning docs

- `PLANNING_behavioral_write_verify.md` §B0-D2 (`:722-740`): in July the probe already found the
  Enpower number "NOT a usable commanded-reserve ledger" and named the Envoy sensor as the
  hardware-enforced reserve. The build wired the number anyway (docstring `:1563` says sensor,
  code reads number). This cycle completes that plan; it is the computed-but-not-consumed class.
- `PLANNING_envoy_local_witness_and_solar_follow.md` §3.7 / A4: proposes an MQTT
  `envoy_stream_backup_reserve` as an extra witness. Stream path closed NO-GO 10-07
  (ENVOY-STREAM-AB-48H-1). Not reused; noted so nobody revives it here.
- `PLANNING_reserve_write_governor.md` (v5.103.66): governor rows, `RESERVE_SET_VALUE_WRITERS`
  allowlist `energy_const.py:2609-2620`. This cycle adds no writer; the AST lint stays pinned.
- `PLANNING_envoy_write_verification_and_redundancy.md`: origin of `_local_entity_for` (H1).
- The audit (all of it).

### 1.4 Memory / design docs

- `project_battery_soc_envoy_not_span` (Envoy is the SOC truth), `reference_ec_reserve_verifiable_backout_knob`
  (`is_reserve_verifiable` uses the CLOUD oracle, `energy_write_verify.py` `is_reserve_verifiable`, not the
  local witness; unaffected), `feedback_coincidental_equality_masks_concept_split` (the frozen value
  10 equalling common commands is exactly this smell).
- ura-energy-invariants context: every reserve WRITE goes through `_reserve_action`
  (`energy_battery.py:6983`), `force_redispatch`, or `_apply_evse_battery_hold` (allowlist above).
  This cycle changes none of them. Its only behavioural reach into the write side is the
  stand-down skip (`is_standdown_active_for_value`, read in `_reserve_action`), which a witness
  change can arm or disarm (§4).

### 1.5 Code surveyed

`energy_write_verify.py` 340-420, 975-1020, 1057-1176, 1555-1575, 2126-2338, 2385-2530;
`energy_battery.py` 830-905, 2495-2505, 3045-3075, 5300-5310, 6983-7070;
`energy.py` 4228-4245, 5364-5372, 9690-9726; `energy_const.py` 1555-1612, 1821-1975, 2430-2450,
2587-2620; HA `enphase_envoy/sensor.py` 740-770, 1256-1316, `number.py` 55-75.

---

## 2. Falsifiable invariant

**INV-W1.** On any install where the enphase_envoy entity registry has a `sensor` entity with
unique_id `<serial-of-configured-SOC-entity>_reserve_soc`, the reserve verifier NEVER reads
`reserve_soc_number` as its witness on ANY of its three read paths (pending watchdog,
local-divergence compare, command_trail), including while that sensor is `unavailable`
(abstain, never fall back to the number).

**INV-W2 (no-sensor homes byte-identical).** Where that sensor is not resolvable, every witness
read returns exactly today's entity, and charge_from_grid / storage_mode witness resolution is
byte-identical on every install.

**INV-W3 (no write-side change).** No reserve write emission, deadband, floor or tolerance changes:
`RESERVE_SET_VALUE_WRITERS` lint stays green and unchanged; `_compare` is untouched.

Break attempts reviewer D must make: sensor `unavailable` during an Envoy outage while the number
still reads 10 (must abstain, not converge on 10); anchor `battery_soc` unset / non-Envoy;
registry raising; a `number` with the same unique_id (domain must be `sensor`); SOC entity
overridden explicitly to a non-Envoy sensor; renamed sensor entity_id.

---

## 3. Producer and consumer checks

### 3.1 Producer: the witness value

- **Today:** `number.enpower_482348004678_reserve_battery_level`, Enpower `reserved_soc`.
  Health: BROKEN. Only `10.0`/`unavailable` since 2026-08-05 (3,726 divergence rows), `61.0` before
  (audit §2). External ground truth disagreed on every non-10 command.
- **After:** `sensor.envoy_482543015950_reserve_battery_level`, Encharge aggregate
  `reserve_state_of_charge`. Health: tracked the cloud number within median ~41 s (B0-D2) and
  matched real behaviour in both 10-12/13 (read 14 while battery obeyed 14) and 10-14 (90 at
  15:48:22, 46 s after the cloud). 10 of 13 governor writes landed on it within 19 min (audit §3.3).
  Goes `unavailable` with the Envoy (40 episodes / 8 days; long outages 586/714 min) → abstain.
- Residual: a sensor that lags its own field. If the sensor is slower than the 15-min attempt-1
  rung, attempt-1 rows could still appear on a slow land (audit saw a 19-min land). That is a real
  "slow" signal, not an artifact; attempt 3 needs ~60 min.

### 3.2 Consumers of `_local_entity_for(RESERVE)` (re-grep: `grep -n "_local_entity_for\|_local_reserve_witness_state" energy_write_verify.py`)

| # | Site | Use | Trust vs display |
|---|---|---|---|
| C1 | `_witness_compare` `:990` (reserve leg; CFG leg also calls it, unchanged) | emits `write_local_witness_divergence` (never NM-critical) | anomaly rows (analytics) |
| C2 | `_local_reserve_witness_state` `:1567` → `_pending_watchdog_reserve` `:2147` | converge/diverge → attempts 1/2/3, NM pages, HARD STAND-DOWN | **trust decision** (pages + stand-down) |
| C3 | `_local_reserve_witness_state` → command_trail `:2498` | `hw` value in the 3-way trail | display |
| C4 | `_local_entity_for` → command_trail `:2515` | `hw_age_s` | display |
| C5 (indirect) | stand-down state → `is_standdown_active_for_value` read in `_reserve_action` (`energy_battery.py`, the skip block) and `force_redispatch` | suppresses same-value re-dispatch until desire change / 3 h | **trust decision on the write path** |

No other `role="read"` reads of `reserve_soc_number` exist in `energy*.py`: the other reads
(`energy_battery.py:2500, 5304, 6133, 7021, 7568`; `energy.py:5368, 7251, 7471, 9697`) are
`role="write"` (cloud-first) or the write target itself, and stay untouched. `is_reserve_verifiable`
reads the cloud oracle only.

### 3.3 Emission sites touched

None. `pending_write_stuck` (`:2265-2276`) gains the additive `hw_witness_entity` key.

---

## 4. What changes behaviourally (both directions)

| Situation | Today (frozen 10) | After |
|---|---|---|
| Commanded X != 10, battery obeyed X | diverged → 3 attempts → CRITICAL + stand-down (311 certain + ~300 probable artifacts) | converged, silent |
| Commanded 10, battery at 14 (10-12/13 pending episode) | converged, silent (masked) | diverged → ladder → real CRITICAL |
| Commanded 10, battery at 9 (10-17 18:01) | converged (within ±2) | converged (within ±2): **unchanged**, see §9 Q1 |
| Envoy offline, number reads 10 | compared vs 10 | abstain (sensor unavailable) |
| Commanded 3 (out_of_range), sensor 5 | diverged vs 10 | diverged vs 5 by 2.0 → matched (≤2). Commanded 3 vs 6+ would diverge. Not this card. |

Stand-down skip (C5) follows: fewer false stand-downs, so `_reserve_action` resumes sending
values it was wrongly withholding.

---

## 5. Deliverables

### D1: Resolve the Envoy reserve sensor as the reserve witness

In `energy_write_verify.py`:
- New private helper `_envoy_reserve_sensor_eid(self, battery) -> Optional[str]`:
  1. anchor = `battery._get_entity("battery_soc")`; None → return None.
  2. `reg = er.async_get(self.hass)`; `ent = reg.async_get(anchor)`; require
     `ent.platform == "enphase_envoy"` and `ent.unique_id` ending `"_battery_level"`; serial =
     unique_id with that suffix removed.
  3. return `reg.async_get_entity_id("sensor", "enphase_envoy", f"{serial}_reserve_soc")`.
  4. Any exception → None. On None, log at INFO **once per instance** ("reserve witness: Envoy
     reserve sensor not resolved; using <fallback>"), mirroring `_nws_last_updated_entity`.
  No caching (registry indexed lookup each call; a renamed entity is followed).
- `_local_entity_for(RESERVE)`: return the helper's result when not None; else today's
  `battery._get_entity("reserve_soc_number", DEFAULT_RESERVE_SOC_ENTITY, role="read")`.
  CFG and storage_mode branches byte-identical.
- **Ordering rule (load-bearing):** fallback is decided on RESOLVABILITY, never on state. A
  resolved sensor reading `unavailable`/`unknown` returns its entity id; the existing abstain at
  `:1570-1571` / `:2148-2153` then holds. Builders will be tempted to "fall back when unavailable";
  that re-introduces the frozen 10 during every Envoy outage.
- Fix docstrings at `:370-380` and `:1559-1565` to describe the resolution order.

#### Acceptance
- **Verify:** registry has `sensor.envoy_S_reserve_battery_level` (unique `S_reserve_soc`) and SOC
  anchor `sensor.envoy_S_battery` (unique `S_battery_level`) → `_local_entity_for(RESERVE)` returns
  the sensor; with neither registered → returns the configured number (INV-W2).
- **Discriminates:** sensor resolved + `unavailable`, number = 10, commanded 10 → watchdog ABSTAINS
  (no converge log, `_pending_last_oracle` not updated). A wrong fallback-on-state implementation
  converges on 10 instead. Commanded 30 under the same state → still abstains, no attempt row (wrong
  impl would fire attempt 1).
- **Test (new file `quality/tests/test_ec_reserve_witness_resolution.py`):**
  `test_reserve_witness_prefers_envoy_sensor_via_registry`,
  `test_reserve_witness_falls_back_when_sensor_unregistered`,
  `test_reserve_witness_unavailable_sensor_abstains_not_fallback`,
  `test_reserve_witness_ignores_number_domain_same_unique_id`,
  `test_reserve_witness_anchor_not_envoy_falls_back`,
  `test_reserve_witness_registry_raises_falls_back`,
  `test_cfg_and_storage_mode_witness_unchanged`.
  Fixtures use the real `entity_registry` from pytest-homeassistant-custom-component (registry entries
  created with `async_get_or_create`), not a stubbed `_local_entity_for`.

### D2: Both-direction behavioural acceptance on the pending watchdog

Drive `_pending_watchdog_reserve` with a real commanded ledger (`_last_reserve_level`,
`_last_reserve_level_at`) and registry-resolved entities, advancing time past attempt thresholds.

#### Acceptance
- **Direction 1 (the 311 artifact class):** commanded 80, sensor 80, number 10, age 3,700 s →
  zero `pending_write_stuck` emits, zero NM calls, no stand-down; `write_local_witness_divergence`
  not emitted. (Today: attempt rows + CRITICAL + stand-down; so it discriminates.)
- **Direction 2 (masked real failure, recommended fixture = 10-12/13):** commanded 10, sensor 14,
  number 10 → attempts 1/2/3 fire at the existing thresholds, attempt 3 is CRITICAL with
  `oracle_seen=14.0` and `hw_witness_entity=sensor.envoy_S_reserve_battery_level`, stand-down set.
  (Today: silent; discriminates.)
- **Direction 2b (10-17 literal, pins current policy):** commanded 10, sensor 9 → converged, silent.
  Test name states the reason (`..._within_deadband_tolerance_is_converged`) so a future tolerance
  change is a visible decision. If the operator picks §9 Q1 option (b) this test flips and D3 is added.
- **Test:** `test_watchdog_no_alert_when_envoy_sensor_matches_command`,
  `test_watchdog_alerts_when_sensor_diverges_and_frozen_number_equals_command`,
  `test_watchdog_one_point_miss_within_deadband_tolerance_is_converged`,
  `test_pending_stuck_row_carries_hw_witness_entity`,
  `test_standdown_not_armed_on_matching_sensor` (asserts `is_standdown_active_for_value` False after
  the full ladder window, so C5 is covered).
- **Live:** see §7.

### D3 (only if operator picks Q1(b)): not specced here. Re-plan; it changes `_compare` and the
deadband relationship, which moves this to Tier 3.

---

## 6. Numbers and knobs

No new knob. Behavioural numbers reused unchanged: `_compare` tolerance 2.0 (inline at `:1140`,
pre-existing; noting it is an un-named literal, carded as a LOW naming tidy only if the operator
wants, not in this cycle), `CONF_PENDING_MAX_ATTEMPTS`, attempt ages, 3-h cool-off, all existing
rung-1 constants. Kill switch for the whole watchdog stays `CONF_PENDING_WATCHDOG_ENABLED`
(`:2135`). The unique_id suffixes `"_battery_level"` / `"_reserve_soc"` are protocol strings from
HA core, module constants `ENVOY_SOC_UNIQUE_SUFFIX` / `ENVOY_RESERVE_UNIQUE_SUFFIX` in
`energy_const.py` (rung 1: changing them requires review against HA core source).

---

## 7. Live validation (post-restart, Envoy online)

1. `sensor.ura_energy_coordinator_*` command_trail attribute (the 3-way trail, `:2490-2530`): `hw`
   value equals `sensor.envoy_482543015950_reserve_battery_level` state, not 10.0 (unless reserve
   really is 10). Discriminates: under the old code hw is 10.0 regardless.
2. HA log: no "reserve witness ... not resolved" INFO line on this house.
3. First non-10 governor `reserve_write applied` after restart: within 60 min, URA DB
   `anomaly_log` has NO `pending_write_stuck` row whose commanded equals the sensor's value at that
   time; `write_local_witness_divergence` rows for reserve show `local_seen` = the sensor value
   (varying), never a constant 10.0.
4. Any `pending_write_stuck` row that does appear carries `hw_witness_entity` =
   `sensor.envoy_482543015950_reserve_battery_level`.
5. If the Envoy is offline at validation time: verify abstain (no new reserve `pending_write_stuck`
   rows during the outage), and defer items 1/3 to its return; record that in the README table.

Trip-wire: none new. The existing pending ladder is now the trip-wire, and it will be honest.

---

## 8. out_of_range: decided, separate card

**Evidence (audit §3.3, §5.4):** three governor `reserve_write` rows FAILED 10-17 07:47-08:17 CDT,
commanded 3 ("Off-peak hold, SOC 3% <= target 10%", `energy_battery.py:6918` builds the hold at
current SOC), Enphase `ServiceValidationError translation_key=out_of_range`; cloud number never
below 5.0 in the recorder. The decision side clamps only 0-100 at `_reserve_action`
(`energy_battery.py:7015`, `max(0, min(100, folded))`).

**Why not here:** (1) it is a WRITE-value change at the governor chokepoint, which stamps
`_last_reserve_level_desired` and is composed by `force_redispatch` and the EVSE overlay; the
falsifiable surface is every reserve writer in `RESERVE_SET_VALUE_WRITERS`, which is Tier 3 by the
CLAUDE.md trigger (value threaded through a shared primitive with many consumers, cost/safety).
This card is read-only. (2) The right minimum is a hardware fact (cloud number `min` attribute vs
a constant); that needs its own measure step. (3) Coupling is benign: under the new witness,
commanded 3 vs sensor 5 is within ±2 (silent); commanded 3 vs higher sensor would page, which is
correct (URA is asking for the impossible).

**Action:** mint card `EC-RESERVE-HW-MIN-CLAMP-1` (Tier 3, energy thread, related
EC-RESERVE-WRITE-GOVERNOR-1): "clamp reserve desire to the write target's hardware minimum at
`_reserve_action` (clamp before stamp); measure first: write target `min` attribute vs observed
floor." Run the adjacency sweep before minting (no existing card found: board grep for
`out_of_range|HW-MIN|hardware minimum` hits only an unrelated TOU test name).

---

## 9. Operator decisions

- **Q1 (required before build).** The 10-17 9-vs-10 miss is inside the ±2 tolerance by design.
  (a) **Recommended:** keep ±2; acceptance (2) uses the 10-12/13 masked episode (4-point miss) and
  a test pins 9-vs-10 as converged. Marginal benefit of (b) is 1 reserve point; its risk is the
  forever-REVERTED band A-HIGH-2 was fixed for, plus a new tolerance/deadband split on a write-path
  primitive (Tier 3).
  (b) Tighten the watchdog tolerance to exact-integer for the pending ladder only. Moves the cycle
  to Tier 3 and needs a re-plan.
- **Q2 (FYI).** Mint EC-RESERVE-HW-MIN-CLAMP-1 as Tier 3 per §8.

---

## 10. Non-goals

- No change to `energy_reserve_soc_entity`, write routing, write failover, or any writer.
- No change to `_compare` tolerance or the ±2 dispatch deadband (unless Q1(b)).
- No stale-cloud-oracle handling (10-14 cloud stuck at 6; self-heal / reverted pages): resilience card.
- No pending-episode back-off / one-page-per-episode: resilience card item (2), built on this.
- No charge_from_grid or storage_mode witness changes.
- No MQTT stream witness (closed NO-GO).
- No out_of_range clamp (§8).
- No backfill or relabel of historical `pending_write_stuck` rows.

## 11. Tier

**Tier 2**, read-path only, one plan review before build. Elevated to **three framing-disjoint code
reviews** under the standing regression-prone-energy rule, because the witness arms the stand-down
skip on the reserve write path (C5) and the anomaly row gains a key:
A = resolution correctness + fallback ordering + edge cases (§2 break list);
B = write-path ripple (stand-down arm/disarm, `force_redispatch`, restart with restored ledger
`energy.py:2003-2004`, governor lint unchanged);
C = test authority via per-site mutation:
- M1: `_local_entity_for(RESERVE)` returns the fallback unconditionally → `..._prefers_envoy_sensor...`
  and both direction tests RED.
- M2: fall back when the resolved sensor state is unavailable → `..._unavailable_sensor_abstains...` RED.
- M3: drop the `"sensor"` domain / platform filter (scan by suffix) → `..._ignores_number_domain...` RED.
- M4: drop the `_battery_level` anchor check → `..._anchor_not_envoy_falls_back` RED.
- M5: omit `hw_witness_entity` → `..._carries_hw_witness_entity` RED.
Live validation per §7; README write-back of the validated table.

If Q1(b) is chosen: Tier 3 and re-plan.
