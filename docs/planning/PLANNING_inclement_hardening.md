# PLANNING — Inclement-Weather Hardening (NARROW extension of v5.5.0)

**Card:** `EC-INCLEMENT-HARDENING-1`
**Tier:** 3 (shared primitive — `determine_mode` precedence chain + `_floor_reserve` consumers; cost + safety ripple)
**Status:** `pre_planning` → BUILD-READY after Rev 3 reviews.
**Rev:** **3** (2026-10-15; narrows Rev-2 after Plan Review #2 → `docs/reviews/code-review/plan_inclement_hardening_review_2.md`, operator constraint `operator_instruction_2026_10_15_b`, and `docs/planning/AUDIT_nws_alert_history_lakeway.md`).
**Branch target:** `develop`.
**Scope posture:** this is an **EXTENSION of v5.5.0**, not a rebuild. Prior art = `docs/planning/PLANNING_inclement_weather_reserve.md` + the shipped v5.5.0 code. Every deliverable states its concrete improvement over current behaviour, measured against the Lakeway audit, and reuses existing machinery (existing tiers warn/watch/notice/none, existing `_full_hold_floor`/`_partial_floor_value`, existing `_result` emit path, existing `_floor_reserve`, existing `WeatherProviderManager`).

**Operator posture (verbatim 2026-10-15 b):** *"Make sure reading the original plan is prior art. I won't rebuild for fun. It has to be an actual improvement."* Also: *"Our inclement weather module was built to be a more measured storm guard [than Enphase's indiscriminate alert-driven one]. I turn [Enphase Storm Guard] off and hope it sticks."*

**Operator thesis (2026-10-15 a):** *"(1) Blind pause: why stop reasoning when you clearly can? (2) Fix the matching. (3) Forecast never consulted seems dumb."*

**Supersedes behavior shipped in v5.5.0:** one explicit rule — **L-criterion "a hold cannot outlive the alert's Expires"** (`PLANNING_inclement_weather_reserve.md:326`) is replaced with "a hold lives to `Ends`, falling back to `Expires` only when `Ends` is absent". No other v5.5.0 invariant is overturned.

---

## Rev-3 changelog (P2 finding → disposition)

| ID | Sev | Disposition | Where in Rev 3 |
|---|---|---|---|
| P2-01 | HIGH | **Fixed** by narrowed scope. Pre-onset = NOT ACTIVE (re-evaluated each tick), not a new tier. New §Tonight walkthrough gives per-segment expected values for shoulder-season TOU (off_peak 00-17 + 21-24, mid_peak 17-21, no `peak`). |
| P2-02 | HIGH | **Moot by scope-cut.** D-forecast PARKED with evidence (see §Parked). Hourly forecast on our provider carries `wind_speed` only (no `wind_gust_speed`); 43 % precip < any sane default; no honest marginal benefit until the provider exposes gust or probabilities rise. |
| P2-03 | HIGH | **Fixed.** Blind cap lives inside `InclementFusion._full_hold_floor(current_soc)` (now takes `blind_floor_knob` through the constructor at `energy_battery.py:2708`); `decision.reserve_floor` is itself the capped value, so INV-H holds with no secondary helper. Deleted `reserve_floor_blind`. |
| P2-04 | HIGH | **Fixed.** Blind full_hold floor = `max(reserve_soc, partial_floor, knob)`. Config-extreme test `test_blind_floor_respects_partial_floor_inversion` added. |
| P2-05 | HIGH | **Fixed.** D-blind emits ONLY via `self._result(...)` so the diff + `_last_reserve_level_desired` stamping are reused. Acceptance restated: "at most one reserve write per CHANGE of floor; zero on steady blind ticks." |
| P2-06 | HIGH | **Fixed.** INV-B rewritten: "no CFG **turn_on** under full-blind; de-escalation CFG turn_off survives." Regression test `test_blind_peak_cfg_turn_off_survives` added. |
| P2-07 | HIGH | **Fixed.** Certainty map: `Unlikely → watch` (not notice). WIY/Unlikely inside `[Onset, Ends]` → watch, satisfying INV-C. Removed pending/breadth from INV-C exits (pending no longer a tier). |
| P2-08 | HIGH | **Dropped (scope cut).** No `pending` tier. No pre-charge CFG writer. `_demote` unchanged. "Not yet active" is handled by the hazard-window check filtering the alert out of the classifier until `now ≥ Onset`; the fusion then re-evaluates on the next tick. |
| P2-09 | HIGH | **Moot** (D-forecast parked). Lifecycle sketched in §Parked for future revival. |
| P2-10 | MED | **Moot** (D-forecast parked). |
| P2-11 | MED | **Fixed.** Site 18 marked already-floored (post partial_hold clamp near `energy_battery.py:~6223`). Site table anchored to symbols, not raw line numbers (lines drift). `_floor_reserve` description corrected (pure function of `(existing, effective_reserve, hold_depth)`; it does NOT read `_last_inclement_decision`). |
| P2-12 | MED | **Fixed.** "Reason prefix" mechanism dropped. Write-verify behaviour under blind pinned: because D-blind emits via `_result`, `_last_reserve_level_desired` is stamped; `_inclement_partial_hold_floor` (`energy_write_verify.py:1647`) continues to work unchanged; extended once to recognise full_hold floor (one-line change). Test `test_write_verify_silent_during_blind_hold`. |
| P2-13 | MED | **Fixed.** Added `INCLEMENT_CODE_DEFAULT_TIER: dict` (rung 1); codes not in the dict default to `watch`. Name fallback runs only when `NWSCode` is missing/empty. Legacy saved list `CONF_INCLEMENT_POWER_THREAT_EVENTS` migrated once at setup (operator-visible repair notice); union with the new default code set; operator keeps authority to override. Product-folding on the code path retired. |
| P2-14 | MED | **Moot by scope-cut** (no forecast-only tier). |
| P2-15 | LOW | **Fixed.** Test names cleaned up. `Effective` removed from `_hazard_window`. D-blind live-check reads `command_trail` + actuator entity history, not `energy_write_queue`. |
| P2-16 | LOW | Noted in D-blind as a non-issue (per-tick `now` cache at `energy_battery.py:2667-2672`; signal fires only on `(tier, depth)` change at `:2733-2737`). |

---

## Falsifiable invariants (Rev 3)

> **INV-H (emission floor):** when `_inclement_decision(...)` returns a decision with `hold_depth ∈ {partial_hold, full_hold}`, every reachable reserve emission in the same tick commands `reserve_soc ≥ decision.reserve_floor`. Scope covers all `_result(reserve_level=...)` sites in `energy_battery.py` (anchored by symbol in §Reserve emission site inventory), the blind-gate emit (D-blind, routed through `_result`), the EVSE overlay `_apply_evse_battery_hold` at `energy.py:_apply_evse_battery_hold` (max()-safe; verify at BOTH call sites `energy.py:6459, :7174`), and the drain-precedence ledger `energy_drain_precedence.py:68, 98`.

> **INV-C (classification):** for any `alert ∈ attributes.Alerts` with `Status=="Actual"`, `Type=="Alert"`, `NWSCode ∈ CONF_INCLEMENT_POWER_THREAT_EVENT_CODES`, `now ∈ [Onset, Ends]` (fallback `[Sent, Expires]` when either is missing), the classifier returns `tier ≥ watch`. The only legal exits below watch are: breadth-demote to `notice` for codes marked breadth-sensitive in the trust table; `Certainty==Unlikely` demotes to watch (not lower).

> **INV-B (blind safety):** under full-blind (`envoy_available=False` AND resolved SOC None after 3-tier fallback), URA emits NO `charge_from_grid` **turn_on** write. The existing peak de-escalation CFG `turn_off` write MUST still fire when peak-or-into-peak and CFG currently on. Reserve writes are allowed and must respect INV-H.

---

## Prior art — the v5.5.0 plan is the baseline

Read end-to-end during scoping (not skim): `docs/planning/PLANNING_inclement_weather_reserve.md`. Rev 3 **does not re-litigate** its invariants, its tier model (none/notice/watch/warn), its hold-depth ladder (allow_discharge/partial_hold/full_hold), its reserve-floor arithmetic (`_full_hold_floor`, `_partial_floor_value`), its solar-horizon recoverability (`compute_solar_horizon` + `_expected_solar_surplus_pct`), its grid-precharge policy (`CONF_INCLEMENT_GRID_PRECHARGE_ON_HOLD` default False), its weather-provider election, or its storm-charge threshold. All of those are KEPT.

**What this cycle changes, concretely:**

| v5.5.0 behaviour today | Measured consequence (Lakeway) | Change in Rev 3 | Deliverable |
|---|---|---|---|
| Threat set is a substring-matched name list `[Tornado, Severe Thunderstorm, Ice Storm, Winter Storm, High Wind, Extreme Wind, Hurricane, Blizzard]` (`energy_const.py:630-639`) | **Wind Advisory never matches** (not a substring of any keyword). Audit: Wind Advisory fired **33× in 5.8 yrs (~6/yr)**; "High Wind" fired **0×**. Current list is blind to the dominant local wind event; carries a dead keyword. | Switch primary gate to `NWSCode` (code set); add `WIY` (Wind Advisory); retire `High Wind` from code-default set (operator can re-add); keep name-match as fallback for alerts whose `NWSCode` field is empty. | **D-match** |
| `_alert_expires_at(alert) = min(Ends, Expires)`; current-time filter at `inclement.py:213` drops any alert where that minimum has passed | Tonight's Wind Advisory `Onset=Expires=04:00, Ends=19:00` would survive the pre-04:00 drop (Expires is future) but **would be dropped at 04:00** when `min(Ends,Expires)=04:00` passes — exactly when the hazard begins. | Hazard-window helper `(Onset, Ends)` with fallback to `(Sent, Expires)`. Drop only when `now > hazard_window.end`. A pre-onset alert (`now < Onset`) is filtered as "not yet active" and the classifier returns `none` for that alert; next tick re-evaluates. **No new tier, no new CFG writer.** | **D-ends** |
| Envoy-blind gate at `energy_battery.py:5578-5710` short-circuits BEFORE `_inclement_decision` runs; inclement attrs go stale; no reserve write queued | 2026-10-15 live: Envoy offline 17:38; URA produced no inclement hold on any axis. | Move `_inclement_decision(...)` ABOVE the blind-gate. Emit under blind via `self._result(...)` with `reserve_level=decision.reserve_floor` and `charge_from_grid=False`. Compose with existing peak de-escalation (CFG turn_off survives). Bake the bounded-blind cap INSIDE `InclementFusion._full_hold_floor(None)` so `decision.reserve_floor` is the single source of truth. | **D-blind** |
| Forecast lookahead not consulted (`PLANNING_inclement_weather_reserve.md` grep for forecast-lookahead keywords = 0 matches) | 2026-10-15 live: hourly 43 % lightning-rainy within 3 h, no active NWS alert during that window. Would be relevant signal — IF the provider carried the right fields. | **PARK with evidence.** The configured hourly provider (`weather.nws_30_314635_98_015861_kryw`) carries `wind_speed` only (NO `wind_gust_speed`); tonight's 43 % precip-prob is below any sane default (≥50 %). Adding forecast requires a new async cache + timer lifecycle. Marginal benefit does not pay today. Document a revival trigger and a design sketch (see §Parked). | **(parked)** |

---

## Tonight walkthrough (shoulder season, 2026-10-15/16 Lakeway)

TOU for October (shoulder, `energy_const.py:36-50`): off_peak = `[00,17) ∪ [21,24)`, mid_peak = `[17,21)`. **No `peak`.**

Alert: WIY Moderate/Likely, `Onset=04:00, Expires=04:00, Ends=19:00`.

Envoy offline from ~17:38 (10-15). Battery ~30 % at drop; SOC resolution via 3-tier (EC p1) resolver — may return LKG, cloud, or None.

| Local time | TOU | Alert state at this moment | Classifier output | `decide()` output | Expected `_result` emission |
|---|---|---|---|---|---|
| 22:00 (10-15) | off_peak | `now < Onset` ⇒ **filtered out** by hazard-window pre-check. Alerts list contains the Wind Advisory, but classifier returns `tier=none`. | `tier=none, source=none` | `allow_discharge` | reserve_level = `self.reserve_soc` (unchanged). No new write unless floor changed. |
| 02:30 (10-16) | off_peak | still `now < Onset`; same filter. | `tier=none` | `allow_discharge` | unchanged. |
| 04:00 (10-16) | off_peak | `now ≥ Onset` and `now ≤ Ends`. Classifier runs. NWSCode `WIY` → code_default `watch`; `Certainty=Likely` → certainty_tier `warn`; `tier = min(watch, warn) = watch`. Breadth: WIY not breadth-sensitive. | `tier=watch, source=alert` | **off_peak + watch**: current code path is `watch_corroborated_offpeak_full_hold` IF `watch_requires_corroboration` AND condition-stormy (`inclement.py:629-645`). Default `watch_requires_corroboration=True`. The condition path is state-only; if ≥1 provider is stormy, corroborated → full_hold. If not stormy, uncorroborated → off_peak partial_hold (`inclement.py:619-626`). D-forecast parked, so no forecast corroboration. | **Case A (not corroborated by condition):** `partial_hold`, `reserve_floor = _partial_floor_value(soc) = max(reserve_soc, 50) = 50`. `_result` emits reserve=50 (or higher if SOC blind-resolved); CFG not written. **Case B (corroborated by condition):** `full_hold`, `reserve_floor = _full_hold_floor(soc, blind_knob)`. If SOC resolved: `max(reserve_soc, partial_floor, int(soc))`. If SOC None: `max(reserve_soc, partial_floor, blind_knob)` = `max(10, 50, 60) = 60` (default knob 60). CFG not written (precharge off; INV-B). |
| 04:00-17:00 | off_peak | watch active | same as above (per-tick re-evaluation; condition sampling may toggle corroboration — v5.5.0 behaviour, not Rev-3 change) | partial_hold or full_hold | one reserve write per **change** of floor; otherwise no new write. |
| 17:00 (10-16) | mid_peak | watch active | `tier=watch` | **mid_peak + watch**: current code path `watch_corroborated_recoverable_partial_hold` OR `watch_corroborated_not_recoverable_full_hold` (depends on `compute_solar_horizon`; uncorroborated mid-peak returns `allow_discharge`, `inclement.py:619-626`). | if corroborated + recoverable → partial_hold floor 50; else full_hold floor; else allow_discharge (reserve = `reserve_soc`). |
| 19:00 (10-16) | mid_peak | `now > Ends` ⇒ alert dropped by hazard-window | `tier=none` | `allow_discharge` | reserve back to `reserve_soc`; one de-escalation write. |

**Load-bearing improvements vs v5.5.0 code TODAY, on this exact timeline:**
1. Today the classifier **never matches WIY** (substring list) → tier stays `none` the whole night → `allow_discharge` the whole night. Rev 3 makes 04:00 → `watch` and 04:00-19:00 can hold.
2. Today the Envoy-blind gate suppresses `_inclement_decision` entirely → no attrs, no reserve write — even if WIY had matched. Rev 3's D-blind runs the decision and emits via `_result`.
3. Today `_alert_expires_at = min(Ends,Expires) = 04:00` would drop the alert the instant it became active. Rev 3's hazard-window keeps it alive until 19:00.

---

## Reserve emission site inventory (symbol-anchored)

Each site must respect INV-H. Anchored to symbols (line numbers drift ±4-13 vs HEAD per P2-11).

| # | Anchor | Current flooring | Rev 3 change |
|---|---|---|---|
| 1-6 | `_floor_reserve` emits in attain/peak-buffer/drain-park paths (around `energy_battery.py:3933/3956/3997/4720/4774/5013`) | floored via `_floor_reserve(existing, effective_reserve, hold_depth)` (`:3855`, pure function) | unchanged. |
| 7-16 | 10 full-hold / partial_hold / discharge-with-floor emits inside the inclement + TOU ladders (around `:5820-5994`) | `decision.reserve_floor` / `effective_reserve = max(reserve_soc, decision.reserve_floor)` / `max(soc-5, effective_reserve)` | unchanged (consume `decision.reserve_floor` which now carries the bounded blind cap by construction). |
| 17 | arbitrage emit (`_floor_reserve` wrap) around `:6098` | floored | unchanged. |
| 18 | off-peak drain `reserve_level=drain_target` around `:6238` | **already clamped by `drain_target = max(drain_target, effective_reserve)` under partial_hold** (`:~6223`) — P2-11 correction, **not a leak**. | no change. D-pass keeps a mutation here as a regression anchor. |
| 19 | off-peak hold emit around `:6265` (`hold_reserve`) | floored via `_floor_reserve` | unchanged. |
| 20 | WAIT narration floor around `:6687` | `_floor_reserve` | unchanged. |
| 21 | **blind de-escalation reserve write at `:5667-5673` writing `int(self.reserve_soc)` UNFLOORED** | — | **D-blind:** entire branch routes through `_result(current_mode, reason, current_mode, reserve_level=decision.reserve_floor, charge_from_grid=False)` so the floor is applied uniformly. The de-escalation CFG `turn_off` is appended to the same `_result` return's `actions` list (one return per tick). |
| 22 | **NEW blind pre-emit (D-blind)** | — | emitted through `_result` with `reserve_level = decision.reserve_floor`. Diff + stamp handled by existing `_result`. |
| 23 | EVSE overlay `_apply_evse_battery_hold` (`energy.py:_apply_evse_battery_hold`, called at `:6459` and `:7174`) | max()-safe post-decision | **re-verify** at both call sites (reviewer B). No code change expected. |
| 24-25 | Drain-precedence ledger `energy_drain_precedence.py:68, 98` | writes consume `effective_reserve` passed in | re-verify consumer still receives the post-fusion `effective_reserve`. No change expected. |

**D-pass must mutation-anchor every site in this table.** The only new code path is site 21+22 (the blind branch); everything else is "unchanged by construction because `decision.reserve_floor` is where the cap lives".

---

## How NWS alerts work + trustworthiness (narrowed)

### Live payload (verified 2026-10-15)

Fields present on each `alert ∈ sensor.nws_alerts_gps_….attributes.Alerts`: `Event, ID, URL, Headline, Type, NWSCode, Status, Severity, Certainty, Sent, Onset, Expires, Ends, AreasAffected, Description, Instruction`. **Fields NOT present:** `MessageType`, `Urgency`, `Effective`. The plan consumes `Type, NWSCode, Status, Severity, Certainty, Onset, Expires, Ends, AreasAffected, Event` only.

`AreasAffected` is a `;`-separated STRING. Area count = `len([s for s in str(AreasAffected).split(";") if s.strip()])`.

### Expires vs Ends (cited)

- CAP v1.2 §3.2.2 — `Expires` is "the point at which the information is to be considered stale" ([CAP v1.2 Guide](https://www.weather.gov/media/alert/CAP_v12_guide_03-07-2017.pdf)).
- NWS extends CAP with `Ends` for hazard end ([NWS Web API](https://www.weather.gov/documentation/services-web-api), [openapi.json](https://api.weather.gov/openapi.json)).
- NWS 2023 CAP User Training notes `Expires` ≠ `eventEndingTime` ([deck](https://www.weather.gov/media/wrn/calendar/2023NWS-CAP-User-Training.pdf)).
- Tonight: `Expires=Onset=04:00, Ends=19:00` — the message is superseded at Onset by an Update; the hazard runs through 19:00. **D-ends keeps the hold alive to `Ends`.**

### Point-filtering (inferred, non-load-bearing)

Our `nws_alerts` integration resolves `30.3146,-98.0159` to zone `TXZ192` + county `TXC453`; the API returns alerts whose `AreasAffected` overlaps either UGC. URA does NOT re-filter (Non-goal 4). Marked *inferred*.

### Trust table (operator-reviewable; feeds the code-default-tier dict)

Scoring reads directly off the 5.8-year audit at `docs/planning/AUDIT_nws_alert_history_lakeway.md`.

| NWSCode | Event | Lakeway fires (5.8y) | Code default tier | Breadth-sensitive? | Keep in default set? |
|---|---|---|---|---|---|
| `TOR` | Tornado Warning | 5 | warn | No | YES |
| `TOA` | Tornado Watch | 11 | watch | **Yes** (area ≥ 20 → notice) | YES |
| `SVR` | Severe T-storm Warning | 131 (county, polygon over-counts) | warn | No (polygon over-count is a known limitation; see Parked V4) | YES |
| `SVA` | Severe T-storm Watch | 44 | watch | **Yes** (area ≥ 25 → notice) | YES |
| `WIY` | Wind Advisory | **33** | watch | No | **YES (new)** |
| `WIH` | High Wind Warning | **0** | warn | No | **NO** (retire — never fires here; operator can re-add) |
| `HWA` | High Wind Watch | 0 | watch | No | NO (symmetric with WIH; operator can re-add) |
| `WSW` | Winter Storm Warning | 9 | warn | No | YES |
| `WSA` | Winter Storm Watch | 5 | watch | No | YES |
| `ISW` | Ice Storm Warning | 1 | warn | No | YES |
| `EWW` | Extreme Wind Warning | 0 | warn | No | YES (consequence > base-rate justifies keeping) |
| `BZW` | Blizzard Warning | 0 | warn | No | YES (consequence > base-rate) |
| `HUR`/`TRW` | Hurricane/Tropical | 0 | warn | No | YES (consequence) |

**Default code set (post-D-match): `{TOR, TOA, SVR, SVA, WIY, WSW, WSA, ISW, EWW, BZW, HUR, TRW}`.** `WIH`/`HWA` retired by default per audit; operator-reinstatable via `CONF_INCLEMENT_POWER_THREAT_EVENT_CODES`.

### Severity × Certainty rules (resolves P2-07, P2-12)

- Primary gate: `NWSCode ∈ code set`.
- `code_default_tier` from `INCLEMENT_CODE_DEFAULT_TIER: dict` (rung 1, authoritative). Codes present in the operator's set but missing from the dict default to `watch`.
- `certainty_tier(c)`: `Observed → warn`, `Likely → warn`, `Possible → watch`, `Unlikely → watch` (P2-07 fix), `Unknown → watch`.
- Tier = `min(code_default_tier, certainty_tier)`.
- Breadth-demote: if the trust table marks the code breadth-sensitive and `area_count ≥ threshold`, demote `watch → notice`.
- **Severity demote on code-match path = REMOVED.** Severity emitted in attrs only.
- Name-match fallback (used only when `NWSCode` is empty/missing): keeps the current v5.5.0 severity-demote and product-folding ("...Warning" → warn) for back-compat; same tier model.

### Legacy list migration (resolves P2-13)

`CONF_INCLEMENT_POWER_THREAT_EVENTS` (saved as a list of name keywords; current default excludes "Wind Advisory") is READ on setup. If the operator has not customised it (equals the shipped default), it is auto-migrated and dropped from options; a repair notice records the migration. If the operator has customised it, it is RESPECTED on the name-fallback path (never overrides the code set — union semantics: an alert is a threat iff code matches OR name-fallback matches). Code path never consults the legacy list.

---

## Deliverables

### D-match — code-based matching + Wind Advisory (improves on substring/name list)

**Concrete improvement:** adds WIY (audit: 33 fires in 5.8y, dominant local wind event); retires WIH/HWA from default (audit: 0 fires); gate is byte-exact NWSCode so locale changes cannot regress. Name-match fallback keeps alerts whose `NWSCode` is empty working.

**Change (symbol-anchored):**
- `inclement.py:141-149` `_event_matches_threat` replaced by `_classify_event(alert, code_set, legacy_names) → (matched: bool, code_default_tier: str)` using `INCLEMENT_CODE_DEFAULT_TIER` dict (new const in `energy_const.py`) and the legacy name set as fallback when `NWSCode` is empty.
- `inclement.py:218-245` severity-demote retained ONLY on the name-match branch.
- `_classify_event` consumer in `classify()` (`:216-220`) threads `code_default_tier` into the tier calculation.
- New `energy_const.py` constants: `INCLEMENT_CODE_DEFAULT_TIER` (dict rung 1), `DEFAULT_INCLEMENT_POWER_THREAT_EVENT_CODES` (list rung 2 options), breadth thresholds `INCLEMENT_BREADTH_DEMOTE_AREA_COUNT_TOA = 20`, `..._SVA = 25` (rung 1).
- Legacy list migration (one-shot at setup).

**Acceptance:**
- **Verify:** WIY/Moderate/Likely with `area_count=33` ⇒ `tier=watch` (no breadth-demote on WIY).
- **Verify:** TOA with `area_count ≥ 20` ⇒ `tier=notice`.
- **Verify:** FLA (not in set) ⇒ gated out (no name match either).
- **Verify:** Alert with empty `NWSCode` + Event="Tornado Warning" ⇒ matched via name fallback → warn.
- **Verify:** Legacy list that still equals v5.5.0 default auto-migrates on setup; repair notice created.
- **Test:** `test_match_wiy_wind_advisory`, `test_toa_broad_demotes_to_notice`, `test_area_count_split_semicolon`, `test_name_fallback_when_nwscode_empty`, `test_legacy_list_migration_only_when_untouched`, `test_wih_retired_from_default`.
- **Live:** on first post-ship real WIY, `inclement_tier=watch` and `inclement_contributing_event=Wind Advisory` visible on `sensor.ura_energy_coordinator_battery_strategy`.

### D-ends — hazard-window: `Ends` is the primary close (improves on `min(Ends,Expires)`)

**Concrete improvement:** fixes the tonight-case drop-at-Onset bug. Also treats pre-Onset alerts as "not yet active" by filtering, not by introducing a new tier (no new state machine, no new writer).

**Change:**
- Replace `_alert_expires_at(alert)` at `inclement.py:129-138` with:
  - `_hazard_window(alert) → (start_dt | None, end_dt | None)` where `start = Onset or Sent`, `end = Ends or Expires`.
- Filter rule at `inclement.py:201-215`:
  - Drop `status != Actual`.
  - Drop `type != "Alert"` (future-proof; today always "Alert").
  - Drop when `end is not None and now > end`.
  - **Drop (filter out) when `start is not None and now < start`** — pre-onset alerts are treated as "not yet active"; the next tick re-evaluates automatically. **No new tier.**
- Update `_dt_le` call site to use `end` instead of `_alert_expires_at`.
- Public attr `inclement_expires_at` now carries `end` (hazard end), not the CAP message expiry.

**Supersedes v5.5.0 L-criterion** (`PLANNING_inclement_weather_reserve.md:326` "a hold cannot outlive the alert's Expires"). Explicit supersession recorded here and in the ship README.

**Acceptance:**
- **Verify:** Wind Advisory `Onset=04:00, Ends=19:00`, posted 02:30 ⇒ 02:30 classifier returns `tier=none` for this alert (filtered pre-onset); 04:00 ⇒ `tier=watch`; 19:00:01 ⇒ `tier=none` again (post-hazard).
- **Verify:** Alert with `Ends=None, Expires=12:00` ⇒ hazard end falls back to 12:00; drops at 12:00.
- **Verify:** Alert with `Onset=None` ⇒ start falls back to `Sent`; treated as active immediately if `now ≥ Sent`.
- **Test:** `test_wind_advisory_lives_to_ends`, `test_pre_onset_filtered_out`, `test_fallback_to_expires_when_ends_absent`, `test_fallback_to_sent_when_onset_absent`.
- **Live:** on the first real multi-hour alert post-ship, `inclement_hold_depth` tracks `[Onset, Ends]` (not `min(Ends, Expires)`); verifiable via `sensor.ura_energy_coordinator_battery_strategy` state history over the alert window.

### D-blind — decide while blind; emit via `_result`; CFG turn_off survives (improves on short-circuit)

**Concrete improvement:** the Envoy-blind gate now runs `_inclement_decision` before the short-circuit. Attrs stay fresh. Reserve-raise is emitted via the existing `_result` emit path (idempotent diff + `_last_reserve_level_desired` stamp); the write-verify and EVSE-overlay machinery continue to work unchanged. CFG turn_on remains forbidden under blind; CFG turn_off (de-escalation) remains required.

**Change (symbol-anchored):**
- `energy_battery.py:2708` `InclementFusion(...)` constructor gains `blind_floor_knob` arg (default read from new `CONF_INCLEMENT_BLIND_SOC_FREE_FULL_HOLD_FLOOR_PCT`).
- `inclement.py:724-732` `_full_hold_floor(current_soc)` becomes `max(reserve_soc, partial_floor, blind_knob)` when `current_soc is None`; `max(reserve_soc, partial_floor, int(current_soc))` when SOC resolved. **`decision.reserve_floor` is the single source of truth.** No `_full_hold_floor_blind` helper; no `reserve_floor_blind()` method on the frozen dataclass. (P2-03/P2-04.)
- `energy_battery.py:5578-5710` blind-gate branch:
  - Call `decision = self._inclement_decision(tou_period, now)` BEFORE the gate (safe per per-tick cache P2-16).
  - When fully blind AND `decision.hold_depth != allow_discharge`, go through `self._result(current_mode, reason, current_mode, reserve_level=decision.reserve_floor, charge_from_grid=False)` and let `_result` do the diff + stamp. Append the peak de-escalation CFG `turn_off` action to the `_result` return's `actions` list when `_is_peak_or_into_peak and _cfg_currently_on`.
  - When fully blind AND `decision.hold_depth == allow_discharge`, keep the existing blind-pause return pack (plus the pre-existing peak CFG `turn_off`).
- Blind-peak de-escalation freshness check (`:5607-5634`) simplifies to `decision is not None` (always true after the move).
- Do NOT de-dupe the second call at `:5787` (per-tick cache handles it, P2-16).
- Signal fires only on `(tier, depth)` change (`:2733-2737`); now additionally fires on blind ticks when the decision transitions — fine, consumers verified non-blocking.

**Acceptance:**
- **Verify:** `inclement_tier`, `inclement_source`, `inclement_hold_depth`, `inclement_reserve_floor` all update within one tick after Envoy drops with a qualifying active alert.
- **Verify:** on a steady blind hold, **zero** reserve writes after the first (diff suppression via `_result`).
- **Verify:** on a blind transition from allow_discharge → partial_hold → full_hold, exactly ONE reserve write per floor change.
- **Verify:** blind + peak + CFG currently on + `decision.hold_depth=full_hold` ⇒ exactly ONE CFG `turn_off` emitted; no CFG `turn_on` ever.
- **Verify:** `write_verify` does not alarm during a blind partial_hold (reads `decision.hold_depth` and the stamped `_last_reserve_level_desired`); one-line extension to recognise `full_hold` floor also (P2-12).
- **Verify (INV-H config extreme):** `reserve_soc=20`, `partial_floor=80`, `blind_knob=60`, blind + off_peak + corroborated-watch → `full_hold`, `decision.reserve_floor = max(20, 80, 60) = 80`; `_result` emits 80. (P2-04)
- **Test (mutation-anchored):** `test_inclement_blind_runs_decide`, `test_blind_full_hold_floor_is_decision_reserve_floor`, `test_blind_floor_respects_partial_floor_inversion`, `test_blind_peak_cfg_turn_off_survives` (P2-06), `test_blind_no_cfg_turn_on`, `test_blind_steady_hold_no_repeat_writes`, `test_blind_decision_signal_fires`, `test_write_verify_silent_during_blind_hold` (P2-12).
- **Live (per P2-15):** no restart or firewall-games required. (a) in-suite mutation-anchored proof is primary. (b) on the next organic Envoy-blind episode, read `command_trail` + the actuator entity history (`number.enphase_envoy_…_reserve_soc` state log + the write-verify logbook); expect reserve writes to show the fusion-bounded floor during the blind window, with CFG unchanged (except a possible single de-escalation turn_off).

### D5 — observability (small; attrs + README)

Add attrs on the inclement sensor (REUSE/EXTEND `_inclement_attrs` at `energy_battery.py:2764-2805`): `inclement_hazard_start` (new, was implicit), `inclement_hazard_end` (replaces/aligns `inclement_expires_at` meaning), `inclement_blind_decision_emitted` (bool), `inclement_recent_events` (rolling 20-entry, 24h window). `inclement_source` is REUSE/EXTEND (already present at `:2779, 2801`).

Update the precedence comment at `energy_battery.py:5728-5772` to reflect "decide-before-blind" ordering (6 steps).

**Acceptance:**
- **Verify:** attrs present post-restart; stable on no-event tick.
- **Verify:** `inclement_blind_decision_emitted = True` only during full-blind-with-hold.
- **Live:** developer-tools shows attrs; no deprecation warnings.

### D6 — Enphase Storm Guard coexistence (one line)

**Operator-cut per `operator_instruction_2026_10_15_b`:** URA is the measured storm guard; Enphase's indiscriminate one should be off. ONE README line: *"Rev 3 reminder: Enphase Storm Guard (Enlighten app) should be OFF. URA is the storm authority — see `inclement_hold_depth` on `sensor.ura_energy_coordinator_battery_strategy`."* No attr, no code read, no detection logic.

---

## Non-goals (Rev 3)

1. Do not read Enphase Storm Guard state (one-line README only).
2. Do not add a `_paused_by_storm` set to `energy_pool.py`.
3. Do not change the arbitrage-WAIT floor plumbing (v5.5.3 settled).
4. Do not polygon-geo-filter in URA; rely on `nws_alerts` zone/county UGC.
5. Do not emit `charge_from_grid=True` writes under full-blind (INV-B).
6. **Do not introduce a `pending` tier or a pre-charge CFG writer.** Pre-onset alerts are filtered as not-yet-active.
7. **Do not introduce a forecast tier.** D-forecast is PARKED with evidence; see §Parked.
8. Do not consume `MessageType`, `Urgency`, or `Effective` (not in the integration's payload).
9. Do not persist an alert ledger to the URA DB (D5 attribute-only).
10. Do not re-litigate v5.5.0 invariants beyond the explicit Expires→Ends supersession.

---

## Knob ladder (Rev 3)

Only knobs this cycle **changes** or **adds**. Everything else from v5.5.0 is kept.

| Name | Rung | Default | Bound | Why |
|---|---|---|---|---|
| `CONF_INCLEMENT_POWER_THREAT_EVENT_CODES` | 2 (options) | `{TOR, TOA, SVR, SVA, WIY, WSW, WSA, ISW, EWW, BZW, HUR, TRW}` | — | Per-deployment code gate (audit-driven default). |
| `CONF_INCLEMENT_POWER_THREAT_EVENTS` (legacy) | 2 (options) | existing | — | KEEP as name-match fallback; auto-migrated when equals v5.5.0 default. |
| `CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION` | 2 (options) | True | — | PROMOTED from hidden (was `energy_const.py:621` hidden). |
| `CONF_INCLEMENT_WARN_MIN_SEVERITY` | 2 (options) | existing `Severe` | — | KEEP for legacy name-match path only; unused on code-match path; candidate removal `<ship+1>`. |
| `CONF_INCLEMENT_BLIND_SOC_FREE_FULL_HOLD_FLOOR_PCT` | 3 (live Number) | **60** | 50-100 | NEW: bounds `_full_hold_floor` under SOC-None blind so overnight blind watches don't pin at 100. Enforced as `max(reserve_soc, partial_floor, knob)` so inversion-safe. |
| `INCLEMENT_CODE_DEFAULT_TIER` | 1 (dict const) | per trust table | — | Authoritative code→tier; codes outside dict default `watch`. Rung 1 because changes alter decision topology. |
| `INCLEMENT_BREADTH_DEMOTE_AREA_COUNT_TOA` | 1 (const) | 20 | — | breadth threshold. |
| `INCLEMENT_BREADTH_DEMOTE_AREA_COUNT_SVA` | 1 (const) | 25 | — | breadth threshold. |
| `INCLEMENT_RECENT_EVENTS_WINDOW_H` | 1 (const) | 24 | — | rolling attr window. |
| `INCLEMENT_RECENT_EVENTS_MAX` | 1 (const) | 20 | — | rolling attr bound. |

**Removed from the plan vs Rev 2:** `CONF_INCLEMENT_FORECAST_*` (all 5 — D-forecast parked), `CONF_INCLEMENT_ONSET_PRECHARGE_LEAD_MIN` (no precharge writer), `INCLEMENT_DECISION_FRESH_S` (collapsed to `decision is not None`), `INCLEMENT_FORECAST_SERVICE_TIMEOUT_S`, `INCLEMENT_D4B_*` (D4b replaced by Lakeway audit, no runtime knob needed).

---

## Parked — with revival triggers

### D-forecast (hourly forecast corroboration)

**Why parked (evidence):**
1. Our configured hourly provider `weather.nws_30_314635_98_015861_kryw` carries fields `{datetime, precipitation_probability, condition, wind_bearing, temperature, dew_point, wind_speed, humidity}` — **NO `wind_gust_speed`**. Gust-threshold corroboration (the mechanism most closely tied to local tree-on-line outages per the audit) is not implementable on this provider today.
2. Tonight's hourly precipitation peak is **43 %**; any defensible default threshold is ≥ 50 %. The forecast would NOT corroborate the live case anyway.
3. Building the feature requires a new async cache + `async_track_time_interval` lifecycle + staleness semantics + first-tick-after-boot behaviour (P2-09, P2-10). Each is a Tier-3 risk ingredient. Marginal benefit vs the simpler fixes (D-match + D-ends + D-blind) is small-and-unevidenced right now.
4. Operator posture (`operator_instruction_2026_10_15_b`): "I won't rebuild for fun. It has to be an actual improvement." Rev-2's D-forecast did not clear that bar.

**Revival trigger:** any ONE of —
- Our hourly provider begins publishing `wind_gust_speed` (verify via `weather.get_forecasts` probe quarterly), AND the audit shows ≥1 missed outage event in a window where forecast corroboration would have fired on gust.
- Operator adds a second hourly provider that carries `wind_gust_speed` and provider agreement ≥2 becomes feasible.
- A post-ship audit on D-match/D-ends/D-blind shows a measurable "hold-arrived-late" cost (e.g. a WIY that posted mid-dropout: forecast would have triggered pre-emptive hold earlier).

**Design sketch (for revival):**
- Owner: `WeatherProviderManager` (not `energy_battery.py`). Timer: `async_track_time_interval`, unsub appended to `self._unsub_handles` (`weather_manager.py:188-221`); refresh runs through `_pending_refresh_tasks`; WPM-C1 re-entrancy guard covers it (P2-09).
- Immediate first refresh in `async_setup` (pattern at `weather_manager.py:~205`). "Never-fetched" distinct attr value from "stale" (P2-10).
- Forecast-only hold tier emitted as `tier=notice, source=forecast` (NOT `watch`) — mirrors existing condition-only path (`inclement.py:707-716`) for consumer symmetry (P2-14).
- Hysteresis / min-dwell to prevent reserve-write flap across refresh-staleness boundary (P2-10).

### V2 — mid/peak forecast × Solcast hold
Deferred until D-forecast ships and ≥1 missed peak-outage logged in a 90-day post-ship audit.

### V3 — URA reads Storm Guard then concedes
Card `EC-STORM-GUARD-COEXIST-1`; triggered only if operator's "turn it off and hope it sticks" fails measurably.

### V4 — Polygon-tight geo filtering (Shapely)
Trigger: post-ship audit shows UGC-wide feed produces >25 % false-positive hold-hours. SVR polygon over-count (audit §Finding 2) is the specific candidate.

---

## Producer / Consumer map (narrowed)

### Producer dependencies for `InclementDecision`

- `AlertClassification` — adds `(Onset, Ends, NWSCode, Type, AreasAffected-split)` reads (defensive, all optional).
- `StormConditionResult` — unchanged (state-only).
- `SolarHorizon` — unchanged.
- `current_soc` — 3-tier (EC p1).
- `tou_period` — unchanged.

### Consumers (symbol-anchored)

| Site | Symbol / anchor | Trust/display | Rev 3 change |
|---|---|---|---|
| decision cache | `energy_battery.py:_inclement_decision :2663`, cache store `:2734-2735` | internal | now reached pre-blind. |
| signal dispatch | `energy_battery.py:2737-2751` (`SIGNAL_INCLEMENT_STATE_CHANGED`) | trust (consumers may act) | now fires on blind ticks when `(tier, depth)` changes. |
| `_inclement_attrs` | `energy_battery.py:2764-2805` | display | new siblings (D5); `inclement_source` extends additively. |
| `_result` reserve emit path | `energy_battery.py:_result :~6278` (via `_last_reserve_level_desired` stamp `:5768-5772`) | trust | D-blind reuses it. |
| determine_mode precedence | `energy_battery.py:5787` | trust | preserved. |
| blind-gate branch | `energy_battery.py:5578-5710` | trust | D-blind restructures (`_result` emit, CFG turn_off preserved). |
| `_precharge_refused_on_blind` | `energy_battery.py:4110-4150` | trust (freshness) | unchanged (no precharge writer added). |
| EVSE overlay | `energy.py:_apply_evse_battery_hold` called at `:6459, :7174` | trust | re-verify max()-safe at both. |
| write-verify partial-floor | `energy_write_verify.py:_inclement_partial_hold_floor :1647-1662` | trust | one-line extension to recognise full_hold floor too (P2-12). |
| write-verify reserve check | `energy_write_verify.py:1756` | trust | compares against `_last_reserve_level_desired` as today; D-blind's `_result` stamp makes this coherent during blind. |
| DP ledger | `energy_drain_precedence.py:68, 98` | trust | re-verify (expected unchanged). |
| dashboard sensor | `sensor.py:9256-9308` | display | new tier values additive (no new tier string; code-set changes do not change tier vocabulary). |

---

## Recommended sequencing

1. **D-match** first (no `determine_mode` touch; smallest Tier-3 surface; audit-grounded default).
2. **D-ends** second (small helper refactor; carries the v5.5.0 supersession).
3. **D-blind** third (precedence-chain move; depends on D-match + D-ends being correct so the decision it moves above the gate is correct).
4. **D5** + **D6** land with the ship.

Each of D-match/D-ends/D-blind is independently reviewable Tier-3 four-framing (including adversarial-completeness D-pass). D-blind is INV-H's load-bearing site; D-pass re-enumerates every reserve-emission site (§Reserve emission site inventory) and mutation-anchors each — but note P2-11: the only NEW site is #22 (blind pre-emit via `_result`); site #21 (blind de-escalation) changes from unfloored hand-written to `_result`-routed. All others are unchanged by construction.

---

## Supersession & post-ship audit plan

- **DELETE candidates (`<ship+1>` after live validation):** legacy severity-demote on code-match path; `CONF_INCLEMENT_WARN_MIN_SEVERITY` if the audit shows zero name-fallback events in 30 days. Dead `High Wind` keyword removed on migration.
- **KEEP+DOCUMENT:** v5.5.0 L-criterion is explicitly superseded (recorded in the ship README + this plan).
- **Post-ship audit (30 days):** reconfirm the Lakeway code-default set against live fires; verify breadth thresholds TOA 20 / SVA 25 match live false-positive rate; verify the blind-knob default 60 against observed overnight self-consumption vs reserve-holding tradeoff.

---

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018uEjYPUcWq73wfBS3t1NEa
