# PLANNING — Inclement-Weather Hardening (Reasoning-under-Blind, Threat-Model Matching, Forecast Lookahead)

**Card:** `EC-INCLEMENT-HARDENING-1`
**Tier:** 3 (shared primitive — `determine_mode` precedence chain, reserve-floor state; cost + safety ripple into EV / arbitrage; falsifiable "qualifying threat ⇒ hold" invariant)
**Status:** `pre_planning` → BUILD-READY after plan reviews.
**Branch target:** `develop`.
**Supersedes behavior shipped in:** v5.5.0 (initial inclement fusion) + v5.5.3 (arbitrage-WAIT floor). Does NOT touch the arbitrage-WAIT floor; does change the alert gate, the Envoy-blind precedence, and introduces a forecast tier.

**Operator thesis (verbatim 2026-10-15):** *"(1) Blind pause: I understand being unable to command but why stop reasoning when you clearly can? (2) Fix the matching. Reason from first principles: is it above medium? What would we act on for inclement weather? We built this so we don't react to things that don't matter that come over alerts, for our GPS coord. (3) Forecast never consulted seems dumb; peering into the future is an advantage."*

**Operator additions 2026-10-15 (second pass):**
1. **Onset handling APPROVED** — *"Read alert start times. YEs"* — D3 is a firm deliverable (not optional).
2. **"Already GPS-filtered" is a VERIFY, not a trust** — see §How NWS alerts work below.
3. New section §How NWS alerts work + trustworthiness, with per-event-code trust verdicts (predictive vs administrative; broadness penalty).

**Load-bearing live case (2026-10-15/16, Austin):** NWS hourly rainy / lightning-rainy 01-03 at 43 %, rainy 04-06 at 41 %; Wind Advisory Moderate / Likely, `Onset=Expires=04:00`, `Ends=19:00`, gusts 40-50 mph; Envoy offline since 17:38; battery ~30 %. **URA produced no inclement hold on any axis.** Each wart below contributed; the plan dissolves each one.

---

## Falsifiable invariant (Tier-3, D-pass must break or affirm)

> **INV-H:** When a qualifying outage threat is **active or forecast within H hours** (defaults: `H = CONF_INCLEMENT_FORECAST_LOOKAHEAD_H = 6`), the commanded `reserve_soc` **is never below** `max(reserve_soc, CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR)` on **ANY** reachable path from `determine_mode`, **including the Envoy-blind branches** (SOC None and SOC resolved-via-fallback), the arbitrage WAIT/CHARGE phases, and the EVSE-overlay path. A "qualifying threat" is defined in §Operator Q2 **and §How NWS alerts work (trust table)**.

The reviewer-D job is to produce a legal-config reachable repro that commands below that floor while INV-H's hypothesis holds. Config combinatorics (floor > SOC, floor > current reserve, blind + partial, blind + full-hold-with-grid-precharge-off) must each be exercised at extremes.

---

## How NWS alerts work + trustworthiness (NEW — operator addition #3)

This section is grounded in the NWS CAP v1.2 user guide + the HA `nws_alerts` integration source. Where a claim is not directly cited it is noted as *inferred* and should be verified by the builder with a live replay against the recorder before load-bearing use.

### CAP fields on each `alert` in `attributes.Alerts`

Fields emitted by `nws_alerts` (verified against our live sensor attributes earlier today):

| Field | Meaning | Load-bearing use in URA |
|---|---|---|
| `Event` | Human-readable event name ("Wind Advisory", "Tornado Warning", "Severe Thunderstorm Watch"). | Legacy name match (fallback only after D4). |
| `NWSCode` | Short code (`TOR`, `WIY`, `SVR`, `SVA`, `WSW`, etc.) — locale-free, byte-exact. | **PRIMARY GATE** post-D4. |
| `Severity` | CAP: `Extreme | Severe | Moderate | Minor | Unknown`. | Noise filter only — never the gate. |
| `Certainty` | CAP: `Observed | Likely | Possible | Unlikely | Unknown`. | Tier assignment (Observed/Likely → warn, else watch). |
| `Urgency` | CAP: `Immediate | Expected | Future | Past | Unknown`. | **NEW USE (D3):** `Future` + populated `Onset` → `pending` tier. |
| `Status` | `Actual | Exercise | System | Test | Draft`. | Drop non-`Actual` (already in `inclement.py:208`). |
| `MessageType` | `Alert | Update | Cancel | Ack | Error`. | **NEW USE (D4):** on `Cancel` or `Ack`, DROP (do not treat Cancel as new tier). |
| `Onset` | **Expected start of the HAZARD** (not the message). | **NEW USE (D3).** |
| `Effective` | When the MESSAGE becomes operative. Rarely diverges from `Sent`. | Documented, not consumed. |
| `Expires` | When the **MESSAGE** should be considered stale (CAP spec). | Existing use — keep. |
| `Ends` | When the **HAZARD** is expected to end (NWS extension; sometimes absent). | Existing use — keep in `min(Ends, Expires)` for `_alert_expires_at`. |
| `AreasAffected` / `UGC` | Zone/county list the alert covers. | **NEW USE (observability):** record alert `area_count = len(AreasAffected)` for broadness penalty (see Trust table). |
| `Instruction`, `Description`, `Sender`, etc. | Human narrative. | Not consumed. |

**Expires vs Ends — the gotcha that produced tonight's bug:**

- `Expires` = *when the CAP message is stale*. For a short-advisory-type product, NWS often sets `Expires = Onset` (tonight's Wind Advisory: `Expires=Onset=04:00`) — because the message itself gets *superseded* by a new Update at onset. **This does NOT mean the hazard ends at 04:00.** The hazard window is `[Onset, Ends]` = `[04:00, 19:00]`.
- Current `inclement.py:129-138` computes `min(Ends, Expires)` = `04:00` for tonight → classifier at `:213` drops it as "already expired" the moment URA is checked after 04:00. **This is the bug.**
- **Correct semantics (D3 + D4):**
  - `_message_fresh_at(now)` = `Expires` (fallback to `Ends`). A stale CAP message is one we should refetch.
  - `_hazard_active_at(now)` = `Onset ≤ now ≤ Ends` (fallback: `Effective ≤ now ≤ Expires` when `Onset`/`Ends` absent).
  - Drop the alert only when BOTH the message is stale (CAP replaced) AND the hazard window is past. Tonight that would never drop the Wind Advisory before 19:00.

### Point-filtering: how NWS resolves "my point"

- The HA `nws_alerts` integration is configured here with `configuration_type: "GPS Location"`, `gps_location: 30.314635,-98.015861`.
- The NWS public API's `/alerts/active?point=lat,lng` query resolves the point to its **forecast zone (UGC Z-code) AND county (UGC C-code)** and returns every active alert whose `AreasAffected` includes either code. It does **NOT** polygon-intersect the point with each alert's draw polygon — zone/county membership is enough. (NWS CAP user training deck confirms UGC-based filtering; the detailed Alerts Geolocation Guide hosts the authoritative text.)
- **Verdict on "already GPS-filtered":** **YES-with-nuance.** The feed is zone/county-tight, NOT point-polygon-tight. A tornado warning drawn over the southeast corner of our county WILL appear in our feed; a Wind Advisory covering 33 counties including ours WILL appear (and SHOULD — gusts don't respect county lines). We must NOT re-filter in URA. We MAY use breadth as a trust signal (see trust table).
- URA's job is NOT to geo-tighten (we'd need the full polygon + Shapely to do that correctly, and NWS does this at issue time for products with polygons). URA's job is to pick which product types are credible outage precursors.

### Trust table — predictive vs administrative, per event

Scored by (a) outage mechanism credibility, (b) issuance frequency on broad advisories ("administrative noise"), (c) breadth of area (wide → lower trust per instance), (d) base rate of actual outage in Hill Country / Austin.

| NWSCode | Event | Default tier (D4) | Trust verdict | Breadth-penalty? |
|---|---|---|---|---|
| `TOR` | Tornado Warning | warn | **High.** Short, point-like, high outage base rate. | No. |
| `TOA` | Tornado Watch | watch | **Moderate.** Broad; precursor only. | **Yes** (demote to notice if `area_count ≥ 20`). |
| `SVR` | Severe T-storm Warning | warn | **High.** Line/tree outage mechanism. | No. |
| `SVA` | Severe T-storm Watch | watch | **Moderate.** Broad. | **Yes** (demote notice if `area_count ≥ 25`). |
| `WIY` | Wind Advisory | watch | **High for THIS GPS.** Trees + wet soil = our dominant outage. Gust 40-50 mph is the live case. | No (gust threshold is the real signal; even broad advisory warrants watch). |
| `WIH` | High Wind Warning | warn | **High.** | No. |
| `HWA` | High Wind Watch | watch | **High.** | No. |
| `EWW` | Extreme Wind Warning | warn | **High.** | No. |
| `WSW` | Winter Storm Warning | warn | **High** in Austin (rare → high consequence). | No. |
| `WSA` / `WSY` | Winter Storm Watch / Advisory | watch | **High** here. | No. |
| `ISW` | Ice Storm Warning | warn | **Very high.** The 2021 outage mechanism. | No. |
| `BZW` | Blizzard Warning | warn | **High.** | No. |
| `HUR` / `TRW` | Hurricane / Tropical | warn | **High** (slower, forecast-visible — forecast tier often fires first). | No. |
| `FFW` | Flash Flood Warning | notice | **Low for outage** at elevated property; HIGH for life safety (not URA's job). Keep OUT of threat set. | — |
| `FLW` / `FLA` | Flood Warning / Watch | notice | **Low.** OUT. | — |
| `HTA` / `HTY` | Heat Advisory / Warning | notice | **None.** Not outage-predictive by itself. OUT. | — |
| `AQA` | Air Quality | notice | **None.** OUT. | — |
| `SPS` | Special Weather Statement | notice | **Mostly administrative.** OUT by default; opt-in only. | — |
| `DSW` | Dust Storm Warning | notice | **None here.** OUT. | — |

**Breadth-penalty rule (D4b, additive):** when a code's trust row says "Yes", a `watch` demotes to `notice` if `AreasAffected count ≥ threshold`. This is the "33-county Wind Advisory" question operationalized **only for the Watch tier** of codes that routinely issue wide — Wind Advisory itself is NOT penalized because its mechanism (wind) is credibly correlated with our outage rate regardless of area. Threshold is a module-constant `INCLEMENT_BREADTH_DEMOTE_AREA_COUNT = 20/25` per code (not operator-tunable; code-review change).

**Does URA log alert history?** Grep for `alert_history|inclement.*log` in `custom_components/`: no dedicated alert ledger. The strategy sensor's `inclement_contributing_event` + its state history in HA recorder is the only trail today. **D5 adds `inclement_recent_events` as a rolling 24h list in attrs** so that post-ship we can audit "which codes fired in the last 24h vs which SHOULD have triggered holds". Not a new DB table; attribute payload only, bounded to 20 entries.

**Builder evidence task (pre-build measurement, per Measure-Before-Build):** before D4 lands, run a one-shot read-only probe over the HA recorder's last 90 days of the `sensor.nws_alerts_gps_30_3146_98_0159_nws_alerts_alerts` state attributes. Produce a `docs/planning/AUDIT_nws_alerts_90d_at_point.md` tallying `(NWSCode, count, median_area_count, overlap_with_known_outage_log)`. Any code with ≥10 fires and ≤1 outage correlation becomes a candidate for `notice`-tier default (operator reviews). Any code with ≥1 outage correlation and no fire in our list is a candidate for inclusion. This is the measurement that justifies the D4 default set.

---

## Institutional context verified

### Code read end-to-end / partial during scoping

- `domain_coordinators/energy_battery.py` — Envoy-blind gate `:5578-5710` (returns BEFORE `_inclement_decision :5787`); last-decision cache `:780-781, :2663-2735`; `_inclement_attrs` `:2764-2780` (reads cache ⇒ **stale when blind-gate short-circuits**); EV-overlay re-entry `:4140`; attribute pack `:6985`; D2 blind-peak de-escalation `:5598-5684` (keyed on CFG only, NOT on inclement tier). The precedence comment `:5728-5772` names 5 ordered steps.
- `domain_coordinators/inclement.py` — `AlertClassifier.classify` `:152-266`; **substring threat match `_event_matches_threat :141-149`** against `DEFAULT_INCLEMENT_POWER_THREAT_EVENTS` (`energy_const.py:630-639`); `_alert_expires_at :129-138` = `min(Ends, Expires)` (Onset never read; current-time filter `:213` drops the alert *at* Onset for future-dated events); severity ranking + demote `:235-245`; `InclementFusion.decide` `:564-720`; condition-only path requires ≥2 providers `:579-581` and never holds at mid/peak `:712-717`.
- `domain_coordinators/weather_manager.py` — `current_storm_condition :785-843` reads **state only** (no forecast call); `_STORM_CONDITIONS :74-77`.
- `domain_coordinators/energy_const.py` — knob block `:609-661`; `CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION :621` is **defined but not exposed in config_flow** (hidden; always True via default); no `CONF_INCLEMENT_FORECAST_*` exists; no gust / probability knob exists.
- `config_flow.py` — existing collapsed "Advanced" subsection pattern (`fan_recheck_advanced :2981-2993` flattened on submit `:2893`) is the re-use target for new Advanced knobs.
- `translations/en.json` + `strings.json` — labels/descriptions live here; must be updated for every new CONF.
- **No URA-side alert ledger** — confirmed by grep `alert_history|inclement.*log`: 0 matches. Only the HA recorder has the trail.

### Prior planning docs / READMEs / memory consulted

- `docs/planning/PLANNING_inclement_weather_reserve.md` — original (FINAL 2026-06-15) v5.5.0 plan. **Grep for `forecast lookahead|hourly forecast|precipitation_probability|get_forecasts`: 0 matches.** Only Solcast; current-state only. **Verdict: forecast lookahead was NOT deliberately rejected — out of scope.** (See Operator Q3.)
- `docs/planning/PLANNING_arbitrage_wait_inclement_floor.md` — v5.5.3; 7-site clamp. Not reopened; new blind-emit site requires its own completeness re-sweep in D-pass.
- `docs/readmes/README_v5.5.0.md` — `storm_forecast = hold_depth != allow_discharge`.
- Memory `project_v5_5_0_inclement_weather_shipped.md` — entity names.
- Memory `project_inclement_arbitrage_wait_floor_gap.md` — v5.5.3 closed; do not re-open.
- Memory `project_enphase_coupling_tier.md` — Tier 2 writes; Storm-Guard coexistence context.

### Prior-art scan + REUSE / BUILD verdicts (per proposed piece)

| Proposed piece | Grep | Verdict | File:line |
|---|---|---|---|
| Keep classify / fusion primitives | `AlertClassifier\|InclementFusion` | **REUSE** both; extend internals. | `inclement.py:152, 545` |
| Reasoning when Envoy-blind SOC-None | `envoy_avail and soc is None` | **BUILD-NEW** — move `_inclement_decision` ABOVE the gate; emit reserve-only when blind. REUSE SOC-free `_full_hold_floor` branch. | `energy_battery.py:5578, inclement.py:724` |
| LKG / cloud SOC fallback | EC p1 3-tier SOC resolver | **REUSE** (reconfirm site at build). | energy_battery.py (EC p1) |
| NWSCode / event-code matching | `NWSCode\|event_code` | **BUILD-NEW** — code-set primary + legacy word-boundary fallback. | `inclement.py:141-149` |
| MessageType handling | `MessageType` | **BUILD-NEW** — drop `Cancel`/`Ack` early. | `inclement.py:201-215` |
| Urgency → `pending` tier | `Urgency` | **BUILD-NEW** — Future + Onset in-window → pending. | same |
| Breadth-penalty | `AreasAffected` | **BUILD-NEW** — per-code area-count demote in classifier. | same |
| Expose `WATCH_REQUIRES_CORROBORATION` | config_flow | **BUILD-NEW** selector; promote to Advanced. | config_flow.py |
| Hourly forecast lookahead | `weather.get_forecasts\|hourly` | **BUILD-NEW** — new `WeatherProviderManager.forecast_outage_risk`. | `weather_manager.py:785` |
| New knobs (see §Knob ladder) | `CONF_INCLEMENT_*` | **BUILD-NEW** per piece. | `energy_const.py:609-661` |
| Enphase Storm Guard read | `storm_guard\|StormGuard` | **CONFIRMED-ABSENT.** No read; policy documented only. | — |
| `storm_forecast` attribute | `storm_forecast` | **REUSE** back-compat alias. | `energy_battery.py:2764-2780` |
| 24h recent-events rolling attr | `inclement_recent_events` | **BUILD-NEW**. | `energy_battery.py:_inclement_attrs` |

### Design docs
No `docs/Coordinator/Energy.md` exists. Precedence comment at `energy_battery.py:5728-5772` is the de-facto design doc and MUST be updated in-cycle.

---

## Operator questions — answered BEFORE deliverables

### Q1 — "Why stop reasoning when you clearly can?"

**Answer: we shouldn't. The blind gate is a COMMAND gate, not a DECISION gate.** The current branch at `energy_battery.py:5578-5710` conflates three jobs:

1. **Decide** — depends on alerts/forecast/condition/TOU/Solcast. SOC only matters for mid/peak recoverability; `full_hold` is SOC-free (`inclement.py:724` returns 100 when SOC is None).
2. **Command** — depends on Envoy availability + trustworthy SOC witness.
3. **Observe (attrs)** — depends only on the decision.

Current branch collapses all three into "do nothing" the moment Envoy is unavailable AND SOC is None. That is why `inclement_hold_depth` attrs went STALE for the live case and **no reserve write even reached the queue**.

**Decision-vs-command enumeration (completeness pass over blind-gate exit `energy_battery.py:5578-5710`):**

| Item at :5728-5772 | Keep reasoning when blind? | Reason |
|---|---|---|
| 1. envoy_unavail + SOC None short-circuit | **SPLIT** — compute decision; emit SOC-free full-hold reserve write ONLY (no CFG). | Reserve raise is safe; CFG is cost + breaker-adjacent. |
| 2. grid_disconnected → BACKUP | **YES** — already SOC-agnostic. | Grid-connectivity drives it. |
| 3. inclement hold-depth ladder | **YES — THIS IS THE FIX.** | `full_hold` floor is SOC-free. |
| 4. peak / mid_peak discharge | **NO** — needs SOC. | SOC-dependent. |
| 5. off_peak arbitrage phase | **NO** — CHARGE entry refused on blind (EC p1). | Pre-existing design. |
| D2 blind-peak de-escalation `:5634` | **KEEP** — but reads live decision. | INV-H consistency. |
| `_arbitrage_active = False` reset `:5587` | **KEEP.** | state hygiene. |

**SOC under blind:** three-tier ladder (EC p1): (a) live Envoy, (b) LKG + staleness tag, (c) cloud witness. All-None → `full_hold` floor 100 % SOC-free; `partial_hold` floor `max(reserve_soc, partial_hold_reserve_floor)` SOC-free. `compute_solar_horizon` short-circuits ⇒ `watch` demotes to full_hold on mid/peak (conservative).

### Q2 — Fix the matching. Threat model from first principles.

**Threat model = credible probability of a grid outage long enough we needed headroom.** Central Texas base-rate ranking:

1. **Wind + wet soil → tree-on-line** — dominant. High Wind, Extreme Wind, Hurricane, **AND Wind Advisory** (gusts 40-57 mph: lines drop). Current substring excludes `Wind Advisory`; this is wrong.
2. **Ice / Winter Storm** — in list.
3. **Tornado / Severe Thunderstorm (incl. Watch for the latter via `SVA`)** — in list.
4. **Flood** — exclude (elevated property).

**Matching scheme (BUILD):**

- **Primary gate** = `NWSCode` set (byte-exact).
- **Secondary gate** = word-boundary name match on `Event` as deprecated fallback for one release.
- **New knob `CONF_INCLEMENT_POWER_THREAT_EVENT_CODES`** — default set per trust table above.
- **GPS-filtered?** YES-with-nuance (§How NWS alerts work). URA re-filters NOTHING; may use breadth as watch demotion.

**Severity / Certainty policy (REVISED):**

- Severity is a tiebreaker, not the gate. Code match + `Certainty ∈ {Observed, Likely}` → `warn`; else `watch`. Severity floor only breaks ties within tier (and may demote `watch → notice` on `Minor` + breadth).
- Promote `CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION` to Advanced subsection (operator override).

### Q3 — Was forecast lookahead deliberately rejected?

**No.** Grep `PLANNING_inclement_weather_reserve.md` for forecast-lookahead keywords: 0 matches. Only Solcast was consulted; current-state condition only. Memory #16 (v5.3.8 attainability) is about Solcast overstatement — a *different* axis. **Verdict: OMITTED, NOT REJECTED.**

**Proposed input (BUILD, D2):** `WeatherProviderManager.forecast_outage_risk(now, horizon_h)` via HA service `weather.get_forecasts({"type": "hourly"})` per healthy provider, scanning `[now, now+H]` for `precipitation_probability ≥ P` + stormy condition, OR `wind_gust_speed ≥ G`. `agreeing_providers ≥ 2`. Forecast-only → off-peak partial_hold; mid/peak default `allow_discharge` (V2 parked).

**Marginal-benefit decomposition:**

| Variant | Captures | Risk | Verdict |
|---|---|---|---|
| V0 (D1+D3+D4, no forecast) | ~70-80 % of tonight. | Low. | **GO.** |
| V1 (V0 + off-peak forecast hold) | Pre-storm quiet windows. | Low-moderate. | **GO.** |
| V2 (V1 + mid/peak forecast × Solcast) | Afternoon forecast into peak. | Moderate (TOU × combinatorics). | **PARK with 90-day-trip trigger.** |

Recommend **V1**.

### Q4 — Onset + Enphase Storm Guard

**Onset:** D3 reads `Onset`; `pending` tier when `now < Onset ≤ now + CONF_INCLEMENT_ONSET_PRECHARGE_LEAD_MIN`. Pending + off_peak + `grid_precharge_on_hold=True` + in-window → single CFG write. See §How NWS alerts work for Expires-vs-Ends resolution.

**Enphase Storm Guard:** no local entity exposed by any of our 3 Enphase integrations. URA does NOT read; **operator config-first action = disable Storm Guard in Enphase app** (NM-visible reminder attr in D6). Future card `EC-STORM-GUARD-COEXIST-1` parked.

---

## Knob ladder — every number named, rung-placed, justified

| Name | Rung | Default | Bound | Why that rung |
|---|---|---|---|---|
| `CONF_INCLEMENT_POWER_THREAT_EVENT_CODES` | 2 | `[TOR, TOA, SVR, SVA, WIY, WIH, HWA, WSW, WSA, ISW, BZW, HUR, EWW]` | — | Per-deployment regional variation. |
| `CONF_INCLEMENT_POWER_THREAT_EVENTS` (legacy) | 2 | existing | — | REUSE; deprecated fallback. |
| `CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION` | 2 | `True` | — | PROMOTED from hidden. |
| `CONF_INCLEMENT_FORECAST_LOOKAHEAD_H` | 3 (live Number) | `6` | 1-24 | Operator tunes; `0` disables forecast tier. |
| `CONF_INCLEMENT_FORECAST_PRECIP_PROB_PCT` | 3 (live Number) | `50` | 10-100 | Live tune after false alarms. |
| `CONF_INCLEMENT_FORECAST_GUST_MPH` | 3 (live Number) | `40` | 20-65 | NWS Wind Advisory floor; live-tunable. |
| `CONF_INCLEMENT_FORECAST_MIN_AGREEMENT` | 2 | `2` | 1-5 | Structural (provider count). |
| `CONF_INCLEMENT_FORECAST_PRE_PEAK_H` | 2 | `3` | 0-12 | V2 gate; off by default. |
| `CONF_INCLEMENT_ONSET_PRECHARGE_LEAD_MIN` | 3 (live Number) | `90` | 15-240 | Operator tunes against Onset accuracy. |
| `CONF_INCLEMENT_PARTIAL_HOLD_RESERVE_FLOOR` | 2 | existing `50` | — | REUSE. |
| `INCLEMENT_FORECAST_GUST_UPPER_BOUND_MPH` | 1 (const) | `65` | — | Safety ceiling on the live Number. |
| `INCLEMENT_BLIND_SOC_FREE_FULL_HOLD_FLOOR_PCT` | 1 (const) | `100` | — | Already implicit; promote to named const. |
| `INCLEMENT_FORECAST_SERVICE_TIMEOUT_S` | 1 (const) | `3` | — | Service timeout; must not block tick. |
| `INCLEMENT_BREADTH_DEMOTE_AREA_COUNT_TOA` | 1 (const) | `20` | — | Breadth-penalty threshold for Tornado Watch. |
| `INCLEMENT_BREADTH_DEMOTE_AREA_COUNT_SVA` | 1 (const) | `25` | — | Breadth-penalty for Severe T-storm Watch. |

Kill-switch semantics inline (`LOOKAHEAD_H=0` disables forecast tier; `WATCH_REQUIRES_CORROBORATION=False` relaxes condition-path corroboration).

---

## Producer AND Consumer map (per Producer/Consumer rule)

### `InclementDecision` producer dependencies (health check)

- `AlertClassification` — new deps `Onset`, `NWSCode`, `MessageType`, `Urgency`, `AreasAffected` (defensive reads; all optional).
- `StormConditionResult` — state-only (existing).
- `ForecastOutageRisk` — NEW producer; depends on provider health + `weather.get_forecasts` service.
- `SolarHorizon` — existing (`_expected_solar_surplus_pct`, `classify_tomorrow_solar`).
- `current_soc` — 3-tier resolver (EC p1).
- `tou_period`.
- Alternative derivations: none. Fusion is single-site.
- External witness: HA `weather.<provider>` + `nws_alerts.sensor` attrs. Both third-party.

### Consumers (count-the-consumers)

| Site | File:line | Trust vs display | Change |
|---|---|---|---|
| `_inclement_decision` cache store | `energy_battery.py:2734-2735` | internal | called from BEFORE blind-gate too. |
| `_inclement_attrs` | `energy_battery.py:2764-2780` | display | add forecast + pending + recent-events siblings. |
| determine_mode precedence `:5787` | `energy_battery.py:5787` | trust-decision | preserved. |
| **NEW blind-gate pre-emit** | `energy_battery.py:~5578` | trust-decision | **D1.** |
| D2 blind-peak de-escalation | `energy_battery.py:5607-5634` | trust-decision | reads live, simplifies freshness check. |
| EV-overlay re-entry read | `energy_battery.py:4140` | display | unchanged. |
| attribute pack | `energy_battery.py:6985` | display | new siblings. |
| `_apply_evse_battery_hold` | `energy.py` (BOTH call sites `:2566` + `:2890` per v5.5.0 corrections) | trust-decision | **re-verify `max()`-safe** at both. |

### Discriminator (acceptance observation must differ under fix vs. plausible alt-failure)

Under fix on tonight-type repro (NWS Wind Advisory Moderate/Likely + hourly ≥43 % lightning-rainy within 3h + Envoy offline + SOC None):

- `inclement_tier = "watch"` (code match `WIY`, forecast-corroborated).
- `inclement_source = "alert+forecast"`, `forecast_outage_risk.stormy = true`, `agreeing_providers ≥ 2`.
- `inclement_hold_depth = "partial_hold"` (watch + off_peak + forecast corroboration).
- `inclement_reserve_floor = 50`.
- `storm_forecast = true`.
- Queue shows ONE `number.set_value reserve_soc_number=50` with `envoy_available=false`; CFG write **absent**.

Plausible alt-failure (forecast producer silently empty): `tier=notice`, `source=alert`, `hold_depth=allow_discharge`. **Discriminated** on `source`, `forecast_*`, `hold_depth`.

---

## Deliverables

### D1 — Envoy-blind: decide always; command safely (Q1)

Move `self._inclement_decision(tou_period, now)` ABOVE the blind-gate at `energy_battery.py:5578`. Under full-blind (envoy down + SOC None):

- `decision.hold_depth ∈ {full_hold, partial_hold}` → emit result pack with `reserve_level = decision.reserve_floor` (SOC-free), `charge_from_grid=False`, `arbitrage_active=False`, `envoy_available=False`, reason prefix `"Inclement-under-blind ({decision.reason}) — reserve-only emit"`.
- `allow_discharge` → fall through to existing blind-pause return pack.
- D2 blind-peak de-escalation at `:5634` reads the live `decision`; `_inc_fresh` collapses to `decision is not None`.

**Acceptance:**
- **Verify:** `inclement_hold_depth` updates within one tick after Envoy drops with an active qualifying alert.
- **Verify:** reserve-write queue shows the single reserve-raise under full-blind; no CFG write.
- **Sensor:** `sensor.ura_energy_coordinator_battery_strategy.attributes.inclement_source` non-empty under blind when alert exists.
- **Test:** `test_inclement_blind_decides_and_emits_reserve_only`, `test_inclement_blind_no_cfg_write`, regression `test_blind_pause_no_alert_unchanged`.
- **Live:** restart with Envoy-blocked firewall rule + injected test alert; confirm attrs + queued write + no CFG write.

### D2 — Forecast-outage-risk producer + fusion wire (Q3, V1)

New `WeatherProviderManager.forecast_outage_risk(now, horizon_h) → ForecastOutageRisk`. Fusion branch `has_forecast_hold` evaluated when `not has_alert_hold and not condition_only`. Off-peak + forecast corroborated → `partial_hold`. Mid/peak forecast-only → `allow_discharge` (V2 parked).

**Acceptance:**
- **Verify:** 2026-10-15/16-style replay produces `tier=watch, source=forecast, hold_depth=partial_hold` on off-peak.
- **Verify:** `LOOKAHEAD_H=0` → byte-identical to v5.5.0 (kill-switch regression guard).
- **Sensor:** 4 new siblings: `forecast_horizon_h`, `forecast_max_precip_prob`, `forecast_max_gust_mph`, `forecast_agreeing_providers`.
- **Test:** 5 unit tests ((a) no healthy provider → None, (b) 1-of-2 agreeing → false, (c) 2-of-2 precip → true, (d) 2-of-2 gust → true, (e) service timeout → graceful false).
- **Live:** first full day with ≥2 providers, sample attribute values at off-peak boundary; NM silent while `forecast_hold=False`.

### D3 — Onset handling + `pending` tier + precharge lead (Q4) — **APPROVED by operator 2026-10-15 ("Read alert start times. YEs")**

Add `_alert_window(alert)` returning `(onset, ends)`; split current `_alert_expires_at` into `_message_fresh_at` (CAP `Expires`/`Ends` fallback) + `_hazard_active_at` (`Onset ≤ now ≤ Ends`). Drop only on `_message_fresh_at(now)` past AND `_hazard_active_at(now)` false. Pending tier emits when `Urgency == Future` OR `now < Onset ≤ now + CONF_INCLEMENT_ONSET_PRECHARGE_LEAD_MIN`. Pending + off_peak + `grid_precharge_on_hold=True` + lead-in-window → single CFG write; otherwise pending demotes to the watch-off-peak partial_hold path.

**Acceptance:**
- **Verify:** Wind Advisory `Onset=04:00, Ends=19:00` posted at 02:30 → `tier=pending, source=alert` at 02:30; `tier=watch` at 04:00; **does NOT drop at 04:00** (the live-case bug).
- **Verify:** Pending + off_peak + precharge switch on + lead in-window → ONE CFG write; switch off → no CFG write.
- **Test:** `test_pending_tier_before_onset`, `test_pending_demotes_at_onset`, `test_wind_advisory_lives_until_ends`, `test_pending_precharge_respects_switch`.
- **Live:** inject synthetic pending alert via dev-tools; attrs flip `allow_discharge → partial_hold (pending) → watch (partial_hold)`.

### D4 — Code-match + word-boundary name + MessageType + Urgency + breadth + corroboration knob exposed (Q2)

Replace `_event_matches_threat`: (a) exact `alert["NWSCode"]` membership; (b) legacy word-boundary name match as fallback. Early-drop on `MessageType ∈ {Cancel, Ack}`. Breadth-penalty demote per trust table. Expose `CONF_INCLEMENT_WATCH_REQUIRES_CORROBORATION` in Advanced subsection.

**Acceptance:**
- **Verify:** `WIY` + Moderate/Likely → `watch` (code promotes; severity floor off the gate).
- **Verify:** `FLA` (Flood Watch) still gates out — no regression of the v5.5.0 CAP-axis property.
- **Verify:** `Cancel` MessageType drops without classifying.
- **Verify:** `TOA` with `area_count ≥ 20` → `notice` not `watch` (breadth-demote).
- **Test:** `test_match_wiy_wind_advisory`, `test_match_cancel_dropped`, `test_toa_broad_demotes_to_notice`, `test_legacy_substring_fallback`, `test_watch_corroboration_knob_live`.
- **Live:** Advanced subsection shows the WATCH_REQUIRES_CORROBORATION toggle; options-reload persists; attr reflects new value.

### D4b — AUDIT_nws_alerts_90d_at_point.md (Measure-Before-Build gate for the default code set)

One-shot read-only recorder probe (per Measure-Before-Build): tally last 90 days of the point sensor's state attributes by `(NWSCode, count, median_area_count, co-occurrence with outage markers in power/HA logs)`. Verdict table of candidate includes/excludes. **BUILD-D4 default code set is confirmed OR amended against this measurement before ship.**

**Acceptance:**
- **Verify:** `docs/planning/AUDIT_nws_alerts_90d_at_point.md` exists with per-code counts and includes/excludes rationale.
- **Live:** none (planning artifact; feeds D4 defaults).

### D5 — Observability + attribute pack + precedence-comment update

Add attributes: `inclement_source` (`none|alert|condition|forecast|alert+forecast|condition+forecast`), `forecast_*` (4 fields), `pending_onset_at`, `blind_decision_emitted` (bool), `inclement_recent_events` (rolling 24h, bounded 20). Update precedence comment at `energy_battery.py:5728-5772` to 6-step ordering (decide-first, blind-emit-reserve-only).

**Acceptance:**
- **Verify:** all new attributes present after restart; stable on no-event tick.
- **Verify:** `blind_decision_emitted = True` ONLY under full-blind-with-hold; else False.
- **Verify:** `inclement_recent_events` grows per fired event, bounded 20.
- **Live:** attribute values readable via developer-tools; no deprecation warnings.

### D6 — Enphase Storm Guard coexistence note + README

`enphase_storm_guard_coexistence` string attr + README section instructing the operator to disable Storm Guard in the Enphase app.

**Acceptance:**
- **Verify:** attr + README section present.
- **Live:** operator confirms Storm Guard off at ship time; STAND-DOWN page rate unchanged or lower after a storm event.

---

## Non-goals (explicit)

1. **Do not** read Enphase Storm Guard state (Q4).
2. **Do not** add a `_paused_by_storm` set to `energy_pool.py` (collision-class #15/#16).
3. **Do not** change the arbitrage-WAIT floor plumbing (v5.5.3 settled).
4. **Do not** add mid/peak forecast-only holds in V1 (V2 parked).
5. **Do not** polygon-geo-filter in URA; rely on `nws_alerts` zone/county UGC.
6. **Do not** emit CFG writes under full-blind (D1 safety).
7. **Do not** persist alert ledger to the URA DB; attribute payload only (D5).

---

## Parked variants

- **V2 — Forecast-driven mid/peak hold with Solcast gating.** Revival trigger: "≥1 missed peak-outage logged in 90 days post-D2."
- **V3 — URA reads Storm Guard and concedes.** Separate card `EC-STORM-GUARD-COEXIST-1` after one storm cycle on D1-D6.
- **V4 — Polygon-tight geo filtering.** Only if the UGC-wide feed is empirically found to produce >25 % false-positive hold-hours in 90-day audit; needs Shapely dep.

---

## Recommended sequencing

1. **D4b** — AUDIT (gated by Measure-Before-Build; cheap).
2. **D4** — matching (fastest, no `determine_mode` touch).
3. **D3** — Onset / pending / Expires-vs-Ends fix.
4. **D1** — blind-decide + reserve-only emit (precedence-chain move; after D3/D4 so the decision is correct).
5. **D2** — forecast producer + fusion wire.
6. **D5** + **D6** land with the ship.

Each of D1-D4 independently reviewable (Tier-3 four-framing including adversarial-completeness D-pass). D1 is INV-H's load-bearing site; D-pass MUST re-enumerate every reserve-emission site (the 7 from v5.5.3 + the new blind-emit) and mutation-anchor each. D3's `_message_fresh_at` / `_hazard_active_at` split is a secondary load-bearing site and must get its own completeness drill (what if `Onset` missing? `Ends` missing? both?).

---

## Supersession & post-ship audit plan

- **DELETE candidate (after live-validation):** legacy substring list used only as fallback — removed in `<ship+1>` once code-match proven on tonight's log replay. Defer the only irreversible move.
- **KEEP+WIRE:** D2 blind-peak de-escalation should consume `decision.hold_depth` directly rather than CFG-only read — park as `EC-INCLEMENT-D2-CONSUMES-DECISION-1`.
- **KEEP+DOCUMENT:** `has_storm_forecast()` was deleted in v5.5.0 — no new doc.
- Post-ship audit = re-run D4b on the first 30 days post-ship; verify breadth-penalty thresholds (TOA 20, SVA 25) match live false-positive rate.

---

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018uEjYPUcWq73wfBS3t1NEa
