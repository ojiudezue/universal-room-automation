# PLANNING: EC storm and blind decisions (arc steps 2–7, one integrated plan)

**Arc:** `docs/planning/ARC_energy_coordinator_resilience.md` steps 2–7. Its planning rule applies: one decision model, written once, built in stages.
**Cards:** EC-INCLEMENT-HARDENING-1 (D-blind, D-match, D-ends, outage ledger, D-forecast), EC-BLIND-DEESCALATE-TOP-RATE-1.
**Supersedes:** `PLANNING_inclement_hardening.md` Rev 3. Every finding from its three plan reviews is dispositioned in §11.
**Built on:** the reserve write governor shipped in v5.103.66 (`PLANNING_reserve_write_governor.md` Rev 3.2, `README_v5.103.66.md`).
**Tier:** 3 overall. Per-stage tiers are in §9.
**Status:** draft for plan review (Tier 3, so two framing-disjoint plan reviews before any build dispatch).

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

The inclement floor is still applied by 8 per-branch `_floor_reserve` wraps (`energy_battery.py:3855`, callers `:3926/3949/3991/4715/4769/5004/5952/6098`, narration `:6687`). Full-hold emits use `decision.reserve_floor` directly. The blind de-escalation writes `reserve_soc` with no floor (`:5650-5660`).

So "register the floor with the governor" has nothing to register with yet. **D-A2 builds that registration as the governor's missing piece, not as parallel machinery:** one per-tick floor, folded at the one decision-side reserve writer, which the governor's lint pins. The README line should be corrected in the Stage A ship commit.

---

## 1. Institutional context verified (prior-art scan by function)

### 1a. REUSE / EXTEND / BUILD per function

| Function in the decision model | Prior art (file:line) | Verdict |
|---|---|---|
| Alert source | `nws_alerts` integration, configured `gps_loc 30.314635,-98.015861`, interval 1 min. It queries `api.weather.gov/alerts/active?point=` (`ha-config/custom_components/nws_alerts/coordinator.py:135`). Payload keys come from `:160-180`. **`Type` = CAP `messageType` (Alert / Update / Cancel), `:166`.** | **REUSE.** Rev 3's "drop Type != Alert" would have dropped every Update message. Corrected in D-B2. |
| Locality | The point query above is already the feed's locality filter. Zone products (winter, freeze, wind) can't get finer than zone TXZ192 (`AUDIT_nws_alert_history_lakeway.md` addendum). | **REUSE, probe-gated (P2).** Whether `?point=` is polygon-exact for SVR/TOR is unverified. URA-side point-in-polygon is built only if P2 shows it is not. |
| Classification | `inclement.py:152-266 AlertClassifier.classify` (substring gate `:141-149`, certainty fold, severity demote) | **EXTEND.** Exact code/name table replaces the substring list. Severity/certainty move to attrs only. Tier vocabulary is unchanged. |
| Hazard window | `inclement.py:129-138 _alert_expires_at = min(Ends, Expires)`, drop at `:211-214` | **EXTEND** to `(Onset, Ends)`, plus a probe-gated memory past Expires (D-B3). |
| Hold depth | `inclement.py InclementFusion.decide` (`:560-720`), `_full_hold_floor :724`, `_partial_floor_value :733`, `compute_solar_horizon` | **REUSE unchanged**, except: the blind SOC-None floor (D-A3); bottom-rate input replaces the literal `off_peak` (D-B4); forecast counts as corroboration (D-C2). |
| Decision cache / signal / attrs | `energy_battery.py:2663 _inclement_decision` (per-tick cache), `:2732 _cache_inclement`, `:2764 _inclement_attrs`. `SIGNAL_INCLEMENT_STATE_CHANGED` (`signals.py:120`) has **no listeners** (grep). | **REUSE.** |
| Floor enforcement | 8 `_floor_reserve` wraps; full_hold emits use `decision.reserve_floor` | **KEEP** as defense in depth. The new fold (D-A2) makes them redundant by construction, and they are not deleted in this arc (KEEP+DOCUMENT). |
| Decision-side reserve writer | `_result` reserve block `energy_battery.py:~6350-6395` (target resolve, clamp, stand-down skip, ≥2 deadband); blind de-escalation dict `:5650-5660` | **EXTRACT** into one helper `_reserve_action` (D-A2). Both call it. |
| Writer lint + rows | `energy_const.py:2307 RESERVE_SET_VALUE_WRITERS`; `quality/tests/test_reserve_write_chokepoint_lint.py`; rows C1/C2/C3 | **REUSE.** The allowlist changes from `_result:1 + determine_mode:1` to `_reserve_action:1`. Rows log blind writes through C1 unchanged. |
| Write-verify under blind | `_desired_stamped_at` stamp `energy_battery.py:6559`; sweep stand-down `energy_write_verify.py:880-905`; I-D3 in `force_redispatch :6721-6769` | **REUSE unchanged.** Blind never stamps `_desired_stamped_at`, so I-D3 holds (P3-02). |
| Blind SOC freshness | `_precharge_refused_on_blind :4106` (fully blind refuses precharge) | **REUSE.** |
| Top-rate | `energy_tou.py TOURateEngine`: `get_season :449`, `get_current_period :459`, `get_current_rate :472`; rates in `ha-config/universal_room_automation/tou_rates.json` (PEC: summer off/mid/peak; shoulder and winter off/mid only). Closest existing rate-aware helper: `energy_battery.py:4501 _midpeak_rate_lt_peak` (reads `_rates` directly). | **BUILD** `rate_rank` / `is_top_rate` / `is_bottom_rate` in the engine (D-A1). `_midpeak_rate_lt_peak` stays: it answers a different question, "is mid cheaper than peak". |
| Outage witness | `energy_write_verify.py:1821 _grid_outage_active` (tri-state read of `grid_enabled` = `switch.enpower_482348004678_grid_enabled`, local Envoy). `grid_connected` (`energy_battery.py:2210`) **defaults True when unavailable**, so it can't serve as a witness. | **REUSE `_grid_outage_active`** (tri-state). |
| Outage ground truth | Enphase cloud calendar `calendar.main_panel_wall_enphase_cloud_hacs_system_event_history` (`AUDIT_outage_alert_correlation.md` method). No URA reference today (grep `system_event_history` gives 0 hits). | **BUILD** a daily read-only sweep (D-L2), probe-gated (P4). |
| Durable rows | `database.py:6233 log_activity` (single-writer queue, `:523-541`) | **REUSE.** No schema, no table. |
| Hourly forecast | `weather_manager.py:366 _fetch_provider_forecast` is daily only (`type: "daily"`, `:376`). Grep for `hourly` in URA gives 0 hits. Providers: `weather.phalanxmadrone`, `weather.madroneweather_tracker_dynamic_weather_madroneweather_tracker`, `weather.madronehaos` (live CM options). | **EXTEND `WeatherProviderManager`** (owner, lifecycle `:188-221`, `_unsub_handles`, `_pending_refresh_tasks`, WPM-C1 lock). Probe-gated (P1). |
| Condition corroboration | `weather_manager.py:785 current_storm_condition` | **REUSE unchanged.** |
| Legacy threat list | `CONF_INCLEMENT_POWER_THREAT_EVENTS`; live value equals the shipped default (read from `.storage/core.config_entries`, 2026-10-16) | **RETIRE** (KEEP+DOCUMENT the constant; remove from the options UI). No options write at setup. |

### 1b. Greps run (summary; all on worktree HEAD de5217ae5)
- `grep -n "_floor_reserve\|def _result" energy_battery.py`: 8 callers + def `:3855` + narration `:6687`. **No floor inside `_result`.**
- Period-name literals (`== "peak"`, `== "mid_peak"`, `in ("peak","mid_peak")`): 35 sites, classified in §8.
- `grep -rn "hourly"` (forecast context): 0. `grep -rn "system_event_history\|calendar.get_events"`: 0.
- `grep -rn "SIGNAL_INCLEMENT_STATE_CHANGED"`: defined `signals.py:120`, sent `energy_battery.py:~2745`, **no subscriber**.
- `grep -rn "_last_inclement_decision"` outside energy_battery: `energy_write_verify.py:1659, 1755, 1933`; `energy.py:9153` (governor row).
- Every reserve-bearing `self._result(` call is reached from `determine_mode` **after** `_inclement_decision` (`:5787`). The only earlier `_result` is grid-disconnect `:5776`, which passes no `reserve_level`. Helper callers: `:5919, :6065, :6129, :6146`. `determine_mode` is synchronous, so nothing can interleave inside a tick.

### 1c. Docs and memory read
- In full: arc doc, `README_v5.103.66.md`, `PLANNING_reserve_write_governor.md` (incl. Known limits), `PLANNING_inclement_hardening.md` Rev 3, plan reviews 1/2/3, both audits, `audit_reserve_surface_ground_truth.md`, cards EC-INCLEMENT-HARDENING-1 and EC-BLIND-DEESCALATE-TOP-RATE-1.
- Skimmed: `PLANNING_inclement_weather_reserve.md` (v5.5.0 prior art: invariants, matrix D-A..D-O, Expires L-criterion `:326`); `README_v5.5.0.md`.
- HVAC / presence state-of-play docs: not applicable (energy-only cycle; no HVAC or presence surface touched).

---

## 2. The decision model (the one design every stage implements)

```
NWS feed (point query, 1-min poll)
  │  D-B1 filter: Status=Actual, Type≠Cancel, Onset ≤ now ≤ Ends   (pre-onset ⇒ not active)
  │  D-B2 product table: code (or exact event name) → class {HOLD-warn, HOLD-watch, NOTICE}
  │  D-B1 locality: polygon products need point-local confirmation (P2)
  ▼
AlertClassification (tier none|notice|watch|warn)  ──►  D-L1 alert ledger row (first sighting per alert ID)
  │
  │  + condition corroboration (existing)  + D-C forecast corroboration over [now, Ends] (P1-gated)
  ▼
InclementFusion.decide (v5.5.0 ladder, rate band from D-A1)  ──►  InclementDecision.hold_depth / reserve_floor
  │
  ▼  D-A2 register: self._tick_reserve_floor = decision.reserve_floor  if hold_depth ∈ {partial, full} else None
  │
  ├── sighted: existing branches → _result → _reserve_action (fold) → dispatch → governor row C1/C2
  └── fully blind (envoy down AND SOC None on all tiers): D-A3 blind rules → _reserve_action (fold) → C1
                         │
  grid witness + Enphase cloud calendar ──► D-L2 grid_outage row (episode + inclement decision at onset)
```

**Two design principles that hold across all stages:**
1. **Raise-only asymmetry.** Forecast and locality can *add* corroboration or *confirm* applicability. They never demote a HOLD-warn product. A false hold costs one day of arbitrage. A missed freeze outage costs far more. That is why forecast can't demote a Winter Storm Warning even when our point forecast reads 35 °F.
2. **One floor, one writer.** The current tick's floor is registered once, and the one decision-side writer folds it. Blind and sighted paths share that writer. The overlay (`_apply_evse_battery_hold`) stays max-only and allowlisted.

---

## 3. Falsifiable invariants

> **INV-1 (floor by construction).** In any `determine_mode` call whose current-tick decision has `hold_depth ∈ {partial_hold, full_hold}`, every reserve value the decision side emits (every `_reserve_action` output: sighted, blind hold, blind release, blind de-escalation) is `≥ decision.reserve_floor`. The EVSE/DP overlay can only raise it. **Falsifier:** a `reserve_write` row with `path ∈ {timer, evaluate}` whose `value` < the floor registered in that tick. **Legal-config repro to test:** `reserve_soc=20, partial_floor=50`, fully blind, top-rate de-escalation with CFG on, uncorroborated off-peak watch (today this writes 20 at `:5658`; after the change it writes 50).

> **INV-2 (blind command surface).** While fully blind, the decision emits only (a) at most **one** reserve `number.set_value` via `_reserve_action` and (b) the pre-existing top-rate de-escalation `switch.turn_off`. It never emits CFG turn_on, storage-mode select, or a `_desired_stamped_at` refresh. If the blind episode raised the reserve, the first blind tick whose decision is `allow_discharge` restores the pre-raise value. **Falsifiers:** a blind tick with two reserve actions, or any CFG turn_on, or a select action; a stamped `_desired_stamped_at` during blind; the reserve still at a URA-raised floor after the hazard ends while blind, with the episode flag set.

> **INV-3 (classification).** For an alert with `Status=Actual`, `Type≠Cancel`, a product-table class of HOLD, locality confirmed, and `Onset ≤ now ≤ end`: the tier is ≥ the table tier. An alert with `now < Onset` contributes nothing. `WIY` (Wind Advisory) is never above `notice` in any reachable path, so it never produces a hold. **Falsifier:** a WIY alert yielding `hold_depth ≠ allow_discharge`; a Hard Freeze Warning inside its window yielding tier < warn.

> **INV-4 (top rate).** `TOURateEngine.is_top_rate(now)` is True iff the import rate of the active period equals the season's maximum distinct import rate **and** the season has ≥2 distinct rates. Blind de-escalation keys on it, so it fires in shoulder/winter `mid_peak` 17–21. **Falsifier:** October 18:00, fully blind, CFG on, no de-escalation.

> **INV-5 (ledger completeness).** Each local witness on→off transition opens exactly one `grid_outage` episode. Each off-grid event in the cloud calendar inside the sweep lookback appears in the ledger exactly once (deduplicated against witness rows). Each alert ID seen in the feed has exactly one `nws_alert` row per boot. **Falsifier:** an off-grid calendar event with no row after a sweep; two rows for one episode.

---

## 4. Producer and consumer checks

| Value | Producer (arithmetic + dependency health) | Consumers (file:line, trust vs display) |
|---|---|---|
| `InclementDecision` | Classifier + fusion. Dependencies: NWS sensor (healthy: 1-min poll, but nothing checks staleness today, which is P3-07; D-B3 adds a bound); weather providers (3 configured; health per `_check_provider_health`); Solcast via `_expected_solar_surplus_pct`; SOC (3-tier resolver, None when fully blind). Under blind, `compute_solar_horizon` coerces SOC None to 0, so permitted discharge = 0 and a top-rate corroborated watch is always "recoverable", giving partial_hold (P3-09). **Intended:** a blind partial hold is the conservative outcome. | `determine_mode` precedence (trust); `_inclement_attrs` (display); `energy_write_verify.py:1659` partial-floor exception (trust); `:1755`, `:1933` (trust); governor row `energy.py:9153` (display/audit); signal (no listener). |
| `inclement_expires_at` / hazard end | `max-known end` per D-B1. **Behavior change:** later ends lengthen `compute_solar_horizon`'s window (`inclement.py:384-391`), which can flip partial↔full at top rate. Listed so reviewers check it. | horizon (trust), attrs (display), signal payload. |
| `_tick_reserve_floor` (new) | `decision.reserve_floor` when holding, else None. Entry-reset at the top of `determine_mode`. Partial: `max(reserve_soc, partial_floor)`. Full, sighted: `int(soc)`, which can be below `reserve_soc` (fold must not raise it to `reserve_soc`; config-extreme test). Full, blind: `max(reserve_soc, partial_floor, INCLEMENT_BLIND_FULL_HOLD_FLOOR_PCT)`. | `_reserve_action` fold (trust). The governor row keeps computing its own partial-only `inclement_floor`; it is unchanged (non-goal). |
| `rate_rank` / `is_top_rate` / `is_bottom_rate` | Distinct import rates of `get_season(now)`, ranked ascending; period from `get_current_period(now)`. Dependency: tariff JSON validated at load (`_validate_parsed_data :141`). Engine absent means callers fall back to the legacy literal (byte-safe). | Stage A: blind de-escalation (trust). Stage B: fusion bottom-rate (trust). Stage D: the 9 "high-rate" sites (§8). New attr `tou_top_rate` (display). |
| Grid outage episode | `_grid_outage_active` tri-state (`True` off-grid / `False` / `None` unknown) sampled per decision tick, plus the cloud-calendar sweep. Local witness health: the Envoy flaps 220–324 times a day (memory), so `None` is common. That is why the sweep exists. | Ledger rows only (audit). No decision consumer, by design. |
| Forecast outlook (Stage C) | Hourly `weather.get_forecasts` per healthy provider; aggregated over `[now, hazard end]`: min temp, max precip-probability, max gust (if present), storm-condition hours. Health: fetched_at ≤ staleness; P1 decides which fields exist. | Fusion corroboration (trust); attr `inclement_forecast` (display). |

---

## 5. Emission and decision-site enumeration (re-run by plan review D)

**Reserve writers** (package-wide; the lint pins them). Today: `_result:1`, `determine_mode:1` (blind de-escalation), `force_redispatch:2`, `_apply_evse_battery_hold:1`, readers `_tap_write_verifier:1` and `_evaluate_battery:1`, non-reserve pool/EVSE/radar. **After Stage A:** `_reserve_action:1` replaces `_result:1 + determine_mode:1`. Everything else is unchanged.

**Floor-relevant reserve emissions** (all reach `_reserve_action` after Stage A): the 19 `self._result(` calls in `energy_battery.py` (`:3933, 3956, 3997, 4720, 4774, 5013, 5776 (no reserve), 5816, 5836, 5852, 5863, 5879, 5886, 5955, 5975, 5990, 6107, 6238, 6265`), the blind hold/release (new), the blind de-escalation (`:5650-5660`), the overlay (max-only, energy.py `:5248`, called `:6468`, `:7183`), the DP fold (inside the overlay), and `force_redispatch` (re-sends `_last_reserve_level_desired`, which is already folded; gated off under blind by I-D3).

**Top-rate decision sites:** §8 (35 sites).

**Alert-consuming sites:** `classify` (`inclement.py:169`) only. The NWS sensor has no other URA reader (grep `nws_alerts`: `_read_nws_alerts :2640` only).

---

## 6. Deliverables

### Stage 0: probes (read-only; `ura-prober`; no build until each gate reads GO)

**P1: forecast provider probe (gates Stage C).** For each of the 3 configured providers (plus `weather.nws_*` if present), call `weather.get_forecasts type=hourly`. Record per provider: fields present (`temperature`, `precipitation_probability`, `wind_gust_speed`, `wind_speed`, `condition`), horizon length, update cadence, and health over 24 h. *Note:* Rev 3's "no gust" evidence came from `weather.nws_30_314635_98_015861_kryw`, which is not one of the configured providers, so it does not count.
- **GO** if ≥1 healthy provider carries hourly `temperature` + `precipitation_probability` for ≥48 h. Temperature alone is enough for the freeze products. **NO-GO** parks Stage C with this report as the evidence.

**P2: NWS feed semantics (gates D-B1 locality and D-B3 memory).**
- (a) From recorder history of `sensor.nws_alerts_gps_…_alerts` for 2026-10-16 03:00–05:00 (the 10-15 WIY, Onset=Expires=04:00, Ends=19:00): did the alert leave the feed at Expires? Did an `Update` arrive, and when? Was the feed ever without it inside `[Onset, Ends]`?
- (b) Is `?point=` polygon-exact for SVR/TOR? Answer from the api.weather.gov OpenAPI/docs (cite), cross-checked if any SVR polygon is live during the probe.
- (c) For watches (WSA, SVA, TOA), is `onset` the hazard start or the issue time (IEM VTEC begin vs issue for past TXZ192 watches)?
- (d) Does the sensor carry `last_updated`?
- **Gates:** (a) decides whether D-B3 memory is built; (b) decides whether URA-side polygon matching is built (default: not built); (c) is recorded in the product table notes.

**P3: product codes (gates the D-B2 table).** For each table row, verify the `NWSCode` (`eventCode.NationalWeatherService`) from api.weather.gov alert history for TXZ192/TXC453 or an authoritative NWS code list (cite). **Any code that can't be verified ships as exact-name match only for that row** (no guessed codes; P3-06).

**P4: outage witness probe (gates D-L2).** Check `switch.enpower_…_grid_enabled` state and availability ratio over the recorder window. Check that `calendar.get_events` on the Enphase calendar for a 48 h window returns within 30 s. Record the exact summaries of off-grid, on-grid and generator events. The sweep is built only if the call returns reliably.

### Stage L: outage ledger (arc step 5) — ships first; every week of delay is lost evidence (Enphase keeps ~7 weeks)

**D-L1 `nws_alert` rows.** On each decision tick, for every alert ID in the feed not yet logged this boot, write one `ura_activity_log` row (`coordinator="energy"`, `action="nws_alert"`). `details_json`: `Event, NWSCode, Type, Status, Severity, Certainty, Sent, Onset, Expires, Ends, AreasAffected`, the `ura_class` and `ura_tier` this build assigns, and `local` (true/false/unknown). The seen-set is RAM-only, so a restart re-logs active alerts once; analysis dedups by ID.
**D-L2 `grid_outage` rows.** (i) Witness: on a `_grid_outage_active` transition False→True, open an episode row; on True→False, write a close row (episode id, duration). The open row embeds the current inclement decision (tier, hold_depth, reserve_floor), the active alert IDs, SOC (or None), and `witness="local"`. `None` readings neither open nor close an episode. (ii) Sweep (P4-gated): once per `OUTAGE_SWEEP_INTERVAL_H`, plus once 5 min after setup, read the last `OUTAGE_SWEEP_LOOKBACK_H` of the cloud calendar. Write `witness="cloud"` rows for off-grid events with no local row within `OUTAGE_DEDUP_TOLERANCE_MIN`. Record generator events in the same window as `generator_events: [...]`, tagged but not excluded. The sweep runs through the tracked-task pattern, under a timeout, and is cancelled on unload. Calendar entity: new EC role `grid_event_calendar`, defaulted in `EC_ROLE_KEY_DEFAULTS`, with no UI field.
**Correlation** is a SQL join (alerts whose `[Onset, Ends]` overlaps an outage). No code computes it.

**Acceptance**
- **Verify:** one `nws_alert` row per distinct alert ID per boot; a second tick logs nothing.
- **Verify:** witness sequence False, True, True, None, False gives exactly one open and one close; `None` never opens or closes.
- **Verify:** a cloud event 3 min from a local open is deduplicated; a cloud event with no local row gives one `witness=cloud` row.
- **Verify:** the sweep raising or timing out writes no row, logs debug, and leaves the decision path untouched.
- **Test:** `test_alert_ledger_one_row_per_id`, `test_outage_witness_episode_open_close`, `test_outage_witness_none_is_not_a_transition`, `test_outage_sweep_dedups_local`, `test_outage_sweep_failure_isolated`, `test_outage_sweep_task_cancelled_on_unload`.
- **Live:** (a) after restart, the `nws_alert` row count for this boot equals the sensor's state (active alert count; 0 means 0 rows). A broken writer shows fewer rows; a missing dedup shows a multiple. (b) the first sweep logs `outage sweep: parsed N events, M off-grid` with **N > 0**. The calendar carries ~35 nightly "Gateway rebooted" events per 7 weeks, so N=0 means parsing failed, not that the house had no outages. (c) 0 ERRORs mentioning `nws_alert` / `grid_outage`.

### Stage A: top rate + one floor + blind decisions (arc steps 2 and 7-core)

**D-A1 top-rate primitive** (`energy_tou.py`). Add `rate_rank(now) -> int`, `is_top_rate(now) -> bool`, `is_bottom_rate(now) -> bool`, and `period_rank(season, period) -> int`. Ties share a rank. A single-rate season means every hour is bottom and none is top. Add a strategy-sensor attribute `tou_top_rate` (REUSE `sensor.py` battery strategy attrs; no new entity).
**D-A2 one decision-side writer and registered floor** (`energy_battery.py`).
- Extract `_result`'s reserve block into `_reserve_action(reserve_level) -> dict | None`. It keeps the write-leg target resolve, the 0–100 clamp, the stand-down skip and the ≥2 deadband. It then **folds** `target = max(target, self._tick_reserve_floor)` when that is not None, applying the fold **before** the clamp, the stand-down check and the deadband (clamp-before-stamp).
- `_result` calls it. `_tick_reserve_floor` is entry-reset to None at the top of `determine_mode` (next to the existing ENTRY-RESETs, `:5480-5495`) and set immediately after each `_inclement_decision` call (sighted `:5787`, blind D-A3).
- `RESERVE_SET_VALUE_WRITERS`: replace the `_result` and `determine_mode` rows with `("energy_battery.py", "_reserve_action", "reserve", 1)`.
- `_last_reserve_level_desired` keeps being stamped by `_result` from the post-fold value.
**D-A3 blind decisions.** Move `decision = self._inclement_decision(tou_period, now)` above the fully-blind gate (safe: per-tick cache `:2668`). Register the floor. Inside the blind branch, emit **at most one** reserve action, by this precedence:
1. **De-escalation** (if `is_top_rate(now)` or `tou_transition_into` maps to top rank, CFG on, and not a full_hold; the existing exemption is kept, its freshness check reduces to the current-tick decision): `turn_off` (unchanged) + `_reserve_action(reserve_soc)`, folded, so INV-1 holds (P1-02 fixed).
2. **Hold** (`hold_depth ≠ allow_discharge`): `base = _last_reserve_level_desired` (or the write-leg state when None); emit `_reserve_action(max(F, base))`. This never lowers a held value (the v5.17.5 "hold current" semantics plus the floor). On the first raise this episode, capture `_blind_pre_raise = base` and set `_blind_raised = True`.
3. **Release** (`allow_discharge` and `_blind_raised`): `_reserve_action(_blind_pre_raise)`; clear the flag (P3-01).

The blind branch stamps `_last_reserve_level_desired` to the target it computed (overlay base coherence; see edge case 6). It **never** stamps `_desired_stamped_at` (I-D3 kept, P3-02) and never calls `_result` (so `envoy_available=False` and the blind dict keys are kept, P3-03, and there is no CFG double-emit, P3-04). Episode flags are RAM-only and reset when the gate is not engaged. `_full_hold_floor(None)` becomes `max(reserve_soc, partial_floor, INCLEMENT_BLIND_FULL_HOLD_FLOOR_PCT)`. **Only the None branch changes**; the sighted branch keeps `int(soc)` (P3-08).

**Honest scope (P3-11):** this only helps the *fully* blind case (Envoy down and no LKG/cloud SOC). With LKG/cloud SOC, the existing relaxed gate already runs the decision. On 10-15 the hold also failed because WIY didn't match, which Stage B fixes (by making WIY *notice*, deliberately).

**Acceptance**
- **Verify (INV-4):** for every hour of a year under the committed PEC tariff, `is_top_rate` equals {summer 16–20, shoulder 17–21, winter 05–09 and 17–21}; `is_bottom_rate` equals the hours where `get_current_period == "off_peak"`. A tariff with mid == peak gives both rank 1. A single-rate season gives no top hours.
- **Verify (byte-identical):** the governor A/B golden (`quality/tests/fixtures/reserve_governor_golden.json`) is **unchanged** with Stage A applied. Every `_result` site under partial_hold and full_hold emits the same value with the fold patched to a no-op. **If any sighted case differs, stop:** that is a pre-existing floor leak (the D-HIGH-1 class) and must be reported, not absorbed.
- **Verify (INV-1 repro):** `reserve_soc=20, partial_floor=50`, fully blind, October 18:00, CFG on, uncorroborated watch in shoulder mid_peak gives allow_discharge, so the decision has no floor and de-escalation writes 20. The same at 03:00 (off-peak, partial hold, floor 50) gives a hold write of 50. A partial-hold variant at top rate (corroborated, recoverable) gives de-escalation folded to 50.
- **Verify (INV-2):** steady blind hold gives zero reserve actions after the first. Hazard end while blind gives one release to `_blind_pre_raise`, then none. Blind + allow_discharge with no prior raise and a pre-blind arbitrage desire of 80 gives no reserve action (v5.17.5 kept). A blind tick never emits a select action or CFG turn_on, and `_desired_stamped_at` is unchanged across blind ticks.
- **Verify:** fully blind at 18:00 in October, CFG on, gives exactly one turn_off and one reserve action (today: none, because it keys on "peak").
- **Test (mutation-anchored):** `test_tou_rate_rank_hour_sweep_pec`, `test_tou_rate_rank_ties_and_single_rate`, `test_reserve_action_fold_raises_only`, `test_reserve_action_fold_before_deadband`, `test_tick_floor_entry_reset`, `test_governor_golden_unchanged_stage_a`, `test_blind_runs_inclement_decision`, `test_blind_hold_writes_floor_once`, `test_blind_hold_never_lowers_held_value`, `test_blind_release_at_hazard_end`, `test_blind_no_release_without_raise`, `test_blind_deescalation_shoulder_midpeak`, `test_blind_deescalation_reserve_folded`, `test_blind_never_stamps_desired_at`, `test_blind_one_reserve_action_per_tick`, `test_blind_full_hold_floor_inversion` (`reserve_soc=20, partial=80, knob=60` gives 80), `test_sighted_full_hold_floor_below_reserve_soc_unchanged` (SOC 15, `reserve_soc` 20, writes 15), `test_blind_hold_overlay_cannot_lower_floor`, lint `test_reserve_write_chokepoint_lint` green with the new tuple.
- **Live:** (a) `tou_top_rate` on `sensor.ura_energy_coordinator_battery_strategy` reads **true** at 17:00–21:00 local in October and false at 16:00. A name-keyed implementation would read false all day in shoulder, so this discriminates. (b) On the next fully-blind episode with no hold (the Envoy is flapping now): zero `reserve_write` rows whose reason starts "Envoy unavailable". A writer that ignores v5.17.5 would show a row per change. (c) The governor `floor_ok` query **without** the old `NOT LIKE 'Blind de-escalation%'` exclusion returns 0. (d) 0 ERRORs mentioning `_reserve_action` / `blind`.

### Stage B: matching, locality, Onset→Ends (arc steps 3 and 4)

**D-B1 hazard window and filter** (`inclement.py`). `_hazard_window(alert) -> (start, end)` with `start = Onset or Sent` and `end = Ends or Expires`. Drop `Status ≠ Actual`, drop `Type == "Cancel"` (keep Alert **and Update**), drop `now < start` (not active) and `now > end`. Polygon-local products (`polygon_local` in the table: SVR, TOR, EWW) count only if P2(b) shows `?point=` is polygon-exact. Otherwise they are classified at most `notice` until a URA-side check exists (parked, §10). `inclement_expires_at` carries `end` (attr keeps its name; meaning documented).
**D-B2 product table** (`energy_const.INCLEMENT_PRODUCT_TABLE`, rung 1): rows of `(code | None, exact_event_name, class, polygon_local)`. A match is the code **or** the exact (case-folded) event name. When one matches and the other disagrees, log a warning and create an `ura_activity_log` `inclement_code_drift` row (the P3-06 trip-wire). Tier = the table tier. **No severity or certainty demotion on this path** (both go to attrs and the ledger). No breadth-demote either (dropped as unevidenced; the alert ledger collects the evidence).

| Class | Products (code per P3) | Tier |
|---|---|---|
| HOLD-warn | Winter Storm Warning, Ice Storm Warning, Hard Freeze Warning, Extreme Cold Warning, Wind Chill Warning, Blizzard Warning, Tornado Warning (point-local), Severe Thunderstorm Warning (point-local), Extreme Wind Warning, Hurricane Warning, Tropical Storm Warning | warn |
| HOLD-watch | Winter Storm Watch, Hard Freeze Watch, Extreme Cold Watch, Wind Chill Watch, Tornado Watch, Severe Thunderstorm Watch, Hurricane Watch, Tropical Storm Watch | watch |
| NOTICE (shown and logged, never a hold) | **Wind Advisory**, High Wind Warning/Watch, Winter Weather Advisory, Freeze Warning, Wind Chill Advisory, Cold Weather Advisory | notice |
| gated out | everything else (heat, fog, red flag, flood, fire) | none |

SVA/TOA/SVR/TOR hold today through the substring list. Keeping them is a **no-regression** choice. Point-locality cuts SVR roughly 4×. Freeze products are added on outage evidence (Uri, Jan 2026). High Wind moves to notice (0 fires in 5.8 years, operator: no wind outages seen).

**D-B3 staleness and memory.** If the sensor's `last_updated` (P2d) is older than `NWS_ALERTS_STALE_S`, keep the last classified HOLD alerts until their own `end` and accept no new ones; set attr `inclement_alerts_stale`. A storm can take the internet down with the grid, and dropping holds exactly then would be wrong. An alert with no `Ends` and no `Expires` is capped at `INCLEMENT_ALERT_MAX_HOLD_H` from `Sent` (closes the pre-existing unbounded case). **If P2(a) shows the feed drops alerts at Expires before Ends:** keep an RAM memory of HOLD alerts keyed `(code, start)` until `end`, cleared when a matching `Cancel` appears. Otherwise build no memory.
**D-B4 bottom rate in the hold logic.** `InclementFusion` gets `bottom_rate: bool` from `is_bottom_rate(now)` (fallback `tou_period == "off_peak"` if there is no engine). It replaces the literal `off_peak` checks in `decide` (4 sites) and `compute_solar_horizon` (`:355`). Byte-identical on PEC (hour sweep).
**D-B5 retire the legacy list.** Remove `CONF_INCLEMENT_POWER_THREAT_EVENTS` and `CONF_INCLEMENT_WARN_MIN_SEVERITY` from the options-flow schema; keep the constants (KEEP+DOCUMENT). If a stored list differs from the v5.5.0 default, raise one repair issue at setup listing what the table now does. **No options write** (avoids the reload hazard). The live list equals the default, so no issue fires here.

**Acceptance**
- **Verify (10-15 replay, committed fixture from the recorder payload):** WIY, Onset 04:00, Ends 19:00. At 02:30, not active (tier none). At 04:00 and 18:59, tier notice and allow_discharge. At 19:01, gone. An Update message with a new Expires is kept, not dropped. A buggy `Type≠Alert` filter would drop it, so this discriminates.
- **Verify (INV-3):** Hard Freeze Warning inside its window gives warn and full_hold. Hard Freeze Watch at off-peak, uncorroborated, gives partial_hold. Freeze Warning gives notice. Flood Watch is gated out. An empty-code alert named "Winter Storm Warning" matches by name. A code/name disagreement writes one drift row.
- **Verify:** an SVR without polygon-local confirmation gives notice (when P2b is NO).
- **Verify:** stale sensor plus a known Winter Storm Warning holds until Ends. A stale sensor never admits a new alert. An alert with no end drops after `INCLEMENT_ALERT_MAX_HOLD_H`.
- **Verify:** the bottom-rate hour sweep gives identical decisions to the literal path across a year.
- **Test:** `test_wiy_is_notice_never_hold`, `test_freeze_products_hold`, `test_pre_onset_not_active`, `test_update_message_kept_cancel_dropped`, `test_hold_lives_to_ends`, `test_fallback_expires_when_no_ends`, `test_code_name_drift_row`, `test_svr_not_point_local_is_notice`, `test_stale_feed_keeps_known_holds_to_end`, `test_unbounded_alert_capped`, `test_fusion_bottom_rate_hour_sweep_identical`, `test_legacy_list_no_options_write`, `test_customized_legacy_list_raises_repair_issue`.
- **Live:** (a) `nws_alert` rows (Stage L) written after Stage B carry `ura_class`; any WIY row reads `notice` with no hold on the strategy sensor at that time (today WIY is gated out with no attr). (b) `inclement_gated_out_events` lists heat/fog/flood products and **not** Wind Advisory. (c) The options flow no longer shows the threat-list and severity fields; the CM entry does not reload at setup (no `async_update_entry` in the log window).

### Stage C: forecast slice (arc step 6). Built only on P1 GO

**D-C1 hourly outlook** (`WeatherProviderManager`): `async_track_time_interval(FORECAST_REFRESH_MIN)` with its unsub in `_unsub_handles`; refreshes run through `_pending_refresh_tasks` under the WPM-C1 lock; an immediate first refresh in `async_setup`; `never_fetched` is distinct from `stale` (P2-09, P2-10). Method `hourly_outlook(start, end) -> Outlook | None` aggregates healthy providers' hourly rows in the window. Stale beyond `FORECAST_STALE_MIN` returns None.
**D-C2 corroboration.** For a HOLD-watch alert, `forecast_confirms(product, outlook)` per the table rule. Freeze/cold products: min temp ≤ `FORECAST_FREEZE_CONFIRM_F`. Winter storm: min temp ≤ 32 °F and max precip-probability ≥ `FORECAST_PRECIP_CONFIRM_PCT`. Convective: max precip-probability ≥ that value or a storm condition in the window. Window = `[now, hazard end]` capped at `FORECAST_WINDOW_MAX_H`. A confirmation **counts as watch corroboration** in the existing slot (`corroborated = condition OR forecast`; P1-04 resolved: yes). It never touches warn (raise-only). None means no change from today. A forecast alone never creates a hold (no forecast-only tier; P2-14 moot).
**D-C3 attr** `inclement_forecast` = `{fetched_at, providers_ok, window_end, min_temp, max_pop, max_gust, confirms}`.

**Acceptance**
- **Verify:** Hard Freeze Watch, off-peak, outlook min 22 °F gives full_hold (corroborated). With a min of 40 °F it gives partial_hold (uncorroborated, today's behavior). With outlook None it is identical to today.
- **Verify:** a Winter Storm Warning with a 40 °F outlook still gives full_hold (raise-only).
- **Verify:** teardown leaves no timer (`async_teardown`); the first tick after boot has `never_fetched` and today's behavior.
- **Test:** `test_forecast_confirms_freeze_watch`, `test_forecast_never_demotes_warn`, `test_forecast_none_is_noop`, `test_forecast_timer_torn_down`, `test_forecast_first_tick_never_fetched`, `test_forecast_window_capped`.
- **Live:** `inclement_forecast.fetched_at` advances every `FORECAST_REFRESH_MIN` (±1 tick) and `providers_ok` equals P1's healthy count. A dead timer shows a frozen `fetched_at`; a fetch that silently fails shows `providers_ok=0`.

### Stage D: remaining period-name sites (arc step 7 remainder; separable)
Migrate the 9 **H** sites (§8) to `not is_bottom_rate(now)`. They are byte-identical on PEC, proven by a full-year hour sweep per site. Add a pinned allowlist test (rung-1 tuple `TOU_PERIOD_NAME_LITERAL_SITES`, the same AST pattern as the governor lint) for the 20 **N** sites, so new literal checks fail CI. The 4 **T-change** sites change shoulder/winter behavior and ship only on explicit operator approval, each with its own acceptance criterion.
- **Test:** `test_period_literal_sites_pinned`, `test_<site>_hour_sweep_identical` ×9.
- **Live:** `sensor.ura_energy_coordinator_battery_strategy` attributes and EVSE/pool behavior unchanged across the next 17:00 shoulder boundary (`ura_activity_log` actions for pool/EVSE at 17:00 compared with the prior day).

---

## 7. Numbers get knobs

| Knob | Rung | Default | Why / kill-switch |
|---|---|---|---|
| `INCLEMENT_PRODUCT_TABLE` | 1 | §6 D-B2 | Decision topology; a change must be reviewed. Removing a row stops matching that product. |
| `INCLEMENT_BLIND_FULL_HOLD_FLOOR_PCT` | 1 | 60 | Blind full hold without SOC: holds enough without pinning 100 overnight. Applied as `max(reserve_soc, partial_floor, knob)`. Set to 100 for the legacy behavior. Promotion trigger: the operator wants to tune it by observation. |
| `NWS_ALERTS_STALE_S` | 1 | 900 (15× the 1-min poll) | Feed staleness bound. A very large value disables the stale branch. |
| `INCLEMENT_ALERT_MAX_HOLD_H` | 1 | 48 | Caps alerts with no Ends/Expires. |
| `OUTAGE_SWEEP_INTERVAL_H` | 1 | 24 | Cloud-calendar sweep cadence. 0 disables the sweep. |
| `OUTAGE_SWEEP_LOOKBACK_H` | 1 | 48 | Overlaps a missed day; small enough to finish inside the timeout. |
| `OUTAGE_DEDUP_TOLERANCE_MIN` | 1 | 10 | Local-vs-cloud episode match (5-min tick + cloud lag). |
| `OUTAGE_SWEEP_TIMEOUT_S` | 1 | 30 | Calendar reads time out on long windows (audit). |
| `ACTIVITY_LEDGER_IMPORTANCE` | 1 | same as `RESERVE_WRITE_LOG_IMPORTANCE` | Parity. |
| `FORECAST_REFRESH_MIN` (C) | 1 | 30 | Hourly forecasts change slowly; per P1 cadence. |
| `FORECAST_STALE_MIN` (C) | 1 | 120 | Beyond this the outlook is None. |
| `FORECAST_WINDOW_MAX_H` (C) | 1 | 48 | Bounds a long Ends. |
| `FORECAST_FREEZE_CONFIRM_F` (C) | 1 | 28 | NWS hard-freeze threshold. |
| `FORECAST_PRECIP_CONFIRM_PCT` (C) | 1 | 50, final value from P1 | Rev 3's 43 % night shows why the probe sets it. |

Unchanged v5.5.0 knobs (partial floor 50, precharge off, corroboration mode, surplus margin) are kept. **No new rung-2 or rung-3 knobs.** The options flow shrinks by two fields (D-B5).

---

## 8. The 35 period-name sites, classified

Classes: **T** = means top rate (migrate in Stage A). **T-change** = means top rate, but migrating changes shoulder/winter behavior (Stage D, needs operator approval). **H** = means "above the bottom rate", i.e. not off-peak (Stage D, byte-identical). **N** = means the named period on purpose: summer bracket logic with peak-ahead walks, rate-aware attain gates, learning baselines, labels (stays named; pinned).

| # | Site | Use | Class |
|---|---|---|---|
| 1 | `energy_battery.py:1879` | skip untrusted-SOC page during peak | T-change |
| 2–3 | `:4448`, `:4455` | mid_peak walk to next peak (summer bracket) | N |
| 4–7 | `:4574`, `:4921`, `:5082`, `:5164` | attain mid_peak gated by `_midpeak_rate_lt_peak` (already rate-aware) | N |
| 8–9 | `:5327`, `:5427` | stage label | N |
| 10–11 | `:5632`, `:5680` | **blind de-escalation** (+ log label) | **T** (Stage A) |
| 12–13 | `:5877`, `:5898` | peak / mid_peak branches (season-aware by design) | N |
| 14 | `energy.py:6383` | SOC-at-peak degradation baseline | N |
| 15 | `:8352` | summer post-peak mid_peak (explicit season) | N |
| 16 | `:8367` | load-shed at peak with low SOC | T-change |
| 17–18 | `:8375`, `:8380` | HVAC coast at peak; mid_peak poor-solar branch | N |
| 19–20 | `:8493`, `:8495` | energy situation (display) | H |
| 21 | `:8522` | load shed only above off-peak | H |
| 22 | `:8572` | peak import learning history | N |
| 23 | `energy_pool.py:405` | pool speed reduce at peak | T-change |
| 24 | `:1371` | EVSE peak/mid handling | H |
| 25 | `:1858` | excess-solar EVSE never during peak | T-change |
| 26–27 | `:2771`, `:2773` | fill-priority inert (peak_ahead bracket) | N |
| 28 | `:3944` | proactive hold cleanup | H |
| 29–30 | `:4534`, `:4536` | fill-priority inert (bracket) | N |
| 31 | `energy_tou.py:613` | `peak_ahead_before_offpeak` walk (defines the bracket) | N |
| 32–33 | `hvac_predict.py:2049`, `:2059` | anchor to next high-rate window | H |
| 34 | `sensor.py:9266` | next-boundary text (display) | H |
| 35 | `energy_billing.py:739` | displaced periods for peak-avoidance | H |

Totals: T 2, T-change 4, H 9, N 20. Not counted: `energy_tou.py:47` (validation set) and inclement's `off_peak` checks (migrated in D-B4).

**Marginal-benefit note (pushback):** only the 2 T sites change a decision this arc needs. The 9 H sites are byte-identical on PEC; their value is tariff-portability, since URA is rolling to more homes. The 20 N sites are correct as named, and converting them would destroy summer-bracket semantics. Stage D is therefore separable and Tier 2, and the T-change sites are a per-site operator call.

---

## 9. Build staging and tiers

| Stage | Contents | Tier | Depends on | Builder |
|---|---|---|---|---|
| 0 | P1–P4 probes | none (read-only) | none | ura-prober |
| L | D-L1, D-L2 | **2-DB** (new activity-row producers; payload shape matters; no schema) | P4 for D-L2 (D-L1 needs nothing) | ura-builder |
| A | D-A1, D-A2, D-A3 | **3** (shared writer + floor + blind state machine) | none | ura-super-builder |
| B | D-B1–D-B5 | **3** (classification feeds every hold) | P2, P3; Stage A (bottom-rate primitive) | ura-super-builder |
| C | D-C1–D-C3 | **3** (new async producer feeding the hold) | P1 GO; Stage B | ura-super-builder |
| D | §8 H migrations + pin; T-change by approval | **2** | Stage A | ura-builder |

Ship order: L and 0 in parallel → A → B → C → D. L ships first because evidence accrues only from its ship date. A precedes B so the blind floor and top-rate are live before matching widens the set of holds. Each Tier-3 stage gets four framing-disjoint reviews, orchestrator re-grep plus own mutation drills, and an operator checkpoint before deploy.

**Mutation plan (Review C, real per-site edits):** remove the fold in `_reserve_action`; move the fold after the deadband; drop the `_tick_reserve_floor` entry-reset; route blind de-escalation around `_reserve_action`; stamp `_desired_stamped_at` in the blind branch; drop the release; emit both hold and de-escalation; `is_top_rate` by name; `Type≠Alert` filter; substring match; Expires instead of Ends; the forecast confirming a warn demotion; the ledger dedup removed; witness `None` treated as a transition. Each must turn its named test RED.

---

## 10. Non-goals and parked items

**Non-goals:**
1. No change to the governor's rows, gate or `inclement_floor` field (only its allowlist tuple), the overlay internals, write-verify, `_resolve_hold_owner`, or `force_redispatch`.
2. No deletion of the 8 `_floor_reserve` wraps (redundant after D-A2; KEEP+DOCUMENT, revisit after a clean Stage A).
3. No CFG writer under blind other than the existing turn_off. No pre-charge writer anywhere. Grid precharge stays the existing default-off knob.
4. No `pending` tier and no pre-onset hold (the operator's rule). No forecast-only tier.
5. No Enphase Storm Guard read (README line only, as in Rev 3 D6).
6. No new options-flow fields, entities or tables.
7. No arc steps 8–11 (TOU-transition/self-heal paths; their own joint plan).

**Parked, with revival triggers:**
- *URA-side polygon matching* (fetch the alert `URL` GeoJSON, ray-cast). Trigger: P2(b) shows `?point=` is not polygon-exact **and** the operator wants SVR/TOR to hold. Until then, unconfirmed SVR/TOR stay notice.
- *Pre-onset prepare floor* (raise to the partial floor N h before a forecast-confirmed HOLD-warn onset, at bottom rate only). Trigger: the outage ledger shows an outage that began within N h of an alert's onset with SOC below the partial floor. (Open question 3.)
- *Severity/certainty or breadth modulation.* Trigger: ledger data shows a class of HOLD alerts with zero outages and material hold cost.
- *Promoting Wind Advisory to hold.* Trigger: ≥1 ledger outage overlapping a WIY window, in the house's local witness or the cloud calendar.

---

## 11. Disposition of Rev-3 review findings

| ID | Disposition |
|---|---|
| P1-01 | Fixed: §5 full enumeration; INV-1 enforced by construction at `_reserve_action`, so a missed branch can't leak. |
| P1-02 | Fixed: de-escalation reserve is folded (D-A3.1). |
| P1-03 | Fixed: INV-1 is stated over hold_depth. |
| P1-04 | Resolved: forecast counts as corroboration (D-C2); expected values derived in Stage A/C acceptance. |
| P1-05 | Fixed: payload from the integration source; `Type` = messageType (corrects Rev 3 too). |
| P1-06 / P1-07 | Fixed: Expires→Ends supersession stated (D-B1); P2 probe supplies the semantics evidence. |
| P1-08 | Moot: no pending tier. |
| P1-09 | Fixed: §4. |
| P1-10 | Fixed: WPM is the forecast owner (D-C1). |
| P1-11 | Moot (no D5 attr claim). |
| P1-12 | Fixed: no severity demote on the code path. |
| P1-13–15 | Fixed: §7 knobs; Live bullets are one-shot; the outage source is the ledger. |
| P2-01 | Fixed: 10-15 replay with WIY = notice. |
| P2-02 | Fixed: the P1 probe sets thresholds; freeze uses temperature. |
| P2-03 / P2-04 | Fixed: the blind floor lives in `_full_hold_floor(None)` with the max() form. |
| P2-05 | Fixed differently: the blind path shares `_reserve_action` (diff, deadband, stand-down, desired stamp) rather than `_result`, because `_result` carries side effects P3-02/03/04 proved wrong for blind. |
| P2-06 | Fixed: INV-2 keeps the turn_off. |
| P2-07 | Moot: no certainty mapping. |
| P2-08 | Moot: no pending. |
| P2-09 / P2-10 | Fixed: D-C1 lifecycle. |
| P2-11 | Kept: site 18 not a leak; the fold makes it moot. |
| P2-12 | Fixed: the write-verify partial exception is unchanged. Full hold under blind is covered by the stale-stamp stand-down, not by a new extension. |
| P2-13 | Fixed: table rung 1, legacy retired without an options write. |
| P2-14 | Moot. |
| P2-15 / P2-16 | Fixed / noted (per-tick cache). |
| P3-01 | Fixed: blind release (D-A3.3), INV-2. |
| P3-02 | Fixed: blind never stamps `_desired_stamped_at`. |
| P3-03 | Fixed: blind never calls `_result`; keeps its own dict. |
| P3-04 | Fixed: no `_result` CFG path under blind; the full_hold exemption is kept unchanged. |
| P3-05 | Fixed: D-B5 (single semantics; repair issue only when customized; no options write). |
| P3-06 | Fixed: P3 probe plus exact-name fallback plus drift trip-wire. Hurricane/Tropical watches added. |
| P3-07 | Fixed: P2(a) gates the D-B3 memory; staleness bound added. |
| P3-08 | Fixed: only the None branch changes. |
| P3-09 | Fixed: §4 states the horizon effect and the blind degenerate outcome. |
| P3-10 | Moot: no certainty demotion. |
| P3-11 | Fixed: honest scope in D-A3. |
| P3-12 | Fixed: recent_events and the corroboration promotion dropped; no Number entity. |
| P3-13 | Fixed: Stage A top-rate. |

---

## 12. Config-extreme and edge cases (tests must cover)
1. `reserve_soc=80 > partial_floor=50`: floor 80; the fold never lowers.
2. `partial_floor=100`: partial hold pins 100; blind knob 60 is irrelevant (max).
3. Blind knob < partial floor (`partial=80, knob=60`): 80.
4. Sighted full hold with SOC 15 < `reserve_soc` 20: writes 15 (fold = `decision.reserve_floor`, not `reserve_soc`).
5. Floor > target (`peak_buffer_target=40`, floor 80): 80.
6. Blind steady hold with an EVSE hold of 45 and a blind floor of 60: the overlay base is the stamped 60, so no 45 write.
7. Blind entered with an arbitrage desire of 80 and a floor of 60: no write (never lowers). Hazard end: no release (never raised).
8. Restart during a blind raise: flags are lost, so no blind release. The first sighted tick re-derives. **Known limit.**
9. Operator lowers the reserve during a blind hold: the next tick re-asserts the floor, which is sighted-path parity. Escape: the EC enable switch. **Known limit, by design.**
10. Single-rate season or a tariff with mid == peak: rank ties; de-escalation is never top in a single-rate season.
11. Engine missing (`_tou is None`): literal fallback, byte-identical.
12. Feed stale through a grid outage: known holds persist to Ends; no new alerts.

---

## 13. Supersession (post-ship audit inputs)
- **DELETE (after Stage B validates):** `_event_matches_threat` (the substring gate, a footgun superseded by the table).
- **KEEP+DOCUMENT:** the 8 `_floor_reserve` wraps; `CONF_INCLEMENT_POWER_THREAT_EVENTS` / `_WARN_MIN_SEVERITY` constants; `_midpeak_rate_lt_peak` (distinct question).
- **Should-be-consuming gaps to card at ship:** the strategy-sensor NM path could consume `nws_alert` rows for operator notification of HOLD alerts. Not in scope.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018uEjYPUcWq73wfBS3t1NEa
