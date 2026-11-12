# PLANNING: EV rung-1 redirect cap + post-pause latch hold

Card: `EV-ARBITRAGE-RUNG1-WAIT-OSCILLATION-1` (Tier 3, `approval: explicit`, operator 2026-11-12 "Go on fix D plan").
Source analysis: `docs/planning/AUDIT_ev_rung1_oscillation_fix_options.md` (shape D). This plan is the sprint contract
for fix D. It needs two framing-disjoint plan reviews and operator approval before any build dispatch.

Operator constraints (card `refinement_2026_11_12`, `operator_decision_2026_11_12c`):
1. Protect overnight off-peak EV charging.
2. No new machinery on hardened code.
3. Grid-charge intent must always still pause the EVs (breaker invariant).

---

## 0. Institutional context verified

### 0.1 Docs read

| Doc | Read | Relevance |
|---|---|---|
| `CLAUDE.md` Tier 3 rules | full section | Four review framings, falsifiable invariant up front, config-extreme testing, orchestrator mutation re-run, operator checkpoint before deploy |
| `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` | §2.2-2.3 (l.70-100), rung/gate attrs row l.399, changelog l.779 | WAIT parks at the drain floor and never grid-charges; rung 1 cannot start at night (daylight horizon). No contradiction with code found. |
| `docs/planning/AUDIT_ev_rung1_oscillation_fix_options.md` | full | Mechanism, Q1/Q2, shapes A-D, recommendation D, fallback cap-only |
| `docs/planning/PLANNING_arbitrage_solar_attainability_ladder.md` | skim (l.9-145) | Original rung-1 design. Its rung-1 row (l.68) defines the credit as the full `ev_load_w`. That is the defect this plan fixes. Its l.72 operator ruling: no new kW threshold, reuse existing guard inputs. Honoured. |
| `docs/planning/PLANNING_ec_daylight_horizon_and_poor_night_floor.md` | known via code comments `energy_battery.py:4227-4243`, `:4297-4312` | v5.103.37 daylight horizon + night latch release. This is why rung 1 can no longer fire at night. Kept as is. |
| `docs/planning/DESIGN_ec_degraded_data_policy.md` §9.1/9.3 | via card | 10-01 replay: rung_1 entered with EV ≥ 11.6 kW 13/13, WAIT entered with EV off 34/34 |
| HVAC / presence state-of-play docs | not read | Out of domain. This cycle touches neither HVAC nor presence. |

Memory bodies consulted (index lines + the bodies named in the card): `project_ev_drain_precedence_cycle` (Path A untouched),
`project_charge_onset_correct_site` (onset = off-peak ensure-on, untouched), `feedback_marginal_benefit_pushback`,
`feedback_measure_before_build` (the audit's recorder replay is the measurement; no new probe needed, see §0.4).

### 0.2 Line-number re-verification against current develop (HEAD `64ef3740`)

All audit cites were re-read. **None have drifted.**

| Audit cite | Current develop | Content |
|---|---|---|
| `energy_battery.py:265` | `:265` | `ATTAIN_RATE_WINDOW_TICKS = 3` |
| `:300` | `:300` | `ARB_LADDER_SOLAR_NEGLIGIBLE_PCT_PER_H = 0.5` |
| `:4060-4093` | `:4060-4093` | `_effective_import_kw()` |
| `:4217-4221` | `:4217-4221` | capacity + `ev_load_kw` + `ev_load_pct_per_h` |
| `:4308-4312` | `:4308-4312` | night release of the rung-1 latch |
| `:4322` | `:4322` | latched solar-collapse escape |
| `:4333-4376` | `:4333-4376` | latched counterfactual exit to rung 0 |
| `:4377-4389` | `:4377-4389` | latched escalation `projected_rung0 < exit_band` → rung_2 |
| `:4413-4472` | `:4413-4472` | rung-1 entry; latch set `:4464`; snapshot `:4468` |
| `:4498-4542` | `:4498-4542` | `_gate_is_open` |
| `energy.py:8185-8195` | `:8179-8195` | pause-reason derivation (breaker first, then redirect) |
| `energy_pool.py:3114-3141` | `:3091-3140` | arbitrage pause branch |

### 0.3 REUSE-or-BUILD per piece

| Piece | Verdict | Evidence |
|---|---|---|
| Non-battery grid import (kW) for the cap | **REUSED** `_effective_import_kw()[0]` | `energy_battery.py:4060-4093`. One snapshot of `net_power_w` minus `max(0, battery_power_w)`. `battery_power_w` is already freshness-gated (`:2436-2460`, `DEFAULT_BATTERY_POWER_MAX_AGE_S`) and its None fails safe (no subtraction → larger import → smaller credit). |
| Freshness gate on `net_power` at the cap only | **REUSED** `_read_fresh_power_w("net_power", DEFAULT_NET_POWER_MAX_AGE_S)` | Wrapper `energy_battery.py:2493-2520`; constant `energy_const.py:551` (180 s, rung 1). Used **only as a gate** at the rung-1 entry. The `net_power_w` producer stays ungated, as Tier-3 MED-2 requires (`energy_const.py:545-550`). See D1 and Q1. |
| EV draw | **REUSED** `ev_load_w` from `current_charging_load_w()` | `energy_pool.py:3013-3039`, sums all charging EVSEs, threaded via `_tick_ev_load_w` (`energy_battery.py:6448`, `:4528`) |
| kW → %/h conversion | **REUSED** `:4217-4221` | Same capacity and fallback `ARB_LADDER_DEFAULT_BATTERY_KWH` |
| Hold length for the latch | **REUSED** `ATTAIN_RATE_WINDOW_TICKS` (`:265`) through the sampler's own trim `_record_attain_sample` (`:5014-5031`, `max_len = K+1`) | No new number. The hold is "until the oldest sample in the rate window is at or after the entry tick". |
| Latch entry timestamp | **NEW** attribute `_arb_rung1_latched_at: datetime \| None` | grep of `energy_battery.py` / `energy.py` / `energy_pool.py` for `_arb_rung1_latch*`, `latched_at`, `rung1_.*_at`: only `_arb_rung1_latch` (bool, `:936`). No timestamp exists. The rate window holds `(datetime, soc)` tuples, so the hold needs the entry `now` to compare against. |
| Kill switch / enable flag | **NONE** (see §5) | grep `RUNG1_ENABLED\|rung1_enabled\|redirect_cap\|redirectable` over `custom_components` + `quality`: no hits. Nothing is added. Rollback is revert. |
| CONF_* / sensor / entity / signal | **NONE** | Observability rides the existing strategy-sensor attrs `arbitrage_rung`, `arbitrage_intent`, `arb_projection_rung1` (`energy_battery.py:8383-8387`) plus one new attribute (D3). |
| Regression trip-wire | **REUSED** EC-EV-TOGGLE-TRIPWIRE-1 | `energy.py:8702-8724`, `energy_const.py:758-776` (2 toggles per 3600 s). Note `EV_TOGGLE_TRIPWIRE_NOTIFY_ENABLED = False` (`:776`): it writes an anomaly row but does not page. See Q3. |

### 0.4 Measure-before-build

The gating measurement already exists: the audit's recorder replay of 11-08 20:03-20:33Z (net import 12.9-14.7 kW with the EVs
on, 2.4-3.5 kW with them paused, solar 0.8-1.9 kW, SOC flat at 30 %) and the DESIGN §9.1 replay of 10-01 (import peaked
17.7 kW with the EV on vs 5-6 kW off, at night). Every recorded rung-1 episode had `ev_kw ≤ effective_import_kw` at entry, so
the cap would have blocked every one. No new probe is needed. Retention note: the recorder only goes back to 11-05.

### 0.5 Config-first check

No setting fixes this. Live knobs (audit l.64-66): `peak_buffer_target` 90, `arbitrage_charge_lead_time` 150. Raising
`peak_buffer_target` moves the target and leaves the false credit in place. Turning `ev_tou_management` or `grid_arbitrage` off
removes features the operator wants. The defect is in the producer arithmetic.

---

## 1. Falsifiable invariants

**INV-1 (entry honesty).** On any tick, `_classify_attain_rung` newly sets `_arb_rung1_latch = True` only if, on that
tick, `net_power` is present and fresh and `ev_load_kw > effective_import_kw` (some of the EV draw is covered by solar
or by battery discharge the pause would avoid). The %/h credit it adds and snapshots never exceeds
`clamp(ev_load_kw − effective_import_kw, 0, ev_load_kw) / capacity × 100`.
*Break it with:* any reachable `(ev_load_w, net_power, battery_power, freshness)` where the latch is set with
`ev_load_kw ≤ effective_import_kw`, or with net_power None or stale, or where the snapshot `_arb_last_ev_load_pct_per_h`
differs from the credit used at entry.

**INV-2 (no lag-driven escalation).** While `_arb_rung1_latch` is True, the `projected_rung0 < exit_band` escalation
(`:4382`) does not fire while the rate window still holds a sample older than the latch entry tick. The other exits stay
ungated: night release `:4308`, solar collapse `:4322`, counterfactual-to-rung_0 `:4366`, forecast gate closed `:4519`.
*Break it with:* a latched tick that returns rung_2 through `:4382` while `self._attain_soc_history[0][0] < _arb_rung1_latched_at`.

**INV-3 (bounded hold).** The INV-2 guard never holds a rung-1 pause longer than `ATTAIN_RATE_WINDOW_TICKS` ticks that
carry a valid SOC sample after entry. Once the window has flushed, `:4382` behaves exactly as it does on develop.
*Break it with:* a sample sequence where the oldest window entry stays older than the entry time after K valid
post-entry appends.

**INV-4 (breaker unchanged).** For every tick where `grid_charge_intent` is True or the phase is CHARGE, `pause_reason == "breaker"`
and the EV pause is dispatched before the battery actions (`energy.py:8185-8209`). This holds whatever the rung,
latch, or cap state. *Break it with:* any tick that commands charge_from_grid with an EVSE not in `_paused_by_arbitrage`.

**INV-5 (overnight untouched).** Outside daylight (the `in_daylight` predicate, `:4248-4252`), this cycle changes no output
of `_classify_attain_rung` and no EV action. *Break it with:* any non-daylight tick whose rung, intent, or EV actions
differ between develop and the branch for the same inputs.

**Observable consequence (what D's live and replay criteria check):** under 11-08 / 10-01 conditions no garage EVSE shows
an arbitrage-owned off→on→off within `ATTAIN_RATE_WINDOW_TICKS + 1` ticks.

**Stated residual (not covered by the invariants):** a *genuine* entry (EV partly solar-fed) whose post-flush observed rate
still projects below `exit_band` escalates at most once per flush. If the next tick re-enters on the same live conditions,
the worst case is an off/on period of about K+1 ticks (20 min) instead of 10. That only happens when the capped credit is
materially wrong. One known way is battery acceptance being lower than the credit assumes; see §3 case 9. The tripwire
records it (anomaly row), and the D-alt fallback (§8) is the remedy. No new machinery is added to suppress it.

---

## 2. Producer / consumer map

### 2.1 Producers

| Value | Producer | Arithmetic | Dependency health |
|---|---|---|---|
| `ev_load_w` | `EVChargerController.current_charging_load_w()` `energy_pool.py:3013` | Σ `power` over EVSEs with `charging=True`. Unavailable power sensor falls back to an estimate (`energy_pool.py:4776-4779`, `EVSE_ESTIMATED_POWER_W` `:1155`) | Healthy on 11-08 (10.1-11.7 kW logged). The estimate path is a credit-error source (§3 case 7). |
| `effective_import_kw` | `_effective_import_kw()` `energy_battery.py:4060` | `net_w − max(0, batt_w)`, in kW; None if `net_power_w` is None | `net_power_w` (`:2591`) is **not freshness-gated** (intentional, `energy_const.py:545-550`). The Envoy has a flapping history (memory `project_session_pickup_2026_09_23`). That is why D1 adds a gate local to the cap. |
| `redirectable_kw` (NEW local) | D1 | `clamp(ev_load_kw − effective_import_kw, 0, ev_load_kw)`; 0 if the snapshot is None or net_power is stale | Ground truth: equals `min(ev, solar + battery_discharge − non-EV load)`. 11-08 at 20:03: `10.1 − 12.9 < 0 → 0`. |
| `ev_load_pct_per_h` | `:4221`, changed by D1 | `redirectable_kw / capacity × 100` | capacity from `_battery_capacity_kwh()` or a 40 kWh fallback |
| `projected_rung1_entry` | `:4433-4461` | unchanged formula, smaller `extra_rate` | |
| `_arb_rung1_latch` | set `:4464` only; cleared `:4312`, `:4323`, `:4369`, `:4383`, `:4520` | | Verified by grep: there is no other writer (init `:936`). |
| `_arb_last_ev_load_pct_per_h` | set `:4468`; cleared `:4311`, `:4328`, `:4372`, `:4385` | snapshot of the **capped** credit (D1) | read only at `:4333` (counterfactual) |
| `_arb_rung1_latched_at` (NEW) | set at `:4464` beside the latch (D2) | `= now` | read only inside the latched branch (D2) |
| `_attain_soc_history` | `_record_attain_sample` `:5014`, called at `:4174` and `:6008` | trimmed to K+1 tuples; cleared at `:5796` (chunk reset) and `energy.py:12125` (arbitrage toggle) | **Finding:** both callers can append the same `(now, soc)` on one tick, so the window can span fewer than K ticks. D2 is defined on timestamps, not counts, so it stays correct either way (§3 case 11). |
| `_arbitrage_intent` | `_gate_is_open` `:4521/4532/4536/4540`; entry-reset `:6424` | `"redirect"` iff rung_1 | |

### 2.2 Consumers: every site that reads rung_1, the latch, or the intent (re-enumerated by grep)

Command used: `grep -rn --include='*.py' "_arb_rung1_latch\|_arb_last_ev_load_pct_per_h\|_arb_last_rung\b\|_arbitrage_intent\|closed_rung_1\|_arb_last_projection_rung1\|\"redirect\"" custom_components/universal_room_automation`

| Site | Reads | Trust or display | Changed? |
|---|---|---|---|
| `energy_battery.py:4166` | rung cache | trust (idempotent second call per tick) | no |
| `:4309-4312` | latch (night release) | trust | no (INV-5) |
| `:4319-4393` | latch, `_arb_last_ev_load_pct_per_h` | trust: keep / exit / escalate | **D2 at `:4382` only** |
| `:4424-4472` | `ev_load_pct_per_h` | trust: entry | **D1 at `:4220-4221` and the entry guard** |
| `:4519-4520` | latch clear on forecast-closed | trust | no |
| `:4530-4538` `_gate_is_open` | rung → intent `"redirect"`, gate outcome `closed_rung_1` | trust | no |
| `:7250-7266` | `closed_rung_1`, `_arb_last_projection_rung1` | **display** (phase `solar_attain`, reason suffix) | no |
| `:8383-8387` | `arbitrage_rung`, `arbitrage_intent`, `arb_projection_rung1` | display (sensor attrs) | **D3 adds one attr** |
| `energy.py:8179-8195` | `_arbitrage_intent` → `pause_reason` | **trust: the only EV-switching consumer** | no |
| `energy_pool.py:3091-3140` | `pause_reason` → turn_off + `_paused_by_arbitrage` + `_arbitrage_pause_reason` | trust (emission) | no |
| `energy_pool.py:3143+` | release branch (pause_reason None) | trust (emission) | no |
| `energy_pool.py:3353` | reason map → diagnostic attr | display | no |

**Emission sites for EV switching: zero changed.** All EV switching still flows through `energy.py:8185-8195` →
`determine_arbitrage_actions`. Both D1 and D2 change only *which rung string* the classifier returns. D1 can only turn
a rung_1 into a rung_2. D2 can only turn an escalation-rung_2 into rung_1, and only on a latched daylight tick inside the window.

---

## 3. Config-extreme / knob-inversion cases (each becomes a test, D4)

`imp` = `effective_import_kw`, `ev` = `ev_load_kw`.

| # | Case | Expected under fix | Why |
|---|---|---|---|
| 1 | 11-08: ev 10.1, net 12.9, batt 0, solar 1.2, SOC 30, target 90 | rung_2, no latch, `redirectable_kw = 0` | imp > ev |
| 2 | ev < imp (ev 3, imp 5) | rung_2 | cap 0 |
| 3 | Daylight but solar ≈ 0 (deep overcast) | rung_2 via `:4415` or cap 0 | either guard is enough |
| 4 | `net_power` unavailable (snapshot None) | rung_2, no latch | fail toward not pausing for redirect |
| 5 | `net_power` stale (last_reported > 180 s), frozen at −2 kW (export) while the EV draws from grid | rung_2, no latch | D1 freshness gate. On develop this case gives full credit. |
| 6 | Exporting (net −3, ev 7) | credit = full 7 kW (legacy behaviour) | all EV draw is solar-fed |
| 7 | EV kW unknown → estimate path | credit = clamp(estimate − imp); imp includes the real draw, so the error is bounded by estimate error | accepted residual |
| 8 | Two EVs (6 + 5 kW), net 8 | credit 3 kW; redirect pauses **both** (pool pauses all EVSEs, `:3114`) | sum in, sum out |
| 9 | Battery discharging 5 kW (above the floor), ev 10, house 2, solar 1 → net 6 | credit 4 kW (= discharge avoided) | real SOC benefit. Not "solar" in the narrow sense, but the projection effect is correct. If the strategy reserve stops the battery discharging to cover the EV, the credit overstates (stated residual). |
| 10 | `battery_power_w` None/stale | imp = net (no subtraction) → smaller credit | conservative |
| 11 | Duplicate `(now, soc)` samples (both sampler calls in one tick) | D2 flush on timestamp, so the hold is 1..K ticks, never longer | INV-3 |
| 12 | SOC None for some ticks while latched | `:4176` returns rung_2 (develop behaviour, latch kept); hold counts only valid samples | pre-existing, unchanged |
| 13 | Rate window cleared mid-latch (chunk reset `:5796` / toggle `energy.py:12125`) | rate None → `:4203` rung_2 (develop); after reseed every sample is post-entry → flushed | no stuck hold |
| 14 | `peak_buffer_target` ≤ SOC while latched | `:4187` rung_2 HOLD (develop) | unchanged |
| 15 | `peak_buffer_target` extremes (e.g. 30 = drain floor, 100) | entry band 33 / 103; at 100 an entry needs a raw projection ≥ 103, which is legal but clamped; the cap still applies | knob inversion: target ≤ drain floor |
| 16 | Night (any inputs) | identical to develop | INV-5 |
| 17 | Grid-charge intent on, rung_1 latched (redirect→breaker flip) | pause_reason `breaker`, dispatch before CFG | INV-4 |
| 18 | `_arb_rung1_latched_at` None while latched (impossible by construction; test it anyway) | guard treats it as flushed → develop behaviour | fail toward legacy |
| 19 | Genuine redirect: ev 7, net 2 (solar 7, house 2), pre-pause rate +2 %/h, post-pause +14.5 %/h | entry with credit 5 kW; ticks N+1..N+2 held by D2; after the flush `projected_rung0` ≥ exit → stays rung_1 | the case D2 exists for |
| 20 | Genuine entry, post-flush rate does not rise (battery not accepting) | escalation at the flush tick (≤ K ticks), then the stated residual | bounded |

---

## 4. Deliverables

### D1: Cap the rung-1 entry credit (producer fix)

In `_classify_attain_rung`, replace the credit at `:4220-4221`:

```
ev_load_kw = max(0.0, float(ev_load_w or 0.0)) / 1000.0
redirectable_kw = 0.0
if ev_load_kw > 0.0 and self._read_fresh_power_w("net_power", DEFAULT_NET_POWER_MAX_AGE_S) is not None:
    snap = self._effective_import_kw()
    if snap is not None:
        redirectable_kw = min(ev_load_kw, max(0.0, ev_load_kw - snap[0]))
ev_load_pct_per_h = (redirectable_kw / capacity_kwh) * 100.0
```

- The existing `ev_load_pct_per_h <= 0.0` short-circuit (`:4424`) then turns a zero credit into rung_2 with no further change.
- The snapshot at `:4468` already stores `ev_load_pct_per_h`, so it stores the **capped** value and the counterfactual
  at `:4349` subtracts the same quantity the entry added (snapshot consistency, no edit there).
- The freshness read and `_effective_import_kw()` run in one synchronous call (no await), so they read the same state.
- Stash `self._arb_last_redirectable_kw = round(redirectable_kw, 2)` for D3. Reset it to None as the first statement after
  the cache check (`:4167`) so it never carries over between ticks.
- **Builder must not** touch `net_power_w` (`:2591`) or `_effective_import_kw` itself. Both feed the breaker guard (MED-2).

#### Acceptance criteria
- **Verify:** replaying 11-08 20:03Z (ev 10100 W, net 12900 W, batt 0, SOC 30, target 90, daylight, surplus ≥ 0.5) gives `rung_2`, `_arb_rung1_latch False`, `_arbitrage_intent == "breaker"`; the phase is WAIT before the window opens and CHARGE after it.
- **Verify (discriminating):** the same replay on develop gives `rung_1`. If the post-fix result is rung_1, the cap is not wired. If it is rung_0, the fixture is wrong (rung 0 must fail at 32.8 %).
- **Verify:** cases 2-10 in §3 give the stated rung and credit.
- **Test:** `test_rung1_cap_1108_replay_grid_fed_ev_no_entry`, `test_rung1_cap_ev_below_import`, `test_rung1_cap_net_power_none_no_entry`, `test_rung1_cap_net_power_stale_no_entry`, `test_rung1_cap_export_full_credit`, `test_rung1_cap_two_evs_summed`, `test_rung1_cap_battery_power_none_conservative`, `test_rung1_cap_snapshot_equals_entry_credit`.
- **Fixture churn (expected, not a regression):** existing rung-1 tests (`test_arbitrage_solar_attainability_ladder.py::test_rung_1_evs_eating_solar`, `::test_oscillation_t_osc_rung_1_stable_across_5_ticks`, `::test_rung_1_to_rung_0_when_solar_surges`, `::test_pause_reason_redirect_records_label`, `::test_label_flips_redirect_to_breaker_no_churn`, `::test_rung_1_over_fires_with_13_5_default`, `::test_assumed_load_cleared_on_rung_1_release`, plus rung-1 cases in `test_ec_daylight_horizon_poor_night_floor.py` and `test_arbitrage_completed_chunk_hold_precedence.py`) never set `net_power`, so they will go red. The builder adds a fresh `net_power` state showing the EV as solar-fed (e.g. net = −1000 W) to `_build_strategy` or per test. **No assertion may be weakened.** Every changed test is listed in the review record with the before and after fixture.
- **Mutation:** (M1) replace `redirectable_kw` with `ev_load_kw` in the pct line → the 1108 replay and ev-below-import tests go RED. (M2) delete the freshness gate → the stale test goes RED. (M3) drop the `snap is None` branch (treat None as 0 import) → the net-none test goes RED.

### D2: Hold the rung-1 latch until the rate window is all post-pause

1. `__init__` (beside `:936`): `self._arb_rung1_latched_at: datetime | None = None`.
2. At the entry site `:4464`: `self._arb_rung1_latched_at = now` (only writer).
3. At `:4382`, before the escalation:
   ```
   _hist = self._attain_soc_history
   _latched_at = self._arb_rung1_latched_at
   window_flushed = _latched_at is None or (bool(_hist) and _hist[0][0] >= _latched_at)
   if window_flushed and projected_rung0 < exit_band:
       ...existing escalation body unchanged...
   ```
   If not flushed and `projected_rung0 < exit_band`, fall through to the existing rung_1 return at `:4390`.
4. No clearing at the five latch-clear sites. The timestamp is read only while the latch is True, and the latch is only
   set at `:4464`, which overwrites it. This avoids adding a sixth state to keep in step at every clear site (Bug Class #53).
5. Hold length comes from `ATTAIN_RATE_WINDOW_TICKS` through the sampler trim (`:5029`). No new number.

The sample at entry tick N is taken **before** the pause is dispatched, so a window whose first sample is N measures only
post-pause intervals. That is why the comparison is `>=`.

#### Acceptance criteria
- **Verify:** case 19. Entry at N with a pre-pause window; at N+1 and N+2 `projected_rung0 < exit_band` (still mostly pre-pause samples) → `rung_1` held; at N+3 the window is `[N..N+3]` and the post-pause rate projects ≥ exit → `rung_1`. On develop, N+1 gives `rung_2`, which discriminates.
- **Verify:** case 20. The post-pause rate stays flat → `rung_2` at the first flushed tick (≤ N+3), latch cleared.
- **Verify:** night release, solar collapse, counterfactual-to-rung_0, and forecast-closed each still exit at N+1 while unflushed (INV-2 ungated exits).
- **Verify:** cases 11, 12, 13, 18.
- **Test:** `test_rung1_hold_until_window_post_pause`, `test_rung1_hold_escalates_after_flush_when_rate_flat`, `test_rung1_hold_does_not_gate_night_release`, `test_rung1_hold_does_not_gate_solar_collapse`, `test_rung1_hold_does_not_gate_counterfactual_rung0`, `test_rung1_hold_duplicate_samples_bounded`, `test_rung1_hold_window_cleared_midlatch`, `test_rung1_hold_latched_at_none_legacy`.
- **Mutation:** (M4) force `window_flushed = True` → the hold test goes RED. (M5) change `>=` to `>` → the hold test at the N+3 boundary goes RED (pins the off-by-one). (M6) gate the solar-collapse exit with the same guard → the solar-collapse test goes RED.

### D3: Observability (display only)

Add `arb_rung1_redirectable_kw: self._arb_last_redirectable_kw` beside `arb_projection_rung1` at `:8387`. The live
discriminator then has the producer's own number, so nobody has to infer it from the reason text.

#### Acceptance criteria
- **Sensor:** `sensor.ura_energy_coordinator_battery_strategy` attribute `arb_rung1_redirectable_kw` is present. It is None on ticks that did not reach the entry; otherwise it is a float.
- **Test:** `test_rung1_redirectable_kw_attr_round_trip`.

### D4: End-to-end replays + config-extreme suite

New file `quality/tests/test_ev_rung1_redirect_cap.py`. It drives `determine_mode` → `_gate_is_open` → the `energy.py`
pause-reason derivation → `determine_arbitrage_actions` with the real pool (no fake coordinator; see memory
`project_incident_v5_8_0_setup_recursion`).

- **11-08 replay (14:03-14:33 CST, 7 ticks):** inputs per the audit table (solar, net import, SOC 30, EV 10.1-11.7 kW, two garage EVSEs on). Assert zero arbitrage-owned `switch.turn_off` before the window opens at 14:30 CST, then the `breaker` pause dispatched before the CFG turn_on. Develop reproduces 3 off / 3 on (discriminates).
- **10-01 replay (01:00-03:00 CDT, night, EV 11.6 kW, SOC 7-9 %):** byte-identical rung / intent / actions to develop (INV-5). Variant shifted to daylight with import 17.7 kW: no entry.
- **Genuine-redirect scenario (case 19):** one pause; held through the flush; no off→on→off within K+1 ticks.
- **Breaker sweep (INV-4):** for each of {rung_1 latched, unflushed, flushed, cap 0} × {grid_charge_intent True, phase CHARGE}, `pause_reason == "breaker"` and the pause is ordered before the CFG write (reuse the `test_breaker_pause_ordering_*` pattern).
- **Config extremes:** §3 cases 14, 15 (target 30, target 100, target ≤ SOC).
- **Mutation (whole-path):** M1 and M4 above, re-run against the replay tests. Both must go RED.

#### Acceptance criteria
- **Test:** `test_replay_1108_no_arbitrage_toggle_before_charge`, `test_replay_1001_night_identical_to_develop`, `test_replay_1001_daylight_grid_fed_no_entry`, `test_genuine_redirect_single_pause_no_flap`, `test_breaker_always_pauses_matrix`, `test_target_extremes_cap_holds`.
- **Verify:** full suite name-diff against `pre-review-<version>` shows only the listed fixture-churn tests changed, all green.

### D5: Doc write-back (same commit)

- `ENERGY_COORDINATOR_MANUAL.md` l.399 row: rung 1 credits only the EV draw not covered by grid import, and a rung-1 pause is held until the rate window is all post-pause.
- Changelog row (l.779 area).
- Code comments at `:4127-4130` (docstring rung_1 semantics) and `:4377-4381` (the stale "rate already reflects" claim, which the audit showed is wrong for the first K ticks).

### Live criteria (post-deploy, feed Review D / README validation table)

- **Live 1 (organic, binary, ~1 week):** query `ura_activity_log` for `energy_pool` `charger_off` rows with `pause_owners` containing `arbitrage`, in daylight, where the strategy row at the same tick has `arbitrage_intent = redirect`. For each such row: `arb_rung1_redirectable_kw > 0` **and** the recorder `net_power` at that tick < the EV power. PASS = every redirect pause satisfies this (or there are none). FAIL = any redirect pause with `redirectable_kw` 0/None or net import ≥ EV draw. (A different failure, such as another owner flapping, shows a non-arbitrage `pause_owners` value and is not confounded.)
- **Live 2:** the attribute `arb_rung1_redirectable_kw` exists on the strategy sensor after restart.
- **Live 3 (trip-wire):** `ev_toggle_tripwire` anomaly rows with an arbitrage owner, from deploy to disposition = 0. If one appears, check whether it is the stated K+1 residual (redirectable_kw > 0 at entry) or a cap leak.
- **Live 4 (overnight protection):** on the first poor-forecast night after deploy, garage EVSE on-time from 01:00-07:00 is not reduced by any `arbitrage`/`redirect` pause (expected zero redirect rows at night, as on develop).
- The disposition window follows the soak-exit rule: dispose at the first poor-forecast daytime with an EV drawing, or after about 1 week. If no such day occurs, close as "met by replay; organic precondition did not recur", with the trip-wire as the standing guard.

---

## 5. Numbers and knobs

| Number | Source | Rung | Why |
|---|---|---|---|
| Hold length | `ATTAIN_RATE_WINDOW_TICKS` (existing, `:265`) | module constant (existing) | Defined by the rate window. Changing K changes smoothing and hold together, which is correct. |
| net_power freshness | `DEFAULT_NET_POWER_MAX_AGE_S` 180 s (existing, `energy_const.py:551`) | rung 1, existing | Same Envoy cadence threshold the D-OBS sensor and CostTracker use. Kill switch `<= 0` already documented on the constant. Setting it to 0 disables the gate here too, so the cap then trusts any net_power value. |
| Cap clamp bounds | 0 and `ev_load_kw` | not knobs | physical identities, not tunables |

**No new number. No new kill switch.** A rung-1 enable flag (`ARB_LADDER_RUNG1_ENABLED`) is added only if the D-alt fallback is invoked (§8).

---

## 6. Non-goals

- **Daytime EV policy (solar-led vs off-peak) is out of scope.** Midday is off-peak in shoulder and winter (`energy_const.py:36-60`), so a grid-fed car at midday is cost-neutral under this tariff. Whether daytime EV charging should follow excess solar is a separate policy question (card `refinement_2026_11_12`; not carded).
- No change to `energy.py:8179-8209` (pause-reason derivation, breaker ordering), `determine_arbitrage_actions` or its release branch, `_paused_by_*` peers, fill_priority, drain-precedence Path A, off-peak ensure-on / onset, or `net_power_w` / `_effective_import_kw`.
- No blanket arbitrage-active EV pause (shape A) and no tuned minimum hold timer (shape C).
- No fix for duplicate sampling into `_attain_soc_history` (§2.1 finding). D2 is robust to it. Card it as an observation (see Q4), don't fix it here.
- No change to rung 0, attain, WAIT floor, or the daylight horizon.
- Not retiring rung 1 (D-alt) unless §8 triggers.

---

## 7. Tier classification

**Tier 3.** Trigger: the change threads a value through the arbitrage rung state machine whose output drives EV
emission and breaker-adjacent behaviour (cost and safety), in an area with a multi-fix-up history (ladder D1 fix-ups,
v5.17.4, v5.103.37). Required: two framing-disjoint plan reviews (completeness + adversarial build-prediction), then
`ura-super-builder`, four build reviews (A local arithmetic / B state machine + no-op byte-identity + night identity /
C per-site mutation M1-M6 / D adversarial completeness against INV-1..5 with legal-config repros), orchestrator mutation
re-run, and an operator checkpoint before deploy. PATCH bump.

Marginal-benefit note (my own pushback on D2): the cap alone (D1) removes every recorded episode, since all of them were
grid-fed. D2 adds one attribute and one condition. Its value is conditional: once D1 removes the false entries, the
entries that remain are the genuine ones, and those are exactly the ones the `:4382` lag flaps. So without D2, D1 leaves
rung 1 firing only when it is real and flapping when it does. That is why I recommend shipping both. D2 creates no new
owner, no new emission, no timer, and no new clear sites. If plan review judges D2 not worth its surface, ship D1 alone
(§8).

---

## 8. Fallbacks

1. **Cap alone (D1 + D3 + D4 minus the D2 tests).** Ship it if either plan review rejects D2. Park D2 with this revival trigger: an arbitrage-owner EV toggle cluster (trip-wire row) whose entry tick had `arb_rung1_redirectable_kw > 0`, meaning a genuinely solar-fed redirect flapped on the lag.
2. **D-alt (retire rung 1).** Use it if, after D1 ships, a redirect pause occurs with `redirectable_kw > 0` and the battery gains nothing over the flushed window (the credit was wrong in practice). Add `ARB_LADDER_RUNG1_ENABLED = False` (module constant, rung 1 because it sits in the arbitrage state machine) so entry always returns rung_2. That would be a separate cycle.

---

## 9. Open questions for plan review / operator

- **Q1. Freshness gate on the cap.** The audit's D reuses `_effective_import_kw()` verbatim. This plan adds a `net_power` freshness *gate* local to the entry (REUSED wrapper + constant), because a frozen Envoy reading at an export value would give full credit to a grid-fed car (case 5). The breaker path is untouched. Reviewers: accept, or drop it for strict verbatim reuse?
- **Q2. Battery-discharge credit (case 9).** The cap credits avoided battery discharge as redirect value. In WAIT at the drain floor the battery does not discharge, so this is moot for every recorded episode. Is a narrower "solar only" cap wanted? It would need a solar reading and a second derivation, which I do not recommend.
- **Q3. Trip-wire paging.** `EV_TOGGLE_TRIPWIRE_NOTIFY_ENABLED = False` means Live 3 is only an anomaly row. Should this cycle flip it on? I recommend not, because that is a separate rung-1 constant change, but the operator may want the page.
- **Q4. Duplicate sampling.** Calls at `:4174` and `:6008` can append the same `(now, soc)`, which shortens the effective rate window below the documented 15 min. This affects attain and rung 0 too. Card it separately (not in scope)?
