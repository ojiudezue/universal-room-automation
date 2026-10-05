# PLANNING — Enphase connectivity + command resilience (8.x reality) and Phase-1 adjustments

**Cards:** EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 (primary), EC-DEGRADED-DATA-POLICY-1 Phase 1 (adjust before ship,
§13 hold ruling), EC-LKG-NEVER-PERSISTED-1 (absorbed), ENPHASE-REALTIME-TRIAL-1 (trial design), ENVOY-STREAM-AB-48H-1
(gate input, readout 2026-10-05 13:05 CDT).
**Author:** ura-planner, 2026-10-04 (REV 1). Plan only. No code edited.
**Phase-1 build under audit:** branch `feature/ec-degraded-data-p1` @ `651c72cfc`, worktree
`.claude/worktrees/agent-aebf583902376cc85`. Line numbers marked **(p1)** are from that worktree. Unmarked lines are
from the same tree (it is develop + phase 1).
**Tier:** the ship bundle (Phase 1 + §5 MUST adjustments) is **Tier 3**. Phase-2 items are tiered one by one in §6.
**Version:** the bundle is a PATCH (`5.103.x`). No new user-facing capability beyond pages and optional config fields.

---

## 0. Why this re-plan exists

Phase 1 was planned on 2026-10-03, before the Enphase research. The operator held its deploy (§13 of
`PLANNING_ec_degraded_data_phase1.md`) with: "Too important to ship with stale assumptions." The operator's guidance
on the resilience card is binding:

- Respect the prior commanding investment. Every phase-2 piece **extends** it and does not replace it.
- The stream must make commanding **stronger**, as an independent witness of whether a command took effect.
- Consolidation of the 3 integrations is judged on **redundancy, accuracy and supply-chain risk**, and decided by a
  measured trial, not a README.

### 0.1 Facts and their effect

| # | Fact | Source | Effect on design |
|---|---|---|---|
| F1 | Local battery control (reserve, CFG, storage mode) was removed at fw 8.2.4225. Writes are cloud-only. | Research 2026-10-03. Consistent with manual §2.6: on 8.3.x local writes are "accepted-then-ignored". | Any path that writes to the local leg is dead code at best and a silent no-op at worst (§2 row C7). |
| F2 | The local API is unsupported and changes per release. `production.json` hangs on 8.x. pyenphase now recommends `/ivp/meters`. | Research | Every local read is supply-chain fragile. The core integration blocks setup on `production.json`, which is the restart-outage mechanism. |
| F3 | Tokens last about a year. Renewal is manual when the account has MFA. | Research | A silent all-local blackout on a predictable date. Nothing in URA watches for it today (§2 row C15). |
| F4 | The cloud enforces Retry-After limits. | Research. Verified in installed `enphase_ev` 4.3.5: `coordinator.py:1899-1912` parses Retry-After; `:2059-2061` and `:4383-4388` back off. | Cloud writes can fail or be delayed. URA cannot see this today (F6). |
| F5 | `enphase_ev` 4.3.5 CFG setter: writes, then force-refreshes up to 4 times over ~2.25 s. If the refreshed state does not match, it raises `ServiceValidationError("charge_from_grid_toggle_not_applied")`. A 2 s settings-write debounce raises `battery_settings_update_debounced`. | `battery_runtime.py:4372-4404`, `:1321-1328`; `const.py:158`. Read this session from `/Users/okosisi/ha-config/custom_components/enphase_ev/`. A directory-wide grep of the SMB mount returned nothing, so each file was checked one at a time. | (a) The cloud switch state is the **cloud setting read back**, not proof the gateway applied it. B0-D2 measured apply-lag p90 at 7.7 min (`energy_const.py:500-501`). (b) Failed writes **raise**. |
| F6 | URA swallows every service-call exception (`_LOGGER.exception`). The write-verify tap then runs anyway and stamps the command ledger as if the write landed. | `energy.py:7201-7227` (p1) `_execute_service_action`; `energy.py:6990-6996` (p1) dispatch loop; ledger stamp `energy.py:8518-8522` (p1). | A failed CFG/reserve write is invisible for up to 15 min (verify window), or forever if the oracle is also unreadable. Phase 1 D3 adds new CFG `turn_off` writes, so this is now a Phase-1 concern (§3 A2). |
| F7 | `enphase_ev` has an account session quota error, `EnlightenAuthTooManySessions`. | `api_client/errors.py:60-61` | A second cloud client on the same account (for example ha-enphase-realtime's writes) shares a failure mode with `enphase_ev` and can trip it. |
| F8 | The MQTT stream publishes more than SOC: `Battery Power` (storage `agg_p_mw`), `Grid Power`, `House Load`, `Solar Production`, `Backup Reserve` (`backup_soc`, the gateway's own reserve) and **`Data Timestamp`** (the Envoy's own `last_update`). All carry `expire_after: 60`. | `docs/ha-config-snapshots/envoy_mqtt.yaml:42-225` | (a) `Data Timestamp` is a true producer-freshness witness: it changes only when the Envoy produces new data. That makes it a better D1 co-witness than grid power, and it is a config choice, not code. (b) `Backup Reserve` + `Battery Power` + `Grid Power` give a **local, core-integration-independent** witness of whether a command took effect (R3). |
| F9 | ha-enphase-realtime v1.0.1 (MIT, 9 days old). Review verdict: TRIAL WITH CONDITIONS, NO FORK. | Card ENPHASE-REALTIME-TRIAL-1 `review_2026_10_04` | §7. |
| F10 | LKG SOC and solar LKG are never saved: `_save_evse_state` references an unbound `_json`, and the error is swallowed at DEBUG. | `energy.py:2102`, `:2136` (p1). The phase-1 builder confirmed it in a comment at `:2109-2112` (p1) and worked around it only for the new keys (`import json as _ecdd_json`, `:2113`). | Phase 1 assumed LKG persists (plan §1.3 row "LKG + persistence REUSE"). It does not. Outages start at restarts, so this is a MUST (§3 A1). |

---

## 1. Institutional context verified

### 1.1 Documents read
- `CLAUDE.md` (project): Tier 3, plan-review tiers, prior-art scan, knob ladder, producer/consumer, config-first,
  supersession triage.
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.5, §2.5a, §2.6 (read), headings for the rest.
- `docs/planning/PLANNING_ec_degraded_data_phase1.md` (full, including both plan reviews, §12 rulings and §13 hold).
- `docs/planning/DESIGN_ec_degraded_data_policy.md` REV 2 §0-§3 (read). §4+ skimmed through the phase-1 plan's
  citations.
- `docs/planning/PLANNING_envoy_write_verification_and_redundancy.md` (full): W-1..W-6, D1-D3.
- `docs/planning/PLANNING_envoy_telemetry_failover_map.md` (full): I-F1..I-F7, D1-D5 (never built).
- `docs/planning/AUDIT_envoy_telemetry_pairing_manual.md` (full): T1-T12, F1-F8, B0 probe.
- Kanban `docs/planning/kanban.data.yaml:438-505`: EC-LKG-NEVER-PERSISTED-1, EC-ENPHASE-CONNECTIVITY-RESILIENCE-1
  (incl. `operator_guidance_2026_10_04`), ENPHASE-REALTIME-TRIAL-1 (incl. `review_2026_10_04`),
  ENVOY-STREAM-AB-48H-1, EC-EV-TOGGLE-TRIPWIRE-1.
- `docs/ha-config-snapshots/envoy_mqtt.yaml` (stream entity contract).
- Installed `enphase_ev` 4.3.5: `manifest.json`, `api_client/errors.py` (full), `switch.py:700-740`,
  `battery_runtime.py:4372-4404, 1193-1328`, `coordinator.py:7155-7212, 8854-8861`, plus grep hits for
  Retry-After / ConfigEntryAuthFailed.
- Not re-read this session: `VISION_v7.md`, `ROADMAP_v9.md`, `WORKFLOW_GUIDE.md`, `quality/QUALITY_CONTEXT.md` body.
  The bug classes cited (#7, #19, #34, #53, #57, #63) are taken from the phase-1 plan's verified list.
- Memory: `MEMORY.md` index lines for the envoy arc (2026-09-23/25 pickup), `reference_ec_config_surface`,
  `project_battery_soc_envoy_not_span`, `feedback_suppression_needs_discharge`, `project_single_user_no_backcompat`.
  Bodies were not pulled this session. Flagged for plan review #1.

### 1.2 Greps run and REUSE / BUILD verdicts (new pieces only; §2 lists the existing machinery)

| Proposed piece | Verdict | Evidence |
|---|---|---|
| LKG save fix | **REUSE** the existing writer; fix the binding | `energy.py:2095-2141` (p1) |
| Write-outcome capture | **EXTEND** `_execute_service_action` (`energy.py:7201` p1) to return `bool` + exception; **EXTEND** `WriteVerifier` with a `dispatch_failed` record status beside `STATUS_*` (`energy_write_verify.py:51-65`) | grep `dispatch_failed|write_failed|ServiceValidationError` in `domain_coordinators/`: zero hits |
| NM for failed writes | **REUSE** `WriteVerifier._maybe_fire_nm` (`energy_write_verify.py:1191`), with a per-surface, per-day latch | — |
| Command-outcome physics witness | **EXTEND** `WriteVerifier` (new `_outcome_witness_*`, sibling of `_conduct_check_reserve` :1767 and `_pending_watchdog_reserve` :1922) | grep `outcome|physics` in `energy_write_verify.py`: no witness for CFG exists. The conduct check covers reserve only and abstains when `battery_power_w` is None. |
| Stream reserve witness | **EXTEND** `_local_reserve_witness_state` (:1354) with a second witness (stream `backup_soc`) | the pending watchdog's only witness is the core-integration entity, so it abstains during exactly the outages that matter (:1943-1950) |
| Integration health / auth monitor | **REUSE** the `ConfigEntryState.LOADED` check pattern (`aggregation.py:385-394`); **EXTEND** `_track_envoy_availability` (`energy.py:3031-3067` p1) | grep `cloud_reachable|last_successful_update|reauth|ConfigEntryState` in `domain_coordinators/energy*.py`: zero hits. URA does not watch either Enphase integration's health. |
| Cloud-read freshness | **REUSE** `_read_cloud_settings_max_age_s` (`energy_battery.py:1205`, uses `last_reported`) and `CONF_CLOUD_LAG_ALERT_S` (`energy_const.py:444`) | already computed every tick for the cloud-lag NM (:1525-1610) |
| Stream telemetry pairs | **REUSE the design** of `PLANNING_envoy_telemetry_failover_map.md` D1/D2 (debounce constants, I-F1/I-F3/I-F7), **scoped down** to a hand-built map (AUDIT corollary: hand-build first) | `telemetry_failover.py` does not exist (glob). Never built. |
| Write-churn trip-wire | **REUSE** card EC-EV-TOGGLE-TRIPWIRE-1's shape (count per rolling hour → NM + anomaly) for battery surfaces | `kanban.data.yaml:490-497` |
| New config fields | Stream co-witness = **REUSE** phase-1 `CONF_ENERGY_STREAM_COWITNESS_ENTITY` (`energy_const.py:343` p1), pointed at `sensor.envoy_stream_data_timestamp`. New for R3/R4: optional stream battery-power / grid-power / backup-reserve entity fields. | grep `stream` in `energy_const.py` (p1): only the two phase-1 keys |

### 1.3 Config-first check
- **Stream co-witness** (§3 A5): pure config. Set the phase-1 field to the stream `Data Timestamp` entity. No code.
- **ha-enphase-realtime trial**: install, configure and remove. No URA code.
- **Token renewal**: an operator action. URA can only detect and page (R5).
- **Cloud write failures, the LKG bug, physics witness, should-start-by**: no setting covers them. Code is needed.

---

## 2. Prior-art inventory — commanding, verification and fallback

Status: **LIVE** (runs and consumed), **DORMANT** (built but off or unreachable), **OBSOLETE** (premise false under
F1/F2), **NEVER BUILT** (design only).

| # | Mechanism | file:line | Status | Note under the 8.x facts |
|---|---|---|---|---|
| C1 | Cloud-first write routing `ENERGY_CLOUD_FIRST_WRITES=True` → `_write_failover_by_surface` | `energy_const.py:515-524`; `energy_battery.py:546-552` | **LIVE** | Correct for F1. The name "failover" is now misleading: it is the routing table. KEEP + DOCUMENT. |
| C2 | `_get_entity(role="write")` choke point | `energy_battery.py:812-832` | **LIVE** | Every write and command-state read goes through it. |
| C3 | `_cloud_write_target` blank-oracle "coherent demotion" back to the **local** leg | `energy_battery.py:834-870` | **OBSOLETE premise (reachable)** | Blanking a cloud oracle field routes writes to the local Enpower entity. On fw ≥ 8.2.4225 that is a silent no-op. Reachable by config (options-flow blank, and a second home with no `enphase_ev`). → R6a. |
| C4 | Cloud oracle defaults `DEFAULT_CLOUD_*` | `energy_const.py:305-314` | **LIVE** | House-specific defaults. Multi-home rule → R6a also reviews them. |
| C5 | WriteVerifier echo check (schedule → 15 min → compare cloud oracle) | `energy_write_verify.py:125, 401, 591`; window `energy_const.py:315-317` | **LIVE** | The oracle is the **cloud setting**, so it proves "Enphase cloud accepted it". It does not prove "the gateway did it" (F5a). R3 adds the outcome leg. |
| C6 | Reversion sweep + local secondary witness | `energy_write_verify.py:710, 747, 954`; `_local_entity_for` :353-396 | **LIVE, partly OBSOLETE** | Reserve local witness: still meaningful (it is the pending watchdog's hardware witness). **CFG local witness: OBSOLETE.** The Enpower CFG switch is a standing "on" (phase-1 plan §1.4, card EC-RUNG1-WAIT-EV-PINGPONG-1). → R6d. |
| C7 | D3 dormant write-failover design (switches, auto-promotion) | `PLANNING_envoy_write_verification_and_redundancy.md` §D3 | **OBSOLETE (inverted, never built)** | H1 (2026-07-13) inverted it to cloud-primary. The three failover switches were never built (grep `cloud_write_failover` in `switch.py`: 0). Local is no longer a fallback for writes on fw ≥ 8.2.4225. → R6b (doc-only supersession). |
| C8 | Self-heal N=3 starvation alarm; cloud-write-leg-unavailable N=3 + 6-cycle backoff | `energy_write_verify.py:163-180` | **LIVE** | Closest existing thing to write-path health. It detects symptoms (no maturation, unavailable leg). It never sees the **exception** from the dispatch (F6). R2 extends it. |
| C9 | Pending-write-stuck ladder (15/30/60 min, 3 attempts, hard stand-down, cool-off probe) + NM | `energy_write_verify.py:1900-2165`; knobs `energy_const.py:499-513` | **LIVE (reserve only)** | Witness = core-integration `sensor.envoy_*_reserve_battery_level` (:1354-1373). It abstains on `unavailable` (:1943-1950), so it is blind during restart outages. R3 adds the stream `backup_soc` witness. CFG has no ladder. |
| C10 | Hardware-noncompliance conduct check (reserve floor held, SOC below floor, discharging N ticks) | `energy_write_verify.py:1767`; knobs `energy_const.py:483-497` | **LIVE (reserve only)** | Reads `battery_soc` (resolver) + `battery_power_w` (native). Abstains when native power is None. R3/R4 add the stream battery power. |
| C11 | `is_reserve_verifiable` (blind-window guard predicate) + backout knob | `energy_write_verify.py:219-310`; `CONF_RESERVE_VERIFIABLE_MAX_AGE_S` (manual §2.5a) | **LIVE** | Unchanged. Do not touch (manual §2.5a). |
| C12 | 3-tier SOC resolver + phase-1 stream tier | `energy_battery.py:909-1000` (p1); stream helpers :1615-1860 (p1); `SOC_TRUSTED_TIERS` :115-120 (p1) | **LIVE; stream DORMANT** (`SOC_STREAM_TIER_ENABLED=False`, `energy_const.py:336` p1) | §3. |
| C13 | Cloud-vs-native SOC divergence (D2 v5.20) + tier observability | `energy_battery.py:1317, 1378` | **LIVE** | — |
| C14 | Cloud settings-lag freshness detector + NM | `energy_battery.py:1205-1260, 1525-1610`; `CONF_CLOUD_LAG_ALERT_S` `energy_const.py:444` | **LIVE** | The only cloud-health signal URA has. It measures the age of the settings entities, not the integration's state or its auth. Reused by §3 A3. |
| C15 | Envoy-offline NM after 3 misses | `energy.py:3031-3067` (p1) | **LIVE, text stale** | (a) It cannot tell device-offline from integration-not-loaded or auth failure (F3). (b) The text "Battery strategy is holding — no commands being issued" is false on `cloud_fallback` ticks and, once D1 is on, on stream ticks. → R5 + §3 A6. |
| C16 | `envoy_available` = fresh native SOC **AND** local Enpower `storage_mode` readable | `energy_battery.py:3044-3079` (p1) | **LIVE, latent hazard** | If a future core/pyenphase release drops the local storage-mode entity (F1/F2), `envoy_available` goes permanently False. The strategy then holds in its blind branch with a **trusted** SOC. D4 does not page, because D4 keys on the tier. → §3 A7 (verify now), R6e (rework). |
| C17 | Breaker chokepoint (`_execute_breaker_safe_dispatch`) + LKG latch + phase-1 D2b ledger | `energy.py:6884-6998` (p1) | **LIVE** | It believes an explicit cloud `off`. Under F5a the gateway may still be charging for minutes. Pre-existing. R3 adds the physics leg (tighten only). |
| C18 | Telemetry failover map (`TelemetryPair`, debounce, auditable map) | `PLANNING_envoy_telemetry_failover_map.md` D1-D5 | **NEVER BUILT** | D3/D4 were rejected on B0 measurement (cloud power 5-15 min stale; cloud net power semantically wrong, AUDIT F1). The stream changes the economics: local and ~5-6 s cadence. → R4 revives a hand-built subset. |
| C19 | Storm-precharge cloud exemption (v5.17.6) | phase-1 `_result(cloud_withhold_exempt=True)` `energy_battery.py:5838, 5851` (p1) | **LIVE** | Kept (operator Q2). |
| C20 | Phase-1 D2a/D2b/D2c/D3/D4/D5 | `energy.py:5463-5610, 6884-7175` (p1); `energy_battery.py:5518, 6281-6315, 1860+` (p1) | **BUILT, unshipped** | §3. |

---

## 3. Audit of the Phase-1 build against the new facts

Each finding names the assumption the phase-1 plan made, what is actually true, and the adjustment.
**MUST** = lands before the bundle ships. **SHOULD** = in the bundle if the probe allows, else first follow-up.
**LATER** = phase 2.

| # | Phase-1 assumption | Reality | Adjustment | When |
|---|---|---|---|---|
| **A1** | LKG persists across restart, so restart-triggered outages start with a usable LKG (plan §1.3, §2.1) | Never saved (F10). Every restart outage starts with LKG empty. Within ~5 min of restart, if native is not back, the tier drops straight to `cloud_fallback`/`none`. That fires D3 withholds, D2a refusals and D4 dwell timers that a persisted LKG would have avoided. | **R1:** bind `json` once at the top of `_save_evse_state` (same pattern as the `dt_util` fix at `energy.py:2053-2058`). Drop the `_ecdd_json` workaround. Raise the LKG/solar save swallow from DEBUG to WARNING, once per boot. Real save → restore test through the production writer and reader (KV-capture fake DB, the phase-2b persistence-oracle pattern noted at `energy.py:2069-2071`). | **MUST** |
| **A2** | A dispatched CFG/reserve write landed. The ledger `_last_charge_from_grid_command` records what URA sent. | Writes can raise (F5b, F4, auth). The exception is swallowed and the ledger is stamped anyway (F6). Phase-1 **D3** issues new `switch.turn_off` writes on cloud-only ticks. If one fails, the strategy reason says "grid charge withheld" while CFG stays on. That is Bug Class #53 (claimed, not done) on the exact cost path D3 exists to close. | **R2-core:** `_execute_service_action` returns `(ok, exc_type, translation_key)`. The dispatch loop passes it to `_tap_write_verifier`. On failure for a battery surface: record status `dispatch_failed`, emit anomaly `battery_write_failed` (surface, service, exception class, HA translation key), and NM via `_maybe_fire_nm` (per surface, per day). **Ledger semantics stay as they are**: it is an *intent* ledger and stays fail-closed for D2b, which keeps EVs breaker-held on a failed `turn_on`. Document that. Phase-1 D5 gains attribute `grid_charge_withhold_dispatch_failed`. | **MUST** |
| **A3** | An explicit cloud CFG `off` read is current (D2a "provably off" `energy.py:7117-7145` p1; D2c `_cfg_breaker_blocks_ev_start` :7147-7175 p1) | The cloud switch is the cloud setting, polled. During a Retry-After backoff, or while the integration serves cached data, the entity can show a stale `off` (unmeasured: P3). Even a fresh `off` is not gateway-applied for up to ~8 min (F5a). | For the **new** phase-1 predicates only: an `off` read counts as provably off only when `_read_cloud_settings_max_age_s()` ≤ `CONF_CLOUD_LAG_ALERT_S` (REUSE C14). Otherwise treat it as unknown, which means the D2b ledger/LKG rule decides. The pre-existing chokepoint is left to R3. | **SHOULD.** MUST if probe P3 shows `last_reported` keeps advancing on cached values. In that case use the integration's own last-success timestamp instead (P3 decides which). |
| **A4** | D3's withhold/resume toggling is harmless (plan review R2-6 accepted envoy/cloud alternation → CFG off/on every tick) | Cloud writes have a 2 s debounce and Retry-After limits (F4/F5). Worst case: 12 CFG writes per hour on alternating tiers. If that churn triggers a cooldown, a later **safety** write can be rejected (peak de-escalation CFG off, D3's own withhold). | No resume hysteresis (R2-6 is right that it would strand charges). Add **R2-churn:** count battery-surface writes per surface per rolling hour. Above `DEFAULT_BATTERY_WRITE_CHURN_MAX_PER_H` → one NM + anomaly (sibling of EC-EV-TOGGLE-TRIPWIRE-1). Set the threshold from probe P3's measured baseline. | **MUST** (counter + NM only, about 30 LoC; no behaviour change) |
| **A5** | D1 freshness mode (a) or (b), with a co-witness that "changed recently" (grid power suggested) | The stream publishes `Data Timestamp` = the Envoy's own `last_update` (F8a). It changes only on new Envoy data. Grid power can repeat if the add-on re-publishes the same JSON. | **Config only:** set `CONF_ENERGY_STREAM_COWITNESS_ENTITY` to `sensor.envoy_stream_data_timestamp` (verify the entity id live). Keep `DEFAULT_SOC_STREAM_MAX_AGE_S=0` (mode b, fail-closed) unless D0-S1 resolves to (a). LATER: also bound `now − Data Timestamp value` ≤ 120 s (~20 s skew measured), which catches a stuck Envoy clock. | **MUST (config)**, LATER (code) |
| **A6** | (Implicit) The Envoy-offline NM text is accurate | "Battery strategy is holding — no commands being issued" is false on degraded ticks (C15b) | One-string change: report the tier ("using cloud reading only" / "using local stream" / "holding — no reading"). Use `_tick_soc_source` from the battery. | **SHOULD** |
| **A7** | `envoy_available` tracks Envoy health | It also requires the local `select.enpower_*_storage_mode` to be readable (C16). Local battery control is gone at the firmware level (F1), and pyenphase may drop the entity. | **Verify now (no code):** confirm the entity exists and is readable on the live install (`ha_get_state`). Record it in the README. Rework is R6e (Tier 3). | **MUST (verify)**, LATER (code) |
| **A8** | Must-start-by (now "should start by", D2c) waits behind every protective hold (operator ruling + pending answer: blind-window guard hold and TOU pauses too) | D2c (`energy.py:5470-5506` p1) waits behind cap, load-shed, fill, arbitrage (both labels), CFG, drain and TOU (`_paused_by_us`). It does **not** wait behind `_paused_by_blind_window`. Today must-start-by is the guard's **terminal discharge**: max-defer can refuse release on the envelope (`energy_pool.py:1477-1484`, "the DP machinery's own timer will ultimately fire") and must-start-by releases with `has_pressure=True` (`energy.py:5515-5519` p1). | Add `_paused_by_blind_window` to the D2c hold list (label `blind_window`). The discharge becomes: data returning (sighted tick drains the set, `energy_pool.py:1520-1522`), or max-defer with a passing envelope, or the operator responding to the held-past-deadline NM + anomaly (`_report_must_start_by_held` `energy.py:5578` p1). This satisfies the suppression-needs-discharge rule through a page instead of a release. Update the INV-BW1 terminal-discharge tests. They assert must-start-by releases a blind-window pause and must now assert the hold + page. | **MUST** (operator ruling; confirm Q1) |
| **A9** | The stream is a trustworthy local source | It reads `/ivp/livedata/status` through a third-party add-on. That endpoint is unsupported local API (F2) and may change per firmware. | No code change. D1 is fail-closed (unit/range/freshness/co-witness/quarantine guards), so a schema change makes the tier refuse and fall through. Document it in the README as a supply-chain dependency. | doc |
| **A10** | `_witness_compare` local CFG leg adds signal | The local CFG switch is a standing "on" (C6) | Exclude the CFG surface from the local secondary-witness compare (log noise, not a decision input). → R6d. | LATER |
| **A11** | Physics never contradicts the cloud CFG read | Unverified (F5a) | → R3. Not in the bundle: it touches the breaker chokepoint, and the sign/scale of stream battery power is unmeasured (P1). | LATER |

**Phase-1 items confirmed sound under the new facts** (no change): D2a refusal kwarg threading; D2b unknown≠off
(more holding, which is correct with a fragile local API); D3 chokepoint at `_result`; D4 page; D1's kill switch +
fail-closed guards; persisted D1 trust + D4 latch (they use their own `json` binding, so they are not affected by A1).

---

## 4. Falsifiable invariants

Bundle (Phase 1 invariants I-1..I-7 still apply; Reviewer D's target is the union):

- **I-R1 (no silent failed battery command).** For every battery-surface service call (write-leg reserve number, CFG
  switch, storage select) that raises, the same tick produces a `battery_write_failed` anomaly row and the verifier
  record shows `dispatch_failed`. If the NM latch for that surface and day is open, exactly one NM fires.
  *Repro:* `hass.services.async_call` raises `ServiceValidationError` on `switch.turn_off` for the cloud CFG during a
  D3 withhold → expect anomaly + NM + `grid_charge_withhold_dispatch_failed=True`. Today: one log line.
- **I-R2 (LKG survives restart).** After `_save_evse_state` runs with LKG set, and the coordinator restarts within
  `STALE_MAX_AGE_HOURS`, `get_lkg_snapshot()` returns the saved value and stamp. *Repro:* today → None.
- **I-R3 (should-start-by never overrides a protective hold).** Must-start-by never turns an EV on while it is in
  `_paused_by_blind_window`, `_paused_by_arbitrage`, `_paused_by_us`, `_paused_by_battery_drain`, grid-cap,
  load-shed or fill-priority, or while `_cfg_breaker_blocks_ev_start()` is True. Each (evse, deadline) held past its
  deadline yields exactly one NM + one anomaly. *Repro:* EVSE in `_paused_by_blind_window` + `_paused_by_dp`,
  envelope below drain, must-start-by fires → today: released (`has_pressure=True`).
- **I-R4 (churn visible).** More than `DEFAULT_BATTERY_WRITE_CHURN_MAX_PER_H` writes to one surface in a rolling hour
  → exactly one NM per surface per day.

Phase 2:

- **I-W1 (witnesses only tighten).** No witness added in phase 2 (stream physics, stream reserve, cloud health) can
  remove a breaker intent, release an EV pause, mark an untrusted SOC tier trusted, or make
  `is_reserve_verifiable()` True. Witnesses can only add breaker intent, add "unverifiable", or page.
  The **only** loosening source remains the D1 stream tier under its own gates.
  *Repro to try:* cloud CFG reads `on`, stream battery power shows 0 W for 20 min → breaker intent must stay True.
- **I-W2 (outcome witnessed or paged).** For every CFG `on` command that the cloud accepted, within
  `DEFAULT_CFG_OUTCOME_WINDOW_S` either stream physics shows grid charging, or the verifier shows `outcome_missing`
  and the pending ladder (now CFG-capable) engages. Abstain only when the stream is not live.
- **I-W3 (integration loss visible).** If `enphase_envoy` or `enphase_ev` is not `LOADED` (or has an open reauth
  flow) for ≥ `DEFAULT_ENPHASE_INTEGRATION_DOWN_PAGE_MIN`, exactly one NM per episode names the integration and the
  remedy ("re-enter token / sign in again").
- **I-W4 (no write to a dead leg).** With `ENERGY_CLOUD_FIRST_WRITES=True` and a blank cloud oracle for a surface,
  no `number.set_value` / `switch.turn_*` / `select.select_option` reaches a local Enpower entity, unless the
  operator explicitly opted in (R6a).

---

## 5. Ship bundle (Phase 1 + MUSTs) — deliverables

Build in the phase-1 worktree branch, on top of `651c72cfc`. Builder: `ura-super-builder`.

### B1 — LKG persistence fix (A1, absorbs EC-LKG-NEVER-PERSISTED-1)
**Acceptance**
- **Test:** `test_lkg_soc_survives_restart_real_writer` drives the production `_save_evse_state` →
  `_restore_evse_state` against a KV-capture fake DB → the snapshot is restored. Call-neuter drill: re-introduce the
  unbound name → RED.
- **Test:** `test_solar_lkg_survives_restart_real_writer` (same for `solar_production_w_lkg`).
- **Test:** `test_lkg_save_failure_logs_warning_once`.
- **Live:** after the deploy restart, the `battery_soc_lkg` row in `energy_state` (URA DB) has an `updated` stamp
  later than the deploy. *Discriminator:* under the bug the row is absent or older than 2026-10-01.

### B2 — Battery-write outcome capture + churn trip-wire (A2, A4)
`_execute_service_action` returns a small result. It changes no behaviour for any caller that ignores it.
`_tap_write_verifier` takes it. New verifier status `STATUS_DISPATCH_FAILED = "dispatch_failed"` (it is not
`STATUS_OK`, so `is_reserve_verifiable` returns False with no code change). Anomaly `battery_write_failed`. NM through
`_maybe_fire_nm` (per surface, per day; severity `high`). The churn counter is a rolling deque per surface.
**Acceptance**
- **Test:** `test_cfg_turn_off_failure_records_dispatch_failed` — service raises `ServiceValidationError` → status
  `dispatch_failed`, 1 anomaly, 1 NM. A second failure the same day → anomaly only.
- **Test:** `test_failed_turn_on_keeps_ledger_fail_closed` — ledger True, cloud `unavailable` → `grid_charge_intent` True.
- **Test:** `test_d3_withhold_dispatch_failed_attr`.
- **Test:** `test_execute_service_action_callers_unchanged` — every existing caller (EV, pool, plugs) behaves the same.
- **Test:** `test_battery_write_churn_nm` — 13 CFG writes in 60 min → 1 NM; 12 → 0.
- **Test (Reviewer C mutation):** neuter the `ok` thread-through → the first test goes RED.
- **Live:** no `battery_write_failed` rows in steady state. If the HA log shows any `enphase_ev`
  `ServiceValidationError` after deploy, a matching anomaly row exists. *Discriminator:* a log exception with no row
  means the wiring is broken.

### B3 — Should-start-by waits behind the blind-window guard (A8)
**Acceptance**
- **Test:** `test_must_start_by_holds_behind_blind_window` → no turn_on, DP claim kept, 1 NM + 1 anomaly
  `ev_must_start_by_held` with `hold=blind_window`.
- **Test:** update the existing INV-BW1 terminal-discharge tests (enumerate them by grepping
  `blind_window_liveness_release` in `quality/tests/`). The new oracle: hold + page, and sighted-tick drain still
  releases.
- **Test:** `test_must_start_by_releases_when_no_hold` (liveness preserved).
- **Live:** prove in-suite. Organic occurrence is rare. Say so in the README.

### B4 — Config + text (A5, A6, A7)
- Set the stream co-witness field to the stream data-timestamp entity (operator action or validator step; verify the
  id first).
- A6 string change, with a test asserting the text per tier.
- A7: one live read, recorded in the README.

### B5 — Cloud-read freshness on the new phase-1 predicates (A3) — SHOULD, gated on probe P3

### Bundle gates
1. **Stream A/B readout (2026-10-05 13:05 CDT)** → phase-1 §9. GO → flip `SOC_STREAM_TIER_ENABLED`. NO-GO → ship D1
   dormant (operator Q1 ruling) and stop the add-on.
2. **Probes P1-P3** (§6 R0) appended to this doc. P3 is the only one that gates the bundle (B2 threshold, B5).
3. Re-review **only the changed sites** plus Reviewer D over the whole I-1..I-7 + I-R1..I-R4 surface. See §8.

---

## 6. Phase 2 deliverables (each extends §2 machinery)

### R0 — Measurement probes (read-only; measure before build)
`ssh ha "python3 -" < probe.py` against the recorder in `mode=ro`, plus journald for the log census. Results go in §9.

| Probe | Question | Gates |
|---|---|---|
| **P1** | Sign and scale of stream `Battery Power` and `Grid Power` against native `battery_power_w` / `net_power_w` during a known charge and a known discharge (AUDIT §2b method). Lag and agreement p50/p95/p99. `Backup Reserve` against the commanded reserve ledger: apply lag p50/p90. | R3, R4 |
| **P2** | URA CFG `on` windows over the last 30 days (activity log / write-verify records), at night with no solar. Time until stream battery power ≥ X kW charging. Time after `off` until charging stops. Gives `DEFAULT_CFG_OUTCOME_WINDOW_S` and the power thresholds. Also: windows where cloud CFG = `off` but the battery charged from grid (Enphase-autonomous: storm guard, schedule, maintenance). | R3 |
| **P3** | (a) Census over 30 days of `enphase_ev` `ServiceValidationError` / 429 / Retry-After / auth / `TooManySessions` in journald. (b) URA battery writes per surface per day and peak per hour (baseline for B2 churn). (c) Whether the cloud CFG switch's `last_reported` keeps advancing during `enphase_ev` backoff windows, against `sensor.enphase_cloud_last_successful_update` (entity id to verify; AUDIT §3 named it on 2026-07-13). | Bundle B2 threshold, B5 |
| **P4** | Token horizon. Operator-run: core `enphase_envoy` token expiry date (Enlighten UI or decode the `exp` claim outside URA), MQTT add-on token expiry, account MFA status. | R5 urgency |

### R1 — LKG persistence → shipped in bundle B1.

### R2 — Cloud write-path health (extends C8/C9; bundle ships R2-core + churn)
Follow-up adds: subscribe to `enphase_ev` repair issues (`issue_registry`, prior art `__init__.py:1222`) → NM when a
backoff or auth issue opens. Map the HA translation keys from F5 (`charge_from_grid_toggle_not_applied`,
`battery_settings_update_debounced`, `charge_from_grid_unavailable`) to plain NM text. When a write fails
`debounced`, retry once on the next tick only if the desire still matches (reuse the pending-ladder freshness seam
:2015-2049). **Tier 2-DB.**
**Acceptance:** tests per translation key; mutation on the issue listener; **Live:** a forced debounce (two rapid
writes in a test service call, operator-approved) produces exactly one anomaly + retry.

### R3 — Command-outcome witness from stream physics (extends C5/C9/C10/C17)
- New verifier legs: `_outcome_witness_cfg` and `_outcome_witness_reserve`. CFG on: confirmed when stream battery
  power ≥ `+DEFAULT_CFG_OUTCOME_CHARGE_W` while solar < ε within `DEFAULT_CFG_OUTCOME_WINDOW_S`. CFG off: confirmed
  when charging falls below ε, or solar explains it. Reserve: stream `backup_soc` == commanded ±1 within the window.
- Feeds: (1) the verifier record (`outcome_confirmed` / `outcome_missing` / `abstain_stream_down`); (2) the
  **pending ladder gains a CFG surface**, with the stream as witness and the same 3-attempt ladder and stand-down;
  (3) the pending reserve watchdog gains `backup_soc` as a second witness. Core-integration witness first, stream
  when core is unavailable. This ends the abstain-during-outage gap (C9); (4) the breaker chokepoint gains a
  **tighten-only** leg: stream shows grid charging (battery charging ≥ threshold, solar < ε) → `grid_charge_intent`
  True, whatever the cloud switch says (I-W1). This also covers Enphase-autonomous grid charging that URA did not
  command (P2).
- The conduct check (C10) uses stream battery power when native is None.
- **Tier 3.** It touches the breaker chokepoint and a shared verifier primitive. Gated on P1/P2.
**Acceptance:** I-W1/I-W2 tests at config extremes (thresholds 0 / huge; stream fresh, stale or quarantined; solar
high at dusk); per-site mutation on each of the 4 feeds; replay fixtures from P2 windows (recorder-derived).
**Live:** the next URA arbitrage CHARGE shows `outcome_confirmed` within the window on the strategy sensor
`last_verified_write_charge_from_grid`. *Discriminator:* `abstain_stream_down` with the stream live means the
wiring is broken.

### R4 — production.json-independent reads (revives C18, scoped down)
A hand-built pair table (extends the AUDIT §5 verdict table with stream rows from P1). It covers net power
(stream `Grid Power`), battery power (stream `Battery Power`) and production (stream `Solar Production`). Reuse the
failover-map debounce contract (I-F1 single blip never flips, I-F3 return > trip, I-F7 mismatch → none). No
auto-builder (operator directive in the failover-map plan; the hand-built table is the fixture). The net-power pair
unlocks phase-1 Q5 (attain may grid-charge on a stream tick, closing the 10-02 class). Each pair is kill-switched and
off until its P1 row is GO. **Tier 3** (net power feeds grid-charge entry and INV-6).
**Acceptance:** byte-identical when every pair is off; I-F1/I-F3/I-F7 tests; the 10-03 16:00-17:28 replay shows
`net_power_source=stream`. **Live:** next native outage.

### R5 — Integration health and token/auth alert (extends C14/C15)
- Watch `enphase_envoy`, `enphase_ev` and (if configured) stream liveness (data-timestamp age). Report states
  `loaded`, `setup_retry`, `setup_error`, reauth-in-progress, `not_loaded` (REUSE `aggregation.py:385` pattern via
  `hass.config_entries.async_entries(domain)`).
- Rework the C15 NM to name the cause: "Envoy device not answering" vs "Envoy integration not loaded (likely token
  expired — re-enter token)" vs "Enphase cloud sign-in needed (MFA)".
- Optional days-to-expiry (Q4). Default: off.
- Integration domains are config, not hard-wired (multi-home). Unset → monitor off.
- **Tier 2** (alerts only, no actuation).
**Acceptance:** tests per entry state; one NM per episode; no NM during the first `DEFAULT_ENPHASE_BOOT_GRACE_S`
after start (restart outages are expected). **Live:** in-suite, plus a live check that the monitor's attribute shows
`loaded` for all three after deploy.

### R6 — Retire or rework obsolete paths (supersession triage)
| Item | file:line | Bucket | Action |
|---|---|---|---|
| R6a Blank cloud oracle → local write demotion | `energy_battery.py:834-870` | **REWORK** | Blank cloud oracle → surface commands **disabled**, plus a one-time WARNING and NM ("battery commands are off: no cloud battery entity configured"). Local writes are allowed only behind an explicit options flag `CONF_ENERGY_LOCAL_BATTERY_WRITES` (default off, helper text "Only for Envoy firmware older than 8.2"). Q2. **Tier 2-DB** (write routing). |
| R6b D3 dormant failover design | `PLANNING_envoy_write_verification_and_redundancy.md` §D3 | **DOCUMENT (superseded)** | Add a header note: inverted by H1, local leg unsupported since fw 8.2.4225. Nothing to delete (never built). |
| R6c `_write_failover_by_surface` naming / `write_route` attr | `energy_battery.py:548`; `energy_write_verify.py:2174-2197` | **KEEP + DOCUMENT** | Comment: "routing table; True = cloud". No rename (attr consumers). |
| R6d Local CFG secondary witness | `energy_write_verify.py:374-386` (CFG row) | **KEEP + DOCUMENT → DELETE after R3 live** | Exclude CFG from the local witness compare. The physics witness replaces it. |
| R6e `envoy_available` storage-mode conjunct | `energy_battery.py:3074-3079` | **REWORK** | If the local storage-mode entity is **not registered** (removed upstream), drop the conjunct with a one-time WARNING. If registered but `unavailable`, keep today's semantics. **Tier 3** (blind-branch trigger; I-7 peak de-escalation). |
| Local reserve witness | `energy_write_verify.py:1354` | **KEEP** | Still the hardware witness. R3 adds `backup_soc` beside it. |

### R7 — Consolidation trial → §7.

---

## 7. Consolidation: 3 integrations vs consolidated

### 7.1 What redundancy can and cannot buy here
- **Writes have exactly one service path: the Enlighten cloud API** (F1). Two integrations that both write go to the
  same cloud, the same account and the same session quota (F7). They are redundant against **integration bugs**
  (an `enphase_ev` release breaks), not against **service failures** (cloud down, rate limit, auth). A second
  writer also adds a shared failure (session quota) and a split-brain risk (two writers to CFG/reserve).
- **Local reads all share one box.** Every local reader polls the same Envoy, with the same token and the same weak
  HTTP server. More clients means more load, and load is the suspected cause of `production.json` hangs and peak
  cutouts (A/B S5, 09-29 evidence of 37-94 cutouts per day with the stream on). Local read redundancy is real
  against **integration-level** failures (core setup blocked on `production.json`) and adds to **box-level** risk.
- **The strongest independence available is reads vs writes:** a local witness checking a cloud command. That is R3.
  It needs no new integration.

### 7.2 Options scored (H = good for the house, L = bad; evidence in brackets)

| Option | Redundancy | Accuracy | Supply chain | Verdict |
|---|---|---|---|---|
| **O0 Today:** core `enphase_envoy` (local reads) + MQTT add-on (local stream) + `enphase_ev` (cloud reads + all writes) | Reads: 2 local paths, independent at the integration level (the stream survived both 10-03 outages) + 1 cloud. Writes: 1 path. **M-H** | SOC: native ≈ stream (A/B S3 pending); cloud bad (p95 11.5 pp, frozen). Net power: native OK; cloud NEVER ADMIT (AUDIT F1). **H** once S3 passes. | 3 third-party surfaces (pyenphase/core, add-on, HACS). 2 Envoy clients. 2 tokens (core + add-on). **M** | **Baseline.** Keep if A/B is GO. |
| **O1** Drop the MQTT add-on (A/B NO-GO) | Reads: 1 local + 1 cloud. Restart outages = blind local. **L** | Same as O0 minus stream. **M** | 2 surfaces, 1 Envoy client. **H** | Fallback if the A/B shows load harm. |
| **O2** Replace the MQTT add-on with ha-enphase-realtime (reads only; core kept, its entities `_2`) | Same shape as O0. realtime also reads `/ivp/meters` and `/stream/meter`, so it has richer local reads with no `production.json`. **M-H** | Unknown → trial. | Swaps a third-party add-on for a 9-day-old, single-site integration. Default polling is heavy (1 s livedata, 5 s battery, second `/stream/meter`); the review conditions cap it at 5-10 s / ≥10 s / stream off. Takes over core entity ids by design. **M-L** | **Trial candidate** (§7.3). |
| **O3** Replace **core** `enphase_envoy` with ha-enphase-realtime (reads) | Removes the integration that blocks on `production.json` (the restart-outage mechanism). Leaves 1-2 local paths. **M** | Unknown. All native consumers (SOC primary, `envoy_available`, conduct, pending watchdog) would re-point. **Risk H.** | Drops the best-maintained component (HA core). **L** | **Not now.** Revisit only if the O2 trial is clean for ≥ 2 weeks and core outages persist after the next pyenphase release. |
| **O4** ha-enphase-realtime for reads **and** writes (single integration) | Concentrates every path in one 9-day-old project. Its writes duplicate `enphase_ev` (split-brain, shared session quota F7). **L** | — | **L** | **Reject.** |
| **O5** Add realtime's writes as a standby second command path behind `enphase_ev` | Integration-level redundancy only (§7.1). Adds F7 quota risk. Its "locally verified" property is matched by R3 without a second writer. **L-M** | — | **L** | **Reject now.** Revisit only if `enphase_ev` breaks for > 24 h with no fix (evidence trigger). |

**Recommendation:** O0 + R3 (local outcome witness) gives the commanding strength the operator asked for. Run the
O2 trial for the read side only. O3/O5 are parked with explicit revival triggers.

### 7.3 Measured trial plan (ENPHASE-REALTIME-TRIAL-1)
- **Gate:** after the stream A/B readout. One extra Envoy client at a time: during the trial the MQTT add-on is
  **stopped**, so the Envoy client count equals the A/B configuration. The A/B window is the baseline.
- **Install conditions (from the review):** keep core; realtime entities get `_2` and URA ignores them (no URA
  config change); relay/dry-contacts unticked; maintenance off; **no writes** (verify no write entity is enabled);
  livedata 5-10 s, battery ≥ 10 s, its own stream off.
- **Duration:** ≥ 72 h. Must include ≥ 1 HA restart (taken while the house is awake, per the no-restart-while-asleep
  rule) and ≥ 1 arbitrage night.
- **Metrics** (one-shot recorder probe at the end; no watching):
  1. Envoy load: core `unavailable` transitions per day (restart-coincident counted separately), peak battery
     cutouts per day. Against both the A/B baseline and the stream-off baseline.
  2. Coverage: % of core-dropout minutes where realtime SOC / net / battery power were numeric. Time-to-first-value
     after restart (the `production.json` independence claim).
  3. Accuracy: SOC against native (p99 ≤ 2 pp, max ≤ 5 pp). Net power against the SPAN pair (the validated witness,
     1.6 %). Battery power against physics (ΔSOC × 40 kWh / Δt).
  4. Cadence: p50/p95 per entity.
  5. Safety: zero writes, zero autonomous grid charges (check stream/cloud CFG and battery power for unexplained
     charging).
- **Decision rule:** any rise in non-restart outages or cutouts, or any write → uninstall at once. All metrics meet
  or beat the MQTT stream → choose between O0 and O2 on supply-chain grounds (operator Q5). Otherwise uninstall and
  keep O0.

---

## 8. Tiers and review plan

| Item | Tier | Reviews |
|---|---|---|
| Ship bundle (Phase 1 + B1-B5) | **3** | Phase 1 already had 2 plan reviews + build. This plan gets **one plan review** (completeness, re-greps §2/§3). Build reviews: A/B/C over the **changed sites only** (B1-B5 + D2c list); **D over the full I-1..I-7 + I-R1..I-R4 surface** including pre-existing code; C mutates B1 binding, B2 thread-through, B3 hold entry, churn counter. Orchestrator re-grep + mutation. Operator checkpoint before deploy. No restart while asleep. |
| R0 probes | none | Read-only |
| R2 follow-up | 2-DB | 3 framings |
| R3 | 3 | 2 plan reviews + A/B/C/D |
| R4 | 3 | 2 plan reviews + A/B/C/D |
| R5 | 2 | 2 framings + live |
| R6a | 2-DB | — |
| R6b/c/d | 1 (doc / comment) | 1 |
| R6e | 3 | with R3 or alone |
| R7 trial | operator action, no URA code | probe readout |

Order after the bundle: R0 (P1/P2 run now) → R5 (cheap, and urgent if P4 shows the token horizon is near) → R3 → R4
→ R6a/R6e → R2 follow-up. R7 runs in parallel with R3 planning.

---

## 9. Knobs (new numbers, with rung)

| Name | Value | Rung | Why / kill switch |
|---|---|---|---|
| `DEFAULT_BATTERY_WRITE_CHURN_MAX_PER_H` | from P3 baseline (placeholder 12) | 1 | Alert threshold against an external API; review-gated. `<= 0` = off. |
| `DEFAULT_CFG_OUTCOME_WINDOW_S` | from P2 (expect ~900, matching the pending ladder) | 1 | Protocol window. |
| `DEFAULT_CFG_OUTCOME_CHARGE_W` | from P2 | 1 | Physics threshold. `<= 0` disables the CFG outcome leg. |
| `DEFAULT_ENPHASE_INTEGRATION_DOWN_PAGE_MIN` | 15 | 1 | Alert dwell; filters restart outages. `<= 0` = off. |
| `DEFAULT_ENPHASE_BOOT_GRACE_S` | 300 | 1 | Boot grace (Bug Class #52 family). |
| R4 per-pair enable | False | 1 | Trust decision on a safety input (same posture as `SOC_STREAM_TIER_ENABLED`). |
| `CONF_ENERGY_LOCAL_BATTERY_WRITES` | off | 2 | Per-deployment firmware fact. |
| R3/R4/R5 stream + integration entity fields | unset | 2 | Per-deployment wiring. Unset = leg off (multi-home). |
| Reused: `CONF_CLOUD_LAG_ALERT_S` (1800) for B5 | — | 1/2 | Already rung-2-promoted (`energy_const.py:460-462`). |

---

## 10. Non-goals
- Changing `is_reserve_verifiable` or `CONF_RESERVE_VERIFIABLE_MAX_AGE_S` (manual §2.5a).
- Any write path other than `enphase_ev`. Any local write.
- Auto-building the pair map (failover-map D1 auto-builder): hand-built only.
- Cloud power as a decision input (AUDIT F1/B0: NEVER ADMIT net power; battery power too stale).
- EC-CONSUMPTION-DROPOUT-DAYS-1, ENERGY-HISTORY-KW-SUMMED-AS-KWH-1 (own cards).
- Reading credentials out of other integrations' config entries (Q4 asks; default no).

## 11. Operator questions (recommended answer in brackets; assumed unless changed)
1. **Q1** Should-start-by waits behind the blind-window guard hold too. That removes the guard's terminal release;
   a car can stay uncharged until data returns, and you get a page at the deadline instead. [Yes, matches your
   pending answer]
2. **Q2** Does the second home have Enphase, and on what firmware? If yes, R6a (no silent local writes) moves into
   the next cycle. [Answer needed]
3. **Q3** Bundle scope: Phase 1 + LKG fix + write-failure alerts + churn alert + should-start-by fix (B1-B4), with B5
   only if probe P3 says the cloud switch can show stale values. [Yes]
4. **Q4** Token expiry warning: state-based detection only (integration not loaded / sign-in needed), or also
   days-left by decoding the token's expiry inside URA? [State-based only. Note the expiry date from P4 by hand.]
5. **Q5** Realtime trial: run it with the MQTT add-on stopped, so the Envoy sees one extra client at most? If both
   tie on accuracy, prefer the long-lived add-on or the integration with richer reads? [Yes; prefer the add-on until
   realtime has 3 months of releases]
6. **Q6** Stream physics may **add** an EV breaker pause when the battery is visibly grid-charging but the cloud says
   charge-from-grid is off. It never removes one. [Yes]
7. **Q7** Blank cloud battery entity → battery commands off + alert, instead of silent local writes. [Yes]

## 12. Plan completion tracking
Nothing deferred from this plan yet. The phase-1 items carried forward unchanged are listed in §3 "confirmed sound".
LATER items are tracked as R-deliverables here. Cards to mint after operator review (adjacency-swept against
EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 children): R3 `EC-CMD-OUTCOME-WITNESS-1`, R4 `EC-STREAM-TELEMETRY-PAIRS-1`,
R5 `EC-ENPHASE-INTEGRATION-HEALTH-1`, R6a/e `EC-ENPHASE-OBSOLETE-PATHS-1`.

## 13. R0 probe results (2026-10-04)
Read-only. Scripts ran via `ssh ha "python3 -"` against the recorder (`mode=ro`), the URA DB (`mode=ro`) and
`.storage/core.config_entries` (read only). **The recorder holds only 7.9 days** (from 09-26 04:12), so "30 days"
means 7.9 days for recorder-based numbers. The URA DB covers 30 days. **Log census was blocked:** `docker logs` was
refused (no socket permission for the ssh user), `ha core logs` returned 401, and the MCP `error_log` window covered
only ~3 minutes. `system_log` held no `enphase` entries. P3(a) therefore uses the integration's own recorder
diagnostics instead of log text.

### P1 — stream sign and scale (pairs taken at native update times, stream sample within 30 s, |native| > 300 W)
| Pair | n | Sign agree | Ratio p50 (p05 / p95) | \|diff\| W p50 / p95 / p99 |
|---|---|---|---|---|
| stream `battery_power` vs native `current_battery_discharge` ×1000 | 995 | 0.980 | 0.999 (0.49 / 1.12) | 45 / 4644 / 8351 |
| stream `grid_power` vs native `current_net_power_consumption` ×1000 | 1285 | 0.949 | 0.997 (-0.00 / 1.14) | 40 / 2630 / 7349 |
| stream `battery_power` vs SPAN `battery_power` | 20119 | 0.967 | 1.016 (0.36 / 1.20) | 118 / 5954 / 12897 |
| stream `battery_power` vs cloud `current_battery_power` | 154 | 0.935 | 1.002 (-0.02 / 3.37) | 1572 / 13081 / 29160 |

- **Units and sign:** stream is W, native is kW. Same sign as native: **positive = discharge, negative = charge**
  (native < -1 kW → stream p50 -7956 W; native > +1 kW → stream p50 +4692 W). Grid follows native net
  (positive = import). Scale 1:1.
- **Lag:** on native steps > 2 kW, the stream reaches 70 % of the step a median **69 s before** native
  (p95 +11 s, p99 +46 s; n=194). The stream leads native, as expected for a 5-6 s feed vs native polling.
- Tails (p95 several kW) are transition moments, not a scale error. The cloud pair is the worst (cloud is slow).
- **Reserve:** a cloud reserve number change appears on stream `backup_reserve` within -4..+56 s in 11 of the
  matched cases. Later matches are value coincidences (reserve returned to an earlier value), not lag. Cloud →
  native reserve lag p50 75 s, p90 ~8000 s (same coincidence effect; p50 is the usable number).
- **Gate R3/R4:** GO for battery power and grid power as stream pairs (sign and scale settled). Stream had gaps
  09-29..10-02 (feed not running), so R4's freshness / debounce contract is required.

### P2 — CFG on/off → battery response (stream, charging = battery_power < -1000 W)
24 real CFG transitions in 7.9 days. **None at night.** All fell between 11:00 and 17:00. The stream was down for
16 of them (09-29..10-02). Usable rows:
| Time | Cmd | Solar W | Battery before W | Response s |
|---|---|---|---|---|
| 09-27 13:08 | on | 13428 | -1898 | 3 (solar was already charging) |
| 09-27 13:33 | off | 15466 | -15850 | 704 |
| 09-28 11:02 / 11:06 / 11:11 | on | ~12.5k-13.2k | already charging | 0-1 |
| 09-28 11:03 / 11:08 | off | ~12.9k | -8000 | never stopped (solar kept charging) |
| 09-28 12:46 | off | 15749 | -15962 | 67 |
| **10-03 14:04** | **on** | **1042** | **-59** | **103** |
| **10-03 17:00** | **off** | **683** | **-692** | **62** |
- The only clean sample (low solar) is 10-03: **on → charging in ~103 s; off → charging stops in ~62 s.**
  These match neither the ~35 min addendum figure in `energy_battery.py:262` nor anything daytime-solar.
- **Gate R3:** NOT enough data for `DEFAULT_CFG_OUTCOME_WINDOW_S`. n=1 clean pair. Provisional window 300 s
  (≈3× the observed 103 s). Re-run P2 after ~2 weeks of stream uptime that includes night grid-charge windows.
- No CFG `off` + grid charging (Enphase-autonomous) case was looked for; there were no night windows to test.

### P3 — cloud write failures, write rate, readback freshness
**(a) Failure census (recorder diagnostics, 7.9 d; URA anomaly_log, 30 d):**
- `sensor.enphase_cloud_hacs_cloud_error_code`: `none` on all 25 rows. `..._cloud_backoff_ends`: `unknown` on all
  25 rows → **0 backoff episodes**. `binary_sensor.enphase_cloud_hacs_cloud_reachable`: 5 `off` rows.
  `sensor.enphase_cloud_hacs_service_status`: `degraded` on 772 of 10162 rows (7.6 %).
- URA write-verify anomalies (30 d): `write_verification_failed` 48 and `pending_write_stuck` 180 (138 sev 3,
  42 sev 4). **All 228 are on `number.iq_battery_hacs_battery_reserve`** (latest reason
  `self_heal_starvation`, surface `reserve_soc`). **Zero on the CFG switch.**
  `write_local_witness_divergence` 3958 (sev 1; expected, local leg unsupported since fw 8.2, R6d).
- 429 / `TooManySessions` / auth-text counts: **not measured** (logs unreachable; see top of §13).

**(b) Write-rate baseline (recorder state changes of the cloud surfaces; proxy for URA writes):**
- CFG switch: 24 changes / 7.9 d; per day 2-6; peak **5 in one hour** (09-28 11h, 09-30 11h).
- Reserve number: 87 changes / 7.9 d; per day 3-30 (10-01 = 30); peak **9 in one hour** (10-01 02h).
- Suggested B2 churn threshold: > 12 writes / surface / hour (above the observed peak of 9 with margin). Tune with
  the B2 knob.

**(c) Readback freshness:**
- `sensor.enphase_cloud_last_successful_update` (entity id confirmed): age at each recorder sample p50/p90/p99 =
  1 / 1 / 1 s, max 7 s. Gap between successive successes p50 64 s, p90 73 s, p99 98 s, max 1304 s.
  **11 gaps > 300 s, 1 gap > 900 s in 7.9 d.**
- At every CFG switch row with state on/off (6586 rows), the age of the last cloud success was p99 1 s, max 181 s.
  **0 % of rows older than 300 s.** The switch drops to `unavailable` when the cloud is lost (25 rows); it does not
  hold a stale `off`.

### P4 — token / auth horizon (no token printed; decoded claims only)
| Entry | Credential | Issued | Expires |
|---|---|---|---|
| `enphase_envoy` (Envoy 482543015950), manual token | JWT `exp` | 2026-10-02 | **2027-10-02** |
| `enphase_ev` (Site 5700967) | cookie JWT `exp` | — | 2026-07-23 (past; session renews from stored password, `remember_password=True`) |
| `enphase_ev` | `hems_auth_last_success_utc` | 2026-07-25 01:04 UTC | — |
- Envoy token has ~12 months left. R5 days-to-expiry stays optional (Q4 default off holds).
- `enphase_ev` re-authenticates with the stored password. The stale `hems_auth_last_success_utc` (2026-07-25) needs a
  look under R5: either HEMS auth has not been needed since, or it is failing quietly. MQTT add-on token and MFA
  status were not probed (operator-run).

### B5 go / no-go — "trust cloud CFG `off` only when fresh"
**GO, as a cheap guard.** The cloud CFG readback was fresh on 100 % of on/off rows (max age 181 s). The freshness
gate (`last_successful_update` age ≤ 300 s, else treat CFG as unknown → tighten-only) would have fired in about 11
windows in 7.9 days, never during a CFG row. It costs almost nothing in normal running and closes the stale-`off`
case in a backoff. Two caveats: (1) 0 backoff episodes were seen, so the gate's fire path is untested live → it
needs an in-suite test at age 0 / 300 / 301 / None; (2) the log-text census is missing, so the 429 rate is unknown.
Re-run P3(a) when log access works (fix the ssh user's docker permission or use the Supervisor token).
