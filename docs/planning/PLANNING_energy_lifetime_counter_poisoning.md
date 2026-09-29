# PLANNING — Energy lifetime-counter poisoning of `energy_daily`

**Card:** ENERGY-CONSUMPTION-FORECAST-POISONED-1
**Date:** 2026-09-29 (rev 2 after PLAN-FIX-REQUIRED)
**Tier:** see §Tier classification (per-option: **S = Tier 2**, **F = Tier 2-DB**)
**Companion:** `docs/planning/AUDIT_energy_consumption_forecast_poisoning_2026_09_29.md`, `scripts/probes/energy_consumption_forecast_poison_probe.py`
**Adjacent (non-goal):** ENVOY-FLAKINESS-181243-1 (physical cause), COVERAGE-EVENING-ATTRIBUTION-DRIFT-1 (net vs total sensor selection).

---

## Falsifiable invariant (restated per HIGH-3)

Let **LKG(counter)** = the maximum reading ever ACCEPTED for that lifetime counter, together with the wall-clock `ts` of acceptance. A reading `x` at time `t` is **accepted** iff:
`x is not None AND x ≥ LKG − ε_regress AND x ≤ LKG + MAX_LIFETIME_JUMP_MWH(t − LKG.ts, counter)`
(the upper bound is a physical-throughput cap; the lower bound tolerates only float/quantisation noise).

**INV-LCP1 (Option F):** every persisted `energy_daily.consumption_kwh` and `.solar_production_kwh` for date `D` is derived from a Δ whose **both endpoints** (the midnight-D snapshot AND the midnight-D+1 reading) were accepted under the LKG rule, AND `Δ_kWh ≤ DAILY_*_MAX_KWH`. If either endpoint is unaccepted OR the row was mid-day-seeded within the same day, the row is stored NULL for the affected field(s) and marked `partial_day = 1`.

**INV-LCP1-S (Option S):** every stored `consumption_kwh` / `solar_production_kwh` satisfies `≤ DAILY_*_MAX_KWH`; every value that reaches `record_actual_consumption` / `evaluate_accuracy` / `_solar_forecast_error_baseline` satisfies the same; and any day whose midnight snapshot was seeded mid-day (restart or first-boot) is marked `partial_day = 1` with actual/solar/error NULL.

Falsifier (both options): replay the recorded 0.045505 MWh sequence from `energy_midnight_snapshot` (live today) against the producer; if any resulting row is written with the affected field non-NULL AND ≥ CEILING, or if any DOW deque entry / adjustment-factor input exceeds the ceiling, the invariant fails.

---

## Institutional context verified (revised)

### Prior planning docs consulted
- `PLANNING_envoy_telemetry_failover_map.md` + `_D5_addendum.md` — measurement-before-build precedent.
- `PLANNING_forecast_accuracy_fix.md` — **explicitly kept the live control-path `pct_error` unclamped**; `PCT_ERROR_BOUND=200` (`energy_forecast.py:41-42`) and `pct_error_bounded` helper (`energy_forecast.py:829-875`) exist for the display path. HIGH-8 requires an explicit decision to extend the bound onto the control path.
- `PLANNING_enphase_cloud_reliance.md`, `PLANNING_ec_envoy_boot_decoupling.md`, `PLANNING_envoy_write_verification_and_redundancy.md`, `PLANNING_v4.6.8_ec_tou_rate_reconciliation.md`, `PLANNING_energy_unit_normalization_and_attribution.md`, `PLANNING_v4.x_B4_ENERGY_INTEGRATION.md`, `PLANNING_net_energy_program_R1_R7_R2.md`, `PLANNING_envoy_local_witness_and_solar_follow.md` — skimmed; none proposes a monotonic guard.

### Memory bodies pulled
- `project_envoy_boot_incident_2026_06_12.md` — RestoreEntity unavailable→OFF poisoning; different surface but same lesson (glitched read at lifecycle boundary corrupts downstream).
- `feedback_measure_before_build.md`, `feedback_marginal_benefit_pushback.md`, `feedback_do_robust_fix_not_bandaid_and_card.md`, `feedback_falsify_before_asserting.md`, `feedback_verification_needs_disjoint_framings.md`.

### Design docs
- No `docs/Coordinator/ENERGY_*.md` covers midnight-snapshot derivation; canonical spec = the code at cited lines.

### Prior-art scan (MED-9 corrections applied)
| Proposed piece | Verdict | Existing (file:line) or note |
|---|---|---|
| **LKG persistence** (Option F) | **REUSE** — `save_energy_state` / `restore_energy_state` KV DAO (`database.py:4959`, `:4972`), already used for `peak_avoidance_snapshot` at `energy.py:2390`. NO schema change needed — store `lkg_lifetime_<counter>` = `{value, ts_iso}` as a KV blob. `lkg.py`'s `LkgValue.to_blob/from_blob` is the serialisation prior art. |
| Extend `save_midnight_snapshot` payload with per-counter LKG | **DROPPED** in favour of KV above (MED-9). Midnight-snapshot payload shape unchanged → DAO migration risk removed (Tier consideration below shifts). |
| `_accept_lifetime_reading` guard helper (Option F, on-getter) | **NEW**, but **NOT placed in shared `_get_state_float`** (LOW-17). Wrap only the six `_get_lifetime_*` (2714-2736). |
| `_apply_daily_ceiling(actual_kwh, solar_kwh) -> (a', s', tripped: bool)` | **NEW** — module-local helper in `energy.py`. |
| `DAILY_CONSUMPTION_MAX_KWH`, `DAILY_SOLAR_MAX_KWH`, `LIFETIME_REGRESS_TOLERANCE_MWH`, `MAX_LIFETIME_JUMP_KW`, `LKG_STALE_REBASELINE_HOURS` | **NEW** module constants (`energy_const.py`) — rung 1 (see §Knob ladder). Solar ceiling **derived from `CONF_ENERGY_SOLAR_NAMEPLATE_W`** (`energy_const.py:915`, 19.4 kW) × 24 h × safety factor 1.05 ≈ 490 kWh; DO NOT hardcode 300 (MED-9). |
| `energy_daily.partial_day` column | **NEW** additive column (nullable, default 0). This IS a schema change — kept minimal, additive, INSERT OR REPLACE unaffected. |
| Anomaly emission | **REUSE** `_store_crosscheck_anomaly_event` (`energy.py:3099`) shape; **rate-limit once per counter per rejection episode ≤1/day** per MED-11. |
| Read-side ceiling in `get_energy_daily_recent` caller | **EXTEND caller-side only.** MED-10: existing `>= 10` filter at `energy.py:1446` is consumption-only, and `get_energy_daily_recent` (`database.py:4528`) does **NOT** select `solar_production_kwh` — so any "symmetric solar bound at 1446" is a no-op. Apply solar bound where solar is actually read (regression pairs `energy.py:2225-2258` do not use solar; DOW history / `get_consumption_history` at `database.py:5041` also does not use solar). **The solar ceiling belongs at the producer / _save_daily_snapshot, not at these DAOs.** |
| Split "DOW deque feed" audit locus | Restore path: `energy.py:2264-2274` → `energy_forecast.py:736-764`. Live per-day push: `energy.py:2840` → `energy_forecast.py:766-774`. HIGH-8 concerns the live path. |
| D0 knob flip | **REUSE** — `select.ura_energy_coordinator_dp_house_load_source` at `select.py:767-788`, `config_flow.py:4637-4645, 5777-5861`, `energy_const.py:1585`. |
| D3 backup | **REUSE** SQLite `.backup` / `VACUUM INTO` (MED-13). `cp` on a WAL DB is unsafe; corrected. |

### Correction to earlier institutional claim
`energy.py:2491-2496` is the **envoy_cache** payload (feeds `save_envoy_cache`), NOT the midnight-snapshot payload. Midnight-snapshot payload lives at `energy.py:2371-2375` (`_save_midnight_snapshot`). MED-9. Prior draft was wrong; corrected in the site enumeration below.

### Kanban adjacency
- ENVOY-FLAKINESS-181243-1 — physical cause; non-goal.
- COVERAGE-EVENING-ATTRIBUTION-DRIFT-1 — separate concern (net vs total consumption sensor selection). LOW-16: **do NOT claim `energy_daily` "feeds billing"** — billing/cost coverage runs off different sensors. Consumers of `energy_daily.consumption_kwh` here are the accuracy/adj-factor / regression / DOW paths + `get_energy_daily_for_cycle` (`database.py:4482`) which sums the columns for a cycle summary (a display consumer; but see D3 note — do NOT DELETE, NULL).

---

## Independent site enumeration (revised per HIGH-5, MED-14)

### Lifetime-counter READ sites (6)
`_get_lifetime_consumption` (2714), `_..._production` (2718), `_..._net_import` (2722), `_..._net_export` (2726), `_..._battery_discharged` (2730), `_..._battery_charged` (2734). All call `_get_state_float` (`energy.py:10577`). **The guard MUST be applied here, NOT in `_get_state_float` (which is shared with SPAN power reads etc. — LOW-17).**

### Snapshot SET sites (revised — 3 live, not 4)
| # | Site | Lines | Status |
|---|---|---|---|
| 1 | **Rollover** — assigns all 6 snapshots to current readings | `energy.py:2895-2900` (MED-14: six counters, not two) | LIVE |
| 2 | **Seed-if-None** — per-counter first-availability seed | `energy.py:2908-2919` | LIVE |
| 3 | **Same-day DB restore** | `energy.py:2321-2328` (only runs when `snapshot_date == today` per `:2320`) | LIVE |
| ~~4~~ | ~~Cross-check re-seed~~ | ~~`energy.py:3077-3097`~~ | **UNREACHABLE (HIGH-5).** Sits inside `elif divergence_pct < 5` (`:3065`) AND further gated by `envoy_today_kwh > our_delta_kwh * 2 and our_delta_kwh < 5` (`:3077`). Those two conditions are mutually exclusive at any reasonable magnitude (`divergence < 5%` cannot coexist with a 2× ratio when the smaller side is < 5 kWh). Live check today: `lifetime_consumption` currently NULL → `:3014` early-return keeps the whole method dark. Introduced in v4.3.0 commit `2c8f9c389`; stranded since. **Drop from guarded sites.** Disposition: **KEEP + DOCUMENT** — do not delete in this cycle (out-of-scope surgery); add a one-line comment "stranded since v4.3.0 — reachability proof in PLANNING_energy_lifetime_counter_poisoning.md" and card a follow-up. |

Two additional callers of `_save_midnight_snapshot()` (`energy.py:8521, 9136`) do NOT mutate snapshot values — persistence only; transitively protected.

### Δ-compute (subtraction) endpoints
`energy.py:2745-2823` — six subtractions of (current − snapshot). Per HIGH-6, we guard by **enforcing that BOTH endpoints were accepted**: current is checked by the getter guard; snapshot carries a per-counter `_snapshot_accepted: bool` flag set at every SET site. Δ compute reads the flag; a False flag → field NULL + `partial_day = 1`.

### `energy_daily` READER sites (revised per MED-10)
| Site | Reads | Filter needed |
|---|---|---|
| `energy.py:1441` → `get_energy_daily_recent(30)` | `consumption_kwh`, `predicted_consumption_kwh`, `prediction_error_pct`, `avg_temperature` | Existing `>= 10` at `:1446`. Add upper `≤ DAILY_CONSUMPTION_MAX_KWH` and `abs(pct_error) ≤ PCT_ERROR_BOUND`. Solar NOT selected here (MED-10). |
| `energy.py:2235` → `get_energy_temp_pairs(min_days=30)` | `consumption_kwh`, `avg_temperature` | Add upper `≤ DAILY_CONSUMPTION_MAX_KWH`; also require `partial_day = 0` if column present. |
| `energy.py:2270` (restore path) → `get_consumption_history(60)` → `energy_forecast.py:736-764` | `consumption_kwh` | Add upper ceiling + partial-day filter. |
| `energy.py:2840` (live daily push) → `record_actual_consumption` → `energy_forecast.py:766-774` | `actual_kwh` (in-memory) | **CRIT-1 target** — ceiling applied BEFORE this call. |
| `energy_forecast.py:661` | Display consumer (LOW-17). | Display only; no bounds required beyond D2. |
| `_dp_house_load_kw` `energy.py:4352-4394` | `predicted_consumption_kwh` (post-adjust) | Downstream of adj factor; protected by D2 bound on `pct_error`. |
| `get_energy_daily_for_cycle` `database.py:4482` | Sums `consumption_kwh` / `solar_production_kwh` for cycle summary | Display only. **MED-13:** do NOT DELETE cleaned rows — SUM(NULL) skips, SUM over dropped rows silently under-reports. |

---

## Producer AND Consumer map

**Producer chain (all 6 counters):** `_get_lifetime_*` (2714-2736) → `_get_state_float` (10577) → Δ at 2745-2823 → snapshot mutation (2895-2900 / 2908-2919 / 2321-2328) → `_save_daily_snapshot` (2921) → `log_energy_daily` (`database.py:4438`).

**Dependency health:** production lifetime glitched at 12/28 September midnights (audit §1); currently glitched (`energy_midnight_snapshot.lifetime_production = 0.045505`). Consumption counter equally exposed via identical transport.

**Consumers:** table above. TRUST consumers: `_dp_house_load_kw` (decision), accuracy → adj factor (self-referential feedback), regression refit (every startup), DOW deques (live + restore), `_solar_forecast_error_baseline` update at `energy.py:2863`. Display: forecast sensors `sensor.py:11652-11774`, diagnostics `energy.py:10733`, `get_energy_daily_for_cycle` summary.

---

## Option S (SIMPLIFY) vs Option F (FULL) — marginal-benefit decomposition (per CLAUDE.md)

### Option S — minimum-shape fix, Tier 2
1. **D0** operator flip to `live_span`.
2. **CRIT-1** ceiling correctly placed: `_apply_daily_ceiling` invoked immediately after the `actual_kwh <= 0` guard at `energy.py:2825-2830` and BEFORE `record_actual_consumption` (`:2840`), `evaluate_accuracy` (`:2845`), `get_adjustment_factor` (`:2854`), `_solar_forecast_error_baseline.update` (`:2860`), and the DAO write (`:2878`). On trip → both `actual_kwh` and `solar_produced_kwh` set None; anomaly emitted (rate-limited, MED-11).
3. **HIGH-7 minimal** — add `energy_daily.partial_day` column; set to 1 whenever the row is derived from a snapshot that was **mid-day seed-if-None** (`:2908-2919`) rather than the previous midnight rollover, OR whenever the ceiling trips. Row is still written but with `consumption_kwh`/`solar_production_kwh` NULL for the partial fields. Readers (D2) skip `partial_day = 1` rows.
4. **HIGH-8 decision** — extend `pct_error_bounded` (energy_forecast.py:829-875, bound `PCT_ERROR_BOUND = 200`) to the LIVE control path `evaluate_accuracy` (`energy.py:2845` → `energy_forecast.py:852-880`). Explicit override of `PLANNING_forecast_accuracy_fix.md`'s "raw on control path" choice, justified by the 213,147% row.
5. **D2** caller-side upper-bound filters at the three DAO readers (as tabulated).
6. **D3** cleanup (backup via `sqlite3 ".backup"` / `VACUUM INTO`; NULL not DELETE; do NOT null `predicted_consumption_kwh` per MED-13; scope 4 poisoned + 09-24/25; today's row if written pre-fix).

**What Option S still misses (measured):**
- **Both-ends-glitched undercount** (09-24 48 kWh, 09-25 78 kWh; audit §1 second-order): both midnight reads glitched → both Δ endpoints "valid" numbers → `solar = 0.0`, `consumption ≈ 48-78`. Ceiling does NOT trip (48 kWh < 600, 0 < 490). `partial_day` marker does NOT trip (both endpoints came from rollover, not seed-if-None). **Frequency in audit data: 2/198 rows = 1.0%.** These rows still poison DOW deques (48 kWh vs ~190 kWh clean).
- **Restore-of-glitched-snapshot**: if HA restarts today with `energy_midnight_snapshot.lifetime_production = 0.045505` and boots into a moment where the live sensor also glitches, restore accepts 0.045505; at next accepted live read the Δ blows up. Ceiling catches the Δ (goes NULL) — but ONLY for that day; the restored snapshot lingers until next rollover. Under Option S, no restore-time cross-check exists.
- **Silent adj-factor drift from clean-but-poisoned prediction rows** (audit: 09-01 predicted 0.1 → error 213,147%). CRIT-1 + HIGH-8 fix this on the write side and the live-eval side; older poisoned prediction rows still corrupt adj factor until D3 cleanup + one restart.

### Option F — full LKG design, Tier 2-DB
Everything in S plus:
- **LKG ratchet** per counter, persisted via `save_energy_state` KV (reuse; no schema change), storing `{value, ts_iso}`. Getters (2714-2736) apply `_accept_lifetime_reading` against LKG (HIGH-3, HIGH-6).
- **Restore rule (CRIT-2 corrected):** on same-day restore (`:2321-2328`), for each counter reject the restored snapshot iff `snapshot < LKG − ε` OR `(live − snapshot) × 1000 > DAILY_*_MAX_KWH`. If live is None at restore, defer acceptance to first accepted live read. Restore LKG **irrespective of `snapshot_date`** (LKG survives across day boundaries; `snapshot_date` gates only the snapshot values). This IS the check that would reject today's `0.045505` on the next boot.
- **Legit-reset policy (HIGH-4):** the glitch is a **constant, non-growing** 0.045505 value; a real firmware reset produces a **low but monotonically-growing** series. Re-baseline LKG downward iff we observe `N ≥ 6` consecutive accepted reads (spanning ≥ `LKG_STALE_REBASELINE_HOURS = 6` h) all monotonically increasing below the current LKG, AND the operator sees an anomaly for it. Add upper-jump bound `MAX_LIFETIME_JUMP_KW` (throughput cap: production ≤ nameplate × elapsed, consumption ≤ 240 A × 240 V × elapsed).
- **HIGH-7 full** — seed-if-None consults LKG: if LKG for that counter is ≤ `LKG_STALE_REBASELINE_HOURS` old, seed from LKG (production is flat overnight; consumption drifts modestly — acceptable for undercount-avoidance vs day-loss). Else set `partial_day = 1` and let the day's row go NULL.
- Guard drills (HIGH-6): drill the 3 subtraction endpoints, the restore site, and the getter guard — **not** the getters + SET sites separately (the two-layer design was insulating the drills).

**What Option F additionally catches:**
- **Both-ends-glitched undercount** (Option S miss): the second-endpoint glitch value 0.045505 is < LKG − ε, so the getter rejects it → snapshot un-accepted → row NULL for that day. Frequency: measured 1.0% of days, but each one poisons DOW deques → material for the regression fit.
- **Restore-of-glitched-snapshot** at boot: LKG comparison at `:2321-2328` rejects 0.045505 vs LKG ~18 MWh; today's live row is preserved intact after next accepted read.
- **Adj-factor drift from prediction rows the ceiling didn't see** — LKG prevents the underlying Δ from ever being stored, so the pct_error path never sees the poisoned actual.

### Recommendation — Option F, on measured margin

- **S captures ~most-value-per-code:** CRIT-1 alone stops the 30/31 recent DP evals from picking up the poisoned forecast, and the ceiling stops the write. On the operator's 2026-08-25 "prefer simple" test, S looks tempting.
- **BUT the F-only failure shapes are measured, not hypothetical:** the both-ends-glitched undercount at 09-24/25 is exactly the shape S misses, and it fired **2/6 days** in the tail week (33% of glitch days that reached both endpoints). Once every 3-5 glitch days is not tail risk.
- **Marginal ingredient cost is small and containable:** LKG uses an existing KV DAO (no schema change), the reset policy is a bounded counter + timestamp, and the guard placement (HIGH-6) is a single new helper on 6 getters + one restore check. No cross-coordinator state, no shared-primitive edit, no time-machine machinery.
- **The elevated review cost (Tier 2-DB vs Tier 2) is one extra framing-disjoint reviewer**, which is cheap relative to the "restore poisons Tuesday" scenario (audit's live evidence: today's snapshot is already 0.045505; Option S ships a fix that would let a Tuesday boot re-poison Tuesday's row).
- **Verdict: Option F**, with Option S kept documented as the fallback if plan review or build turns up a load-bearing complication in the LKG restore rule (CRIT-2's revised form).

**Option S kept in-doc** as fallback per marginal-benefit rule — do not delete this section if Option F ships.

---

## Deliverables (Option F — chosen)

### D-1 — Measurement gate (before D1 ε is chosen) — per MED-12
One-shot recorder probe over all 6 lifetime sensors: hour-to-hour decreases in `statistics` for the last 90 days (excludes the 0.045505 glitch by pre-filtering `state > 1.0`; measures pure float/quantisation noise). Report max decrement per counter → ε_regress = 3× that max, floor 0.001 MWh. Committed as `scripts/probes/lifetime_counter_noise_probe.py`. **Gate: no D1 code changes ship until this probe reports.**

**Acceptance:** probe output committed with per-counter max-decrement; `LIFETIME_REGRESS_TOLERANCE_MWH` constant chosen with cited value.

### D0 — Operator knob flip (OPERATOR DECISION)
As in rev 1. Trade-off: `live_span` may read ~0 on SPAN blind spots → DP abstains `MISSING_INPUTS` rather than deciding on wrong load.

**Acceptance:** knob observed at `live_span`; next DP eval `house_load_kw ≠ predicted_consumption_kwh / 24` (± 0.02); if `live_span` = 0, eval reports `MISSING_INPUTS`.

### D1 — Producer guard + ceiling + partial-day marker + anomaly
Land in this order:

**D1a — Ceiling at the correct position (CRIT-1).** In `_maybe_reset_daily` between `:2830` and `:2839`, call `_apply_daily_ceiling(actual_kwh, solar_produced_kwh)`. On trip: both → None; increment per-episode anomaly counter (MED-11) via `_store_daily_plausibility_anomaly` (new sibling of `_store_crosscheck_anomaly_event`). Downstream `if actual_kwh is not None:` block at `:2839` naturally skips learning.

**D1b — LKG ratchet (Option F only).** Add `self._lkg_lifetime: dict[str, tuple[float, str]]` (counter → (value_mwh, ts_iso)); persist per-counter via `save_energy_state("lkg_lifetime_<counter>", blob)` (reuse KV, MED-9). Initialise from `restore_energy_state` at coord init (before restore of midnight snapshot). Update on every accepted getter read.

**D1c — Getter guard (LOW-17, HIGH-6).** In each `_get_lifetime_*` (2714-2736), pass raw `_get_state_float` result through `_accept_lifetime_reading(name, x, lkg, now)`. Rejected → return None (existing None-tolerant callers). **Do NOT modify `_get_state_float`.**

**D1d — Snapshot acceptance flags (HIGH-6).** Add `self._snapshot_accepted: dict[str, bool]`. Set at rollover (`:2895-2900`): True iff the current getter returned non-None. Set at seed-if-None (`:2908-2919`): True iff seeded from LKG within `LKG_STALE_REBASELINE_HOURS`, else False (mid-day partial). Set at restore (`:2321-2328`): True iff CRIT-2 rule passes; else counter left None to be seeded later.

**D1e — Δ endpoint gate.** In the Δ compute (`:2745-2823`), guard each per-counter subtraction with `if not (snapshot_accepted[name] and current is not None)` → treat that term as None; ceiling still runs on the aggregate.

**D1f — CRIT-2 restore rule.** In `_restore_midnight_snapshot` at `:2321-2328`: for each of the 6 counters, if the persisted snapshot value `s` satisfies `s < LKG − ε` OR `(live − s) × 1000 > DAILY_*_MAX_KWH`, reject (leave `_lifetime_*_snapshot = None`, `_snapshot_accepted[name] = False`, emit `snapshot_restore_reject` anomaly). If live is None at restore time, defer acceptance to first accepted live read. Restore LKG irrespective of `snapshot_date`.

**D1g — Legit-reset policy (HIGH-4).** New in-memory rolling window per counter of the last 12 accepted reads. If we observe `N ≥ 6` monotonically increasing reads spanning `≥ 6 h` all below current LKG → re-baseline LKG downward to newest value, emit `lkg_rebaselined` anomaly. Upper-jump bound: reject any accepted read with `(x − LKG) / (t − LKG.ts) > MAX_LIFETIME_JUMP_KW / 1000`.

**D1h — `partial_day` column.** Additive nullable column on `energy_daily`, default 0. `_save_daily_snapshot` sets to 1 iff any endpoint was un-accepted or the ceiling tripped. Existing readers unaffected (SELECTs listed above do not project this column).

**D1i — Anomaly rate-limit (MED-11).** Reuse `_store_crosscheck_anomaly_event` shape: one row per counter per rejection episode; episode ends when the counter re-accepts.

**Acceptance criteria (all F):**
- **Test (fixture from probe, LOW-18):** `test_lifetime_regression_fixture_replay` — feed the audit's exact 0.045505 sequence from `scripts/probes/energy_consumption_forecast_poison_probe.py` (section B ground-truth window `stat_at_midnight()` output for 08-20 / 08-28 / 08-30 / today) into the guarded getter; assert no `_lifetime_production_snapshot` mutation adopts 0.045505 once LKG ≥ 10 MWh.
- **Test (per-site mutation, 3 sites):** getter guard, restore CRIT-2 check, Δ-endpoint gate. Comment out each → a distinct named test fails per site.
- **Test:** `test_daily_ceiling_writes_null_and_partial_day` — synthetic Δ of 18,850 kWh writes NULL + `partial_day = 1` + one anomaly.
- **Test:** `test_restore_rejects_glitched_snapshot_below_lkg` — DB restore with `lifetime_production = 0.045505` and LKG = 15.8 MWh → snapshot not adopted, anomaly emitted.
- **Test:** `test_legit_reset_rebaselines_after_6h_growth` — synthetic 6× monotonic accepted reads below LKG over 6 h → LKG re-baselined, no rejection loop.
- **Test:** `test_both_ends_glitched_writes_null` — 09-24 replay; row NULL for solar AND consumption; DOW deque unchanged.
- **Live (condition-based per MED-15):** on the **first midnight where the 00:00 read or the outgoing snapshot equals 0.045505 (measured from `energy_midnight_snapshot` at `now − 60s`)**, the `energy_daily` row written for that date has `consumption_kwh` and `solar_production_kwh` EITHER NULL OR ≤ ceiling, `partial_day = 1`, AND a matching `energy.lifetime_regress_reject` or `energy.daily_plausibility_reject` anomaly is present, AND `sensor.ura_energy_coordinator_energy_forecast_today.predicted_consumption_kwh` does NOT jump into the 300-2000 kWh band on the next `evaluate_accuracy` cycle (stays within ± 50 kWh of `shadow_predicted_consumption_kwh`).
- **Live discriminator (CRIT-1 specific):** on that same midnight, `record_actual_consumption` is NOT called with a value > ceiling (assert via absence of any DOW deque entry > 600 kWh at coordinator's post-midnight state).

### D2 — Read-side caller filters
As tabulated. Extend `pct_error_bounded` (`energy_forecast.py:829-875`) into the **live** `evaluate_accuracy` path (`energy_forecast.py:852-880`) per HIGH-8 decision. Explicitly note the reversal of `PLANNING_forecast_accuracy_fix.md` on the control-path clamp; document why (213,147% row destabilises adj-factor Bayesian update).

**Acceptance:** as rev 1, plus `test_pct_error_bounded_on_control_path` — a synthetic 8,014% error does NOT drag adj to 1.3.

### D3 — Cleanup (DESTRUCTIVE, OPERATOR APPROVAL, SUPERVISED)
Corrected per MED-13:
1. **Backup:** `sqlite3 /config/universal_room_automation/data/universal_room_automation.db ".backup /config/universal_room_automation/data/universal_room_automation.db.bak_$(date +%Y%m%d_%H%M)"` OR `VACUUM INTO`. NOT `cp` (WAL DB unsafe). Free-space check: `df -h /config` shows ≥ 2× DB size free before proceeding.
2. Re-run probe section A + B to reconfirm.
3. **UPDATE (not DELETE — MED-13; sums-over-cycle at `database.py:4482` would drop billing columns):**
   ```sql
   UPDATE energy_daily
      SET consumption_kwh = NULL,
          solar_production_kwh = NULL,
          prediction_error_pct = NULL
    WHERE date IN ('2026-06-19','2026-08-20','2026-08-28','2026-08-30',
                   '2026-09-24','2026-09-25');
   -- If 2026-09-29 written poisoned pre-D1, add it.
   ```
   **Do NOT null `predicted_consumption_kwh`** (MED-13) — the prediction itself was the model's output at the time and is diagnostically useful; only the error/actual are wrong.
4. Verify with the constants (not the >1000 heuristic): `SELECT COUNT(*) FROM energy_daily WHERE consumption_kwh > <DAILY_CONSUMPTION_MAX_KWH> OR solar_production_kwh > <DAILY_SOLAR_MAX_KWH>` → 0.

**Acceptance:** operator "go" logged; backup verified via `sqlite3 <bak> "PRAGMA integrity_check"`; post-restart regression fit base ≈ 135, coeff ≈ +1.85.

### D4 — Docstring fix at `_dp_house_load_kw`
Unchanged; docstring-only.

---

## Non-goals
Unchanged: physical Envoy cause; net-vs-total sensor; R1 flip; Net Energy sign; repoint `_dp_house_load_kw` to shadow v1; anomaly-registry redesign; **cross-check re-seed dead-code deletion** (KEEP + DOCUMENT this cycle; separate card).

---

## Numbers get knobs — ladder placement

| Number | Value | Rung | Why |
|---|---|---|---|
| `DAILY_CONSUMPTION_MAX_KWH` | 600 | 1 | Safety bound; drift risk. |
| `DAILY_SOLAR_MAX_KWH` | derive from `CONF_ENERGY_SOLAR_NAMEPLATE_W × 24 × 1.05` (≈ 490 kWh at 19.4 kW) | Rung 1 (constant) with formula reading a Rung 2 config (nameplate) at coord init | Do NOT hardcode; MED-9. |
| `LIFETIME_REGRESS_TOLERANCE_MWH` (ε) | **measured by D-1 probe**, floor 0.001 | 1 | MED-12. |
| `MAX_LIFETIME_JUMP_KW` | 25 (nameplate 19.4 kW + margin for production; 240 V × 240 A = 57.6 kW for consumption) — per-counter | 1 | Physical throughput cap; HIGH-4. |
| `LKG_STALE_REBASELINE_HOURS` | 6 | 1 | Reset detection window; HIGH-4. |
| `PCT_ERROR_BOUND` (control path extension) | 200 (existing display-path value) | 1 | HIGH-8. |
| Anomaly channel names | consts | Constants | Greppable. |
| D0 knob | `live_span` | 3 (live entity) | Existing. |
| `partial_day` column | additive | Schema | Additive; nullable default 0. |

---

## Tier classification (per-option)

- **Option S: Tier 2** (2 framing-disjoint reviews + live validation). Justified: CRIT-1 is a single-locus placement fix; the `partial_day` column is additive; no LKG cross-day state.
- **Option F (chosen): Tier 2-DB** (3 framing-disjoint reviews). Justified: adds LKG state persistence path (reused KV, so no DAO shape change — this lowers B risk vs rev 1), adds a schema column (`partial_day`), extends control-path clamp (`pct_error_bounded`), includes destructive DB write (D3). **Not Tier 3:** invariant is local (INV-LCP1); 3 live SET sites are finite and enumerated; measured decision impact still zero.
- **Operator may elevate F → Tier 3** if they want a 4th adversarial-completeness pass on the SET-site enumeration (a missed 4th site is exactly the Tier 3 failure shape).

### Review framings (Option F)
- **Review A — arithmetic + guard correctness.** `_accept_lifetime_reading`, ceiling math, ε application, legit-reset policy, throughput cap.
- **Review B — lifecycle + restore/rollover/seed-if-None interplay across restart in a glitch window; DAO shape (KV LKG round-trip, `partial_day` additive column).** Verifies CRIT-2 revised rule: on today's live state (snapshot=0.045505, LKG=~18.8 MWh) restore rejects; not a re-verification of getter arithmetic.
- **Review C — test authority.** Per-site mutation on 3 sites (getter guard, restore CRIT-2, Δ endpoint gate). Fixture drawn from probe (LOW-18: fixture source = `scripts/probes/energy_consumption_forecast_poison_probe.py` section B midnight-LTS reads for the four poisoned dates + today).

Plan-review (single pass, per operator 2026-08-11): verify institutional-context complete, INV-LCP1 falsifiable and matched by tests, ε chosen from D-1 probe not guessed, 3-site enumeration re-greped, `partial_day` schema additive, D3 backup command correct.

---

## Plan completion tracking
Deferred (tracked, not dropped):
- R1 shadow-only flip → follow-up card after F ships clean.
- Repoint `_dp_house_load_kw` to shadow v1 → R2-flip cycle.
- Cross-check re-seed dead-code deletion (HIGH-5) → new card, out of scope this cycle.
- ENVOY-FLAKINESS-181243-1 → adjacent, non-goal.
- 381 stale-reason `dp_eval` rows → operator decision on a new card.
- "Reset LKG" operator button → deferred; not required in F (auto-rebaseline handles it).

---

## Post-ship supersession & consumer-gap audit (scheduled)
After F + one clean day: sweep energy-hygiene prior art in `energy.py` / `energy_forecast.py` for now-superseded ad-hoc plausibility comments/heuristics; bucket DELETE / KEEP+WIRE / KEEP+DOCUMENT. Do not delete on that pass; card the delete list.
