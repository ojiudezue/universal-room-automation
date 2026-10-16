# PLANNING: EC storm and blind decisions (arc steps 2–7, one integrated plan)

**Arc:** `docs/planning/ARC_energy_coordinator_resilience.md` steps 2–7. Its planning rule applies: one decision model, written once, built in stages.
**Cards:** EC-INCLEMENT-HARDENING-1 (D-blind, D-match, D-ends, outage ledger, D-forecast), EC-BLIND-DEESCALATE-TOP-RATE-1.
**Supersedes:** `PLANNING_inclement_hardening.md` Rev 3. Every finding from its three plan reviews is dispositioned in §11.
**Built on:** the reserve write governor shipped in v5.103.66 (`PLANNING_reserve_write_governor.md` Rev 3.2, `README_v5.103.66.md`).
**Tier:** 3 overall. Per-stage tiers are in §9.
**Status:** **Rev 2.1** (Stage 0 probe results folded in, `AUDIT_ec_storm_stage0_probes.md` incl. P1 addendum). Rev 2: both Tier-3 plan reviews folded in (`docs/reviews/code-review/plan_ec_storm_blind_review_1.md`, `…_review_2.md`). Every finding ID is dispositioned in §15. Seven operator questions are open (§14). The plan is buildable under either answer to each; where an answer changes code, the plan names the switch. Build dispatch waits for the §14 rulings that gate a stage (marked per question).

**Operator doctrine (binding, verbatim where quoted):**
- Flow: alert → local applicability → local forecast over the alert window → hold depth → floor registered → command (or blind rules) → outage ledger.
- Wind Advisory stays MEDIUM, with no hold (0 of 33 windows had an outage). Add Hard Freeze, Extreme Cold and Wind Chill alongside Winter Storm and Ice Storm.
- A hold runs from Onset to Ends, not to Expires. An alert that hasn't started is not active.
- Keep deciding while the Envoy is offline: "why stop reasoning when you clearly can?" Keep the v5.17.5 no-command rule, except for the floor write.
- Forecast is in scope, and the provider probe comes first.
- Top rate means the TOU engine's rate rank. "This text matching is nonsense when there are better candidates."
- "I won't rebuild for fun. It has to be an actual improvement." No scope creep.

---

## 0. Read this first: what the built governor is (code wins over the README)

`README_v5.103.66.md` says *"One floor at `_result`: the inclement partial-hold floor is registered once, at the single exit."* **The code says otherwise.** `_result` (`energy_battery.py:6278-6620`) contains no floor. The governor plan's own Non-goal 1 reads "No floor registry, no fold in `_result`". What actually shipped:
- the writer allowlist and its lint (`energy_const.py:2307-2318`, `RESERVE_SET_VALUE_WRITERS`);
- `reserve_write` activity rows at the three real dispatch points (`energy.py:9094 _record_reserve_dispatch`, C1 in `_tap_write_verifier :9233`, C2 in `_evaluate_battery`, C3 in `force_redispatch`);
- the optimizer hard deny.

The inclement floor is still applied by 8 per-branch `_floor_reserve` wraps (`energy_battery.py:3855`, callers `:3926/3949/3991/4715/4769/5004/5952/6098`, narration `:6687`), plus the two inline off-peak clamps the governor's D-6 added (`:6223-6224`, `:6262-6263`), which also feed the DP stamp in `_offpeak_drain_branch_target` (`:6233`). Full-hold emits use `decision.reserve_floor` directly. The blind de-escalation writes `reserve_soc` with no floor (`:5662-5668`).

So "register the floor with the governor" has nothing to register with yet. **D-A2 builds that registration as the governor's missing piece, not as parallel machinery:** one per-tick floor, folded at the one decision-side reserve writer, which the governor's lint pins. The Stage A ship commit corrects the README line **and** arc row 1 ("one floor registry at `_result`"), which makes the same wrong claim.

---

## 1. Institutional context verified (prior-art scan by function)

### 1a. REUSE / EXTEND / BUILD per function

| Function in the decision model | Prior art (file:line) | Verdict |
|---|---|---|
| Alert source | `nws_alerts` integration, configured `gps_loc 30.314635,-98.015861`, interval 1 min. It queries `api.weather.gov/alerts/active?point=` (`ha-config/custom_components/nws_alerts/coordinator.py:135`). Payload keys come from `:155-176`. **`Type` = CAP `messageType` (Alert / Update / Cancel), `:166`.** `ID = generate_id(alert["id"])` (`:152`): every Update is its own message with its own ID. | **REUSE.** Rev 3's "drop Type != Alert" would have dropped every Update message. Corrected in D-B1. |
| Feed health | The integration has a **separate** `last_updated` timestamp sensor (`nws_alerts/sensor.py:19-24`, `SENSOR_TYPES["last_updated"]`); the alerts sensor that `_read_nws_alerts` reads (`energy_battery.py:2640-2653`, attribute `Alerts` only) has no timestamp attribute. On `AttributeError` the coordinator returns `{"state": 0, "alerts": [], "last_updated": now}` (`coordinator.py:57-72`), an empty feed that looks fresh. Other exceptions raise `UpdateFailed` (`:138-144`); both entities are `CoordinatorEntity`s, so under the standard contract they go `unavailable` (P2(e) confirms from recorder, not assumed). | **REUSE**, read both entities (D-B3). |
| Locality | The point query above is already the feed's locality filter. Zone products (winter, freeze, wind) can't get finer than zone TXZ192 (`AUDIT_nws_alert_history_lakeway.md` addendum). | **REUSE, probe-gated (P2).** Rev 2.1: P2(b) observed `?point=` polygon-exact for one live SVW (n=1; no TOW to test). What happens if it isn't is operator question Q7. |
| Classification | `inclement.py:152-266 AlertClassifier.classify` (substring gate `:141-149`, certainty fold, severity demote) | **EXTEND.** Exact code/name table replaces the substring list. Severity/certainty move to attrs only. Tier vocabulary is unchanged. |
| Hazard window | `inclement.py:129-138 _alert_expires_at = min(Ends, Expires)`, drop at `:211-214`; aggregate `expires_at = min(expiries)` across contributors (`:263`), consumed by `compute_solar_horizon` (`:381-391`) and `_overnight_fallback` (`:438-453`). | **EXTEND** to per-alert `(Onset, Ends)`, aggregate = `max(end)` over HOLD-class contributors (D-B1), plus an unconditional hold memory (D-B3). |
| Hold depth | `inclement.py InclementFusion.decide` (`:560-720`), `_full_hold_floor :724`, `_partial_floor_value :733`, `compute_solar_horizon` | **REUSE unchanged**, except: the blind SOC-None floor (D-A3); bottom-rate input replaces the literal `off_peak` (D-B4); forecast counts as corroboration (D-C2). |
| Decision cache / signal / attrs | `energy_battery.py:2663 _inclement_decision` (per-tick cache), `:2732 _cache_inclement`, `:2764 _inclement_attrs`. `SIGNAL_INCLEMENT_STATE_CHANGED` (`signals.py:120`) has **no listeners** (grep). | **REUSE.** |
| Floor enforcement | 8 `_floor_reserve` wraps; 2 inline off-peak clamps (`:6223-6224`, `:6262-6263`); full_hold emits use `decision.reserve_floor` | **KEEP** as defense in depth. The fold (D-A2) makes them redundant by construction; not deleted in this arc (KEEP+DOCUMENT). |
| Decision-side reserve writer | `_result` reserve block `energy_battery.py:~6350-6395` (target resolve, clamp, stand-down skip, ≥2 deadband) and its desired stamp `:6532-6534`; blind de-escalation dict `:5662-5668` | **EXTRACT** into one helper `_reserve_action` (D-A2), which is also the sole writer of `_last_reserve_level_desired`. |
| Writer lint + rows | `energy_const.py:2307 RESERVE_SET_VALUE_WRITERS`; `quality/tests/test_reserve_write_chokepoint_lint.py`; rows C1/C2/C3, row builder `energy.py:9145-9165` | **REUSE** + one additive row field `tick_floor` (D-A4). The allowlist changes from `_result:1 + determine_mode:1` to `_reserve_action:1`. |
| EVSE overlay | `_apply_evse_battery_hold` (`energy.py:5248`, called `:6468` timer and `:7183` evaluate). Append branch `:5463-5528` writes `max(hold_soc, _last_reserve_level_desired, dp)` with **no deadband** when the decision has no reserve action; reason suffix `" + EVSE hold"` (`:5332`). | **REUSE unchanged** (Non-goal 1). Its behavior under blind is stated in INV-2 and §12. |
| Write-verify under blind | `_desired_stamped_at` stamp `energy_battery.py:6559`; sweep stand-down `energy_write_verify.py:880-905`; I-D3 in `force_redispatch :6721-6772` (gate: stamp age > 600 s) | **REUSE unchanged.** Blind never stamps `_desired_stamped_at`. The first ≤600 s of a blind episode is stated in INV-2. |
| Blind SOC freshness | `_precharge_refused_on_blind :4106` | **REUSE.** |
| Top-rate | `energy_tou.py TOURateEngine`: `get_season :449`, `get_current_period :459`, `get_current_rate :472`; rates in `ha-config/universal_room_automation/tou_rates.json`. Closest existing helper: `energy_battery.py:4501 _midpeak_rate_lt_peak`. | **BUILD** `rate_rank` / `is_top_rate` / `is_bottom_rate` in the engine (D-A1). `_midpeak_rate_lt_peak` stays (different question). |
| Outage witness | **Rev 2.1 (P4): primary = Enphase cloud calendar `calendar.main_panel_wall_enphase_cloud_hacs_system_event_history` (platform `enphase_ev`), substring match; local sensors corroborate only; `sensor.iq_gateway_hacs_grid_mode` rejected (98 false on/off-grid flips in 7 d).** Prior text: `energy_write_verify.py:1821 _grid_outage_active` (tri-state read of `switch.enpower_482348004678_grid_enabled`). `grid_connected` (`energy_battery.py:2210`) defaults True when unavailable, so it can't be a witness. It is a WriteVerifier method, so it is dead when `_write_verifier is None`. Whether the switch flips on a utility drop is unproven (P4 checks it). | **REUSE `_grid_outage_active`**, P4-gated. |
| Outage ground truth | Enphase cloud calendar `calendar.main_panel_wall_enphase_cloud_hacs_system_event_history`. No URA reference today (grep `system_event_history`: 0 hits). | **BUILD** a daily read-only sweep (D-L2), probe-gated (P4). Entity resolved by registry lookup at call time (D-L2), not by an EC role. |
| Durable rows | `database.py:6233 log_activity` (single-writer queue `:523-541`). **Pruned** by `prune_activity_log` (`:6269-6305`): `info` after 7 days, everything else after 30. | **REUSE the table, EXTEND the prune** with a hardcoded action exemption (D-L0). No DDL. |
| Hourly forecast | `weather_manager.py:366 _fetch_provider_forecast` is daily only (`:376`). Grep `hourly`: 0 hits. Providers: `weather.phalanxmadrone`, `weather.madroneweather_tracker_dynamic_weather_madroneweather_tracker`, `weather.madronehaos`. | **EXTEND `WeatherProviderManager`** (lifecycle `:188-221`, `_unsub_handles`, `_pending_refresh_tasks`, WPM-C1 lock). P1-gated. |
| Condition corroboration | `weather_manager.py:785 current_storm_condition` | **REUSE unchanged.** |
| Legacy threat list | `CONF_INCLEMENT_POWER_THREAT_EVENTS`; live value equals the shipped default (read from `.storage/core.config_entries`, 2026-10-16) | **RETIRE** (KEEP+DOCUMENT the constant; remove from the options UI). No options write. |

### 1b. Greps run (worktree HEAD de5217ae5; Rev 2 re-checks on 32f031cda)
- `grep -n "_floor_reserve\|def _result" energy_battery.py`: 8 callers + def `:3855` + narration `:6687`. No floor inside `_result`.
- Period-name literals (`== "peak"`, `== "mid_peak"`, `in ("peak","mid_peak")`): 35 sites, classified in §8. `(==|!=) "off_peak"` / `in ("off_peak"`: 29 (energy.py 8, energy_battery.py 5, energy_pool.py 5, energy_tou.py 3, hvac_predict.py 1, inclement.py 5, sensor.py 2); handling in §8.
- `grep -rn "hourly"` (forecast context): 0. `system_event_history\|calendar.get_events`: 0.
- `SIGNAL_INCLEMENT_STATE_CHANGED`: defined `signals.py:120`, sent `energy_battery.py:2748-2751`, no subscriber.
- `_last_inclement_decision` readers outside energy_battery: `energy_write_verify.py:1659` (`_inclement_partial_hold_floor`, called `:1730` and `:1935`), `:1755` (`_resolve_hold_owner`), `energy.py:9153` (governor row).
- Every reserve-bearing `self._result(` is reached after `_inclement_decision` (`:5787`). The earlier returns are grid-disconnect `:5774-5780` (no `reserve_level`) and the fully-blind gate `:5578-5695`. `determine_mode` is synchronous.
- `number.set_value` literals in `energy_battery.py`: `:5664`, `:6395`, `:6818`, `:6836`. After Stage A: `_reserve_action` + the two in `force_redispatch`.
- `prune_activity_log`: `database.py:6269`, WHERE literals `:6281-6282`.

### 1c. Docs and memory read
- In full: arc doc, `README_v5.103.66.md`, `PLANNING_reserve_write_governor.md` (incl. Known limits), `PLANNING_inclement_hardening.md` Rev 3 and its plan reviews 1/2/3, both audits, `audit_reserve_surface_ground_truth.md`, the two cards, and the two Rev-1 plan reviews of this plan.
- Skimmed: `PLANNING_inclement_weather_reserve.md` (v5.5.0), `README_v5.5.0.md`.
- HVAC / presence state-of-play docs: not applicable (energy-only cycle).

---

## 2. The decision model (the one design every stage implements)

```
NWS feed (point query, 1-min poll)  +  last_updated sensor (feed health)
  │  D-B1 filter: Status=Actual, Type≠Cancel, start ≤ now ≤ end   (pre-onset ⇒ not active)
  │  D-B2 product table: code (or exact event name) → class {HOLD-warn, HOLD-watch, NOTICE}
  │  D-B1 locality: polygon products per Q7
  │  D-B3 hold memory (keyed on alert ID) carries HOLD alerts through feed loss
  ▼
AlertClassification (tier = max over contributors; end = max over HOLD contributors)
  │
  │  + condition corroboration (existing)  + D-C forecast corroboration (P1-gated, latched per alert ID)
  ▼
InclementFusion.decide (v5.5.0 ladder, bottom-rate from D-A1)  ──►  InclementDecision.hold_depth / reserve_floor
  │
  ▼  D-A2 register (in determine_mode): self._tick_reserve_floor = decision.reserve_floor if holding else None
  │
  ├── sighted: existing branches → _result → _reserve_action (fold + stamp) → dispatch → row C1/C2
  └── fully blind: D-A3 blind rules → _reserve_action (fold + stamp) → C1
        then (both paths) EVSE overlay append, max-only, unchanged
  
energy.py decision cycle, after determine_mode returns (independent of every early return):
  D-L1 nws_alert rows (raw feed read)   D-L2 grid_outage rows (witness + cloud sweep)
```

**Two design principles that hold across all stages:**
1. **Raise-only asymmetry.** Forecast and locality can *add* corroboration or *confirm* applicability. They never demote a HOLD-warn product. A false hold costs one day of arbitrage; a missed freeze outage costs far more. (Whether "locality can't be verified" counts as a demotion is Q7. The plan's recommendation keeps this principle intact.)
2. **One floor, one writer, one stamp.** The current tick's floor is registered once, and the one decision-side writer folds it and stamps `_last_reserve_level_desired` from the folded value. Blind and sighted paths share that writer. The overlay stays max-only and allowlisted; because its base is the folded stamp, it can't go below the floor.

---

## 3. Falsifiable invariants

> **INV-1 (floor by construction).** In any `determine_mode` call whose current-tick decision has `hold_depth ∈ {partial_hold, full_hold}`: (i) every `_reserve_action` output (sighted, blind hold, blind release, blind de-escalation) has a target `≥ decision.reserve_floor`; (ii) `_last_reserve_level_desired` after the tick is `≥ decision.reserve_floor`; therefore (iii) the EVSE overlay, in both its update-in-place and append branches, emits `≥ decision.reserve_floor`, and `force_redispatch` re-sends a value `≥` it. **Falsifier:** a `reserve_write` row with `path ∈ {timer, evaluate, redispatch}` whose `value < tick_floor` (the D-A4 row field, captured at dispatch). **Legal-config repro:** `reserve_soc=20, partial_floor=50`, fully blind, October 18:00 (shoulder top rate), CFG on, a corroborated watch, so partial_hold at top rate. Today de-escalation writes 20 at `:5664`; after the change it writes 50. **Overlay repro:** same floor, sighted, hardware already at 50 (deadband suppresses), EVSE hold captured at 45, branch emitting 20: today's literal reading stamps 20 and the overlay appends 45; after the change the stamp is 50 and the overlay appends 50.

> **INV-2 (blind command surface).** While fully blind, per tick:
> (a) the decision emits **at most one** reserve `number.set_value` (via `_reserve_action`) and at most the pre-existing top-rate de-escalation `switch.turn_off`; never CFG turn_on, never a storage-mode select, never a `_desired_stamped_at` refresh;
> (b) **post-overlay:** if `_evse_hold_soc` is set, the overlay append branch may add one `number.set_value` per tick (pre-existing, no deadband, Non-goal 1); its value is `max(hold_soc, folded desired, dp) ≥` the floor, and its reason ends `" + EVSE hold"`;
> (c) **redispatch:** during the first ≤600 s of a blind episode the sighted-era `_desired_stamped_at` is still fresh, so a write-verify retry may re-send `_effective_reserve_desired` via `force_redispatch` (`energy_write_verify.py:1707-1735`); after 600 s it can't (I-D3). Its value inherits the fold through the stamp;
> (d) **release:** if any blind write in the episode raised the reserve above its pre-write base, the first blind tick whose decision is `allow_discharge` restores the captured pre-raise value.
> **Falsifiers:** a blind tick with two decision-side reserve actions; any CFG turn_on or select in a blind decision; a stamped `_desired_stamped_at` during blind; a `redispatch` row more than 600 s after the last sighted stamp while blind; a blind episode where the reserve was raised and is still at the raised value after an `allow_discharge` tick (no flag condition).

> **INV-3 (classification).** For an alert with `Status=Actual`, `Type≠Cancel`, a product-table class of HOLD, and `start ≤ now ≤ end`: the tier is ≥ the table tier (for polygon products, subject to the Q7 ruling, which is a single rung-1 switch). An alert with `now < start` contributes nothing. `WIY` (Wind Advisory) is never above `notice` in any reachable path. **Falsifier:** a WIY alert yielding `hold_depth ≠ allow_discharge`; a Hard Freeze Warning inside its window yielding tier < warn; a Winter Storm Warning hold dropping while the feed is unavailable or empty before its `end`.

> **INV-4 (top rate).** `TOURateEngine.is_top_rate(now)` is True iff the import rate of the active period equals the season's maximum distinct import rate **and** the season has ≥2 distinct rates. Blind de-escalation keys on it, so it fires in shoulder/winter `mid_peak` 17–21. **Falsifier:** October 18:00, fully blind, CFG on, no de-escalation.

> **INV-5 (ledger completeness and retention).** Each off-grid event in the cloud calendar (the primary witness, Rev 2.1) inside the sweep lookback appears in the ledger exactly once as a `grid_outage` episode. A local-sensor transition (change in the last non-None value) never opens an episode by itself; it is recorded as corroboration on the matching cloud episode, or as an uncorroborated `local_only` observation row. Each alert message ID seen in the feed has exactly one `nws_alert` row per boot, **including ticks where `determine_mode` returned early** (grid disconnect, fully blind). Ledger rows (`nws_alert`, `grid_outage`, `inclement_code_drift`, `inclement_memory_cleared`) are never removed by `prune_activity_log`. **Falsifier:** an off-grid calendar event with no row after a sweep; two rows for one episode; no `nws_alert` row for an alert active during a grid-disconnect tick; a ledger row older than 31 days missing after a prune pass.

---

## 4. Producer and consumer checks

| Value | Producer (arithmetic + dependency health) | Consumers (file:line, trust vs display) |
|---|---|---|
| `InclementDecision` | Classifier + fusion. Dependencies: NWS sensor (1-min poll; D-B3 adds a health rule and a memory); weather providers (3 configured; `_check_provider_health`); Solcast via `_expected_solar_surplus_pct`; SOC (3-tier resolver, None when fully blind). Under blind, `compute_solar_horizon` coerces SOC None to 0, so a top-rate corroborated watch is always "recoverable", giving partial_hold (P3-09). **Intended:** conservative. | `determine_mode` precedence (trust); attain/arbitrage helpers that thread `hold_depth` (`energy_battery.py:5042-5445`, trust); `_inclement_attrs` → strategy-sensor attrs and `sensor.ura_inclement_state` attrs (`sensor.py:9376-9385`, eight `inclement_*` keys, display; `inclement_expires_at` changes meaning under D-B1); `energy_write_verify.py:1659 _inclement_partial_hold_floor`, called `:1730`, `:1935` (trust); `_resolve_hold_owner` `:1752-1760` (trust; under Stage A it sees blind-tick decisions, so a blind row's `hold_owner` can now read `inclement`, intended); governor row `energy.py:9153` (audit); signal (no listener). |
| hazard end (`inclement_expires_at`) | Per alert: `end = Ends or Expires or (Sent + INCLEMENT_ALERT_MAX_HOLD_H)`. Aggregate: `max(end)` over **HOLD-class contributors only**; NOTICE alerts never contribute; None when no HOLD contributor. **Behavior change from today's `min` (`inclement.py:263`):** a longer window lengthens `compute_solar_horizon` (`:381-391`) and moves `_overnight_fallback` (`:438-453`), which can flip partial↔full at top rate. Justification for max: the hold is protecting against the latest hazard still active; `min` would let an early-ending Watch end the horizon of a later Warning, which is a demotion by aggregation (principle 1). | horizon (trust), overnight fallback (trust), attrs (display), signal payload. |
| `_tick_reserve_floor` (new) | `decision.reserve_floor` when holding, else None. Entry-reset to None at the top of `determine_mode`; assigned **in `determine_mode`** right after each of the two `_inclement_decision` call sites (sighted `:5787`, blind D-A3), never inside `_inclement_decision` (which `_inclement_attrs` also reaches). Partial: `max(reserve_soc, partial_floor)`. Full, sighted: `int(soc)` (can be below `reserve_soc`; the fold must not raise it to `reserve_soc`). Full, blind: `max(reserve_soc, partial_floor, INCLEMENT_BLIND_FULL_HOLD_FLOOR_PCT)`. | `_reserve_action` fold (trust); D-A4 row field `tick_floor` (audit). The ladder validator `energy.py:10438-10452` reads the configured `partial_hold_reserve_floor`, not this value (config consumer, unaffected). |
| `_last_reserve_level_desired` | **Sole writer after Stage A: `_reserve_action`**, stamped from the folded, clamped target whether or not an action is emitted. Today `_result` stamps it at `:6532-6534` from its raw argument before the deadband. | Overlay update-in-place and append `max()` (`energy.py:5463-5528`, trust); `_effective_reserve_desired` (INV-DP5 mirror, trust); `force_redispatch` (trust); blind hold base (trust). |
| `rate_rank` / `is_top_rate` / `is_bottom_rate` | Distinct import rates of `get_season(now)`, ranked ascending; period from `get_current_period(now)`. Tariff validated at load (`_validate_parsed_data :141`). Engine absent → callers use the legacy literal (byte-safe). | Stage A: blind de-escalation (trust). Stage B: fusion bottom-rate (trust). Stage D: the 9 H sites (trust). Attr `tou_top_rate` (display). |
| Grid outage episode | `_grid_outage_active` tri-state, sampled once per timer decision cycle in `energy.py` (D-L2), plus the cloud sweep. The Envoy flaps 220–324 times a day, so `None` is common; P4 checks the switch actually flips on a utility drop. | Ledger rows only. No decision consumer, by design. |
| Forecast outlook (Stage C) | Hourly `weather.get_forecasts` per healthy provider, aggregated over `[now, hazard end]`; confirmation latched per alert ID. | Fusion corroboration (trust); attr `inclement_forecast` (display). |

---

## 5. Emission and decision-site enumeration

**Reserve writers** (package-wide; the lint pins them). Today: `_result:1`, `determine_mode:1` (blind de-escalation), `force_redispatch:2`, `_apply_evse_battery_hold:1`, readers `_tap_write_verifier:1` and `_evaluate_battery:1`, non-reserve pool/EVSE/radar. **After Stage A:** `_reserve_action:1` replaces `_result:1 + determine_mode:1`. Reviewer D hand-reads `energy_battery.py` to confirm the only remaining `number.set_value` literals are `_reserve_action` and the two in `force_redispatch`.

**Floor-relevant reserve emissions:** the 19 `self._result(` calls in `energy_battery.py` (`:3933, 3956, 3997, 4720, 4774, 5013, 5776 (no reserve), 5816, 5836, 5852, 5863, 5879, 5886, 5955, 5975, 5990, 6107, 6238, 6265`); the blind hold/release (new) and de-escalation (`:5662-5668`); the overlay update-in-place and **append** branches (`energy.py:5463-5528`, called `:6468`, `:7183`; append is deadband-free and writes from the stamp); the DP fold inside the overlay; `force_redispatch` (re-sends the stamped desire; live under blind for ≤600 s, INV-2(c)); the DP stamp in `_offpeak_drain_branch_target` (`:6233`, fed by the inline clamps; reaches dispatch only through `_result`, so the fold covers it).

**Top-rate decision sites:** §8.

**Alert-consuming sites:** `classify` (`inclement.py:169`) and, new, the D-L1 ledger hook (raw read). `grep nws_alerts`: `_read_nws_alerts :2640` only today.

**Observation-mode surfaces touched:** Stage A widens blind de-escalation from summer peak to every shoulder/winter top-rate edge. That edge is also where the evaluate path runs `determine_mode` (`energy.py:7164`), which ignores observation mode (EC-OBSERVATION-MODE-RESERVE-BYPASS-1, arc step 8; the timer path gates at `:6591`). Stated as §12 known limit 14.

---

## 6. Deliverables

### Stage 0: probes (read-only; `ura-prober`; no build until each gate reads GO)

**P1: forecast provider probe (gates Stage C).** For each configured provider (plus `weather.nws_*` if present), call `weather.get_forecasts type=hourly`. Record per provider: fields present (`temperature`, `precipitation_probability`, `wind_gust_speed`, `wind_speed`, `condition`), horizon, update cadence, health over 24 h. Rev 3's "no gust" evidence came from a non-configured entity and doesn't count.
- **GO** if ≥1 healthy provider carries hourly `temperature` + `precipitation_probability` for ≥48 h. **NO-GO** parks Stage C with the report as evidence. Rev 2.1: P1 is **GO** on `weather.phalanxmadrone` (OWM One Call 3.0; live call returned 48 hourly rows each with `condition`, `precipitation_probability`, `wind_gust_speed`, `temperature`). It is the only qualifying provider. `FORECAST_PRECIP_CONFIRM_PCT` is set from history in the Stage C plan, not by P1.

**P2: NWS feed semantics (gates D-B1 and the D-B3 details).**
- (a) Recorder history of the alerts sensor for 2026-10-16 03:00–05:00 (the 10-15 WIY, Onset=Expires=04:00, Ends=19:00): did the alert leave the feed at Expires, did an Update arrive and when, was the feed ever without it inside `[Onset, Ends]`? (Informs the memory test fixture; the memory is built regardless, per D-B3.)
- (b) Is `?point=` polygon-exact for SVW/TOW (Severe Thunderstorm / Tornado Warning)? From the api.weather.gov docs (cite), cross-checked live if an SVW polygon appears. Feeds Q7.
- **Rev 2.1 result for (a):** the 10-15 WIY never left the feed inside `[Onset, Ends]` (an Update at 23:50 superseded the Alert with Expires 19:00; 0 unavailable rows 03:00-05:00). The 10-15 missed hold was a **classification miss** (WIY not matched), not feed loss. D-B3 memory is insurance.
- (c) For watches (WSA, SVA, TOA), is `onset` the hazard start or the issue time? Recorded in the table notes.
- (d) **Which entity carries the feed timestamp:** confirm the `last_updated` sensor's entity_id on this house, that its value changes on every successful poll (so its `State.last_changed` advances every minute), and whether its value is naive local time (`coordinator.py:126,182`).
- (e) Recorder history of both entities across a known internet or API drop: does the alerts sensor go `unavailable`, or return an empty list with a fresh timestamp (the `AttributeError` path)?

**P3: product codes (gates the D-B2 table).** Verify each row's `NWSCode` from api.weather.gov history for TXZ192/TXC453 or an authoritative NWS list (cite). An unverifiable code ships as exact-name match only.

**P4: outage witness probe (gates D-L2).** (i) `switch.enpower_…_grid_enabled` state and availability ratio over the recorder window, and **whether it went `off` during at least one calendar off-grid event** (discriminating: if it never does, the local witness is dropped and the sweep is the only source). (ii) `calendar.get_events` on the Enphase calendar for 48 h returns within 30 s. (iii) Exact summaries of off-grid, on-grid and generator events. (iv) The calendar entity's registry platform name, recorded for D-L2's lookup. The sweep is built only if (ii) holds.
- **Rev 2.1 result:** (i) `grid_enabled` and Enpower `grid_status` are `unavailable` 20.2 % of the window and never left `on`, but the window held no real outage, so whether they flip on islanding is **unproven**. `sensor.iq_gateway_hacs_grid_mode` flipped on/off-grid 98 times in 7 d with no outage and is **rejected**. (ii) not run live; plausible from the 10-15 audit (weekly windows worked). (iii) summaries known only from the audit; match by substring. (iv) platform `enphase_ev`, exactly one entity. D-L2 is redesigned below.

### Stage L: outage ledger (arc step 5) — ships first; evidence accrues only from its ship date

**D-L0 retention (database.py).** `prune_activity_log` (`database.py:6269`) deletes info rows after 7 days and all others after 30, which would destroy the ledger before the first winter. Add a hardcoded predicate to **both** tier WHERE literals (`:6281-6282`): `AND action NOT IN ('nws_alert','grid_outage','inclement_code_drift','inclement_memory_cleared')`, sourced from a rung-1 tuple `ACTIVITY_LEDGER_RETAINED_ACTIONS` rendered to a literal at import (still never user input; the `# SAFETY` comment is updated).
- **Schema/migration plan:** no DDL, no migration, no new table, no index. The existing prune subquery already scans `ura_activity_log` by `importance` and `timestamp`; the extra `action` predicate filters the same scan. Existing readers and analytics queries see the same rows plus older ledger rows.
- **Why not a dedicated table:** it would need a CREATE + migration + a second DAO for ~hundreds of rows a year. Volume bound: `nws_alert` one row per message (the 5.8-year TXZ192 audit averages well under 200 HOLD/NOTICE messages a year; gated-out products are logged too, so budget ≤1,000/yr); `grid_outage` tens per year (cloud off-grid events only; the nightly "Gateway rebooted" events are not off-grid and are not written). If volume ever exceeds 5,000 rows/yr, revisit with a dedicated table (revival trigger).
- **Tier:** this makes Stage L a real Tier 2-DB cycle (Review A covers prune and retention).

**D-L1 `nws_alert` rows.** Hook location is pinned: `energy.py`, in the timer decision cycle **after `determine_mode` returns**, next to `_track_envoy_availability(decision)` (`:7117`), so it runs after every early return (grid disconnect `:5774-5780`, fully blind). It reads the feed through `self._battery._read_nws_alerts(...)` (a pure state read), not the cached classification. For every message ID not yet logged this boot, it writes one row (`coordinator="energy"`, `action="nws_alert"`) fire-and-forget through the same `hass.async_create_task` contract as `_record_reserve_dispatch` (`energy.py:9094`). `details_json`: `Event, NWSCode, Type, Status, Severity, Certainty, Sent, Onset, Expires, Ends, AreasAffected`, plus `ura_class`/`ura_tier` (from the table once Stage B ships; `null` before), `local` (true/false/unknown), and `decision_age_s` (age of `_last_inclement_decision`; under pre-Stage-A blind it is stale, and this field says so). The RAM seen-set is pruned of IDs that leave the feed, so it stays bounded; a restart re-logs active alerts once.
**D-L2 `grid_outage` rows.**
Rev 2.1 redesign (P4): the cloud calendar is the **primary** witness; local sensors are corroboration only. No witness is built on `sensor.iq_gateway_hacs_grid_mode` (98 false flips in 7 d).
- (i) **Primary: cloud sweep** (P4(ii)-gated; one live 48 h `calendar.get_events` call before build). Once per `OUTAGE_SWEEP_INTERVAL_H` and once `OUTAGE_SWEEP_INITIAL_DELAY_S` after setup, read the last `OUTAGE_SWEEP_LOOKBACK_H` from `calendar.main_panel_wall_enphase_cloud_hacs_system_event_history`. Classify events by **case-folded substring** (`OUTAGE_CALENDAR_OFFGRID_SUBSTR = "off grid"`, `OUTAGE_CALENDAR_ONGRID_SUBSTR = "connected to the grid"`, `OUTAGE_CALENDAR_GENERATOR_SUBSTR = "generator"`), never equality, since the exact on-grid and generator-off strings are unverified. Each off-grid event writes one `grid_outage` row with `witness="cloud"` (dedup key: event start). The row embeds the inclement decision recorded nearest the event start if this boot saw it (else null), and `generator_events: [...]` in the window. A 1-min calendar `unavailable` blip skips that sweep only. Tracked-task pattern, `OUTAGE_SWEEP_TIMEOUT_S`, cancelled on unload.
- (ii) **Corroboration: local sensors** (`switch.enpower_…_grid_enabled` via `_grid_outage_active`, and `binary_sensor.enpower_…_grid_status`), same hook location as D-L1. Transition = change in the **last non-None** value; `None` (20.2 % of the time) never transitions and never resets the baseline; a boot reading sets the baseline silently. A local off-grid transition never opens an episode on its own. It writes a `grid_outage` row with `witness="local_only"` carrying the live inclement decision (tier, hold_depth, reserve_floor, `decision_age_s`), active alert IDs and SOC (or None), so the decision at the moment is captured even though the cloud row lands later. The sweep attaches a `local_only` row within `OUTAGE_DEDUP_TOLERANCE_MIN` of a cloud event as `corroborated_by_local=true` on the cloud row. If `_write_verifier is None` the `grid_enabled` leg is inert and setup logs one debug line.
- **Known limit (witness unproven):** whether either local sensor flips on a real islanding is not established; the 7-day window held no outage. Until it is, `local_only` rows are observations, not evidence of an outage, and the decision-at-outage snapshot comes only from them.
- **Calendar resolution (no options write, no new role):** at each sweep, look up the entity registry for `calendar.*` entities whose entity_id ends in `_system_event_history` and whose platform equals the P4(iv) name (rung-1 constant `OUTAGE_CALENDAR_PLATFORM`). Exactly one → use it. Zero or several → skip the sweep and log once at warning (`outage sweep: calendar not resolved (found N)`). Rev 1's EC role would never have resolved here: `EC_ROLE_KEY_DEFAULTS` only reaches options through the one-shot pin in `__init__.py:820-900`, which is idempotent on `EC_DEFAULTS_PINNED_FLAG` (already set on this install), and re-running it is an options write.
**Correlation** is a SQL join (alerts whose `[Onset, Ends]` overlaps an outage), deduplicated on `(NWSCode or Event, Onset)` because each Update is its own row. No code computes it.

**Acceptance**
- **Verify:** one `nws_alert` row per distinct message ID per boot; a second tick logs nothing; an ID that leaves the feed is pruned from the seen-set.
- **Verify:** alerts are logged on a tick where `determine_mode` returned at grid disconnect, and on a fully-blind tick.
- **Verify:** local readings False, True, True, None, True, False give exactly one `local_only` row and open no episode; `None` is not a transition; a boot reading of True writes nothing.
- **Verify:** a cloud off-grid event gives exactly one `witness=cloud` row across two overlapping sweeps; a `local_only` row 3 min from it sets `corroborated_by_local=true`; a summary of `Your system is now off grid` and a variant with different casing/prefix both match; `Gateway rebooted` writes nothing; an unresolved calendar skips the sweep with one warning.
- **Verify:** the sweep raising or timing out writes no row and leaves the decision path untouched.
- **Verify:** a seeded `nws_alert` row 40 days old (importance info and notable) survives `prune_activity_log`; a seeded non-ledger row of the same age is deleted.
- **Test:** `test_prune_keeps_ledger_rows`, `test_prune_still_deletes_other_rows`, `test_alert_ledger_one_row_per_id`, `test_alert_ledger_seen_set_pruned`, `test_ledger_logs_alerts_during_grid_disconnect_return`, `test_ledger_logs_alerts_while_fully_blind`, `test_outage_local_only_never_opens_episode`, `test_outage_witness_none_is_not_a_transition`, `test_outage_witness_boot_sets_baseline_silently`, `test_outage_sweep_substring_match`, `test_outage_sweep_dedups_across_sweeps`, `test_outage_sweep_marks_local_corroboration`, `test_outage_sweep_calendar_unresolved`, `test_outage_sweep_failure_isolated`, `test_outage_sweep_task_cancelled_on_unload`.
- **Live:** (a) after restart, the `nws_alert` row count for this boot equals the alerts sensor's state (active message count; 0 means 0 rows). Fewer = broken writer; a multiple = missing dedup. (b) the first sweep logs `outage sweep: parsed N events, M off-grid` with **N > 0** (the calendar carries ~35 "Gateway rebooted" events per 7 weeks, so N=0 means parsing or resolution failed). (c) Seed one ledger row with a timestamp 31+ days old, call the prune, confirm it survives; delete the seed. (d) 0 ERRORs mentioning `nws_alert` / `grid_outage` / `prune`. (e) **Witness settlement (optional, operator action):** on the first real or deliberate islanding event, the ledger shows one `witness=cloud` row, and either `corroborated_by_local=true` (local sensors proven; the known limit closes) or no `local_only` row within tolerance (local sensors disproven; drop the corroboration leg). Until such an event, (e) reads "not observed" and the known limit stands.

### Stage A: top rate + one floor + blind decisions (arc steps 2 and 7-core)

**Depends on:** the governor's live validation passing (arc step 2 gate, `ARC_energy_coordinator_resilience.md:17`): at least one real `reserve_write` row with non-null `value`, `path` and `hold_owner` columns post-v5.103.66. Today there are none, because the Envoy is hung. If the operator wants Stage A before that, record the gate waiver in the ship README.

**D-A1 top-rate primitive** (`energy_tou.py`). Add `rate_rank(now) -> int`, `is_top_rate(now) -> bool`, `is_bottom_rate(now) -> bool`, `period_rank(season, period) -> int`. Ties share a rank. A single-rate season has every hour bottom and none top. Add strategy-sensor attribute `tou_top_rate` (REUSE `sensor.py` battery strategy attrs).

**D-A2 one decision-side writer, registered floor, one stamp** (`energy_battery.py`).
- Extract `_result`'s reserve block into `_reserve_action(reserve_level: int | None, *, compare_to: int | None = None) -> tuple[int | None, dict | None]`, returning `(folded_target, action)`.
  - `folded_target = max(reserve_level, self._tick_reserve_floor)` when both are not None; `reserve_level` when the floor is None; `None` when `reserve_level` is None (no reserve intent, no stamp). Then the 0–100 clamp. **Fold before clamp, before stand-down, before deadband.**
  - `_reserve_action` **stamps `self._last_reserve_level_desired = folded_target`** (when not None) **before** the stand-down/deadband decision, whether or not an action is emitted. It is the **only** writer of that attribute in the package. Remove the stamp at `_result:6532-6534`.
  - It then applies the stand-down skip and the ≥2 deadband against `compare_to` if given, else the live write-leg state (today's behavior), and returns the action dict or None.
- `_result` calls it and ignores `folded_target` except for narration.
- `_tick_reserve_floor`: entry-reset to None at the top of `determine_mode` (next to the existing ENTRY-RESETs, `:5480-5495`), assigned in `determine_mode` right after each `_inclement_decision` call.
- `RESERVE_SET_VALUE_WRITERS`: replace the `_result` and `determine_mode` rows with `("energy_battery.py", "_reserve_action", "reserve", 1)`.

**D-A3 blind decisions.** Move `decision = self._inclement_decision(tou_period, now)` above the fully-blind gate (safe: per-tick cache `:2668`). Register the floor. Inside the blind branch, emit **at most one** reserve action, by this precedence:
1. **De-escalation** (`is_top_rate(now)` or `tou_transition_into` has top rank; CFG on; not full_hold; the existing exemption is kept and its freshness check reduces to the current-tick decision): `turn_off` (unchanged) + `_reserve_action(reserve_soc)`, folded. Reason prefix `"Blind de-escalation — "`.
2. **Hold** (`hold_depth ≠ allow_discharge`): `base = _last_reserve_level_desired`, else the write-leg state, else **None**. Target = `F` if base is None, else `max(F, base)`. Emit `_reserve_action(target, compare_to=_last_reserve_level_desired if the write-leg state is None else None)`, so an unreadable hardware value can't defeat the deadband and cause a write every tick. Never lowers a held value. Reason prefix `"Blind hold — "`.
3. **Release** (`allow_discharge` and `_blind_raised`): `_reserve_action(_blind_pre_raise if not None else reserve_soc)`; clear `_blind_raised`. Reason prefix `"Blind release — "`.

**Release arming (any rule):** on any blind write whose `folded_target` is above its pre-write base (`_last_reserve_level_desired`, else write-leg state, else "unknown"), and `_blind_raised` is False: capture `_blind_pre_raise = base` (None if unknown) and set `_blind_raised = True`. A de-escalation write whose `folded_target ≤ _blind_pre_raise` clears the flag (it already restored). When base was unknown, release targets `reserve_soc` (the configured backup reserve, which is the value de-escalation already treats as safe).

**Operator-manual-lower behavior:** governed by Q6. Default build (recommended answer **A**): the hold rule's `base` reads `_last_reserve_level_desired`, so a manual lower below the floor is re-asserted next tick; a manual lower that stays above the floor is respected only if it is above the last stamped desire. Answer **B** adds one rule: if the write-leg state is below `_last_reserve_level_desired` and no URA dispatch produced it (C1 last-dispatched value ≠ current state), set `_blind_operator_override = True` and emit no reserve action for the rest of the episode. The switch is a rung-1 constant `BLIND_RESPECT_MANUAL_LOWER` (default per the ruling), so both answers are one build.

The blind branch never stamps `_desired_stamped_at` (I-D3 kept) and never calls `_result` (so `envoy_available=False` and the blind dict keys are kept, P3-03; no CFG double-emit, P3-04). Episode flags are RAM-only and reset when the gate is not engaged. `_full_hold_floor(None)` becomes `max(reserve_soc, partial_floor, INCLEMENT_BLIND_FULL_HOLD_FLOOR_PCT)`; the sighted branch keeps `int(soc)` (P3-08).

**D-A4 row field `tick_floor`** (additive payload change, Tier 2-DB note). `_record_reserve_dispatch` adds `tick_floor` = `battery._tick_reserve_floor`, read synchronously at the dispatch call (before the task is scheduled), plus `tick_hold_depth`. These are the only governor-row changes; `inclement_floor` / `floor_ok` keep their partial-only semantics. Without this, INV-1's live falsifier can't see full_hold or the blind floor. `details_json` keys are additive; no reader parses the row positionally (grep at build to confirm).

**Honest scope (P3-11):** helps only the *fully* blind case. With LKG/cloud SOC, the relaxed gate already runs the decision. On 10-15 the hold also failed because WIY didn't match, which Stage B makes deliberate (WIY = notice).

**Acceptance**
- **Verify (INV-4):** tz-aware local hour iteration over a full year under the committed PEC tariff, **including both 2026 DST transition days and each season-boundary day**: `is_top_rate` equals {summer 16–20, shoulder 17–21, winter 05–09 and 17–21}; `is_bottom_rate` equals `get_current_period == "off_peak"`. mid == peak gives both rank 1. Single-rate season gives no top hours.
- **Verify (golden, expected diff only):** the governor A/B golden (`quality/tests/fixtures/reserve_governor_golden.json`) is **unchanged for the seven sighted cases**. The `blind` case is re-baselined with exactly this expected diff: (1) `last_reserve_level_desired` changes from `null` to the stamped value; (2) the de-escalation `set_value` is now behind the ≥2 deadband and stand-down, so it is absent when the fixture's hardware reserve is within 2 of `reserve_soc`; (3) the reason string changes to the new prefix. The test asserts that set of keys differs and nothing else. **Any sighted-case diff, or any blind diff outside that list, stops the build:** it is a pre-existing floor leak (D-HIGH-1 class) and must be reported. The README lists the blind diff under behavior changes.
- **Verify (INV-1 repros):** the §3 de-escalation repro writes 50 (today 20). The §3 overlay repro appends 50 (pre-fold stamp would give 45). `reserve_soc=20, partial_floor=50`, fully blind, October 18:00, CFG on, **uncorroborated** watch → allow_discharge, no floor, de-escalation writes 20 (correct, not a leak). The same at 03:00 (off-peak, partial hold, floor 50) gives a hold write of 50.
- **Verify (INV-2):** steady blind hold gives zero decision-side reserve actions after the first. With `_evse_hold_soc=45`, blind floor 60: the overlay appends 60 each tick (pre-existing re-send, value ≥ floor, reason ends `+ EVSE hold`). Hazard end while blind gives one release to `_blind_pre_raise`, then none. A de-escalation that raised the reserve arms the release. Blind + allow_discharge with no prior raise and a pre-blind arbitrage desire of 80 gives no reserve action. Restart into blind with desired and write-leg both None: one write of F, then none (deadband against the stamp). No select, no CFG turn_on, `_desired_stamped_at` unchanged across blind ticks.
- **Verify (Q6):** with `BLIND_RESPECT_MANUAL_LOWER=False`, a manual lower to 30 under floor 50 is re-asserted to 50 next tick; with `True`, no reserve action follows and the episode flag is set.
- **Verify:** fully blind at 18:00 in October, CFG on → exactly one turn_off and one reserve action (today: none).
- **Test (mutation-anchored):** `test_tou_rate_rank_hour_sweep_pec_dst`, `test_tou_rate_rank_ties_and_single_rate`, `test_reserve_action_fold_raises_only`, `test_reserve_action_fold_before_deadband`, `test_reserve_action_is_sole_desired_stamper`, `test_reserve_action_stamps_folded_when_deadband_suppresses`, `test_overlay_append_cannot_undercut_floor`, `test_tick_floor_entry_reset`, `test_governor_golden_sighted_unchanged_blind_expected_diff`, `test_blind_runs_inclement_decision`, `test_blind_hold_writes_floor_once`, `test_blind_hold_unreadable_reserve_writes_once`, `test_blind_hold_never_lowers_held_value`, `test_blind_release_at_hazard_end`, `test_blind_no_release_without_raise`, `test_blind_deescalation_raise_arms_release`, `test_blind_deescalation_shoulder_midpeak`, `test_blind_deescalation_reserve_folded`, `test_blind_never_stamps_desired_at`, `test_blind_one_reserve_action_per_tick`, `test_blind_hold_with_standing_evse_hold`, `test_blind_hold_manual_lower` (parametrized on `BLIND_RESPECT_MANUAL_LOWER`), `test_blind_full_hold_floor_inversion` (`reserve_soc=20, partial=80, knob=60` → 80), `test_sighted_full_hold_floor_below_reserve_soc_unchanged` (SOC 15, `reserve_soc` 20 → 15), `test_reserve_row_carries_tick_floor`, lint `test_reserve_write_chokepoint_lint` green with the new tuple.
- **Live** (precondition for (b)–(c): `_write_verifier` present, checked from the setup log; otherwise the row checks are vacuous and read "not observable"):
  - (a) `tou_top_rate` on `sensor.ura_energy_coordinator_battery_strategy` reads **true** at 17:00–21:00 local in October and false at 16:00. A name-keyed implementation reads false all day in shoulder.
  - (b) For each `reserve_write` row with `ts > <Stage A restart>` written while the battery reported `envoy_available=false`: its reason starts with `Blind hold — `, `Blind release — ` or `Blind de-escalation — ` (optionally ending `+ EVSE hold`), and there is at most one `Blind hold — ` row per episode not followed by an EVSE suffix. A writer that ignores v5.17.5 shows a hold row per tick. **If no blind episode occurs before close, (b) reads "not observed" and the in-suite INV-2 tests are the proof of record.**
  - (c) For rows with `ts > <Stage A restart>`: `value >= tick_floor` whenever `tick_floor` is non-null (no `NOT LIKE 'Blind de-escalation%'` exclusion). Count of violations = 0. If no row with non-null `tick_floor` exists, (c) reads "not observed", not PASS.
  - (d) 0 ERRORs mentioning `_reserve_action` / `blind` / `tick_floor`.

### Stage B: matching, locality, Onset→Ends (arc steps 3 and 4)

**D-B1 hazard window and filter** (`inclement.py`). `_hazard_window(alert) -> (start, end)`: `start = Onset or Sent`; `end = Ends or Expires or Sent + INCLEMENT_ALERT_MAX_HOLD_H`. Drop `Status ≠ Actual`, drop `Type == "Cancel"` (keep Alert **and Update**), drop `now < start` and `now > end`. Aggregate across contributors: tier = **max** tier; `expires_at` = **max(end)** over HOLD-class contributors only (§4 for the justification and both consumers). Polygon products (`polygon_local=True` in the table: Severe Thunderstorm Warning `SVW`, Tornado Warning `TOW`, Extreme Wind Warning) follow the rung-1 switch `INCLEMENT_UNVERIFIED_POLYGON_TIER` (`"table"` or `"notice"`), applied only when P2(b) says `?point=` is not polygon-exact. Its default is set by **Q7**; recommendation `"table"`. `inclement_expires_at` carries the aggregate end (attr name kept; meaning documented in the README).

**Stated behavior change (operator doctrine, Q5):** today an alert is active from `Sent` until `min(Ends, Expires)` (`inclement.py:205-214`). After D-B1 it is active only from Onset. A Winter Storm Warning issued 18 h ahead no longer holds from issue, so the battery may drain at peak before the storm arrives. The parked pre-onset floor (Q3) is the only mitigation. Reviewers must not "fix" this; the Stage B checkpoint re-confirms it.

**D-B2 product table** (`energy_const.INCLEMENT_PRODUCT_TABLE`, rung 1): rows of `(code | None, exact_event_name, class, polygon_local)`. A match is the code **or** the exact (case-folded) event name. When one matches and the other disagrees, log a warning and write an `inclement_code_drift` activity row (P3-06 trip-wire). **Rev 2.1 (P3):** the feed uses NWS codes, not SAME: `SVW` (Severe Thunderstorm Warning) and `TOW` (Tornado Warning), not SVR/TOR. Only the probe-verified codes are coded (`SVW`, `TOW`, `FZW`, `FZA`, `HWW`, `HWA`, `TRW`, `WIY`, `WWY`); the 18 unverified products ship `code=None` and match by exact name only, so the drift row can't fire on a guessed code. The drift row records the first observed code for each name-only product. Tier = table tier. No severity, certainty or breadth demotion on this path (attrs and ledger only).

| Class | Products (code per P3; unlisted code = `None`, exact-name match) | Tier |
|---|---|---|
| HOLD-warn | Winter Storm Warning, Ice Storm Warning, Hard Freeze Warning, Extreme Cold Warning, Wind Chill Warning, Blizzard Warning, Tornado Warning `TOW` (polygon), Severe Thunderstorm Warning `SVW` (polygon), Extreme Wind Warning (polygon), Hurricane Warning, Tropical Storm Warning `TRW` | warn |
| HOLD-watch | Winter Storm Watch, Hard Freeze Watch, Extreme Cold Watch, Wind Chill Watch, Tornado Watch, Severe Thunderstorm Watch, Hurricane Watch, Tropical Storm Watch | watch |
| NOTICE (shown and logged, never a hold) | **Wind Advisory** `WIY`, High Wind Warning/Watch `HWW`/`HWA`, Winter Weather Advisory `WWY`, Freeze Warning `FZW`, Wind Chill Advisory, Cold Weather Advisory | notice |
| gated out | everything else (heat, fog, red flag, flood, fire) | none |

SVA/TOA/SVW/TOW (the substring list's "severe thunderstorm"/"tornado") hold today through the substring list; keeping them at table tier is the no-regression choice (and is what Q7's recommended answer preserves). Freeze products are added on outage evidence (Uri, Jan 2026). High Wind moves to notice (0 fires in 5.8 years; operator: no wind outages seen), confirmed under Q4.

**D-B3 feed health and hold memory.**
- **Stale** = the alerts sensor is `unavailable`/`unknown`, **or** the `last_updated` sensor's `State.last_changed` is older than `NWS_ALERTS_STALE_S`. Using `last_changed` of the timestamp sensor (whose value changes every successful poll) avoids parsing its naive-local value and avoids the alerts sensor's own `State.last_updated`, which does not advance while one alert stays steady. The `last_updated` entity is resolved as the sibling of the configured alerts entity (same config entry, via the entity registry); if it can't be resolved, only the unavailable/unknown leg applies and one warning is logged. Attr `inclement_alerts_stale`.
- **Memory, built unconditionally** (not gated on P2(a)): a RAM map keyed on alert **message ID**, holding every alert classified HOLD, with its own `end`, event name, code and window. Each tick, the classifier input is the healthy feed's active alerts **plus** memory entries still inside `[start, end]`.
- **End-time rule per entry:** the entry's own `end` (D-B1). An Update that supersedes an entry (same event name, overlapping window) adds its own ID with its own `end`; the earlier entry stays until its own `end` (so the combined hold lives to the later end, matching the max aggregate).
- **Clearing:** an entry is removed only when (1) `now > end`; or (2) a `Cancel` with the same event name and an overlapping window appears in a healthy feed (code compared when both have one); or (3) the alert disappears from a feed that is healthy **and non-empty**. A feed that drops to zero alerts, is stale, or is unavailable clears nothing, which covers the `AttributeError` empty-feed path. Each clear under (2) or (3) writes an `inclement_memory_cleared` row (ID, event, reason), so drift is visible.
- **No new admissions while stale:** a stale feed adds nothing to memory.
- **Across alerts:** tier = max over memory ∪ feed; end = max(end) over HOLD contributors. Max, not min, for the principle-1 reason in §4: a hold ends when the last HOLD hazard ends.
- **Restart:** memory is RAM-only. A restart during an internet outage loses it (§12 known limit 15).

**D-B4 bottom rate in the hold logic.** `InclementFusion` gets `bottom_rate: bool` from `is_bottom_rate(now)` (fallback `tou_period == "off_peak"` without an engine). It replaces the literal checks in `decide` (`:595/618/640/700`) and `compute_solar_horizon` (`:355`). Byte-identical on PEC (hour sweep).

**D-B5 retire the legacy list.** Remove `CONF_INCLEMENT_POWER_THREAT_EVENTS` and `CONF_INCLEMENT_WARN_MIN_SEVERITY` from the options-flow schema; keep the constants (KEEP+DOCUMENT). If a stored list differs from the v5.5.0 default, raise one repair issue at setup. **No options write.** The live list equals the default, so no issue fires here.

**Acceptance**
- **Verify (10-15 replay, committed fixture from the recorder payload):** WIY, Onset 04:00, Ends 19:00. 02:30 not active; 04:00 and 18:59 notice and allow_discharge; 19:01 gone. An Update with a new Expires is kept (a `Type≠Alert` filter would drop it).
- **Verify (INV-3):** Hard Freeze Warning in window → warn, full_hold. Hard Freeze Watch, off-peak, uncorroborated → partial_hold. Freeze Warning → notice. Flood Watch → gated out. Empty-code "Winter Storm Warning" matches by name. Code/name disagreement writes one drift row.
- **Verify (onset change):** WSW Sent 06:00, Onset 21:00: allow_discharge at 18:00 (today: hold), hold at 21:00.
- **Verify (aggregate):** a Watch ending 20:00 and a Warning ending 06:00 next day → `expires_at` = 06:00; a NOTICE ending later than both does not move it.
- **Verify (polygon):** with P2(b) NO, an SVW returned by the feed gives warn under `"table"` and notice under `"notice"` (parametrized).
- **Verify (feed health):** alerts sensor `unavailable` + a known WSW → hold to Ends. Feed returns `[]` with fresh timestamp (AttributeError path) → hold to Ends. One steady alert for 2 h with the timestamp sensor advancing → not stale. Stale feed never admits a new alert. Cancel with same event and overlapping window in a healthy feed clears and writes one `inclement_memory_cleared` row. Alert with no end drops after `INCLEMENT_ALERT_MAX_HOLD_H`.
- **Verify:** the bottom-rate hour sweep gives identical decisions to the literal path across a year.
- **Test:** `test_wiy_is_notice_never_hold`, `test_freeze_products_hold`, `test_pre_onset_not_active`, `test_wsw_issued_ahead_holds_from_onset`, `test_update_message_kept_cancel_dropped`, `test_hold_lives_to_ends`, `test_fallback_expires_when_no_ends`, `test_aggregate_end_max_over_hold_contributors`, `test_code_name_drift_row`, `test_polygon_tier_switch` (parametrized), `test_unavailable_sensor_is_stale`, `test_steady_alert_not_stale`, `test_empty_feed_on_attribute_error_keeps_hold`, `test_stale_feed_never_admits_new`, `test_memory_cleared_by_cancel_writes_row`, `test_unbounded_alert_capped`, `test_fusion_bottom_rate_hour_sweep_identical`, `test_legacy_list_no_options_write`, `test_customized_legacy_list_raises_repair_issue`.
- **Live:** (a) `nws_alert` rows after Stage B carry `ura_class`; any WIY row reads `notice` and the strategy sensor shows no hold then. (b) `inclement_gated_out_events` lists heat/fog/flood and **not** Wind Advisory. (c) `inclement_alerts_stale` reads false in normal operation (a stuck-true attr means the staleness source is wrong). (d) Options flow no longer shows the two fields; no `async_update_entry` for the CM entry in the setup log window.

### Stage C: forecast slice (arc step 6). Built only on P1 GO

**Rev 2.1 (P1 GO):** the provider is `weather.phalanxmadrone` (OWM; hourly gust, precip probability and condition for 48 h). It is the only qualifying provider, so OWM stale/unavailable means outlook None (Open-Meteo has no precip probability). The Stage C plan sets `FORECAST_PRECIP_CONFIRM_PCT` from history.

**D-C1 hourly outlook** (`WeatherProviderManager`): `async_track_time_interval(FORECAST_REFRESH_MIN)` with unsub in `_unsub_handles`; refreshes through `_pending_refresh_tasks` under the WPM-C1 lock; immediate first refresh in `async_setup`; `never_fetched` distinct from `stale`. `hourly_outlook(start, end) -> Outlook | None`; stale beyond `FORECAST_STALE_MIN` returns None.
**D-C2 corroboration.** For a HOLD-watch alert, `forecast_confirms(product, outlook)`. Freeze/cold: min temp ≤ `FORECAST_FREEZE_CONFIRM_F`. Winter storm: min temp ≤ `FORECAST_WINTER_STORM_CONFIRM_F` and max precip-probability ≥ `FORECAST_PRECIP_CONFIRM_PCT`. Convective: precip ≥ that value or a storm condition in the window. Window `[now, hazard end]` capped at `FORECAST_WINDOW_MAX_H`. **Latch:** once confirmed for an alert ID, it stays confirmed until that alert's `end`, so the shrinking window can't flap full↔partial mid-event. Confirmation counts as watch corroboration (`corroborated = condition OR forecast`). Never touches warn. None = no change from today. A forecast alone never creates a hold.
**D-C3 attr** `inclement_forecast` = `{fetched_at, providers_ok, window_end, min_temp, max_pop, max_gust, confirms, latched_ids}`.

**Acceptance**
- **Verify:** Hard Freeze Watch, off-peak, outlook min 22 °F → full_hold. Min 40 °F → partial_hold. Outlook None → identical to today.
- **Verify:** a confirmed watch whose later outlook min rises to 35 °F stays full_hold until the alert's end (latch).
- **Verify:** Winter Storm Warning with a 40 °F outlook still full_hold.
- **Verify:** teardown leaves no timer; first tick after boot is `never_fetched` with today's behavior.
- **Test:** `test_forecast_confirms_freeze_watch`, `test_forecast_latch_no_flap`, `test_forecast_never_demotes_warn`, `test_forecast_none_is_noop`, `test_forecast_timer_torn_down`, `test_forecast_first_tick_never_fetched`, `test_forecast_window_capped`.
- **Live:** `inclement_forecast.fetched_at` advances every `FORECAST_REFRESH_MIN` (±1 tick) and `providers_ok` equals P1's healthy count. Frozen `fetched_at` = dead timer; `providers_ok=0` = silent fetch failure.

### Stage D: remaining period-name sites (arc step 7 remainder; separable)
Migrate the 9 **H** sites (§8) to `not is_bottom_rate(now)`, each proven byte-identical on PEC by a full-year tz-aware hour sweep. Add a pinned allowlist test (rung-1 tuple `TOU_PERIOD_NAME_LITERAL_SITES`, same AST pattern as the governor lint) for the 20 **N** sites. The 4 **T-change** sites ship only on operator approval (Q1).
- **Test:** `test_period_literal_sites_pinned`, `test_<site>_hour_sweep_identical` ×9.
- **Live:** strategy-sensor attributes and EVSE/pool `ura_activity_log` actions at the next 17:00 shoulder boundary match the prior day's.

---

## 7. Numbers get knobs

| Knob | Rung | Default | Why / kill-switch |
|---|---|---|---|
| `INCLEMENT_PRODUCT_TABLE` | 1 | §6 D-B2 | Decision topology; review required. Removing a row stops matching it. |
| `INCLEMENT_UNVERIFIED_POLYGON_TIER` | 1 | per Q7 (recommended `"table"`) | What an unconfirmed polygon product does. `"notice"` = the demotion. |
| `INCLEMENT_BLIND_FULL_HOLD_FLOOR_PCT` | 1 | 60 (Q2) | Blind full hold without SOC. `max(reserve_soc, partial_floor, knob)`. 100 = legacy pin. |
| `BLIND_RESPECT_MANUAL_LOWER` | 1 | per Q6 (recommended False) | False = re-assert the floor each blind tick; True = a manual lower ends blind reserve writes for the episode. |
| `NWS_ALERTS_STALE_S` | 1 | 900 (must stay > 310) | Feed staleness bound. P2(d)/(e): max healthy poll gap 302 s, max unavailable drop 245 s, so any value ≤ 310 self-triggers; 900 gives ~3× margin. A very large value disables the timestamp leg (the unavailable leg stays). |
| `INCLEMENT_ALERT_MAX_HOLD_H` | 1 | 48 | Caps alerts with no Ends/Expires. |
| `ACTIVITY_LEDGER_RETAINED_ACTIONS` | 1 | the 4 ledger actions | Prune exemption. Empty tuple = prune as before. |
| `OUTAGE_SWEEP_INTERVAL_H` | 1 | 24 | Sweep cadence. 0 disables the sweep. |
| `OUTAGE_SWEEP_INITIAL_DELAY_S` | 1 | 300 | First sweep after setup, off the boot path. |
| `OUTAGE_SWEEP_LOOKBACK_H` | 1 | 48 | Overlaps a missed day; finishes inside the timeout. |
| `OUTAGE_DEDUP_TOLERANCE_MIN` | 1 | 10 | Local-vs-cloud match (5-min tick + cloud lag). |
| `OUTAGE_SWEEP_TIMEOUT_S` | 1 | 30 | Calendar reads time out on long windows. |
| `OUTAGE_CALENDAR_OFFGRID_SUBSTR` / `_ONGRID_SUBSTR` / `_GENERATOR_SUBSTR` | 1 | `"off grid"` / `"connected to the grid"` / `"generator"` | Case-folded substring classifiers (P4(iii): exact strings unverified). Empty off-grid substring = sweep writes nothing. |
| `OUTAGE_CALENDAR_PLATFORM` | 1 | `"enphase_ev"` (P4(iv)) | Registry lookup filter. Empty = sweep disabled. |
| `ACTIVITY_LEDGER_IMPORTANCE` | 1 | `RESERVE_WRITE_LOG_IMPORTANCE` | Parity (retention no longer depends on it). |
| `FORECAST_REFRESH_MIN` (C) | 1 | 30 | Per P1 cadence. |
| `FORECAST_STALE_MIN` (C) | 1 | 120 | Beyond this, outlook None. |
| `FORECAST_WINDOW_MAX_H` (C) | 1 | 48 | Bounds a long Ends. |
| `FORECAST_FREEZE_CONFIRM_F` (C) | 1 | 28 | NWS hard-freeze threshold. |
| `FORECAST_WINTER_STORM_CONFIRM_F` (C) | 1 | 32 | Frozen-precip threshold. |
| `FORECAST_PRECIP_CONFIRM_PCT` (C) | 1 | 50 placeholder; final value set from history in the Stage C plan | Rev 3's 43 % night shows why a single sample can't set it (P1 addendum). |

Unchanged v5.5.0 knobs kept. **No new rung-2 or rung-3 knobs.** The options flow shrinks by two fields (D-B5).

---

## 8. Period-name sites, classified

Classes: **T** = top rate (Stage A). **T-change** = top rate, but migrating changes shoulder/winter behavior (Stage D, Q1). **H** = "above the bottom rate" (Stage D, byte-identical). **N** = the named period on purpose (stays; pinned).

| # | Site | Use | Class |
|---|---|---|---|
| 1 | `energy_battery.py:1879` | skip untrusted-SOC page during peak | T-change |
| 2–3 | `:4448`, `:4455` | mid_peak walk to next peak (summer bracket) | N |
| 4–7 | `:4574`, `:4921`, `:5082`, `:5164` | attain mid_peak gated by `_midpeak_rate_lt_peak` | N |
| 8–9 | `:5327`, `:5427` | stage label | N |
| 10–11 | `:5632`, `:5680` | **blind de-escalation** (+ log label) | **T** (Stage A) |
| 12–13 | `:5877`, `:5898` | peak / mid_peak branches (season-aware) | N |
| 14 | `energy.py:6383` | SOC-at-peak degradation baseline | N |
| 15 | `:8352` | summer post-peak mid_peak | N |
| 16 | `:8367` | load-shed at peak with low SOC | T-change |
| 17–18 | `:8375`, `:8380` | HVAC coast at peak; mid_peak poor-solar | N |
| 19–20 | `:8493`, `:8495` | energy situation (display) | H |
| 21 | `:8522` | load shed only above off-peak | H |
| 22 | `:8572` | peak import learning history | N |
| 23 | `energy_pool.py:405` | pool speed reduce at peak | T-change |
| 24 | `:1371` | EVSE peak/mid handling | H |
| 25 | `:1858` | excess-solar EVSE never during peak | T-change |
| 26–27 | `:2771`, `:2773` | fill-priority inert (bracket) | N |
| 28 | `:3944` | proactive hold cleanup | H |
| 29–30 | `:4534`, `:4536` | fill-priority inert (bracket) | N |
| 31 | `energy_tou.py:613` | `peak_ahead_before_offpeak` walk | N |
| 32–33 | `hvac_predict.py:2049`, `:2059` | anchor to next high-rate window | H |
| 34 | `sensor.py:9266` | next-boundary text (display) | H |
| 35 | `energy_billing.py:739` | displaced periods for peak-avoidance | H |

Totals: T 2, T-change 4, H 9, N 20. Not counted: `energy_tou.py:47` (validation set).

**`"off_peak"` literals (24 outside inclement; the 5 in inclement migrate in D-B4):** energy.py 8, energy_battery.py 5 (including the `tou_transition_into == "off_peak"` chunk reset in `determine_mode`), energy_pool.py 5, energy_tou.py 3, hvac_predict.py 1, sensor.py 2. **Excluded from this arc, stated:** each is an "is bottom rate" check that is byte-identical on every tariff URA knows, because every PEC season has an `off_peak` period that is also its lowest rate. Migrating them adds 24 sweep tests for zero decision change today. The Stage D pin covers `peak`/`mid_peak` only. **Revival trigger:** a second tariff is committed whose lowest-rate period is not named `off_peak`; then classify these 24 and extend the pin.

**Marginal-benefit note:** only the 2 T sites change a decision this arc needs. The 9 H sites are byte-identical on PEC (portability value only). The 20 N sites are correct as named. Stage D is separable and Tier 2.

---

## 9. Build staging and tiers

| Stage | Contents | Tier | Depends on | Builder |
|---|---|---|---|---|
| 0 | P1–P4 probes | none | none | ura-prober |
| L | D-L0, D-L1, D-L2 | **2-DB** (`database.py` prune change; new row producers and payloads) | P4 for D-L2 (D-L0/D-L1 need nothing) | ura-builder |
| A | D-A1–D-A4 | **3** (shared writer + floor + blind state machine + row payload) | governor live-validated (or waiver); Q2, Q6 | ura-super-builder |
| B | D-B1–D-B5 | **3** (classification feeds every hold) | P2, P3; Stage A; Q4, Q5, Q7 | ura-super-builder |
| C | D-C1–D-C3 | **3** (new async producer feeding the hold) | P1 GO; Stage B | ura-super-builder |
| D | §8 H migrations + pin; T-change by approval | **2** | Stage A; Q1 for T-change | ura-builder |

Ship order: L and 0 in parallel → A → B → C → D. L first because evidence accrues only from its ship date. A before B so the blind floor and top rate are live before matching widens the set of holds. Each Tier-3 stage gets four framing-disjoint reviews, orchestrator re-grep plus own mutation drills, and an operator checkpoint before deploy. Stage L's Tier 2-DB reviews: A = prune/retention and existing readers; B = row payload shape and hook placement across early returns; C = test authority (fixtures from production schema, mutation of the prune predicate).

**Mutation plan (Review C, real per-site edits; each must turn its named test RED):** remove the fold in `_reserve_action`; move the fold after the deadband; stamp the pre-fold value; restore a second desired stamp in `_result`; drop the `_tick_reserve_floor` entry-reset; route blind de-escalation around `_reserve_action`; stamp `_desired_stamped_at` in the blind branch; drop the release; arm release only in the hold rule; emit both hold and de-escalation; deadband against hardware when it is None; `is_top_rate` by name; `Type≠Alert` filter; substring match; Expires instead of Ends; aggregate `min` instead of `max`; clear memory on an empty feed; staleness from the alerts sensor's own `last_updated`; forecast latch removed; forecast confirming a warn demotion; the prune predicate removed; the ledger hook moved inside `determine_mode` after `:5787`; ledger dedup removed; witness `None` treated as a transition; `tick_floor` read after the task is scheduled.

---

## 10. Non-goals and parked items

**Non-goals:**
1. No change to the governor's gate or its `inclement_floor`/`floor_ok` fields; the only governor changes are the allowlist tuple and the additive `tick_floor`/`tick_hold_depth` row fields (D-A4). No change to overlay internals (including the append branch's lack of a deadband, stated in INV-2(b)), write-verify, `_resolve_hold_owner`, or `force_redispatch` (its ≤600 s blind window is stated in INV-2(c)).
2. No deletion of the 8 `_floor_reserve` wraps or the 2 inline off-peak clamps (KEEP+DOCUMENT).
3. No CFG writer under blind other than the existing turn_off. No pre-charge writer.
4. No `pending` tier and no pre-onset hold. No forecast-only tier.
5. No Enphase Storm Guard read.
6. No new options-flow fields, entities, tables or DDL. The one `database.py` change is the prune predicate (D-L0). No new EC role.
7. No arc steps 8–11, including the observation-mode bypass on the evaluate path (§12 known limit 14).
8. No migration of the 24 non-inclement `"off_peak"` literals (§8).

**Parked, with revival triggers:**
- *URA-side polygon matching.* Trigger: P2(b) NO **and** the operator rules Q7 = notice but wants SVW/TOW to hold when confirmed.
- *Pre-onset prepare floor.* Trigger: a ledger outage that began within N h of an alert's onset with SOC below the partial floor. (Q3.)
- *Severity/certainty or breadth modulation.* Trigger: a class of HOLD alerts with zero ledger outages and material hold cost.
- *Promoting Wind Advisory to hold.* Trigger: ≥1 ledger outage overlapping a WIY window.
- *Dedicated ledger table.* Trigger: ledger volume > 5,000 rows/yr.
- *Persisting the D-B3 memory across restart.* Trigger: a ledger case where a restart during an internet outage dropped a HOLD before its end.

---

## 11. Disposition of Rev-3 review findings (inherited, unchanged from Rev 1 except where noted)

| ID | Disposition |
|---|---|
| P1-01 | Fixed: §5 enumeration; INV-1 by construction at `_reserve_action`. |
| P1-02 | Fixed: de-escalation reserve folded (D-A3.1). |
| P1-03 | Fixed: INV-1 over hold_depth. |
| P1-04 | Resolved: forecast counts as corroboration (D-C2). |
| P1-05 | Fixed: payload from the integration source; `Type` = messageType. |
| P1-06 / P1-07 | Fixed: Expires→Ends supersession (D-B1); P2 supplies evidence. |
| P1-08 | Moot: no pending tier. |
| P1-09 | Fixed: §4. |
| P1-10 | Fixed: WPM owns the forecast. |
| P1-11 | Moot. |
| P1-12 | Fixed: no severity demote on the code path. |
| P1-13–15 | Fixed: §7; one-shot Live bullets; outage source is the ledger. |
| P2-01 | Fixed: 10-15 replay with WIY = notice. |
| P2-02 | Fixed: P1 sets thresholds. |
| P2-03 / P2-04 | Fixed: blind floor in `_full_hold_floor(None)`. |
| P2-05 | Fixed differently: shared `_reserve_action`, not `_result`. |
| P2-06 | Fixed: INV-2 keeps the turn_off. |
| P2-07 / P2-08 | Moot. |
| P2-09 / P2-10 | Fixed: D-C1 lifecycle. |
| P2-11 | Kept; fold makes it moot. |
| P2-12 | Fixed: partial exception unchanged. |
| P2-13 | Fixed: table rung 1; no options write. |
| P2-14 | Moot. |
| P2-15 / P2-16 | Fixed / noted. |
| P3-01 | Fixed: blind release, armed by any raising rule (Rev 2). |
| P3-02 | **Rev 2: superseded by decision, pending Q6.** The sweep side is fixed (blind never stamps `_desired_stamped_at`). The decision side's response to a manual lower is the operator's call; both behaviors are built behind `BLIND_RESPECT_MANUAL_LOWER` and tested by `test_blind_hold_manual_lower`. |
| P3-03 | Fixed: blind never calls `_result`. |
| P3-04 | Fixed: no `_result` CFG path under blind. |
| P3-05 | Fixed: D-B5. |
| P3-06 | Fixed: P3 probe, exact-name fallback, drift trip-wire. |
| P3-07 | **Rev 2: re-fixed.** Staleness = unavailable/unknown or timestamp-sensor age; memory unconditional (D-B3). |
| P3-08 | Fixed: only the None branch changes. |
| P3-09 | Fixed: §4. |
| P3-10 | Moot. |
| P3-11 | Fixed: honest scope. |
| P3-12 | Fixed. |
| P3-13 | Fixed: Stage A top rate. |

---

## 12. Config-extreme and edge cases (tests must cover)
1. `reserve_soc=80 > partial_floor=50`: floor 80; the fold never lowers.
2. `partial_floor=100`: partial hold pins 100; blind knob irrelevant.
3. Blind knob < partial floor (`partial=80, knob=60`): 80.
4. Sighted full hold with SOC 15 < `reserve_soc` 20: writes 15.
5. Floor > target (`peak_buffer_target=40`, floor 80): 80.
6. Blind steady hold with an EVSE hold of 45 and a blind floor of 60: the stamp is 60, so the overlay appends 60 each tick (pre-existing deadband-free re-send, INV-2(b)); never 45.
7. Blind entered with an arbitrage desire of 80 and a floor of 60: no write (never lowers). Hazard end: no release (never raised).
8. Restart during a blind raise: flags lost, no blind release; first sighted tick re-derives. **Known limit.**
9. Operator lowers the reserve during a blind hold: per Q6 / `BLIND_RESPECT_MANUAL_LOWER`. Escape under either answer: the EC enable switch.
10. Single-rate season or mid == peak: rank ties; no top hours in a single-rate season.
11. Engine missing: literal fallback, byte-identical.
12. Feed stale, unavailable or empty through a grid outage: memory holds known HOLD alerts to their ends; no new admissions.
13. **Envoy flaps split a blind episode.** A sighted tick resets the episode flags; the next blind episode's base is the floored stamp, so it can't release to the original pre-raise value. Sighted ticks in between re-derive the reserve normally, so this matters only if the flap pattern never yields a sighted allow_discharge tick. **Known limit.**
14. **Observation-mode widening.** Blind de-escalation now fires at every shoulder/winter top-rate edge, where the evaluate path runs `determine_mode` without the observation-mode gate (arc step 8). Two dispatches at one edge are possible (B-L1 double consume); the reserve leg of the second is suppressed by the `_reserve_action` deadband, and the CFG turn_off is idempotent. **Known limit**, fixed by arc step 8.
15. Restart during an internet outage loses the D-B3 memory; a WSW held only by memory drops. **Known limit** (parked trigger in §10).
16. First ≤600 s of a blind episode: a write-verify retry may re-send the floored desire once or twice (INV-2(c)). **Known limit.**
17. **Outage witness unproven (Rev 2.1, P4).** Whether `grid_enabled` / Enpower `grid_status` flip on a real islanding is unknown; they read `unavailable` 20.2 % of the time. The cloud calendar is the only evidenced witness, and it lags (sweep cadence). Settled by Stage L Live (e). **Known limit.**

---

## 13. Supersession (post-ship audit inputs)
- **DELETE (after Stage B validates):** `_event_matches_threat` (the substring gate).
- **KEEP+DOCUMENT:** the 8 `_floor_reserve` wraps and 2 inline off-peak clamps; `CONF_INCLEMENT_POWER_THREAT_EVENTS` / `_WARN_MIN_SEVERITY` constants; `_midpeak_rate_lt_peak`.
- **Should-be-consuming gaps to card at ship:** the strategy-sensor NM path could consume `nws_alert` rows for operator notification of HOLD alerts. Not in scope.

---

## 14. Open operator questions (7)

Each is answerable independently. The plan builds under either answer; the "switch" column names what changes.

| # | Question | Options | Recommendation | Switch / gates |
|---|---|---|---|---|
| Q1 | Approve migrating the 4 T-change sites (§8 #1, 16, 23, 25) to top rate? They change shoulder/winter behavior. | (A) approve each with its own acceptance; (B) keep named. | B for now; revisit per site. | Stage D scope only. |
| Q2 | Blind full-hold floor default `INCLEMENT_BLIND_FULL_HOLD_FLOOR_PCT`. | 60 / 100 (legacy pin) / other. | 60. | Rung-1 value; gates Stage A. |
| Q3 | Build the pre-onset prepare floor now, or keep it parked until the ledger shows a need? | (A) park; (B) build. | A (parked, trigger in §10). | None in this arc. |
| Q4 | Confirm the table's class changes: freeze/cold products added as HOLD; High Wind moves to NOTICE; Freeze Warning (not Hard Freeze) is NOTICE. | confirm / amend rows. | Confirm. | Table rows; gates Stage B. |
| Q5 | Confirm the Onset gating as a knowing safety trade: a warning issued ahead no longer holds until Onset (Stage B behavior change). | (A) accept; (B) keep holding from Sent until a pre-onset floor exists. | A (operator doctrine). B would need the parked Q3 work. | D-B1 `start` rule; gates Stage B. |
| Q6 | (P3-02) While fully blind, after the operator manually lowers the reserve below the floor, does the decision side re-assert the storm floor every tick, or respect the lower and stop writing for the episode? | (A) re-assert each tick (§12 case 9 as in Rev 1; sighted-path parity); (B) respect the manual lower, no re-dispatch for the episode. | **A.** The floor write is the doctrine's one named exception to v5.17.5, and a blind house can't see whether the storm passed. The 2026-07-15 lesson was about a stale desire re-dispatched by the sweep, which stays fixed under both answers. The escape is the EC enable switch. | `BLIND_RESPECT_MANUAL_LOWER`; gates Stage A. |
| Q7 | (D-B1 vs principle 1) If P2(b) shows `?point=` is not polygon-exact, do SVR/TOR/EWW stay at table tier (HOLD) or drop to notice? | (A) stay HOLD: an alert the point query returns is treated as local; locality checks only confirm; (B) notice until a URA-side polygon check exists. | **A.** It keeps principle 1 and today's behavior (SVR/TOR hold now). B removes protection on the highest-consequence product to save some false SVR holds (~4× fewer). The parked polygon matcher can recover precision later. | `INCLEMENT_UNVERIFIED_POLYGON_TIER`; gates Stage B. |

---

## 15. Changelog

| Rev | Date | Change |
|---|---|---|
| 1 | 2026-10-16 | Initial integrated plan (5709c31a7). |
| 2 | 2026-10-16 | Folded plan reviews 1 (completeness) and 2 (build-prediction). Disposition per finding below. |
| 2.1 | 2026-10-16 | Folded Stage 0 probes (`AUDIT_ec_storm_stage0_probes.md` + P1 addendum): D-B2 codes `SVW`/`TOW` (not SVR/TOR), only verified codes coded, 18 products name-only, drift trip-wire note; `NWS_ALERTS_STALE_S` 900 with the > 310 s bound; D-L2 witness redesigned (cloud calendar primary with substring match, local sensors corroboration only, `iq_gateway_hacs_grid_mode` rejected, known limit 17, Live (e) settlement); Stage C GO on `weather.phalanxmadrone`, precip threshold deferred to the Stage C plan from history; P2(a) recorded as a classification miss, not feed loss. Operator questions unchanged. |

**Rev 2 disposition map** (R1 = review 1, R2 = review 2; every fix re-checked against the cited code).

| ID | Sev | Disposition |
|---|---|---|
| R2-C1 | CRIT | Fixed: D-L0 prune exemption (`database.py:6269-6282` verified: info 7 d, others 30 d); Stage L is Tier 2-DB with a stated no-DDL schema plan; INV-5 retention clause; tests + Live (c). |
| R1-H1 | HIGH | Fixed via the reviewer's option (b): INV-2(b) states the overlay append re-send (`energy.py:5463-5528`, no deadband, verified) as pre-existing; value ≥ floor through the folded stamp; Live (b) allows the `+ EVSE hold` suffix (`energy.py:5332`); edge case 6 corrected; `test_blind_hold_with_standing_evse_hold`. Option (a) rejected (would change overlay internals, Non-goal 1). |
| R1-H2 | HIGH | Fixed: golden criterion = 7 sighted cases unchanged + an explicit expected-diff list for `blind`; anything else stops the build. |
| R1-H3 | HIGH | Escalated to operator as Q7; built behind `INCLEMENT_UNVERIFIED_POLYGON_TIER`; INV-3 and the polygon test parametrized; recommendation keeps principle 1. |
| R1-H4 | HIGH | Fixed with R2-H3's refinement: stale = unavailable/unknown or timestamp-sensor `last_changed` age. R1's suggestion to use the alerts sensor's own `State.last_updated` rejected: it doesn't advance on a steady alert (R2-H3). P2(d)/(e) added. |
| R1-H5 | HIGH | Fixed: no EC role; registry lookup at sweep time (verified pin idempotent on `EC_DEFAULTS_PINNED_FLAG`, `__init__.py:788, 847`); unresolved = skip + one warning; test added. |
| R1-H6 | HIGH | Escalated to operator as Q6; P3-02 re-dispositioned in §11; built behind `BLIND_RESPECT_MANUAL_LOWER`; `test_blind_hold_manual_lower` parametrized. |
| R2-H1 | HIGH | Fixed: `_reserve_action -> (folded_target, action)`, sole writer of `_last_reserve_level_desired`, stamps before the deadband (current stamp at `energy_battery.py:6532-6534` verified to use the raw argument); overlay repro in INV-1; tests + two mutation items. |
| R2-H2 | HIGH | Fixed: ledger hook pinned in `energy.py` after `determine_mode`, beside `_track_envoy_availability` (`:7117` verified), raw feed read, fire-and-forget; two tests. |
| R2-H3 | HIGH | Fixed: D-B3 rewritten (stale definition, unconditional ID-keyed memory, empty-feed rule, clear rules, end-time rule, max across alerts); three named tests plus two more. |
| R2-H4 | HIGH | Fixed: INV-1 repro replaced with the reachable corroborated top-rate case; uncorroborated case listed as correct (writes 20). |
| R2-H5 | HIGH | Fixed: release armed by any raising blind write; de-escalation at/below pre-raise clears; INV-2(d) drops the flag condition; test + mutation item. |
| R1-M1 | MED | Fixed as stated known limit: INV-2(c), §12 case 16 (I-D3 gate `> 600` at `energy_battery.py:6766` verified). Stamp invalidation rejected (changes I-D3 semantics, Non-goal 1). |
| R1-M2 | MED | Fixed by R2-H1. |
| R1-M3 | MED | Fixed: base None → write F, pre-raise None → release to `reserve_soc`; test. |
| R1-M4 | MED | Fixed by R2-H2 (hook independent of the blind gate) + `decision_age_s` in rows. |
| R1-M5 | MED | Fixed as stated exclusion with count, reason and revival trigger (§8, Non-goal 8). Classification of the 24 rejected as zero-value work this arc. |
| R1-M6 | MED | Fixed: Stage A depends on governor live validation or a recorded waiver. |
| R1-M7 | MED | Fixed as named known limit (§5, §12 case 14) with the deadband mitigation. Re-sequencing arc step 8 ahead of Stage A not adopted (adds scope; Non-goal 7). |
| R1-M8 | MED | Fixed: D-A4 additive `tick_floor` / `tick_hold_depth` row fields; INV-1 falsifier and Live (c) use them. |
| R1-M9 | MED | Fixed: §4 consumer table completed (`sensor.py:9376-9385` verified, it is `sensor.ura_inclement_state`; ladder validator `energy.py:10441`; `_resolve_hold_owner`; attain helpers; `:1933` citation replaced by `:1659/:1730/:1935`). |
| R2-M1 | MED | Fixed: aggregate = max(end) over HOLD contributors, justified; both consumers named; test. |
| R2-M2 | MED | Fixed: base None rule + deadband against the stamp when hardware is unreadable; test. |
| R2-M3 | MED | Fixed: three blind reason prefixes; Live (b) rewritten per episode; (b)/(c) read "not observed" without an episode. |
| R2-M4 | MED | Fixed: boot = unknown baseline, `opened_at_boot`, `episode_id=null` close; P4(i) discriminating switch check. |
| R2-M5 | MED | Fixed: stated behavior change, acceptance line, test, operator checkpoint (Q5). |
| R2-M6 | MED | Fixed: memory keyed on message ID; Cancel clears by event name + overlapping window; `inclement_memory_cleared` row (and retained by D-L0). |
| R2-M7 | MED | Fixed: per-alert-ID forecast latch to `end`; test + mutation item. |
| R1-L1 | LOW | Fixed: inline off-peak clamps added to §0, §1a, §5, §13. |
| R1-L2 | LOW | Fixed: `FORECAST_WINTER_STORM_CONFIRM_F`, `OUTAGE_SWEEP_INITIAL_DELAY_S`. |
| R1-L3 | LOW | Fixed: Live (b)/(c) bounded by `ts > <Stage A restart>`. |
| R1-L4 | LOW | Fixed: correlation dedups on `(NWSCode or Event, Onset)`. |
| R1-L5 | LOW | Fixed: last-non-None transition rule; boot rule. |
| R1-L6 | LOW | Fixed: verifier-present precondition on Stage A Live; witness inert + debug when absent. |
| R1-L7 | LOW | Fixed: §0 adds the arc row 1 correction. |
| R1-L8 | LOW | Fixed: §5 reviewer-D hand-read instruction with the expected literal set. |
| R2-L1 | LOW | Fixed: floor assignment in `determine_mode` at the two call sites, not in `_inclement_decision`. |
| R2-L2 | LOW | Fixed: tz-aware sweep incl. DST and season-boundary days. |
| R2-L3 | LOW | Fixed: §12 known limit 13. |
| R2-L4 | LOW | Fixed: seen-set pruned of IDs that leave the feed; test. |

**Counts:** CRITICAL 1/1 fixed. HIGH 11: 9 fixed, 2 escalated to the operator (Q6, Q7) and built behind a switch. MEDIUM 16: 13 fixed in design (R1-M2 via R2-H1), 3 fixed as stated known limits or exclusions (R1-M1, R1-M5, R1-M7). LOW 12/12 fixed. Rejected sub-options: R1-H1(a), R1-H4's `State.last_updated` source, R1-M1 stamp invalidation, R1-M5 classification of 24 sites, R1-M7 re-sequencing.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018uEjYPUcWq73wfBS3t1NEa
