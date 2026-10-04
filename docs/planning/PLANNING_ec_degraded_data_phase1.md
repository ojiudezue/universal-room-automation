# PLANNING — EC degraded-data policy, Phase 1 (stream SOC tier, no release on missing data, cloud demoted, page before boundary)

**Card:** EC-DEGRADED-DATA-POLICY-1 (parent). Absorbs EC-ATTAIN-HOLD-WHEN-ENVOY-BLIND-1 (re-scoped: page, not
blind charge). Gated input: ENVOY-STREAM-AB-48H-1 (ends 2026-10-05 13:05 CDT). Not in scope:
EC-CONSUMPTION-DROPOUT-DAYS-1 (own card, see Non-goals).
**Author:** ura-planner, 2026-10-03 (REV 1). Plan only. No code edited.
**Tier:** **3** (breaker-safety invariant + shared primitive `battery_soc` consumed by ~30 sites in 4 files).
Two framing-disjoint plan reviews before build; four build reviews (A/B/C/D); operator checkpoint before deploy.
**Version:** PATCH (`5.103.x`). No new user-facing capability beyond a page and an optional config field.

---

## 0. What changed since DESIGN REV 2 / D0 (why Phase 1 is back on)

| Fact (2026-10-03) | Effect on the design |
|---|---|
| v5.103.37/38 shipped: rung-1 night ping-pong fixed (daylight horizon), WAIT holds forecast floor | The 10-01 flap is closed at its root. Phase 1 is no longer an incident fix; it is the degraded-data contract (SPEC INV-3, INV-4, INV-9). |
| Cloud SOC untrustworthy both ways: frozen 10.0 % for ~2 h on 10-02 (true SOC rose to 29 %); 2026-10-03 17:28 cloud 96.2 vs Envoy 90 and stream 90 | D0 NO-GO on P1-1/P1-5 stands. New: cloud must not be the sole basis for any grid-charge decision (today latched charges continue on it). |
| MQTT stream `sensor.envoy_stream_battery_soc` stayed live through both Envoy-integration outages today (~00:37-00:58 and ~16:00-17:28 CDT) | A trustworthy non-native SOC witness may now exist. It was down 09-30 → 10-03 13:03, which is why D0 found none. |
| Envoy outages are triggered by restart/reload: `/production.json` hangs > 60 s, integration setup stalls | Outages start exactly at restarts. Any stream-trust state that resets on restart would be absent exactly when needed (§D1 persistence). |
| Envoy energy counters lose consumption on dropout days; SPAN pair is the steady witness | Separate card. Not touched here. |

---

## 1. Institutional context verified

### 1.1 Documents read (full unless noted)
- `CLAUDE.md` (project) — Tier 3 protocol, plan-review tiers, knob ladder, producer/consumer rule, config-first.
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.5 blind-hold contract, §2.5a backout knob, §2.6 write model (read);
  headings for the rest.
- `docs/planning/DESIGN_ec_degraded_data_policy.md` REV 2 + §9 D0 results (full).
- `docs/planning/SPEC_ec_behaviour_contract.md` (full) — rows B2-B11, INV-3/4/5/6/9, D2-D6, Q4/Q5/Q7.
- `docs/planning/AUDIT_ec_drain_floor_and_pingpong_2026_10_03.md` (full).
- Kanban cards (`docs/planning/kanban.data.yaml:438-553`): EC-CONSUMPTION-DROPOUT-DAYS-1, ENVOY-STREAM-AB-48H-1,
  EC-RUNG1-WAIT-EV-PINGPONG-1, EC-DEGRADED-DATA-POLICY-1, EC-ATTAIN-HOLD-WHEN-ENVOY-BLIND-1,
  EV-ARBITRAGE-BREAKER-FLAP-ON-SOC-DROPOUT-1 (done, refuted).
- `docs/ha-config-snapshots/envoy_mqtt.yaml:20-72` — stream producer, `expire_after: 60`, field `enc_agg_soc`.
- Memory `project_session_pickup_2026_09_23.md` (stream naming contract, 25 entities, `local_stream` tier name
  proposed there).
- `docs/QUALITY_CONTEXT.md` — headings for Bug Classes #7, #19, #53, #57, #63 (the ones this plan names).
- Not re-read this session: `WORKFLOW_GUIDE.md`, `VISION_v7.md`, `ROADMAP`. The cycle does not change process or
  architecture direction.

### 1.2 Code read (all paths under `custom_components/universal_room_automation/domain_coordinators/`)
- `energy_battery.py`: `_state_age_s` :85-107; `_get_entity` :774-794; `_get_state_*` :840-868;
  **resolver `battery_soc` :870-989**; `_read_cloud_soc_snapshot` :1108-1155; `_fire_d2_nm` :1222-1267;
  `_evaluate_soc_resolution` :1269-1320; `_evaluate_soc_divergence` :1322-1404; `_read_fresh_float` :1702-1725;
  `net_power_w` :1767; `soc_envelope` :2407-2457; `get_lkg_snapshot` :2459-2479; `envoy_available` :2641-2675;
  `_effective_import_kw` :2814-2844; arbitrage CHARGE degraded hoist :3348-3380; CHARGE emit :3540-3561;
  `_degraded_entry_refused` :3614-3637; `_breaker_guard_fail_closed_on_blind` :3648-3673;
  `_precharge_refused_on_blind` :3699-3740; attain CHARGE builder :4229-4324; attain CHARGING route :4729-4829;
  attain entry refusals :4970-4985; `determine_mode` SOC read + blind branch :5103-5288; degraded flag :5297-5304;
  storm precharge degraded path :5395-5429; `_result` degraded suffix :5868-5875; CFG ON-heal suppression :5960-5984;
  `_result` return dict :6135-6160.
- `energy.py`: entity map :995-1040; LKG persist/restore :1636-1644, :2050-2053; `blind_hold_active` :3766-3806;
  snapshot :3817-3840; `reserve_write_verifiable` :3842-3856; `soc_envelope` passthrough :3895-3900;
  `_apply_dp_must_start_release` peer deferral :5378, :5280-5299; DP tick blind snapshot :4695-4719;
  decision call :5898-5903; dispatch :6066-6089; **breaker chokepoint `_execute_breaker_safe_dispatch` :6704-6810**;
  post-decision release dispatch :6812-6888; write-verifier tap / CFG ledger :8150-8212; `_send_nm_alert` :8238-8263.
- `energy_pool.py`: guard predicate :654-688; debounce :690-791; liveness ride :793-809; sighted drain :1502-1522;
  force-charge drain :1561-1567; **arbitrage pause/release `determine_arbitrage_actions` :2847-3027**.
- `energy_const.py`: cloud defaults :302-314; `DEFAULT_SOC_LKG_MAX_AGE_S` :318; `DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S`
  :326; `DEFAULT_SOC_DIVERGENCE_THRESHOLD_PCT` :327; `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S` :348;
  `CONF_SOC_DIVERGENCE_THRESHOLD_PP` :396; `CONF_BLIND_WINDOW_MAX_DEFER_MIN` :1702;
  `CONF_BLIND_WINDOW_ENTRY_DEBOUNCE_S` :1710; `CONF_RESERVE_VERIFIABLE_MAX_AGE_S` :1728;
  `DEFAULT_SOC_LKG_ENVELOPE_MAX_AGE_S` :1762.
- `config_flow.py:6910-6920` — the cloud SOC fallback field (pattern for the new optional field).
- `energy_tou.py:645` `get_next_high_rate_transition`.

### 1.3 Greps run and prior-art verdicts (REUSE / BUILD)

| Piece | Verdict | Evidence |
|---|---|---|
| SOC tier resolver | **REUSE + extend** (one new tier inside the existing property) | `energy_battery.py:870-989`; tier tag `_soc_source_last` :459 |
| Fresh-read by `last_reported` | **REUSE** | `_read_fresh_float(..., stamp="last_reported")` :1702; `_state_age_s` :85 |
| Per-tick tier observability (`soc_resolution`, `tier_disagreement_pp`) | **REUSE + extend** (add `stream` to tier map and to the pairwise gap) | `_evaluate_soc_resolution` :1269-1320, attr :1564 |
| Divergence detector + NM | **REUSE pattern** (dwell, abstain, per-day latch); new instance for stream-vs-native | `_evaluate_soc_divergence` :1322-1404; `_fire_d2_nm` :1222 |
| LKG + persistence | **REUSE** (stream reads re-anchor LKG; LKG blob shape unchanged) | :896-897, :2459-2479, `energy.py:1636-1644, 2050-2053` |
| SOC envelope | **REUSE unchanged** (benefits automatically from stream-anchored LKG) | :2407-2457 |
| Blind-window EVSE guard | **REUSE unchanged in Phase 1** (see Q3) | `energy_pool.py:654-791` |
| Write verifier / `is_reserve_verifiable` | **Not touched** (D5/Q4 is out of scope, see Q3) | `energy_write_verify.py` |
| CFG command ledger `_last_charge_from_grid_command` | **REUSE** (persisted, restored) | set `energy.py:8209-8211`; restore `energy.py:1869-1871` |
| CFG LKG latch `_last_known_grid_charge_on` | **REUSE unchanged** | `energy.py:6725-6763` |
| Degraded flag `_degraded_telemetry_source` | **REUSE** | `energy_battery.py:5297-5304` |
| Release-refusal shape ("re-claim as breaker, continue") | **REUSE** | `energy_pool.py:2947-2954` |
| Max-defer bound | **REUSE `CONF_BLIND_WINDOW_MAX_DEFER_MIN`** (60, rung 1, `<=0` = kill) | `energy_const.py:1702` |
| NM send | **REUSE** `_send_nm_alert` via `_fire_d2_nm`-style latch | `energy.py:8238`; `energy_battery.py:1222` |
| Next boundary | **REUSE** `get_next_high_rate_transition` | `energy_tou.py:645` |
| Stream entity config key | **NEW** `CONF_ENERGY_STREAM_BATTERY_SOC_ENTITY` (+ optional co-witness, see D1) | grep `envoy_stream` / `stream` in `custom_components/`: zero hits. Nothing equivalent exists. |
| Tier-trust predicate | **NEW** small helper `soc_tier_trusted()` | grep `trusted` in `energy_battery.py` / `energy.py`: no SOC-trust predicate exists; tier checks today are ad-hoc `== "envoy"` (:1393, `energy.py:2484`) |
| Per-tick tier capture | **NEW attr `_tick_soc_source`** (generalises local `soc_source_at_read` :5108) | `_result` :6136 re-reads `battery_soc`, which can change tier mid-tick (torn read, Bug Class #57) |
| `SocReading` dataclass, hold TTL, attain-on-cloud cap | **NOT BUILT** | DESIGN REV 2 §0, §9.3-9.4 |

### 1.4 Rejected on evidence (do not rebuild)
- **Local Enpower CFG switch as a breaker witness (SPEC D2/Q7).** Card EC-RUNG1-WAIT-EV-PINGPONG-1 (`kanban.data.yaml:479`)
  records it as a standing "on" flag. OR-ing it into breaker intent would pause EVs permanently. Not in Phase 1.
- **Cloud freshness by `last_reported` (P1-1)** and **attain on cloud SOC (P1-5)**: D0 NO-GO (§9.3).
- **Blind-branch "publish last command" (P1-2).** Not needed once the chokepoint resolves *unknown* correctly (D2b).
  The cloud CFG switch is usually readable during an Envoy outage, so the live leg already carries the truth.

### 1.5 Config-first check
No live knob fixes these. `CONF_RESERVE_VERIFIABLE_MAX_AGE_S` only affects guard engagement (DESIGN §7). Blanking
the cloud SOC fallback field (`config_flow.py:6910`) would remove cloud from the resolver entirely. That is a
heavier demotion than D3: HVAC, BAEC and the sensors would lose it as well. It is not recommended, but it is
**available today as an operator stopgap** if cloud-driven decisions bite before this ships.

---

## 2. Producer and consumer check

### 2.1 Producers
| Value | Producer | Health today |
|---|---|---|
| Native Envoy SOC | `sensor.envoy_482543015950_battery`, fresh by `last_reported` ≤ 300 s (:890-894) | Flaky: 22.7 dropouts/day in the D0 week; restart-triggered outages today |
| Stream SOC | `sensor.envoy_stream_battery_soc` = `meters.enc_agg_soc` from `/ivp/livedata/status` (observed ~5-6 s cadence + ~20 s clock skew, memory 2026-09-25; not 1 Hz) via add-on `13e68335_envoy_to_mqtt_json`; HA MQTT `expire_after: 60` → `unavailable` after 60 s of silence | Live since 2026-10-03 13:03; survived both of today's outages. **Unknown: whether HA refreshes `last_reported` on identical MQTT payloads (D0-S1).** |
| Cloud SOC | `sensor.iq_battery_hacs_battery_overall_charge`, fresh by `last_updated` ≤ 600 s (:957-972) | Untrustworthy: frozen, re-reported values; p95 \|Δ\| 11.5 pp, max 74.9 pp (D0 Q3); over-read 96.2 vs 90 today |
| LKG | stamped only on native reads (:896-897) → after D1, also on trusted stream reads | — |

### 2.2 Consumers of `battery_soc` (each sees the new tier and the trust split)
Trust decisions: `determine_mode` :5103 (all strategy branches), `blind_hold_active` `energy.py:3799`, DP tick
`energy.py:4701`, BAEC/EVSE paths `energy.py:5883, 6093, 6219-6235, 6299, 6399, 6424`, HVAC
`hvac.py:971, 2286, 2307, 3002`, write verifier `energy_write_verify.py:1380`, `energy_battery.py:2274, 3280, 6414`.
Display: `_result` :6136, `energy.py:3228`, `energy.py:2471` (gated `== "envoy"` at :2484), `energy.py:9798, 10071`.
Known `or 0` hazards (Phase 2, untouched): `energy.py:7397, 7513, 10159`.

**Consequence:** D1 (stream tier) changes the value seen by **every** consumer above when the native Envoy is down.
That is why D1 ships behind a kill switch and is enabled only on a GO from the A/B. D3 (cloud demotion) is scoped
to grid-charge emission only. It does not change what the other consumers see.

---

## 3. Falsifiable invariants (Reviewer D breaks these)

- **I-1 (no release on missing data).** On any tick where the resolver tier is not trusted (`cloud_fallback`,
  `none`, or a `*_reject` tag), the arbitrage release path (`energy_pool.py:2940-3027`) emits **zero**
  `switch.turn_on`, and no EVSE leaves `_paused_by_arbitrage`. The only exception is the D2a discharge after
  `CONF_BLIND_WINDOW_MAX_DEFER_MIN`, and only when CFG is *provably off* on every witness.
  *Repro to try:* off-peak; EVSE in `_paused_by_arbitrage` (label `breaker`, then `redirect`); alternate trusted and
  untrusted ticks ×10, with the tier flipping between `envoy`, `cloud_fallback`, `none` and `lkg` → expect
  turn_on only on trusted ticks.
- **I-2 (unknown ≠ off).** When the write-leg CFG switch reads `unavailable`/`unknown`/missing **and**
  (`_last_known_grid_charge_on` or `_last_charge_from_grid_command is True`), `grid_charge_intent` is True on that
  tick. An explicit `off` read is still believed.
- **I-3 (cloud never sole basis for grid charge).** No decision dict with `charge_from_grid=True` is returned
  while `_tick_soc_source == "cloud_fallback"`. This holds for every emitter (arbitrage CHARGE :3554, attain :4317,
  storm precharge :5418/:5429, and any future caller of `_result`), subject only to the Q2 storm exemption if the
  operator keeps it.
- **I-4 (stream tier is fail-closed).** A stream reading serves as SOC only when **all** of these hold:
  kill switch on; entity configured; state numeric, in 0-100, unit `%`; fresh per D1's freshness rule; co-witness
  live (if configured); trust state not `quarantined`. If any one fails, the resolver falls through to LKG and then
  cloud, exactly as today.
- **I-5 (byte-identical when off).** With `SOC_STREAM_TIER_ENABLED=False`, or the entity unset, and the native
  Envoy fresh: decisions, actions and attributes are byte-identical to develop, apart from the new attributes
  added in D5.
- **I-6 (page before boundary).** If the tier is untrusted continuously for ≥ `DEFAULT_SOC_UNTRUSTED_PAGE_DWELL_MIN`
  inside the `DEFAULT_SOC_UNTRUSTED_PAGE_LEAD_MIN` window before a high-rate boundary, exactly one NM page is
  sent for that boundary. The page does not repeat for the same boundary, including across a restart.
- **I-7 (peak de-escalation unchanged).** The fully-blind branch at :5159-5288 is byte-identical. INV-5 holds.

---

## 4. Deliverables

### D0 — Stream A/B readout + measurement probe (read-only; gate for D1 activation)

Run at or after **2026-10-05 13:05 CDT**. Use `ssh ha "python3 -" < probe_ec_stream_tier.py` with the recorder in
`mode=ro`. The script goes in the scratchpad; its report is appended to this doc as §9.

- **S1 — `last_reported` behaviour.** For `sensor.envoy_stream_battery_soc` rows, report the distribution of
  `last_reported_ts − last_updated_ts`, and the gaps between consecutive rows while the value is flat.
  *Discriminator:* if HA refreshes `last_reported` per MQTT message, a flat SOC overnight shows small
  `last_reported` ages. If it does not (MQTT skips identical writes), a flat SOC shows `last_reported` gaps of
  minutes to hours while the state stays numeric (`expire_after` not firing). This decides D1's freshness rule.
- **S2 — coverage.** For each native-SOC dropout minute in the A/B window (native not fresh by ≤ 300 s): was stream
  numeric (not `unavailable`)? Report % coverage. Also for the two named outages:
  **2026-10-03 ~16:00-17:28 CDT** (stream on) and ~00:37-00:58 (stream was off, expected 0 %).
- **S3 — agreement.** \|stream − native\| when both are fresh: p50, p95, p99, max. Compare `enc_agg_soc` against
  the native entity (Bug Class #63 smell: also compare `soc_top_level`).
- **S4 — co-witness liveness.** During every dropout minute, did `sensor.envoy_stream_grid_power` (or
  `..._battery_power`) change at least once per 120 s?
- **S5 — load effect (card criteria).** Count native Envoy-integration `unavailable` transitions and peak-period
  battery cutouts in the A/B window against the stream-off baseline. **Confound to report, not hide:** outages
  are restart- and reload-triggered (`/production.json` hang). Count restart-coincident outages separately (HA
  start events), because the stream cannot cause or prevent those.
- **S6 — strategy replay inputs for §6.** Strategy-sensor attributes (`reason`, `soc_source`, `soc_resolution`,
  `arbitrage_phase`, `evse_paused_by_arbitrage`) plus EVSE switch states, for 10-01 05:00-09:00Z,
  10-02 18:30-21:00Z, 10-03 05:30-06:10Z and 10-03 20:50-22:40Z.

**GO for D1 activation (all of):** S5 shows no rise in non-restart outages or peak cutouts; S2 coverage ≥ 95 % of
dropout minutes and 100 % of the 16:00-17:28 outage; S3 p99 ≤ 2 pp and max ≤ 5 pp; S4 co-witness moved in every
covered minute; S1 resolved (it picks the freshness rule).
**NO-GO:** stop the add-on per the card. D1 ships with the kill switch off, or the operator descopes it (Q1).
D2-D5 do not depend on the A/B.

**Acceptance**
- **Verify:** §9 of this doc carries the S1-S6 tables and a GO/NO-GO line per criterion.
- **Live:** none (read-only).

### D1 — Stream SOC tier in the resolver (kill-switched)

**Where:** `energy_battery.py` `battery_soc` :870-989. Insert after the native-primary block (:895-903) and
**before** the LKG block (:904-908).

**Logic:**
1. If `SOC_STREAM_TIER_ENABLED` is False, or `_get_entity("battery_soc_stream")` is None/empty: skip (today's path).
2. Read the state. Reject on `unknown`/`unavailable`, non-numeric, unit not `%`, or out of 0-100 (same guards as
   cloud :922-947).
3. Freshness, per the D0-S1 outcome:
   - **(a) HA refreshes `last_reported` per message:** `_read_fresh_float(eid, DEFAULT_SOC_STREAM_MAX_AGE_S,
     stamp="last_reported")`.
   - **(b) It does not:** freshness = state is not `unavailable` (the `expire_after` contract) **and** the co-witness
     changed within `DEFAULT_SOC_STREAM_COWITNESS_MAX_AGE_S`. `DEFAULT_SOC_STREAM_MAX_AGE_S = 0` (bypass).
     The co-witness is then **mandatory**: with no co-witness configured, the tier refuses (fail-closed). This
     covers a second home whose stream sensor lacks `expire_after`.
4. Trust state `_soc_stream_trust ∈ {"trusted", "quarantined"}` must be `trusted`.
5. On success: `self._soc_lkg = value`, `self._soc_lkg_at = now`, `self._soc_source_last = "stream"`, return.
   LKG re-anchoring keeps `soc_envelope()` tight. The LKG blob shape is unchanged (`source` is dropped in
   `get_lkg_snapshot` :2475).

**Divergence and quarantine** (new `_evaluate_stream_divergence`, a copy of the `_evaluate_soc_divergence`
pattern :1322):
- Runs once per tick from the same caller as `_evaluate_soc_resolution`. It compares only when native **and**
  stream are both fresh this tick. Otherwise it abstains and keeps its state.
- \|native − stream\| > `DEFAULT_SOC_DIVERGENCE_THRESHOLD_PCT` (3, REUSED :327) for
  `DEFAULT_SOC_STREAM_QUARANTINE_TICKS` (2) consecutive compared ticks → `quarantined`. Send one NM via
  `_fire_d2_nm` (latch `_d1_stream_div_nm_date`).
- Within threshold for 2 consecutive compared ticks → `trusted`.
- **Persistence:** `{state, since_iso}` saves and restores on the existing EC energy-state path next to
  `battery_soc_lkg` (`energy.py:1636-1644`, `:2050-2053`), as a new key `battery_soc_stream_trust`. Default when
  absent = `trusted`. **Save immediately on every trust transition** (event save, as above) — the 15-min cadence
  would let a quarantine set <15 min before a restart silently revert to `trusted` (fail-open). Rationale: outages start at restart, so requiring a post-restart agreement would disable the
  tier exactly when it is needed. A persisted `quarantined` survives restart.

**Downstream semantics, kept deliberately narrow:**
- `envoy_available` (:2641) is **unchanged** (native-based). On a stream tick, `_degraded_telemetry_source =
  "stream"`. So fresh grid-charge entries stay refused (`_degraded_entry_refused` :3614; INV-6, because
  `net_power_w` is still native). The reason line carries `(degraded telemetry: stream)`.
- `blind_hold_active` is False on stream ticks (SOC resolved). The EVSE guard does not engage. This is correct
  when the SOC is trusted.
- A latched arbitrage CHARGE (CFG live on, :3363-3380) continues on stream SOC and stops at target with a real
  number. A latched attain releases to HOLD when net power is unreadable (:4799-4829). That is unchanged and safe.
- Tier maps: add `"stream": "local_stream"` to `_evaluate_soc_resolution` :1288. Add stream to the pairwise gap
  :1316 (`tier_disagreement_pp`).

**New config field:** `CONF_ENERGY_STREAM_BATTERY_SOC_ENTITY = "energy_stream_battery_soc_entity"` → map key
`battery_soc_stream` in `_build_entity_map` (`energy.py:999-1025`). Add an optional EntitySelector (domain
`sensor`) next to the cloud SOC field (`config_flow.py:6910-6920`), **with no default**. No house-specific default
entity: per the multi-home rule, a second install without a stream degrades to today's behaviour.
Optional `CONF_ENERGY_STREAM_COWITNESS_ENTITY` (map key `stream_cowitness`), needed only under S1 outcome (b).
Add strings to `strings.json` + `translations/en.json`. Labels (style guide): "Local battery stream" / "Stream
heartbeat sensor". Helper text: "Optional. A fast local battery-level sensor used when the Envoy integration
drops out."

### Acceptance Criteria
- **Test:** `test_stream_tier_serves_when_native_stale` — native stale, stream fresh → `battery_soc == stream`,
  `_soc_source_last == "stream"`, LKG re-anchored.
- **Test:** `test_stream_tier_order_native_wins` — both fresh and different by 2 pp → native value returned.
- **Test:** `test_stream_tier_kill_switch_off_byte_identical` — constant False, native stale, stream fresh → result
  equals develop (LKG then cloud).
- **Test:** `test_stream_tier_rejects` — parametrized: unavailable, non-numeric, unit `W`, 101, stale stamp (a),
  co-witness stale (b), co-witness unconfigured under (b), quarantined → falls through.
- **Test:** `test_stream_quarantine_and_recovery` — 2 divergent compared ticks → quarantined + 1 NM; abstains when
  native absent; 2 agreeing → trusted.
- **Test:** `test_stream_trust_persists_across_restart` — quarantined survives save/restore; missing key → trusted.
- **Test:** `test_stream_tick_degraded_refuses_fresh_charge` — stream tier, attain entry wanted → refused
  (`_degraded_entry_refused`).
- **Test:** config-flow round trip for both new fields (blank → None; entity → mapped).
- **Live (after A/B GO and kill switch on):** in the next native outage, `sensor.ura_energy_coordinator_battery_strategy`
  shows `soc_source=stream` and `soc_resolution.tier=local_stream`, `soc` within 2 pp of the stream entity, and
  the reason line does not say "Envoy unavailable — holding". *Discriminator:* under a broken D1 the same outage
  shows `soc_source=cloud_fallback` or the blind-hold reason.

### D2 — Never release a protective pause on missing data

**D2a — arbitrage release refusal.** At `energy_pool.py:2940`, inside the release loop and **before**
`self._arbitrage_pause_reason.pop` / `discard` (:2955-2956), add a second refusal next to the existing
`grid_charge_on` refusal (:2947-2954):
- **(Plan-review #2 rewrite)** Thread the verdict as an explicit kwarg, exactly like `grid_charge_on`:
  `determine_arbitrage_actions(..., soc_untrusted: bool = False)`. The caller captures
  `soc_untrusted = battery._tick_soc_source not in {"envoy","lkg","stream"}` **immediately after
  `determine_mode` returns (`energy.py:5898`), before the first `await`**, and threads the local through
  `_execute_breaker_safe_dispatch` → `_dispatch_post_decision_tou_and_arbitrage` (`:6884`). Do NOT read it via a
  coordinator method at release time: (i) `attach_coord` is only called when `_ev_tou_enabled` (`energy.py:6853`),
  so with EV TOU off the "no coord → False" fallback silently disables D2a; (ii) `_evaluate_battery`
  (`energy.py:6620`) re-runs `determine_mode` and can overwrite `_tick_soc_source` across the awaits between
  5898 and 6084. Default `False` keeps legacy stubs on today's behaviour.
- If `untrusted`, keep membership and the label, log once per epoch, and `continue`. **No debounce**: refusing to
  loosen must take effect on the first untrusted tick (DESIGN §3).
- **Discharge (the suppression needs one):** stamp `_arb_release_refused_since[evse_id]` (monotonic) on the first
  refusal; clear it on any trusted tick or on release. After `CONF_BLIND_WINDOW_MAX_DEFER_MIN` (REUSED, 60), allow
  release **only if CFG is provably off**: `grid_charge_on` False **and** `_last_charge_from_grid_command is not
  True` **and** the write-leg CFG switch reads exactly `off`. If CFG is not provably off, keep holding. That
  outcome is covered by the D4 page, and breaker safety outranks the car charge.
  `CONF_BLIND_WINDOW_MAX_DEFER_MIN <= 0` → no refusal (today's behaviour). This matches the documented
  kill-switch semantics of that constant (manual §2.5a).
- Restart: `_arb_release_refused_since` is RAM-only. After a restart the timer restarts, which means more holding,
  not less. That is fail-safe. `_paused_by_arbitrage` persistence is unchanged.
- Data back (trusted tick): refusal lifts, and the release runs through the existing peers (:2962-3027).

**D2b — CFG "unknown ≠ off" (still applicable after v5.103.37: the chokepoint is unchanged).** In
`_execute_breaker_safe_dispatch`, at the `else` (unknown/unavailable) branch `energy.py:6747-6759` and the
`st is None` branch :6736-6740 and the except branch :6760-6763: set `live_grid_charge_on = True` when
`_last_known_grid_charge_on` **or** `self._battery._last_charge_from_grid_command is True`. An explicit `off`
read (:6744-6746) is still believed. That avoids the stale-ledger trap on the *same* tick: an operator turning
CFG off by hand leaves the ledger True, but the switch reads `off`.
*(Plan review #1 — stale ledger across ticks.)* The ledger is only advanced by URA's own dispatch tap
(`energy.py:8209-8211`), and `_result` never emits `turn_off` when the switch already reads off (:6031). So after a
manual stop the ledger stays True indefinitely, and every later `unavailable` blip would re-pause EVs as
`breaker`. Rule: stamp `self._last_cfg_off_read_at` (RAM, monotonic-free UTC) on every explicit `off` read in the
chokepoint, and count the ledger only when `_last_charge_from_grid_command is True` **and**
(`_last_cfg_off_read_at is None` **or** `_last_charge_from_grid_command_at > _last_cfg_off_read_at`). Test:
`test_breaker_intent_stale_ledger_after_manual_off` (ledger True at T0, `off` read at T1, `unavailable` at T2 →
intent False).
The fully-blind return dict keeps `"charge_from_grid": False` (:5287), because the chokepoint now carries the
truth. Only one site changes.

**D2c — must-start-by must not override a breaker pause (plan review #1, pre-existing leak; operator Q7).**
`_apply_dp_must_start_release` (`energy.py:5378-5470`, fired by the point-in-time callback `_on_dp_must_start_by`
`:5656-5673`) defers only to grid-cap / load-shed / fill-priority (`:5398-5402`). It does **not** defer to
`_paused_by_arbitrage`, and it does not read CFG. It calls `switch.turn_on` directly (`:5460-5466`). The
arbitrage pause loop then skips the EVSE as "already paused" (`energy_pool.py:2911-2912`) and never re-issues
`turn_off`. Legal repro: shoulder/summer off-peak; EVSE in `_paused_by_dp` (sticky drain claim) and in
`_paused_by_arbitrage` with label `breaker` (rung-2 CHARGE, CFG on, 03:00-05:00 under lead 180); must-start-by
(default 03:00-04:00, `PLANNING_evse_drain_precedence.md:217`) fires → EV on + ~20 kW grid charge = the 134 A
compound load the chokepoint exists to prevent. Same path on an untrusted tick defeats D2a's intent.
Fix (one predicate): before the turn_on, keep the DP claim sticky when
`self._ev._arbitrage_pause_reason.get(evse_id) == "breaker"` **or** the write-leg CFG reads `on`
**or** (`unknown/unavailable` and the D2b ledger rule says on). Liveness is preserved: the next decision tick
after grid charge ends retries via the existing sticky DP retry driver. `redirect` label does not block
(cost, not safety). Tests: `test_must_start_by_defers_to_breaker_pause`,
`test_must_start_by_defers_when_cfg_live_on`, `test_must_start_by_releases_on_redirect_label`; wire-in anchor via
`_on_dp_must_start_by`. If the operator rejects D2c (INV-DP2 liveness priority), card it as
`EC-MUST-START-BY-BREAKER-BYPASS-1` — it must not be dropped silently.

**Not changed:** the guard's sighted-tick drain (`energy_pool.py:1520-1522`). A trusted tick is real data
returning, so draining there is correct.

### Acceptance Criteria
- **Test:** `test_arb_release_refused_on_untrusted_tier` — parametrized over tier tags `cloud_fallback`, `none`,
  `fallback_stale_reject`, `fallback_unit_reject`, `fallback_range_reject` and over labels `breaker`/`redirect` →
  0 turn_on, membership kept.
- **Test:** `test_arb_release_alternating_ticks_no_turn_on` — the I-1 repro (×10 alternation) → turn_on only on
  trusted ticks.
- **Test:** `test_arb_release_discharge_after_max_defer_cfg_off` — at 59 min held; at 61 min with CFG provably off
  → released. At 61 min with ledger True or switch `unavailable` → still held.
- **Test:** `test_arb_release_max_defer_zero_is_kill_switch` — `CONF_BLIND_WINDOW_MAX_DEFER_MIN=0` → today's
  behaviour.
- **Test:** `test_breaker_intent_unknown_with_last_command_on` — switch `unavailable`, LKG latch False, ledger True
  → `grid_charge_intent` True; switch `off`, ledger True → False.
- **Test (wire-in anchor):** coordinator-tick test drives `_dispatch_post_decision_tou_and_arbitrage` with a
  battery whose `_tick_soc_source="cloud_fallback"` → no EVSE turn_on. A call-neuter drill on the new refusal
  line must fail it.
- **Live:** in the next native outage without stream trust, `ura_activity_log` shows no `charger_on` from owner
  `arbitrage` while `soc_source ∉ {envoy, lkg, stream}`. *Discriminator:* a `charger_on` with `pause_owners=none`
  on an untrusted tick means D2a is not wired.

### D3 — Cloud SOC demoted: never the sole basis for a grid charge

**Chokepoint, not per site (Bug Class #53: one missed site is the failure mode):** in `_result`
(`energy_battery.py:5862+`), before actions are built: if `charge_from_grid is True` and
`self._tick_soc_source == "cloud_fallback"` (and the call is not storm-exempt, Q2), then:
- force `charge_from_grid = False`. `_result`'s existing diff logic then emits `switch.turn_off` if the CFG is
  currently on (this is the stand-down of a latched charge);
- keep `reserve_level` as requested (the battery holds rather than discharges; no grid pull);
- append `" (grid charge withheld: cloud-only battery reading)"` to `reason`;
- set `self._grid_charge_withheld_untrusted = True` for the tick (attribute, D5).

The arbitrage phase may stay CHARGE in RAM. The chokepoint then still sets `pause_reason="breaker"` through
`arbitrage_charging_phase` (`energy.py:6775-6778`), so EVs stay paused. That is conservative and intended.

**`_tick_soc_source`:** set once in `determine_mode` at :5108 (`soc_source_at_read`). It replaces the local
variable, and every in-tick consumer reads it. This is needed because `_result` :6136 re-invokes `battery_soc`,
which can change tier mid-tick (Bug Class #57 torn read). `_result` must not re-derive the tier.

**Sites this covers (enumerated, re-verify in plan review):** arbitrage CHARGE `energy_battery.py:3549-3561`;
attain CHARGE builder :4313-4324 (entry already refused when degraded, :4980; continuation :4729+); storm
precharge :5414-5421 and :5425-5429; the CFG ON-heal path inside `_result` :5960-5984 (already suppressed when
degraded; D3 is stricter on cloud). The fully-blind branch (:5159-5288) does not call `_result` and is unchanged.

**What D3 does NOT change:** SOC-derived reserve writes on cloud ticks (e.g. hold `reserve=int(soc)`, mid-peak
freeze). These carry cost risk but not grid-pull risk, so they belong to Phase 2 (envelope holds). The cloud value
stays in `battery_soc` for all other consumers.

### Acceptance Criteria
- **Test:** `test_cloud_tier_withholds_arbitrage_charge` / `..._attain_continuation` — latched charge, tier
  `cloud_fallback`, CFG live on → decision `charge_from_grid=False`, actions include `switch.turn_off` on the
  write-leg CFG, reason carries the suffix.
- **Test:** `test_cloud_withhold_keeps_ev_paused` — same tick through `_execute_breaker_safe_dispatch` →
  `pause_reason == "breaker"`.
- **Test:** `test_stream_and_lkg_tiers_not_withheld` — same scenario on `stream` and on `lkg` → `charge_from_grid`
  True (continuation allowed).
- **Test:** `test_tick_soc_source_not_torn` — the tier flips between the :5103 read and `_result` :6136 → the
  withhold decision follows the :5103 tier.
- **Test (Tier-3 per-site mutation, Reviewer C):** bypass the chokepoint → each of the 3 emitter tests fails.
- **Live:** if a cloud-only tick occurs during a latched charge, the strategy reason shows the withheld suffix and
  the cloud CFG switch goes `off` within one tick. If no such window occurs before close, prove this in-suite only
  and say so in the README.

### D4 — Page the operator before a boundary when SOC is untrusted (SPEC Q5 "hold and page", INV-9)

**Where:** a new `BatteryStrategy._evaluate_untrusted_boundary_page(now, tou_period)`. It is called from
`determine_mode` after the tier capture, on **both** the blind-branch return path and the proceeding path, so it
runs once per tick.

- Untrusted = `_tick_soc_source ∉ {envoy, lkg, stream}`. Dwell starts at the first untrusted tick and resets on
  any trusted tick. **Dwell is wall-clock** (`now - _untrusted_since`), never a tick count: `determine_mode` has
  two callers (`energy.py:5898` timer, `:6620` `_evaluate_battery`), so "once per tick" is not guaranteed.
- Boundary from `self._attain_target_boundary(now, tou_period)` (`energy_battery.py:4029`, REUSE) — off_peak →
  next mid_peak/peak; **mid_peak → next peak**. (Plan-review #2 fix: `get_next_high_rate_transition` only finds
  off_peak→high and would skip the 10-02 mid_peak window that §7 row 3 asserts.) Skip if None or if in `peak`.
- Fire when dwell ≥ `DEFAULT_SOC_UNTRUSTED_PAGE_DWELL_MIN` **and** minutes to boundary ≤
  `DEFAULT_SOC_UNTRUSTED_PAGE_LEAD_MIN`. This is a notification, so the dwell is a debounce on *alerting*, not on
  a loosening. It filters the 66 % of outages under 2 min.
- Latch per boundary: `_untrusted_page_boundary_iso`. Persist under its **own** KV key `ec_untrusted_page_latch`
  (not inside the D1 blob — D1 ships kill-switched and D4 must persist regardless). Save **immediately on latch**
  (`hass.async_create_task(self._save_evse_state())`-style event save), not only on the 15-min cadence
  (`_periodic_db_writes` `energy.py:8515`); otherwise a restart within 15 min of the page re-pages.
- Message (plain): "Battery level is unknown (Envoy offline{, cloud reading only}) {N} min before the {HH:MM}
  higher-rate period. Last trusted reading {LKG}% at {time}. URA is holding and will not grid-charge. Charge by
  hand if needed." Severity `high`, hazard_type `battery_soc_unknown_before_boundary`.
- Send via the coordinator `_send_nm_alert`, copying the `_fire_d2_nm` shape (:1222-1267) — latch-before-dispatch so a
  failed send cannot storm. **Do NOT call `_fire_d2_nm` itself:** it latches per *calendar day* and hardcodes
  `severity="warning"`. Either add `latch_value`/`severity` params to it (default-preserving) or write a sibling.

### Acceptance Criteria
- **Test:** `test_page_fires_once_per_boundary` — untrusted for 15 min at T-60 → exactly 1 send; more ticks → 0;
  next boundary → 1.
- **Test:** `test_page_not_fired_on_blip` — untrusted 5 min then trusted → 0.
- **Test:** `test_page_not_fired_on_stream_tier` — native down, stream trusted → 0.
- **Test:** `test_page_latch_survives_restart`.
- **Test (replay, §6):** 10-02 and 10-03 16:00 fixtures → page time asserted.
- **Live:** the next untrusted window inside the lead → one NM delivered, visible in NM history. Otherwise prove it
  in-suite and record that in the README.

### D5 — Observability (attributes only)

Add to the battery strategy sensor (alongside `soc_source` :6631 / `soc_resolution`): `soc_tier_trusted` (bool),
`stream_trust` (`trusted`/`quarantined`/`disabled`), `grid_charge_withheld_untrusted` (bool),
`arb_release_refused` (list of evse ids). No new entities.

### Acceptance Criteria
- **Test:** attribute presence and values for each tier.
- **Live:** attributes present after restart, with `stream_trust=disabled` until the kill switch flips.

---

## 5. Knobs (every new number, with its rung)

| Name | Value | Rung | Why this rung / kill-switch |
|---|---|---|---|
| `SOC_STREAM_TIER_ENABLED` | `False` at ship → `True` on A/B GO | 1 (module) | Trust decision on a safety input; flipping it must be reviewed. False = today's resolver. |
| `CONF_ENERGY_STREAM_BATTERY_SOC_ENTITY` | unset | 2 (config flow) | Per-deployment wiring; a second home has no stream. Unset = tier off. |
| `CONF_ENERGY_STREAM_COWITNESS_ENTITY` | unset | 2 | Per-deployment wiring. Mandatory only under S1 outcome (b). |
| `DEFAULT_SOC_STREAM_MAX_AGE_S` | 90 if S1(a); 0 (bypass) if S1(b) | 1 | Protocol window, set by measurement. 0 = rely on `expire_after` + co-witness. |
| `DEFAULT_SOC_STREAM_COWITNESS_MAX_AGE_S` | 120 | 1 | Protocol window (~1 Hz producer; 2× `expire_after`). |
| `DEFAULT_SOC_STREAM_QUARANTINE_TICKS` | 2 | 1 | Anti-flap count for a trust verdict. |
| Divergence threshold | REUSE `DEFAULT_SOC_DIVERGENCE_THRESHOLD_PCT` = 3 (:327) | 1 | Same physical source; 3 pp is already the house value. |
| Release max-defer | REUSE `CONF_BLIND_WINDOW_MAX_DEFER_MIN` = 60 (:1702) | 1 | `<=0` = no refusal (documented kill switch). |
| `DEFAULT_SOC_UNTRUSTED_PAGE_LEAD_MIN` | 90 | 1 | SPEC Q5 T-90. The operator might tune it; Q4 asks whether to promote it to a Number. |
| `DEFAULT_SOC_UNTRUSTED_PAGE_DWELL_MIN` | 10 (= 2 ticks) | 1 | Filters blips (66 % < 2 min, `PROBE_envoy_outage_frequency.md`). |

## 6. Config extremes / combinatorics (test at the corners)
- `CONF_BLIND_WINDOW_MAX_DEFER_MIN` ∈ {0, 1, 60, 1440}.
- Stream max-age ∈ {0 (bypass), 1, 90}; co-witness configured / unconfigured / stale, × S1 mode.
- Kill switch {on, off} × entity {set, unset} × native {fresh, stale} × stream {fresh, stale, quarantined}.
- `_last_charge_from_grid_command` ∈ {None, True, False} × write-leg CFG ∈ {on, off, unavailable, missing state} ×
  `_last_known_grid_charge_on` ∈ {True, False}.
- Tier tags: every value `_soc_source_last` can take (:898, :907, :937, :946, :971, :986, :988, + `stream`).
- Page lead ∈ {0 (never pages), 90, 1440}; dwell ∈ {0, 10}; boundary None (holiday schedule).
- `floor > target`-style independence: page lead > minutes-to-boundary at the first untrusted tick (fires after
  dwell, not instantly).

## 7. Replay acceptance (fixtures built from D0-S6, committed under `quality/tests/fixtures/`)

Pattern: reuse the shape of `quality/tests/fixtures/ec_nights_2026_09_28_10_02.json` +
`test_ec_daylight_horizon_poor_night_floor.py`. Fixture values are recorder-derived, not hand-copied
(Tier 2-DB fixture-authority rule). Each row states expected behaviour under the fix **and** under a plausible
different failure.

| Window | Expected under Phase 1 | Discriminates against |
|---|---|---|
| **2026-10-03 ~16:00-17:28 CDT** (native out, stream live, cloud 96.2 vs 90 at 17:28) | Kill switch on: `soc_source=stream` all window, SOC ≈ 90, no page, no blind-hold reason. Kill switch off: cloud or blind tier; page fires by T-dwell (boundary 17:00 shoulder) if untrusted ≥ 10 min before 17:00; no grid charge emitted on any cloud tick; no arbitrage EV release on an untrusted tick. | Broken D1 → cloud tier with 96.2 used; broken D3 → `charge_from_grid=True` on a cloud tick; broken D4 → no page |
| **2026-10-03 ~00:37-00:58 CDT** (restart-induced; stream off) | Tier lkg → cloud/none. No arbitrage release on untrusted ticks. No page (boundary 17:00 is outside the 90-min lead). Stream tier absent (unavailable) → falls through cleanly. | Over-eager page; stream "unavailable" mis-parsed as 0 |
| **2026-10-02 19:00-20:48Z (14:00-15:48 CDT)** attain blind hold, cloud frozen 10 % | Blind branch still holds (no blind charge; P1-5 NO-GO). **Page fires once at the first tick with dwell ≥ 10 min and T ≤ 90 min before 17:00**, i.e. ~15:30 CDT. Cloud ticks (if any) emit no grid charge. | Today: silent hold (INV-9 fails) |
| **2026-10-01 05:50-07:30Z** (native drops; rung-1 loop, now fixed by v5.103.37) | The 1 turn-on on a blind tick and the 3 on `cloud_fallback` ticks (D0 §9.1) → refused by D2a. Turn-ons on `envoy`/`lkg` ticks are unaffected by this cycle (the rung loop fix owns them). | D2a mis-wired → those 4 turn-ons replay |

## 8. Non-goals (explicit)
- Consumption source swap / dropout-day poisoning → **EC-CONSUMPTION-DROPOUT-DAYS-1** (not trivially in scope: it
  touches forecast history producers, a different surface).
- Stream as a **net-power** source (would unlock fresh grid-charge entries on a stream tick) → Phase 3 /
  `TelemetryPair`; see Q5.
- EVSE guard engagement on cloud-only (SPEC D5/Q4), envelope-bounded strategy holds, HVAC `or 0`, DP exception
  direction → Phase 2.
- Local Enpower CFG witness (§1.4).
- EC-EV-TOGGLE-TRIPWIRE-1 (own card).

## 9. D0 results
*(to be appended after 2026-10-05 13:05 CDT)*

---

## 10. Build, review and deploy protocol
- **Plan reviews (Tier 3, two, framing-disjoint):** (1) completeness. Re-enumerate every `charge_from_grid=True`
  emitter, every `battery_soc` consumer, every arbitrage-release path (including `release_all_tou`
  `energy.py:6868`, `_apply_dp_must_start_release`, and the force-charge drain), and every tier tag.
  (2) Build prediction. Name the ambiguities a builder will mis-read (S1 branch, persistence key, `_tick_soc_source`
  lifetime, attach-coord fallback).
- **Builder:** `ura-super-builder`, in a worktree under `.claude/worktrees/`. Build order: D2b → D2a → D3 → D4 → D5
  → D1 (kill switch False). D1's constant flips only after D0 GO, in the same branch if the readout lands before
  deploy, or in a one-line follow-up patch under the same review record.
- **Reviews A/B/C/D** as in CLAUDE.md Tier 3. D's falsification target is I-1 + I-3 across the whole surface
  (pre-existing code included). C does real per-site source mutation for D2a, D2b, the D3 chokepoint and the D1
  insert.
- **Pre-deploy:** orchestrator re-greps emitters and runs the mutation drill. Operator checkpoint with the invariant
  proof. Respect the no-restart-while-sleeping rule.
- **Post-deploy:** README validated table; supersession audit (the cloud-tier `last_updated` gate :957-972 and
  `_degraded_entry_refused` semantics are KEEP; nothing expected in DELETE).

## 11. Operator questions
1. Q1 — If the stream A/B is NO-GO, ship D1 dormant (constant off) or drop it?
2. Q2 — Storm precharge on cloud-only SOC: keep the v5.17.6 exemption (recommended; bounded, rare) or apply "cloud never sole basis"?
3. Q3 — Should the blind-window EV guard also engage on cloud-only ticks (SPEC Q4)? Deferred to Phase 2 by default.
4. Q4 — Page lead time (90 min): code constant or dashboard Number?
5. Q5 — Later card: use stream grid power as the import witness so attain can grid-charge on a stream tick (closes 10-02 automatically)?
6. Q6 — A/B confound: count restart-caused outages separately (today's 16:00 outage had the stream on)?
7. Q7 — Must-start-by (03:00-04:00 liveness) currently overrides a `breaker` arbitrage pause (D2c). Keep the breaker pause (recommended) or let liveness win and card it?

---

## Plan review #2 (build-prediction) — 2026-10-03, ura-reviewer

Framing: what will the builder get wrong. Every item verified against develop at the cited line. Items marked
**[fixed in plan]** were edited above; the rest are directives the builder must follow (treat as part of the spec).

| # | Sev | Item | Disposition |
|---|---|---|---|
| R2-1 | HIGH | D2a read the trust verdict via `coord.soc_untrusted_this_tick()` + `attach_coord`. `attach_coord` runs only under `_ev_tou_enabled` (`energy.py:6847-6856`) → with EV TOU off, D2a is silently off (#53). Also a torn read across awaits: `_evaluate_battery` (`energy.py:6620`) re-runs `determine_mode`. | **[fixed in plan]** capture-before-first-await local, threaded as kwarg like `grid_charge_on`. Wire-in anchor test must run with `_ev_tou_enabled=False` too. |
| R2-2 | HIGH | D4 boundary via `get_next_high_rate_transition` returns only the off_peak→high edge (`energy_tou.py:645-660`); "skip if in high-rate" kills the mid_peak→peak case that §7 row 3 (10-02 ~15:30 page) asserts. | **[fixed in plan]** REUSE `_attain_target_boundary` (`energy_battery.py:4029`); skip only in `peak`. |
| R2-3 | HIGH | D1 quarantine persists on the 15-min `_save_evse_state` cadence (`energy.py:8515`) with default-absent=`trusted` → quarantine set <15 min before a restart reverts to trusted (fail-open, exactly at the restart-triggered outage). Same for the D4 latch (re-page). | **[fixed in plan]** event-save on transition/latch; D4 latch gets its own key so it persists with D1 kill-switched. |
| R2-4 | MED | `_fire_d2_nm` (`energy_battery.py:1222-1267`) latches per calendar day and hardcodes `severity="warning"`; D4 needs per-boundary latch + `high`. A builder "reusing" it ships a per-day page at the wrong severity. | **[fixed in plan]** |
| R2-5 | MED | Dwell/quarantine counted in "ticks": `determine_mode` has two callers (5898, 6620), so two calls seconds apart can satisfy "2 ticks". | **[fixed in plan]** for D4 (wall-clock). **Builder directive** for D1: a compared sample counts only if ≥ 60 s after the previous compared sample (or count distinct native `last_reported` stamps). Test: two back-to-back calls in the same second → still `trusted`. |
| R2-6 | MED | D3 no-flap. A single `cloud_fallback` tick inside a latched charge emits `switch.turn_off` (`_result` else-branch :6023-6066); the next native tick re-emits `turn_on` (no degraded flag → ON-heal not suppressed). Alternating tiers → CFG off/on per tick on the cloud write leg. Not stranding (latch stays in RAM, native tick resumes; an `lkg` tick cannot follow a cloud tick without a native read in between, since LKG is stamped only on native/stream reads :896), but it is actuation churn and a write-verifier interaction. | **Builder directive:** accept the toggle (correct direction: withhold is the safe side) but add test `test_cloud_withhold_alternation_bounded` — envoy/cloud ×10 alternation → turn_off only on cloud ticks, turn_on only on native ticks, never on an `lkg` tick, attain/arbitrage phase not reset to inactive by the withhold. Do NOT add a "N trusted ticks to resume" hysteresis — that strands the charge. |
| R2-7 | MED | D3 attr `_grid_charge_withheld_untrusted` is set only inside `_result`; the blind branch (:5159-5288) returns without `_result` → a True from the previous tick sticks. | **Builder directive:** entry-reset it (and the D2a/D5 per-tick values) at the top of `determine_mode`, next to the `_tick_soc_source` capture at :5108. D5 `soc_tier_trusted` derives from `_tick_soc_source`, NOT `_soc_source_last` (:6631), which HVAC/DP reads of `battery_soc` mutate between ticks. |
| R2-8 | MED | D2b suppression discharge missing. Ledger True + write-leg CFG `unavailable` for hours: `_result` emits `turn_off` only when `current_cfg is True` (:6030), so the ledger never flips False → `grid_charge_intent` stays True → EVs breaker-paused until the cloud switch returns. Pre-existing for the LKG latch; D2b widens it to "LKG False, ledger True". | **Builder directive:** no time-bound loosening (breaker safety outranks car charge); the discharge is (a) explicit `off` read, (b) the D4-style page — extend D4's trigger to also fire when `grid_charge_intent` was forced True by the unknown-leg path for ≥ dwell during off_peak with an EVSE held. Test both. |
| R2-9 | MED | D2a "provably off" must read the **write** leg (`role="write"`, cloud-first) — never `role="read"` (local Enpower, the standing-on flag, §1.4). The cloud leg can itself be frozen; that is accepted because the ledger-not-True conjunct also must hold. | **Builder directive**; test with local leg `on`, cloud `off`, ledger False → released at 61 min (proves local leg is not consulted). |
| R2-10 | LOW | D3 storm exemption (Q2) has no specified mechanism. | **Builder directive:** a keyword `cloud_withhold_exempt: bool = False` on `_result`, passed True only at :5418/:5429, and only if the operator answers Q2 "keep". Default build = exemption ON (recommended) behind that kwarg; Reviewer C neuters it. |
| R2-11 | LOW | D3 must change the **returned** `charge_from_grid` key (:6159), not only skip the action — the chokepoint reads the dict (`energy.py:6720`). | Builder directive; covered by `test_cloud_withhold_keeps_ev_paused`. |
| R2-12 | LOW | I-7 "byte-identical blind branch" vs D4 call on that path: decision dict must stay identical; the page is a side effect only. | Clarification. |
| R2-13 | LOW | Replay tests (§7) are hollow if they set `_tick_soc_source` / `_soc_source_last` directly. | **Builder directive:** drive `hass.states` with recorder-derived values AND `last_reported`/`last_updated` stamps; let the real resolver pick the tier. Reviewer C neuters the D1 insert and the D2a refusal and confirms the replay rows go RED. |
| R2-14 | LOW | Plan said stream ~1 Hz; memory measured ~5-6 s + ~20 s skew. Co-witness 120 s / max-age 90 s still hold. | **[fixed in plan]** |

**Cleared (holds because):**
- `_tick_soc_source` lifetime inside `determine_mode`: no `return` precedes :5108 in `determine_mode` (:5041-5108), so
  set-at-entry is total for that call. `_result` re-reads `battery_soc` at :6136 for the `soc` display key only — fine as
  long as D3/D5 read `_tick_soc_source`.
- D3 cannot strand a latched attain via the ON-heal suppression: suppression (:5960-5984) only applies on degraded ticks;
  a cloud tick can only be followed by a native tick (re-emits on) or another untrusted tick (correctly withheld).
- v5.103.37 WAIT floor / EV drain-precedence: D3 leaves `reserve_level` untouched (WAIT floor reserve writes unaffected);
  D2a gates only `_paused_by_arbitrage` membership — drain-pause/fill/grid-cap owners are separate sets and keep their
  own release paths.

**Verdict: BUILD-READY** with the in-plan fixes above and R2-5..R2-13 as binding builder directives (copy this table
into the build brief). No item requires re-planning.


---

## Plan review #1 (completeness) — 2026-10-03, ura-reviewer

Framing: independent re-enumeration on develop (v5.103.38) of every surface the plan claims. Disjoint from #2
(build-prediction); overlaps with #2 are noted, not re-litigated.

**Re-enumeration results**

| Surface | Enumerated (grep, develop) | Plan coverage |
|---|---|---|
| `charge_from_grid=True` emitters | `energy_battery.py:3554` (arb CHARGE), `:4317` (attain builder), `:5418`, `:5429` (storm). All go through `_result`; `_result` has 19 call sites, all inside the `determine_mode` call tree (`determine_mode` ×13, `_get_arbitrage_decision` ×3, attain ×2, `_maybe_run_reboot_recovery` ×1 — reached from :4659 inside the tick). No CFG `turn_on` outside `_result` (:5952-6023): `force_redispatch` (:6261) is reserve-only; WriteVerifier re-dispatch routes via `force_redispatch`. | COMPLETE. The `_result` chokepoint covers all four. |
| EV turn-on paths vs `_paused_by_arbitrage` | arb release loop `energy_pool.py:2940-3027` (sole `discard`, :2956); ensure-on :1599 + peer :2163/:2514/:2775; `release_all_tou`/`_fill_priority`/`_grid_cap` :3303/:3345/:3386 all defer to arbitrage membership; DP reversion `energy.py:5284` defers; force-charge drains only the blind-window set (`energy_pool.py:1561-1567`). **DP must-start-by `energy.py:5398-5402` does NOT defer to arbitrage** and turns on directly (:5460). | GAP → **D2c added** (C1-1). |
| Breaker chokepoint consumers of `grid_charge_intent` | `_execute_breaker_safe_dispatch` :6764 → returned to `_dispatch_post_decision_tou_and_arbitrage` → `determine_actions(grid_charge_on=)` :6856 and `determine_arbitrage_actions(grid_charge_on=)` :6885. Excess-solar (`energy.py:6113`) takes no `grid_charge_on`, but is covered by membership because the breaker path claims every EVSE into `_paused_by_arbitrage` earlier in the same tick (`energy_pool.py:2902-2932`). Must-start-by is a timer callback outside the tick and reads neither. | Covered except must-start-by (D2c). |
| Tier-tag-sensitive branches | `energy.py:2484` envoy cache gate (`!= "envoy"` → stream correctly excluded); `energy_battery.py:1393` divergence `tier_ok` (stream excluded, correct); `:2474` LKG snapshot `source`; `:1288-1297` tier map; `sensor.py:14316-14317` `fallback_active = src not in (None,"envoy")` — **not in plan §2.2** (display; stream → `fallback_active=True`, which is accurate). `blind_hold_active` `energy.py:3766-3806` keys on `soc is None`, not the tag. | Add `sensor.py:14316` to §2.2 display list (C1-5). |
| Restart persistence | LKG `battery_soc_lkg` saved in `_save_evse_state` (`energy.py:2047-2053`), restored in `_restore_evse_state` (:1636) with `STALE_MAX_AGE_HOURS = 10.0` (:1511). Saves are event-driven (11 sites) + `_periodic_db_writes` :8515 + teardown :9129. CFG ledger persisted/restored (:1868-1871, :2129). `_last_known_grid_charge_on` is RAM-only (`energy.py:441`) — so after a restart D2b's ledger leg is the ONLY fail-closed memory. `_tick_soc_source` RAM, None until first `determine_mode`. | #2 R2-3 fixed event-save. Add: a quarantine older than 10 h restores as absent → `trusted` (document as intended) (C1-6). |
| Config field / second home | Cloud SOC field pattern `config_flow.py:6910-6920` (`suggested_value`), map key `battery_soc_cloud` `energy.py:1020`. | OK. Unset stream → tier off. See C1-4 for a second-home liveness corner. |
| TOU boundary (D4) | PEC built-ins `energy_const.py` `PEC_TOU_RATES`: **October = shoulder, off_peak 0-17, mid_peak 17-21** (no peak). So 10-02 14:00-15:48 CDT was **off_peak**; the 17:00 boundary is off_peak→mid_peak and the original helper would have found it. #2's R2-2 rationale ("10-02 mid_peak window") is factually wrong for October, but its fix (`_attain_target_boundary`, mid_peak→peak) is still correct and needed for **summer** (mid 14-16 → peak 16-20). | Replay rows: verified (see below). |

**Replay acceptance check (§7)** — timezones and boundaries re-derived from the rate table:
- 10-03 16:00-17:28 CDT: off_peak until 17:00 → lead window 15:30-17:00 → page at ~16:10 (dwell 10) under kill-switch-off. Row holds.
- 10-03 00:37-00:58 CDT: next boundary 17:00, outside 90-min lead → no page. Row holds.
- 10-02 19:00-20:48Z = 14:00-15:48 CDT, off_peak, boundary 17:00 → first tick ≥ 15:30 with dwell ≥ 10 → ~15:30. Row holds.
- 10-01 05:50-07:30Z = 00:50-02:30 CDT → D2a refuses the 1 blind-tick + 3 cloud-tick turn-ons. Holds **provided** D2a is the kwarg form (#2 R2-1); the coord form would fail open with EV TOU off.

**Findings**

| # | Sev | Finding | Disposition |
|---|---|---|---|
| C1-1 | **HIGH** (pre-existing) | Must-start-by bypasses a `breaker` arbitrage pause. `_apply_dp_must_start_release` `energy.py:5398-5402` defers only to grid-cap/load-shed/fill-priority, then `switch.turn_on` at :5460-5466; the arbitrage pause loop then treats the EVSE as already paused (`energy_pool.py:2911-2912`) and never re-turns it off. Legal repro: off-peak, rung-2 CHARGE (CFG on, lead 180 → ~03:00-06:00), EVSE in `_paused_by_dp` + `_paused_by_arbitrage["breaker"]`, must-start-by at 03:00-04:00 (`PLANNING_evse_drain_precedence.md:217`) → EV on during a ~20 kW grid charge. Plan §1.2 cited `:5378` as "peer deferral" — that is the normal DP release (:5284), not must-start-by. | **[fixed in plan]** new **D2c** (one predicate; `redirect` does not block). Operator **Q7**: accept D2c over INV-DP2 liveness, or card `EC-MUST-START-BY-BREAKER-BYPASS-1`. Reviewer D must include it in the I-1/breaker surface. |
| C1-2 | MED | D2b stale ledger after a manual stop (distinct from #2 R2-8). The ledger advances only on URA's dispatch tap (`energy.py:8209-8211`); `_result` emits `turn_off` only when the switch reads on (:6031). After an operator stops a charge by hand, the ledger stays True forever, so every later `unavailable` blip re-pauses EVs as `breaker`. | **[fixed in plan]** D2b: ledger counts only if its `_at` stamp is newer than the last explicit `off` read; new test. |
| C1-3 | MED | D2a reuses `CONF_BLIND_WINDOW_MAX_DEFER_MIN` (`energy_const.py:1702`) — also the blind-window guard's kill switch (`energy_pool.py:980`, :1444). Setting it to 0 to back out D2a also disables the guard defer, and vice versa (concept coupling, Bug Class #63). | **Builder directive:** new rung-1 `DEFAULT_ARB_RELEASE_UNTRUSTED_MAX_DEFER_MIN = 60` (its own kill switch, `<= 0` = no refusal). Update §5 and §6 rows. |
| C1-4 | LOW | D2a "provably off" requires the write-leg CFG to read exactly `off`. A home with no CFG entity configured (eid None) can never be provably off → an arbitrage-held EV stays held for the whole untrusted window. | **Builder directive:** CFG write-leg entity unresolvable (no capability) ⇒ treat as provably off. Test it. |
| C1-5 | LOW | §2.2 consumer list misses `sensor.py:14316-14317` (`fallback_active`). Display only; stream → True is correct. | Add to §2.2; no code change. |
| C1-6 | LOW | Stream-trust restore uses the 10 h `STALE_MAX_AGE_HOURS` bound (`energy.py:1511`); a quarantine older than 10 h restores as `trusted`. | Document as intended (a native comparison re-quarantines within 2 compared samples). Test the boundary. |
| C1-7 | LOW | D4 in observation mode: `determine_mode` still runs, dispatch is skipped. Plan is silent on whether the page fires. | **Builder directive:** page fires in observation mode (it is advice to a human, not actuation); state it in the README. |

**Cleared (holds because):**
- I-3 completeness: all four grid-charge emitters reach the decision dict only through `_result`; no CFG `turn_on` exists outside it (grep above).
- I-1 membership: `_paused_by_arbitrage.discard` exists only at `energy_pool.py:2956`; every other release/ensure-on/toggle path defers to membership. So a refusal placed before :2955 holds the EV on every tick-driven path. The one timer path that ignores membership is C1-1.
- `_tick_soc_source` for the 10-01 blind tick: :5108 precedes the fully-blind branch (:5159), so `none` is captured before the early return.
- D1 tag effects: `energy.py:2484` (envoy cache) and `energy_battery.py:1393` (divergence) both exclude `stream` — correct, no change needed.

**Verdict: BUILD-READY for D2-D5 now (with D2c pending operator Q7 — if Q7 is "no", ship D2a/D2b/D3/D4/D5 and card
D2c; do not drop it silently). D1 stays gated on D0.** No re-plan needed; C1-3, C1-4 and C1-7 join #2's binding
builder directives.

## 12. Operator rulings 2026-10-04
- Q1-Q6: agree with recommendations (D1 ships dormant if A/B NO-GO; keep storm-precharge exemption; cloud-only charger guard → Phase 2; 90-min page lead = code constant; card stream-grid-power import witness; count restart outages separately).
- Q7 = (a), reframed: **must-start-by is "should start by"** — demand side, never overrides breaker safety or energy-savings holds. D2c: the timer waits behind the arbitrage `breaker` pause (and every other protective hold). When a start is held past its deadline: log, NM notify the operator, and emit an anomaly row (existing anomaly subsystem) so the operator can tune or intervene. Correction: window-sized attain targets are PARKED (D0 NO-GO); not a mitigation here.

## 13. Operator ruling 2026-10-04 — HOLD deploy for re-plan
Phase 1 builds and reviews, but does NOT ship alone. After the build lands: re-plan with EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 (cloud-only battery writes since fw 8.2.4225; fragile/unsupported local API and production.json; yearly token; cloud retry-after; stream as an extra command-outcome witness; integration consolidation; prior-art commanding machinery extended, not replaced) plus the stream A/B readout (2026-10-05 13:05). Adjust phase-1 code for any stale assumption, re-review changed sites, then ship phase 1 + first resilience deliverables together (operator Tier-3 go). Operator: "Too important to ship with stale assumptions."
