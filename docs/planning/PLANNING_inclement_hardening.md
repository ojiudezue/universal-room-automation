# PLANNING — Inclement-Weather Hardening (Reasoning-under-Blind, Threat-Model Matching, Forecast Lookahead)

**Card:** `EC-INCLEMENT-HARDENING-1`
**Tier:** 3
**Status:** `pre_planning` → BUILD-READY after Rev 2 reviews.
**Rev:** **2** (2026-10-15; addresses Plan Review #1 `docs/reviews/code-review/plan_inclement_hardening_review_1.md`).
**Branch target:** `develop`.
**Supersedes behavior shipped in:** v5.5.0 (initial inclement fusion) + v5.5.3 (arbitrage-WAIT floor). **Explicitly supersedes v5.5.0 L-criterion "a hold cannot outlive the alert's Expires"** (`docs/planning/PLANNING_inclement_weather_reserve.md:326`) with the new rule "a hold lives to `Ends`, falling back to `Expires` only when `Ends` is absent" — see §How NWS alerts work and D3.

**Operator thesis (verbatim 2026-10-15):** *"(1) Blind pause: I understand being unable to command but why stop reasoning when you clearly can? (2) Fix the matching. Reason from first principles: is it above medium? What would we act on for inclement weather? We built this so we don't react to things that don't matter that come over alerts, for our GPS coord. (3) Forecast never consulted seems dumb; peering into the future is an advantage."*

**Operator additions 2026-10-15 (second pass):**
1. **Onset handling APPROVED** — *"Read alert start times. YEs"* — D3 is a firm deliverable.
2. **"Already GPS-filtered" is a VERIFY, not a trust.**
3. Trust/predictiveness analysis per event-code; broadness as a trust signal.

**Load-bearing live case (2026-10-15/16, Austin):** NWS hourly rainy / lightning-rainy 01-03 at 43 %, rainy 04-06 at 41 %; Wind Advisory `Severity=Moderate, Certainty=Likely, NWSCode=WIY, Type=Alert, Onset=Expires=04:00, Ends=19:00`, headline "4 AM TO 7 PM"; gusts 40-50 mph; Envoy offline since 17:38; battery ~30 %. **URA produced no inclement hold on any axis.** Each wart below contributed; the plan dissolves each one.

---

## Rev-2 changelog (finding → change)

| Finding | Severity | Section(s) changed | Change |
|---|---|---|---|
| P1-01 | HIGH | §Reserve emission site inventory (NEW); §Supersession; §Deliverables D1 | Replaced "7+1" with a full site table covering 19 `_result(` sites + `_apply_evse_battery_hold` at `energy.py:5239` (called `:6459, :7174`) + `energy_drain_precedence.py:68,98`. All sites now map explicitly to INV-H via `decision.reserve_floor` or `_floor_reserve`. |
| P1-02 | HIGH | §D1 (ordering); §INV-H; §Blind-write composition (NEW); knob ladder | Blind de-escalation reserve write (`energy_battery.py:5667-5673`) now floored by `decision.reserve_floor` when `hold_depth ∈ {partial_hold, full_hold}`; INV-H test includes the `reserve_soc < partial_floor + CFG-on + transition→peak + partial_hold` repro; "D1 pre-emit + de-escalation" ordering locked (single return per tick: whichever branch runs assembles the full action list; no double-emit). |
| P1-03 | HIGH | §Falsifiable invariants (replaced INV-H + new INV-C) | INV-H restated over `decision.hold_depth`; new INV-C (classification) states "actual qualifying NWS alert with `now ∈ [Onset, Ends]` ⇒ `tier ≥ watch`". Reviewer-D job targets both. |
| P1-04 | HIGH | §Discriminator; §Q3; §Knob ladder (`INCLEMENT_BLIND_SOC_FREE_FULL_HOLD_FLOOR_PCT`) | Rebuilt the tonight-case walkthrough against `inclement.py:629-645` + `:724-731`: forecast corroborates **watch**, so off-peak corroborated watch under blind would reach `full_hold` with SOC-None floor **100** — undesirable overnight. Added bounded blind-floor knob `CONF_INCLEMENT_BLIND_SOC_FREE_FULL_HOLD_FLOOR_PCT` (rung 3, default **60**, bound 50-100) that replaces the implicit 100. Explicitly decided: **forecast DOES count as watch corroboration** when ≥2 providers agree, but under blind the floor caps at the knob (default 60), not 100. Discriminator updated accordingly. |
| P1-05 | HIGH | §How NWS alerts work (CAP field table); §D3; §D4 | CAP field table rewritten from the live payload: fields present are `Event, ID, URL, Headline, Type, NWSCode, Status, Severity, Certainty, Sent, Onset, Expires, Ends, AreasAffected, Description, Instruction`. Removed `MessageType`, `Urgency`, `Effective` from the plan (not emitted here). `AreasAffected` is a `;`-separated string; area count = `len([s for s in AreasAffected.split(";") if s.strip()])`. D3 pending trigger = `now < Onset` (no `Urgency` reliance). D4 "MessageType drop" removed; cancellations are handled by the alert vanishing from the sensor's `Alerts` list. |
| P1-06 | MED | §How NWS alerts work; citations | Added URLs: `https://api.weather.gov/openapi.json` (field inventory + `/alerts?point` behaviour), `https://www.weather.gov/documentation/services-web-api`, `https://www.weather.gov/media/alert/CAP_v12_guide_03-07-2017.pdf` (§3.2 info-block fields, Expires semantics), `https://www.weather.gov/media/wrn/calendar/2023NWS-CAP-User-Training.pdf` (Expires vs event ending). Point→UGC behaviour marked *inferred* and non-load-bearing (Non-goal 5). |
| P1-07 | MED | §Supersession (NEW) | Added explicit note superseding v5.5.0 L-criterion ("hold cannot outlive Expires"); D3 adds test `test_wind_advisory_hold_lives_to_ends` + `test_hold_falls_back_to_expires_when_ends_absent`. |
| P1-08 | MED | §Tier model (NEW); §D3; §D5; signal payload | `pending` ranks between `notice` and `watch` in `_TIER_ORDER` (new = `{"none":0, "notice":1, "pending":2, "watch":3, "warn":4}`). `decide()` adds a `pending` branch early-return that maps to `partial_hold` only on off-peak + corroboration (same corroboration rule as watch) OR to the precharge CFG write when `_pending_precharge_eligible(...)` is True. Precharge CFG writer enumerated as the ONLY new CFG writer added by this cycle; gated by `_precharge_refused_on_blind` (`energy_battery.py:4140-4150`) + the breaker chokepoint (`energy.py:_execute_breaker_safe_dispatch :2922`). Signal payload gains optional `pending_onset_at` (back-compat for consumers that key on tier string). |
| P1-09 | MED | §Consumer map | Added `SIGNAL_INCLEMENT_STATE_CHANGED` dispatch (`energy_battery.py:2737-2751`), `sensor.ura_inclement_state` (`sensor.py:9256-9308`), `energy_write_verify.py:_inclement_partial_hold_floor :1647-1662` + the reserve-check site at `:1756`, drain-precedence ledger (`energy_drain_precedence.py:68, 98`). Fixed `:4140` label to "pre-charge-blind trust decision". Fixed EVSE call sites to `energy.py:6459, 7174` (implementation `:5239`). Noted that the signal will now fire on blind ticks too (new emission); consumers verified non-blocking. |
| P1-10 | MED | §D2; §Prior-art scan | Marked forecast fetch REUSE/EXTEND against `weather_manager.py:367-389` (`weather.get_forecasts` daily call) + `aggregation.py:1119-1175` (cached-forecast pattern with per-tick staleness check). Added explicit async refresh spec: `_refresh_forecast_outage_cache()` runs as a tracked `hass.async_create_task` scheduled every `CONF_INCLEMENT_FORECAST_REFRESH_MIN` (default 10 min), tracked via `self._forecast_outage_unsub` with teardown in `async_will_remove_from_hass`. `_inclement_decision` (sync) reads the cache; cache staleness bound `CONF_INCLEMENT_FORECAST_STALE_MAX_MIN` (default 30 min) — stale cache treated as "no forecast signal" (fail-safe, no false hold). |
| P1-11 | MED | §D5; §Prior-art scan | `inclement_source` is REUSE/EXTEND (exists at `energy_battery.py:2779, 2801`). Enumerated downstream string comparisons of `source`: none found via grep outside display sensors; new values `forecast`, `alert+forecast`, `condition+forecast` are additive (back-compat preserved). Dashboard/sensor consumer verified to render arbitrary strings. |
| P1-12 | MED | §Severity/certainty truth table (NEW) | Collapsed Q2 + trust table + D4 Verify into ONE truth-table rule: **tier = min(code_default_tier, certainty_tier) then breadth-demote**; severity floor REMOVED as a demote mechanism (replaces current `inclement.py:235-245` demote with a no-op when code-match is primary; legacy name-match path keeps the severity demote as back-compat). Full table for `{TOR, WIY, SVA, TOA, FLA} × {Observed, Likely, Possible} × {Minor, Moderate, Severe, Extreme}`. |
| P1-13 | LOW | §Knob ladder | Named numbers: `INCLEMENT_RECENT_EVENTS_WINDOW_H`, `INCLEMENT_RECENT_EVENTS_MAX`, `INCLEMENT_DECISION_FRESH_S`, `INCLEMENT_FORECAST_REFRESH_MIN`, `INCLEMENT_FORECAST_STALE_MAX_MIN`, `INCLEMENT_D4B_INCLUSION_MIN_FIRES`, `INCLEMENT_D4B_INCLUSION_MAX_OUTAGE_CORR`, bounded-blind-floor knob (P1-04). Removed `CONF_INCLEMENT_FORECAST_PRE_PEAK_H` (V2 parked). `CONF_INCLEMENT_WARN_MIN_SEVERITY` disposition = KEEP for the legacy name-match path only; removed from code-match path. |
| P1-14 | LOW | §D1 acceptance | Live check now = (a) in-suite proof via `test_inclement_blind_decides_and_emits_reserve_only` (mutation-anchored), (b) a one-shot recorder read on the next organic Envoy-blind episode (grep `energy_write_queue` for a reserve write bearing the "Inclement-under-blind" reason prefix within the dropout window). No firewall-games; no bespoke restart. |
| P1-15 | LOW | §D4b | Named outage-history source: HA recorder history for `sensor.ura_energy_coordinator_grid_connected` (false transitions) + `sensor.span_panel_grid_connected`. Fallback if both too noisy: Envoy production zero + grid-import spike co-incidence in `energy_history`. Both named; if neither correlates cleanly, mark the outage-correlation column as `UNK` and keep the code in the default set only if base-rate (fires/year) ≥ `INCLEMENT_D4B_INCLUSION_MIN_FIRES`. |

---

## Falsifiable invariants (Tier-3, D-pass must break or affirm)

> **INV-H (emission floor, over hold_depth):** when `_inclement_decision(...)` returns a decision with `hold_depth ∈ {partial_hold, full_hold}`, **every reachable reserve emission in the same tick commands `reserve_soc ≥ decision.reserve_floor`.** This covers: all 19 `_result(reserve_level=...)` sites in `energy_battery.py` (see §Reserve emission site inventory), the blind-gate pre-emit (new, D1), the blind-peak de-escalation reserve write at `:5667-5673` (D1), the EVSE overlay `_apply_evse_battery_hold` at `energy.py:5239` (max()-safe; verify at BOTH call sites `:6459, :7174`), the drain-precedence ledger at `energy_drain_precedence.py:68, 98`, and the pending-precharge path.

> **INV-C (classification):** for any `alert ∈ attributes.Alerts` with `Status == "Actual"`, `Type == "Alert"`, `NWSCode ∈ CONF_INCLEMENT_POWER_THREAT_EVENT_CODES`, and `now ∈ [Onset, Ends]` (fallback `[Sent, Expires]` when Onset/Ends absent), the classifier returns `tier ≥ watch`. Pending (future-Onset) and watch-demotion-by-breadth are the only legal exits below watch; forecast-corroboration never lowers the tier.

> **INV-B (blind safety):** under full-blind (`envoy_available=False` AND resolved SOC None after 3-tier fallback), no `charge_from_grid` write may be emitted, regardless of inclement decision. Reserve writes are allowed and must respect INV-H.

Reviewer-D produces legal-config reachable repros that falsify each invariant. Config combinatorics to exercise at extremes: (floor > SOC, floor > current reserve, blind + partial, blind + full-hold, `reserve_soc < partial_floor`, `tou_transition_into=peak` while off_peak, CFG last-commanded=on + partial_hold, forecast-only vs alert-only vs both).

---

## Reserve emission site inventory (replaces "7+1")

All sites that write `reserve_soc`. Each must respect INV-H. Verified against `develop` HEAD.

| # | File:line | Site | Current floor | Post-D1 floor |
|---|---|---|---|---|
| 1 | `energy_battery.py:3926` | attain `_floor_reserve` emit | via `_floor_reserve` (reads live `_last_inclement_decision`) | unchanged — already floored. |
| 2 | `energy_battery.py:3949` | attain `_floor_reserve` emit | same | unchanged. |
| 3 | `energy_battery.py:3991` | attain `_floor_reserve` emit | same | unchanged. |
| 4 | `energy_battery.py:4715` | peak-buffer `_floor_reserve` | same | unchanged. |
| 5 | `energy_battery.py:4769` | peak-buffer `_floor_reserve` | same | unchanged. |
| 6 | `energy_battery.py:5004` | drain-park `_floor_reserve` | same | unchanged. |
| 7 | `energy_battery.py:5820` | full-hold immediate emit (storm precharge refused) | `decision.reserve_floor` | unchanged. |
| 8 | `energy_battery.py:5841` | full-hold normal emit | `decision.reserve_floor` | unchanged. |
| 9 | `energy_battery.py:5857` | full-hold precharge non-storm | `decision.reserve_floor` | unchanged. |
| 10 | `energy_battery.py:5867` | full-hold final emit | `decision.reserve_floor` | unchanged. |
| 11 | `energy_battery.py:5883` | peak partial_hold emit | `effective_reserve = max(reserve_soc, decision.reserve_floor)` | unchanged. |
| 12 | `energy_battery.py:5890` | peak discharge-with-floor | `max(soc-5, effective_reserve)` | unchanged. |
| 13 | `energy_battery.py:5952` | mid_peak `_floor_reserve` | via `_floor_reserve` | unchanged. |
| 14 | `energy_battery.py:5959` | mid_peak hold emit | `hold_reserve` from `_floor_reserve` | unchanged. |
| 15 | `energy_battery.py:5979` | mid_peak partial_hold emit | `effective_reserve` | unchanged. |
| 16 | `energy_battery.py:5994` | mid_peak discharge-with-floor | `max(soc-5, effective_reserve)` | unchanged. |
| 17 | `energy_battery.py:6098` | arbitrage emit | `_floor_reserve` | unchanged. |
| 18 | `energy_battery.py:6251` | off-peak drain `reserve_level=drain_target` | **unfloored by inclement today** — reviewer-D target; verify `_last_inclement_decision` consulted via `_floor_reserve` wrap. | **CHANGE:** wrap in `_floor_reserve(drain_target, decision)` so partial_hold raises it. |
| 19 | `energy_battery.py:6271` | off-peak hold emit | `hold_reserve` | unchanged (already floored). |
| 20 | `energy_battery.py:6687` | WAIT narration floor | `_floor_reserve` | unchanged. |
| 21 | **`energy_battery.py:5667-5673` (blind de-escalation)** | writes `int(self.reserve_soc)` **unfloored** | — | **D1 CHANGE:** `max(int(self.reserve_soc), decision.reserve_floor)` when `decision.hold_depth != allow_discharge`. |
| 22 | **`energy_battery.py:~5578` (NEW blind pre-emit)** | — | — | **D1 NEW:** `decision.reserve_floor` (SOC-free). |
| 23 | `energy.py:5239` (`_apply_evse_battery_hold`), called `:6459` + `:7174` | EVSE overlay | max()-safe post-decision | **re-verify** at both call sites; unchanged in theory but reviewer-B owns it. |
| 24 | `energy_drain_precedence.py:68` | DP ledger write | consumes `effective_reserve` | re-verify consumes `_last_inclement_decision` floor. |
| 25 | `energy_drain_precedence.py:98` | DP ledger write | same | re-verify. |

**Three leaks fixed by D1:** site 18 (off-peak drain), site 21 (blind de-escalation), + site 22 is new (gained, not leaked). Mutation anchor for D-pass: temporarily neuter `_floor_reserve` to pass-through at ONE site at a time; the test suite must fail with a site-specific name. Any site whose mutation leaves the suite green = unanchored = unacceptable.

---

## How NWS alerts work + trustworthiness (Rev-2: live-payload grounded)

### CAP fields actually present on `sensor.nws_alerts_gps_30_3146_98_0159_nws_alerts_alerts.attributes.Alerts[i]`

Verified from the live sensor at 2026-10-15. Fields emitted:

| Field | Example value tonight | Load-bearing use |
|---|---|---|
| `Event` | "Wind Advisory" | legacy name-match fallback. |
| `ID` | opaque CAP id | de-dupe only (not used today). |
| `URL` | NWS CAP link | display. |
| `Headline` | "...WIND ADVISORY REMAINS IN EFFECT FROM 4 AM TO 7 PM..." | display. |
| `Type` | `"Alert"` | drop non-`Alert` values (future-proof; today it's always "Alert"). |
| `NWSCode` | `"WIY"` | **PRIMARY GATE** post-D4. |
| `Status` | `"Actual"` | drop non-Actual (`inclement.py:208`). |
| `Severity` | `"Moderate"` | tiebreaker only in truth table (not a demote in code-match path). |
| `Certainty` | `"Likely"` | tier assignment per truth table. |
| `Sent` | ISO datetime | message timestamp (fallback for `[Sent, Expires]` window). |
| `Onset` | `"2026-10-16T04:00:00-05:00"` | **D3**: hazard start; `pending` when `now < Onset`. |
| `Expires` | `"2026-10-16T04:00:00-05:00"` | message freshness (often `= Onset` on long advisories, superseded by Update at onset). |
| `Ends` | `"2026-10-16T19:00:00-05:00"` | **hazard end — primary window close.** |
| `AreasAffected` | `"Travis; Hays; Blanco; ...; (33 names)"` | **`;`-separated STRING**, not a list. `area_count = len([s for s in str(AreasAffected).split(";") if s.strip()])`. |
| `Description`, `Instruction` | prose | display. |

**Fields NOT present in this integration's payload (removed from plan):** `MessageType`, `Urgency`, `Effective`. The `nws_alerts` integration does not forward them (verified by live payload inspection). Any dependency on these in Rev-1 is dropped.

**Cancellation handling:** when NWS issues a Cancel, the alert vanishes from the sensor's `Alerts` list on the next poll (the integration prunes). URA needs no `MessageType==Cancel` early-drop; the alert simply disappears. Covered by `test_alert_disappears_releases_hold`.

### Expires vs Ends — the tonight-case gotcha (cited)

- `Expires` = *CAP message expiry* (per [CAP v1.2 §3.2.2](https://www.weather.gov/media/alert/CAP_v12_guide_03-07-2017.pdf) and [NWS 2023 CAP User Training](https://www.weather.gov/media/wrn/calendar/2023NWS-CAP-User-Training.pdf): "the point at which the information is to be considered stale"). NWS commonly sets `Expires = Onset` on long-duration advisories because the message is superseded by an Update at onset.
- `Ends` = NWS-specific *hazard end* field (not in CAP core; NWS extension documented at [https://www.weather.gov/documentation/services-web-api](https://www.weather.gov/documentation/services-web-api) and [https://api.weather.gov/openapi.json](https://api.weather.gov/openapi.json)).
- **Correct URA semantics (D3):** `_hazard_window(alert) = (Onset or Effective or Sent, Ends or Expires)`; `_message_fresh_at(alert) = Expires or Ends`. Keep the alert while `now ≤ _hazard_window.end`; classify `pending` while `now < _hazard_window.start`.
- **Supersedes v5.5.0 L-criterion** "a hold cannot outlive the alert's Expires" (`PLANNING_inclement_weather_reserve.md:326`). The old rule was wrong when `Expires = Onset`: it ended the hold at hazard start.

### Point-filtering (inferred, non-load-bearing per Non-goal 5)

- The HA `nws_alerts` integration is configured here `configuration_type: "GPS Location"`, `gps_location: 30.314635,-98.015861`.
- **INFERRED** (per [NWS API docs](https://www.weather.gov/documentation/services-web-api) + the Alerts Geolocation Guide referenced there): `/alerts?point=lat,lng` resolves to the forecast zone (UGC Z-code) + county (UGC C-code) containing the point and returns alerts whose `AreasAffected` overlaps either. Polygon intersection is NOT performed by the public API for point queries. This is **not load-bearing in URA** — Non-goal 5 forbids URA from re-filtering.

### Trust table (per NWSCode)

Scored by (a) outage mechanism credibility at this GPS, (b) typical breadth of issuance (wide → trust penalty applied via breadth-demote), (c) base rate here.

| NWSCode | Event | Default tier | Breadth-demote? | Note |
|---|---|---|---|---|
| `TOR` | Tornado Warning | warn | No | Point-like, high outage rate. |
| `TOA` | Tornado Watch | watch | Yes (area_count ≥ 20 ⇒ notice) | Broad precursor. |
| `SVR` | Severe T-storm Warning | warn | No | Line/tree outage mechanism. |
| `SVA` | Severe T-storm Watch | watch | Yes (area_count ≥ 25 ⇒ notice) | Broad precursor. |
| `WIY` | Wind Advisory | watch | No | Trees here are dominant outage; mechanism is credible regardless of breadth. |
| `WIH` | High Wind Warning | warn | No | — |
| `HWA` | High Wind Watch | watch | No | — |
| `EWW` | Extreme Wind Warning | warn | No | — |
| `WSW` | Winter Storm Warning | warn | No | Rare, high-consequence. |
| `WSA`/`WSY` | Winter Storm Watch/Advisory | watch | No | — |
| `ISW` | Ice Storm Warning | warn | No | 2021 outage mechanism. |
| `BZW` | Blizzard Warning | warn | No | — |
| `HUR`/`TRW` | Hurricane / Tropical | warn | No | Slow; forecast tier often fires first. |
| `FFW`/`FLW`/`FLA` | Flood (any) | notice | — | OUT of default threat set. |
| `HTA`/`HTY` | Heat (any) | notice | — | OUT. |
| `AQA` | Air Quality | notice | — | OUT. |
| `SPS` | Special Weather Statement | notice | — | OUT (admin). |
| `DSW` | Dust Storm Warning | notice | — | OUT here. |

**Breadth-demote constants (rung 1):** `INCLEMENT_BREADTH_DEMOTE_AREA_COUNT_TOA = 20`, `INCLEMENT_BREADTH_DEMOTE_AREA_COUNT_SVA = 25`. Confirmed by D4b.

### Severity × Certainty × Code truth table (resolves P1-12)

**Rule:** `tier = min(code_default_tier, certainty_tier)`, then apply breadth-demote per table above. **No severity-based demote in the code-match path** (removed from `inclement.py:235-245` when code match succeeds). Severity-demote retained ONLY on the legacy name-match fallback path, for one release.

`certainty_tier`: `Observed → warn`, `Likely → warn`, `Possible → watch`, `Unlikely → notice`, `Unknown → watch`.

Full truth table for load-bearing combinations:

| Code | code_default | Certainty | pre-breadth tier | area_count | post-breadth tier |
|---|---|---|---|---|---|
| TOR | warn | Observed | warn | — | warn |
| TOR | warn | Likely | warn | — | warn |
| TOR | warn | Possible | watch | — | watch |
| WIY | watch | Observed | watch | 33 | watch (no breadth-demote for WIY) |
| WIY | watch | Likely | watch | 33 | watch *(tonight's live case)* |
| WIY | watch | Possible | watch | 33 | watch |
| SVA | watch | Observed | watch | 10 | watch |
| SVA | watch | Observed | watch | 30 | notice (breadth) |
| TOA | watch | Likely | watch | 25 | notice (breadth) |
| FLA | notice | any | notice | any | notice (OUT by default) |

**Severity is observability-only** post-D4: emitted in attrs for the operator but not used to lower tier in the code-match path. `CONF_INCLEMENT_WARN_MIN_SEVERITY` retained for legacy fallback path and removable in `<ship+1>`.

### URA alert ledger

No URA-side alert ledger today (grep `alert_history|inclement.*log`: 0 matches). D5 adds `inclement_recent_events` as a 24h-rolling 20-entry attr for post-ship audit. No DB table.

---

## Institutional context verified (Rev-2 additions)

### Code read end-to-end / partial during scoping

- `domain_coordinators/energy_battery.py` — Envoy-blind gate `:5578-5710`; last-decision cache `:780-783, :2663-2735`; `_inclement_decision` dispatches `SIGNAL_INCLEMENT_STATE_CHANGED` `:2737-2751`; `_inclement_attrs` `:2764-2805` (`inclement_source` already emitted `:2779, 2801`); `_floor_reserve` `:3855`; 19 `_result(reserve_level=...)` sites catalogued in §Site inventory; `_precharge_refused_on_blind` `:4110-4150`; **blind-peak de-escalation `:5607-5684` writes `reserve_soc` UNFLOORED at `:5667-5673` — INV-H leak fixed in D1.** Precedence comment `:5728-5772`.
- `domain_coordinators/inclement.py` — `AlertClassifier.classify` `:152-266`; substring threat match `_event_matches_threat :141-149`; `_alert_expires_at :129-138` = `min(Ends, Expires)` (bug: used as window close); `_TIER_ORDER :269` currently 4 tiers (expands to 5 for `pending`); `InclementFusion.decide :564-720`; **off-peak corroborated watch returns `full_hold` with `_full_hold_floor` `:629-645, :724-731` returning 100 under SOC None** — load-bearing for the tonight-case recomputation (see §Discriminator).
- `domain_coordinators/weather_manager.py` — `current_storm_condition :785-843` state-only; **`get_forecasts` already called at `:367-389` (daily, for freeze/condition path)** — D2 REUSES this plumbing.
- `aggregation.py:1119-1175` — cached-forecast pattern with `hass.data`-stashed response + per-tick staleness check. **D2 REUSES the pattern.**
- `energy_write_verify.py:1541-1662, 1716-1756` — `_inclement_partial_hold_floor` reads live `_last_inclement_decision`; INV-H consumer. Verifies reserve writes under hold; must not false-alarm on blind reserve emits (D1 reason-prefix matched).
- `sensor.py:9256-9308, 9642, 9664, 9733` — `sensor.ura_inclement_state` and the forecast-cache readers.
- `energy_drain_precedence.py:68, 98` — DP ledger reserve writes.
- `signals.py:120` — `SIGNAL_INCLEMENT_STATE_CHANGED`.
- `translations/en.json` + `strings.json` — label targets.

### Prior planning docs / READMEs / memory consulted

- `docs/planning/PLANNING_inclement_weather_reserve.md` — v5.5.0 FINAL. **L-criterion :326 explicitly SUPERSEDED by this cycle.** Grep for forecast-lookahead keywords: 0 matches → omitted, not rejected.
- `docs/planning/PLANNING_arbitrage_wait_inclement_floor.md` — v5.5.3 WAIT floor; untouched. D-pass re-sweep covers the new blind-emit alongside WAIT.
- `docs/readmes/README_v5.5.0.md` — storm_forecast = hold_depth != allow_discharge.
- Memory `project_v5_5_0_inclement_weather_shipped.md`, `project_inclement_arbitrage_wait_floor_gap.md`, `project_enphase_coupling_tier.md`.

### Prior-art scan + REUSE / BUILD verdicts

| Proposed piece | Grep | Verdict | File:line |
|---|---|---|---|
| Classify / fusion primitives | `AlertClassifier\|InclementFusion` | **REUSE**; extend internals. | `inclement.py:152, 545` |
| Blind-decide + reserve-only emit | `envoy_avail and soc is None` | **BUILD-NEW.** | `energy_battery.py:5578` |
| Blind-de-escalation floor | `:5667-5673` | **BUILD-NEW** `max()` with `decision.reserve_floor`. | `energy_battery.py:5667` |
| LKG / cloud SOC fallback | EC p1 3-tier SOC resolver | **REUSE** (reconfirm at build). | — |
| NWSCode primary match | `NWSCode` | **BUILD-NEW** code-set gate. | `inclement.py:141` |
| Word-boundary name fallback | existing substring | **BUILD-NEW** replace substring. | same |
| Breadth-demote (area_count via `;`-split) | `AreasAffected` | **BUILD-NEW**. | same |
| `pending` tier (rank + decide branch) | `_TIER_ORDER` | **BUILD-NEW** tier rank; **BUILD-NEW** decide branch. | `inclement.py:269, 576` |
| Expose `WATCH_REQUIRES_CORROBORATION` | config_flow | **BUILD-NEW** Advanced selector. | config_flow.py |
| Hourly forecast fetch | `weather_manager.py:367` + `aggregation.py:1119` | **REUSE/EXTEND** both — service call pattern + cache pattern. | cited |
| Async refresh task | `async_create_task\|async_track_time_interval` | **BUILD-NEW** `_refresh_forecast_outage_cache` + unsub + teardown. | `energy_battery.py` lifecycle |
| Fusion `has_forecast_hold` branch | `InclementFusion.decide` | **BUILD-NEW.** | `inclement.py:574-720` |
| Enphase Storm Guard read | `storm_guard\|StormGuard` | **CONFIRMED-ABSENT.** Non-goal 1. | — |
| `inclement_source` attribute | `_inclement_attrs` | **REUSE/EXTEND**; new values additive. | `energy_battery.py:2779, 2801` |
| `inclement_recent_events` rolling attr | `inclement_recent` | **BUILD-NEW.** | `energy_battery.py:_inclement_attrs` |
| `storm_forecast` back-compat | `storm_forecast` | **REUSE.** | `energy_battery.py` |
| New knobs | `CONF_INCLEMENT_*` | **BUILD-NEW** per piece. | `energy_const.py:609-661` |

---

## Operator questions — answered BEFORE deliverables

### Q1 — "Why stop reasoning when you clearly can?"

The blind gate is a COMMAND gate masquerading as a DECISION gate. Current `energy_battery.py:5578` collapses DECIDE / COMMAND / OBSERVE into "do nothing" the moment envoy down + SOC None. Fix: evaluate decision BEFORE the gate, keep attrs fresh, emit a reserve-raise under blind for `partial_hold`/`full_hold`, forbid CFG writes (INV-B). The decision itself has a SOC-free path already (`_full_hold_floor(None)=100`, `_partial_floor_value(None)=max(reserve_soc, partial_floor)`); we additionally **bound** the SOC-None full-hold floor via `CONF_INCLEMENT_BLIND_SOC_FREE_FULL_HOLD_FLOOR_PCT` (default **60**, bound 50-100) so a nighttime watch does not pin reserve at 100 and defeat self-consumption until Envoy returns.

**Blind-write composition (new):** per tick, D1's pre-emit and the existing D2 de-escalation both run inside the same blind-gate branch and build a shared `actions` list before a single `return {...}`. Ordering: (1) compute `decision`; (2) if `decision.hold_depth != allow_discharge`, append reserve-raise with `reserve_level = decision.reserve_floor_blind()` where `reserve_floor_blind` applies the bounded blind-floor knob to full_hold; (3) if peak-or-into-peak AND CFG currently on, append the de-escalation CFG-off action AND a de-escalation reserve action with `max(int(self.reserve_soc), decision.reserve_floor_blind())`; (4) dedupe the reserve action by keeping the max of appended `value`s; (5) return once. No double-emit per tick.

### Q2 — Fix the matching. Threat model from first principles.

Covered by §Trust table + §Severity × Certainty × Code truth table. Primary gate is `NWSCode`; severity floor retired from code-match path; breadth-demote only on broad-precursor codes.

### Q3 — Was forecast lookahead deliberately rejected?

No. v5.5.0 plan has 0 hits for forecast-lookahead keywords. Only Solcast was consulted. D2 adds the forecast tier.

**Does forecast corroborate a watch?** **YES — when ≥2 providers agree AND cache fresh.** This mirrors the condition-only corroboration rule at `inclement.py:579-581`. Consequence: an off-peak corroborated watch under blind reaches `full_hold`; the bounded blind-floor knob caps it at 60 % by default (P1-04). Mid/peak with forecast-only (no alert) still returns `allow_discharge` (V1 cost-safe).

**Marginal-benefit decomposition:**

| Variant | Captures | Risk | Verdict |
|---|---|---|---|
| V0 (D1+D3+D4, no forecast) | ~70-80 % of tonight. | Low. | **GO.** |
| V1 (V0 + off-peak forecast hold via async cache) | Pre-storm quiet windows. | Low-moderate (new cached async refresh). | **GO.** |
| V2 (V1 + mid/peak forecast × Solcast) | Afternoon forecast into peak. | Moderate (TOU combinatorics). | **PARK with 90-day trigger.** |

### Q4 — Onset + Enphase Storm Guard coexistence

**Onset:** firm D3. Pending tier ranks between notice and watch; precharge CFG eligibility `_pending_precharge_eligible(now, decision) = tou=off_peak AND grid_precharge_on_hold=True AND (Onset - now) ≤ CONF_INCLEMENT_ONSET_PRECHARGE_LEAD_MIN AND NOT _precharge_refused_on_blind(...)`.

**Storm Guard:** no local entity; operator config-first = disable in Enphase app; attr reminder; future card parked.

---

## `pending` tier model (new section)

- Rank: `_TIER_ORDER = {"none":0, "notice":1, "pending":2, "watch":3, "warn":4}` (Rev-2). `_demote(watch) = pending`; `_demote(warn) = watch`; else unchanged.
- `decide()` branch (new, early-return after warn/watch processing):

```
if tier == "pending":
    if _pending_precharge_eligible(now, decision):
        return InclementDecision(
            hold_depth="full_hold",
            grid_precharge=True,
            tier="pending",
            source="alert",
            reserve_floor=_full_hold_floor_blind(current_soc),
            reason="pending_precharge",
            ...
        )
    if tou_period == "off_peak" and corroborated:
        return InclementDecision(
            hold_depth="partial_hold",
            grid_precharge=False,
            tier="pending",
            source="alert",
            reserve_floor=_partial_floor_value(current_soc),
            reason="pending_offpeak_partial_hold",
            ...
        )
    return _allow_discharge_decision(..., tier="pending", source="alert",
                                     reason="pending_allow_discharge")
```

- `SIGNAL_INCLEMENT_STATE_CHANGED` payload includes `tier="pending"` + optional `pending_onset_at`; sensor consumers render arbitrary strings (verified `sensor.py:9256-9308`).
- Pending precharge is the **only new CFG writer** this cycle; gated by `_precharge_refused_on_blind` + breaker chokepoint.

---

## Producer / Consumer map (Rev-2 complete)

### Producer dependencies

`AlertClassification` new deps: `Onset`, `NWSCode`, `AreasAffected`-split, `Ends`. All defensive reads.
`StormConditionResult` — state-only (existing).
`ForecastOutageRisk` — NEW; async cache fed by `weather.get_forecasts(hourly)` per healthy provider; cadence `CONF_INCLEMENT_FORECAST_REFRESH_MIN`, staleness bound `CONF_INCLEMENT_FORECAST_STALE_MAX_MIN`.
`SolarHorizon` — existing.
`current_soc` — 3-tier (EC p1).
`tou_period`.

### Consumers (file:line, trust vs display, change this cycle)

| Site | File:line | Trust/display | Change |
|---|---|---|---|
| `_inclement_decision` cache | `energy_battery.py:2734-2735` | internal | now reached pre-blind. |
| `SIGNAL_INCLEMENT_STATE_CHANGED` dispatch | `energy_battery.py:2737-2751` | trust (consumers may act) | **now fires on blind ticks** (new). Payload gains `pending_onset_at`. |
| `_inclement_attrs` | `energy_battery.py:2764-2805` | display | add forecast + pending + recent-events siblings; `inclement_source` extended. |
| determine_mode precedence `:5787` | `energy_battery.py:5787` | trust | preserved. |
| **blind pre-emit (new)** | `energy_battery.py:~5578` | trust | **D1.** |
| **blind de-escalation reserve write** | `energy_battery.py:5667-5673` | trust | **D1 floor applied.** |
| `_precharge_refused_on_blind` | `energy_battery.py:4110-4150` | trust (freshness check) | consumed by pending-precharge gate. |
| attribute pack | `energy_battery.py:6985` | display | siblings added. |
| EVSE overlay `_apply_evse_battery_hold` | `energy.py:5239` (called `:6459, :7174`) | trust | re-verify max()-safe at both call sites. |
| write-verify partial-floor read | `energy_write_verify.py:1647-1662` | trust (verify oracle) | reads `_last_inclement_decision`; blind reserve writes must land in the queue with the "Inclement-under-blind" reason to be matched. |
| write-verify reserve check | `energy_write_verify.py:1756` | trust | verify blind reserve write resolves against the cloud-oracle not local reserve (per EC p1). |
| DP ledger | `energy_drain_precedence.py:68, 98` | trust | re-verify `_last_inclement_decision` consulted (should already be via `_floor_reserve`). |
| `sensor.ura_inclement_state` | `sensor.py:9256-9308` | display | new tier string `pending` + source values additive. |
| forecast-cache readers | `sensor.py:9642, 9664, 9733` | display | reused via same cache mechanism (per aggregation pattern). |

### Discriminator (recomputed per P1-04)

Live-case replay (NWS Wind Advisory `WIY/Moderate/Likely`, `Onset=Expires=04:00, Ends=19:00`, hourly ≥43 % lightning-rainy within 3h on ≥2 providers, Envoy offline, SOC None, time=22:00 off_peak):

Under D4 only (classification): `tier=watch` (code `WIY` → watch; certainty `Likely` → warn-cap; `min(watch, warn) = watch`; no breadth-demote for WIY).

Under D4 + D2 (forecast as watch corroboration): corroborated.

Under D1 (blind-decide): fusion reaches the off-peak corroborated-watch path → `_full_hold_floor_blind(None)` = `CONF_INCLEMENT_BLIND_SOC_FREE_FULL_HOLD_FLOOR_PCT = 60` (default).

Expected observations under fix:
- `inclement_tier = "watch"`.
- `inclement_source = "alert+forecast"` (new combination).
- `inclement_hold_depth = "full_hold"` (NOT partial — because watch + off-peak + corroboration → full_hold per `inclement.py:629-645`).
- `inclement_reserve_floor = 60` (not 100, not 50).
- `storm_forecast = true`.
- Queue: ONE `number.set_value reserve_soc_number=60` with reason prefix `"Inclement-under-blind (watch_corroborated_offpeak_full_hold)"`; **no CFG write** (precharge gated by `grid_precharge_on_hold`, default False, and blind-safety INV-B).

Plausible alt-failures discriminated:
- Forecast silently empty → `inclement_source="alert"`, `tier=watch`, un-corroborated under blind → off-peak uncorroborated watch returns `partial_hold` floor `max(reserve_soc, partial_floor)` = 50. Different `source`, `hold_depth`, `reserve_floor` ⇒ discriminating.
- Classifier regression (WIY not matched) → `tier=notice`, `source=none|forecast`, `hold_depth=allow_discharge`. Discriminating.
- Blind de-escalation unfloored (INV-H leak) → queue shows a reserve write at `int(self.reserve_soc)` < 60 with no "Inclement-under-blind" prefix. Discriminating.

---

## Knob ladder — Rev-2 complete

| Name | Rung | Default | Bound | Why |
|---|---|---|---|---|
| `CONF_INCLEMENT_POWER_THREAT_EVENT_CODES` | 2 | per trust table | — | per-deployment. |
| `CONF_INCLEMENT_POWER_THREAT_EVENTS` (legacy) | 2 | existing | — | REUSE deprecated fallback. |
| `CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION` | 2 | True | — | PROMOTED from hidden. |
| `CONF_INCLEMENT_WARN_MIN_SEVERITY` | 2 | existing `Severe` | — | KEEP for legacy name-match fallback only; unused on code-match path; removable `<ship+1>`. |
| `CONF_INCLEMENT_FORECAST_LOOKAHEAD_H` | 3 (live Number) | 6 | 1-24; 0 disables | kill-switch at 0. |
| `CONF_INCLEMENT_FORECAST_PRECIP_PROB_PCT` | 3 (live Number) | 50 | 10-100 | live tune. |
| `CONF_INCLEMENT_FORECAST_GUST_MPH` | 3 (live Number) | 40 | 20-65 | live tune. |
| `CONF_INCLEMENT_FORECAST_MIN_AGREEMENT` | 2 | 2 | 1-5 | structural. |
| `CONF_INCLEMENT_FORECAST_REFRESH_MIN` | 2 | 10 | 5-60 | async refresh cadence. |
| `CONF_INCLEMENT_FORECAST_STALE_MAX_MIN` | 2 | 30 | 10-120 | cache staleness bound; stale ⇒ fail-safe (no hold). |
| `CONF_INCLEMENT_ONSET_PRECHARGE_LEAD_MIN` | 3 (live Number) | 90 | 15-240 | operator tunes against Onset accuracy. |
| `CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR` | 2 | existing 50 | — | REUSE. |
| `CONF_INCLEMENT_BLIND_SOC_FREE_FULL_HOLD_FLOOR_PCT` | 3 (live Number) | **60** | 50-100 | **NEW (P1-04)**: bounds the SOC-None full-hold emit so blind nights don't pin reserve at 100. |
| `INCLEMENT_FORECAST_GUST_UPPER_BOUND_MPH` | 1 (const) | 65 | — | safety ceiling. |
| `INCLEMENT_FORECAST_SERVICE_TIMEOUT_S` | 1 (const) | 3 | — | service timeout; async refresh only. |
| `INCLEMENT_BREADTH_DEMOTE_AREA_COUNT_TOA` | 1 (const) | 20 | — | breadth-demote threshold. |
| `INCLEMENT_BREADTH_DEMOTE_AREA_COUNT_SVA` | 1 (const) | 25 | — | breadth-demote threshold. |
| `INCLEMENT_RECENT_EVENTS_WINDOW_H` | 1 (const) | 24 | — | rolling attr window. |
| `INCLEMENT_RECENT_EVENTS_MAX` | 1 (const) | 20 | — | rolling attr bound. |
| `INCLEMENT_DECISION_FRESH_S` | 1 (const) | 1800 | — | D1 collapses the freshness check to `decision is not None` (fresh by construction) but keeps the const for consumers (`:5624`, `:4150`). |
| `INCLEMENT_D4B_INCLUSION_MIN_FIRES` | 1 (const) | 1 | — | D4b inclusion gate: a code with ≥1 fire AND outage correlation stays. |
| `INCLEMENT_D4B_INCLUSION_MAX_OUTAGE_CORR` | 1 (const) | 1 | — | D4b exclusion gate: a code with ≥10 fires and ≤1 outage correlation becomes `notice` default. |

Removed: `CONF_INCLEMENT_FORECAST_PRE_PEAK_H` (V2 parked).

---

## Deliverables

### D1 — Envoy-blind: decide always; command safely (fixes INV-H leak at `:5667-5673`)

Move `self._inclement_decision(tou_period, now)` ABOVE the blind-gate at `energy_battery.py:5578`. Compose the blind return pack per §Blind-write composition:

- `decision.hold_depth != allow_discharge`: build reserve-raise action with `decision.reserve_floor_blind()` (full_hold uses `CONF_INCLEMENT_BLIND_SOC_FREE_FULL_HOLD_FLOOR_PCT`; partial_hold uses `max(reserve_soc, partial_floor)`).
- Peak-or-into-peak + CFG-on: append de-escalation CFG-off + de-escalation reserve `max(int(reserve_soc), decision.reserve_floor_blind())`.
- Dedupe reserve by max; single return.
- `allow_discharge`: existing blind-pause pack.
- Reason prefix `"Inclement-under-blind (…)"` so `energy_write_verify` matches.
- D2 blind-peak de-escalation reads live `decision`; freshness check becomes `decision is not None` (always true by construction).

**Acceptance:**
- **Verify:** `inclement_hold_depth`, `inclement_tier`, `inclement_source` update within one tick after Envoy drops with an active qualifying alert.
- **Verify:** blind reserve-write queue holds exactly ONE reserve write per tick; CFG write absent.
- **Test (mutation-anchored):** `test_inclement_blind_decides_and_emits_reserve_only`, `test_inclement_blind_full_hold_bounded_by_knob` (SOC-None + partial_hold floor=60), `test_blind_peak_de_escalation_floors_at_decision` (reserve_soc=20, partial=50, blind+peak+CFG-on ⇒ emitted value 50 not 20), `test_blind_pause_no_alert_unchanged` (regression), `test_blind_no_cfg_write` (INV-B).
- **Live:** no restart or firewall-games. (a) in-suite proof is primary. (b) on the next organic Envoy-blind episode, read HA recorder for `energy_write_queue` + `_write_log` entries bearing the "Inclement-under-blind" prefix within the dropout window; expect exactly one reserve write per blind tick during the alert; CFG unchanged.

### D2 — Forecast-outage-risk async cache + fusion wire (REUSE/EXTEND `weather_manager.py:367` + `aggregation.py:1119`)

New `WeatherProviderManager.forecast_outage_risk(now, horizon_h) → ForecastOutageRisk` reads from `self._forecast_outage_cache` populated by `_refresh_forecast_outage_cache()` (tracked `async_track_time_interval(hass, cb, timedelta(minutes=CONF_INCLEMENT_FORECAST_REFRESH_MIN))`; unsub stored at `self._forecast_outage_unsub`; teardown in `async_will_remove_from_hass`). Cache entry carries `fetched_at`; `_inclement_decision` reads cache and treats entries older than `CONF_INCLEMENT_FORECAST_STALE_MAX_MIN` as "no signal" (fail-safe).

Fusion branch: `has_forecast_hold` evaluates after warn/watch; off-peak + ≥2 agreeing providers → counts as corroboration for an active watch (upgrading uncorroborated → corroborated) AND, in the absence of any alert, produces its own `tier=watch, source=forecast, hold_depth=partial_hold` off-peak. Mid/peak forecast-only: `allow_discharge` (V1).

**Acceptance:**
- **Verify:** tonight-case replay produces `tier=watch, source=alert+forecast, hold_depth=full_hold (bounded 60 under blind)`.
- **Verify:** `LOOKAHEAD_H=0` ⇒ fusion byte-identical to v5.5.0 (kill-switch regression guard).
- **Verify:** teardown — reload the EC entry; `_forecast_outage_unsub` cleared; no lingering timer.
- **Sensor:** 5 new siblings: `forecast_horizon_h`, `forecast_max_precip_prob`, `forecast_max_gust_mph`, `forecast_agreeing_providers`, `forecast_cache_age_min`.
- **Test:** 7 unit tests ((a) no healthy provider → None, (b) 1-of-2 agreeing → false, (c) 2-of-2 precip → true, (d) 2-of-2 gust → true, (e) service timeout → graceful false, (f) cache stale → treated as no-signal, (g) teardown unsubs the timer).
- **Live:** first full day with ≥2 providers, read `forecast_cache_age_min` attr every tick; expect < `CONF_INCLEMENT_FORECAST_STALE_MAX_MIN` continuously.

### D3 — Onset handling + `pending` tier + precharge lead — **APPROVED by operator 2026-10-15**

Split `_alert_expires_at` into `_hazard_window(alert) = (Onset or Effective or Sent, Ends or Expires)` and `_message_fresh_at(alert) = Expires or Ends`. Keep alert while `now ≤ hazard_window.end`; drop only when both message is stale AND hazard window closed. Classify `pending` when `now < hazard_window.start`. See §Pending tier model for `decide()` branch + CFG writer.

**Supersedes v5.5.0 L-criterion** (hold cannot outlive Expires). Explicit note here.

**Acceptance:**
- **Verify:** Wind Advisory `Onset=04:00, Ends=19:00`, posted 02:30 ⇒ `tier=pending, source=alert` at 02:30; `tier=watch` at 04:00; **does NOT drop at 04:00**.
- **Verify:** `pending + off_peak + grid_precharge_on_hold=True + lead-in-window` ⇒ ONE CFG write; off ⇒ no CFG write.
- **Test:** `test_pending_tier_before_onset`, `test_pending_demotes_at_onset`, `test_wind_advisory_hold_lives_to_ends`, `test_hold_falls_back_to_expires_when_ends_absent`, `test_pending_precharge_respects_switch`, `test_pending_precharge_refused_on_blind`.
- **Live:** inject synthetic pending alert via dev-tools; attrs flip `allow_discharge → partial_hold (pending) → watch`.

### D4 — Code-match + word-boundary name + breadth + corroboration knob exposed (resolves P1-05, P1-12)

Replace `_event_matches_threat`: (a) exact `alert["NWSCode"]` membership; (b) legacy word-boundary name match (`\bkeyword\b`) as fallback. `area_count = len([s for s in str(alert.get("AreasAffected","")).split(";") if s.strip()])`. Apply per-code breadth-demote per trust table. Severity-demote removed from code-match path (truth table). Expose `WATCH_REQUIRES_CORROBORATION` in Advanced subsection.

**Acceptance:**
- **Verify:** `WIY/Moderate/Likely` ⇒ `watch` (no severity demote).
- **Verify:** `FLA` ⇒ gated out.
- **Verify:** `TOA` with area_count ≥ 20 ⇒ `notice` (breadth-demote).
- **Verify:** area_count correctly derived from `;`-split string (not `len(str)`).
- **Test:** `test_match_wiy_wind_advisory`, `test_toa_broad_demotes_to_notice`, `test_area_count_split_semicolon`, `test_legacy_substring_fallback`, `test_watch_corroboration_knob_live`, `test_severity_not_demoting_on_code_match`.
- **Live:** Advanced subsection shows the toggle; options reload persists; attr reflects value.

### D4b — AUDIT_nws_alerts_90d_at_point.md (Measure-Before-Build)

One-shot read-only recorder probe tallying last 90 days of `sensor.nws_alerts_gps_30_3146_98_0159_nws_alerts_alerts` state attributes by `(NWSCode, count, median_area_count, outage_co-occurrence)`. Outage source: HA recorder history for `sensor.ura_energy_coordinator_grid_connected` false transitions + `sensor.span_panel_grid_connected`. Fallback: Envoy production zero + grid-import spike in `energy_history`. Inclusion/exclusion per `INCLEMENT_D4B_INCLUSION_MIN_FIRES` / `INCLEMENT_D4B_INCLUSION_MAX_OUTAGE_CORR`. Columns with `UNK` for outage-correlation are allowed when no clean signal; code stays in default set if base-rate ≥ fires threshold.

**Acceptance:**
- **Verify:** `docs/planning/AUDIT_nws_alerts_90d_at_point.md` exists with per-code table and the include/exclude rationale.
- **Live:** none (planning artifact; feeds D4 default set).

### D5 — Observability + attribute pack + precedence-comment update

Add attributes: `inclement_source` (REUSE/EXTEND, new values additive), `forecast_horizon_h`, `forecast_max_precip_prob`, `forecast_max_gust_mph`, `forecast_agreeing_providers`, `forecast_cache_age_min`, `pending_onset_at`, `blind_decision_emitted` (bool), `inclement_recent_events` (24h-rolling 20 entries). Update precedence comment at `energy_battery.py:5728-5772` to the 6-step ordering (decide-first, blind-emit-with-dedupe, de-escalation-floored).

**Acceptance:**
- **Verify:** attrs present post-restart; stable on no-event tick.
- **Verify:** `blind_decision_emitted = True` only under full-blind-with-hold.
- **Verify:** `inclement_source` back-compat for prior values (`alert`, `condition`, `none`) preserved.
- **Live:** developer-tools shows attrs; no deprecation warnings.

### D6 — Enphase Storm Guard coexistence note + README

`enphase_storm_guard_coexistence` string attr + README section instructing operator to disable Storm Guard in the Enphase app.

**Acceptance:**
- **Verify:** attr + README section present.
- **Live:** operator confirms Storm Guard off; STAND-DOWN rate unchanged or lower after a storm event.

---

## Non-goals (explicit)

1. Do not read Enphase Storm Guard state.
2. Do not add a `_paused_by_storm` set to `energy_pool.py`.
3. Do not change the arbitrage-WAIT floor plumbing (v5.5.3 settled).
4. Do not add mid/peak forecast-only holds in V1 (V2 parked).
5. Do not polygon-geo-filter in URA; rely on `nws_alerts` zone/county UGC.
6. Do not emit `charge_from_grid` writes under full-blind (INV-B). The pending-precharge CFG writer is the ONLY new CFG writer in this cycle, and it is explicitly gated by `_precharge_refused_on_blind` + breaker chokepoint.
7. Do not persist alert ledger to the URA DB (attribute payload only, D5).
8. Do not consume `MessageType`, `Urgency`, or `Effective` (not in the live payload; Rev-2 removal).

---

## Parked variants

- **V2 — Forecast-driven mid/peak hold with Solcast gating.** Revival trigger: ≥1 missed peak-outage logged in 90 days post-D2.
- **V3 — URA reads Storm Guard then concedes.** Card `EC-STORM-GUARD-COEXIST-1`.
- **V4 — Polygon-tight geo filtering (Shapely).** Trigger: UGC-wide feed produces >25 % false-positive hold-hours in 90-day post-ship audit.

---

## Recommended sequencing

1. **D4b** AUDIT (cheap, feeds D4 defaults).
2. **D4** matching (no `determine_mode` touch).
3. **D3** Onset + pending + Expires/Ends fix.
4. **D1** blind-decide + reserve-only + de-escalation floor (precedence-chain move).
5. **D2** forecast cache + async refresh + fusion wire.
6. **D5** + **D6** ship together.

Each of D1-D4 reviewable Tier-3 four-framing; D1 is INV-H's load-bearing site; D-pass re-enumerates all 25 reserve-emission sites (table in §Reserve emission site inventory) and mutation-anchors each. D3's `_hazard_window` / `_message_fresh_at` split gets its own completeness drill (what if `Onset` missing? `Ends` missing? both?).

---

## Supersession & post-ship audit plan

- **DELETE candidate (after live-validation):** legacy substring list + severity-demote on code-match path — removed `<ship+1>` once code-match proven; defer the irreversible move.
- **KEEP+WIRE:** `_apply_evse_battery_hold` consumers should optionally consume `decision.hold_depth` directly rather than max-overlay — parked as `EC-INCLEMENT-D2-CONSUMES-DECISION-1`.
- **KEEP+DOCUMENT:** `has_storm_forecast()` already deleted in v5.5.0.
- Post-ship audit: re-run D4b on first 30 days post-ship; verify breadth thresholds (TOA 20, SVA 25) + bounded-blind-floor default (60) match live operator preference.

---

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018uEjYPUcWq73wfBS3t1NEa
