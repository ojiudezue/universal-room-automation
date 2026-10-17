# AUDIT: NWS alert fields, pile-up and update handling in URA EC storm logic

Run 2026-10-17 16:4x-17:1x CDT by ura-prober. Read-only. Operator question: "are we reading the right NWS alert fields, and how do we handle alerts that pile up or the same alert updated with different fields?"
Code read: develop `custom_components/universal_room_automation/domain_coordinators/{inclement.py,energy_outage_ledger.py,energy_battery.py}` and the Stage E worktree `.claude/worktrees/ec-storm-stage-e` (HEAD f248ea612), diffed against develop. Prior audits read: `AUDIT_ec_storm_stage0_probes.md` (P2), `AUDIT_nws_alert_history_lakeway.md`.
Live data: HA recorder via `ssh ha` (ro) `sensor.nws_alerts_gps_30_3146_98_0159_nws_alerts_alerts`, rows from 2026-10-15; integration source `/config/custom_components/nws_alerts/{coordinator.py,sensor.py}` (manifest version 6.7.3). Public: api.weather.gov `openapi.json` Alert schema (https://api.weather.gov/openapi.json; docs https://www.weather.gov/documentation/services-web-api) and live `alerts/active` pulls 2026-10-17.

## Answer first

1. **The fields URA reads are the right ones, with one structural limit.** Hazard window = `Onset or Sent` .. `Ends or Expires` (`inclement.py _hazard_window`, develop :255-265) is correct and is validated by live evidence (below). Status/Type/Event/NWSCode/Severity/Certainty are used sensibly. The limit: the `nws_alerts` integration (6.7.3) **drops** `references`, `effective`, `urgency`, `response`, `geocode`, `affectedZones`, `parameters` (incl. VTEC) and the polygon. URA therefore **cannot link an Update to the message it replaces**; it relies on NWS removing the superseded message from the active feed.
2. **Updates are treated as new independent alerts** (new `ID`, since the integration hashes the message URN). This is safe for the hold/classifier path in practice because the NWS active feed drops the superseded message (0 of 482 active alerts referenced another still-active alert, 2026-10-17). Real consequences are in the **Stage E latch/schedule keyed by alert ID** (resets on every Update) and in the **outage ledger** (one row per message, no event grouping, Onset re-stamped).
3. **Pile-up is handled soundly for tier/expires/hold depth** (max over contributors; lower tier cannot mask higher). Minor issues: duplicate contributing_events for adjacent-segment same-product alerts, and `max_severity/max_certainty` tie-break by list order (display only).
4. `Cancel` handling is near-dead code against this feed (0 `Cancel` of 483 active messages). Harmless, but a Cancel-by-event-name could over-clear memory.

## 1. FIELD MAP

### 1a. What the integration exposes (live and source)

Integration builds each alert dict at `/config/custom_components/nws_alerts/coordinator.py` (`async_get_alerts`, the `tmp_dict[...]` block). Recorder row 2026-10-15 11:11:29 confirms keys exactly (case-sensitive, Title case):

| Integration key | Source CAP/API field | Note |
|---|---|---|
| `Event` | `event` | |
| `ID` | `md5(feature.id)` formatted as UUID (`generate_id`) | a hash of the message URN, NOT the VTEC event id |
| `URL` | `feature.id` (the `urn:oid:...` URL) | |
| `Headline` | `parameters.NWSheadline[0]`, else `event` | |
| `Type` | `messageType` | Alert / Update / Cancel / Ack / Error |
| `NWSCode` | `eventCode.NationalWeatherService[0]` | an empty list raises IndexError, which is not in the caught `(KeyError, TypeError)` -> whole poll fails -> `UpdateFailed` (unavailable) |
| `Status` | `status` | |
| `Severity`, `Certainty` | same | |
| `Sent`, `Onset`, `Expires`, `Ends` | `sent`, `onset`, `expires`, `ends` | `onset` and `ends` are nullable in the API schema |
| `AreasAffected` | `areaDesc` | |
| `Description`, `Instruction` | same | |

**Not exposed** (verified in `coordinator.py`, so URA cannot read them): `references`, `effective`, `urgency`, `response`, `category`, `geocode` (SAME/UGC), `affectedZones`, `parameters` (VTEC, eventEndingTime, expiredReferences), geometry. Sensor attributes are `Alerts`, `configuration_type`, `gps_location`, `icon`, `friendly_name` (recorder `shared_attrs` keys). The list is sorted by `ID` (md5), i.e. arbitrary order, not by time (`coordinator.py` `sorted(..., key=lambda x: x["ID"])`).

API semantics, from the schema (https://api.weather.gov/openapi.json, `Alert`): `onset` = "expected time of the beginning of the subject event"; `ends` = "expected end time of the subject event" (nullable); `expires` = "expiry time of the information of the alert message"; `references` = "prior alerts that this alert updates or replaces".

### 1b. URA field uses

| URA site | Reads | Right field for the use? |
|---|---|---|
| `_hazard_window` (inclement.py develop :255-265) | `Onset` -> `Sent` fallback for start; `Ends` -> `Expires` -> `start + INCLEMENT_ALERT_MAX_HOLD_H` for end | **Yes.** Onset=hazard start (P2c measured onset-sent >0 in 100% of watches); Ends=hazard end. Fallbacks are present at both ends. Live proof Ends is the correct end: the 10-16 18:53 Update has `Expires 20:00`, `Ends 19:00`, and the alert left the feed at 19:00:36 (state 0), not 20:00. Using Expires would have held 1 h too long. |
| `_is_actual` (:268) | `Status`, default "Actual" when absent | Yes. Default-to-actual on a missing key is a fail-toward-hold choice; the integration always supplies it. |
| `_is_cancel` (:273) | `Type == cancel` | Right field. A `Cancel` is effectively never seen: 0 of 483 `alerts/active` messages were Cancel on 2026-10-17 (245 Alert, 238 Update). NWS removes cancelled products from the active feed instead. |
| `match_product` (:277-308) | `Event` (casefold) and `NWSCode` | Yes. `NWSCode` is `eventCode.NationalWeatherService`, the code P3 verified (not SAME). |
| `classify` severity/certainty (:526-533) | `Severity`, `Certainty` | Display-only (attrs). No other consumer of `max_severity`/`max_certainty` found outside inclement.py (grep). Doctrine in the module header (:18) is correct: Severity is not the gate (a Flood Watch is Severe). |
| `update_alert_memory` / `classifier_input` / `alert_key` (:249-252, :346-436) | `ID` (else `URL`, else `Event|Sent`), window, `Event`, `NWSCode`, `Type` | Key = message-level id. Correct as a message key, wrong as an event key (see section 3). |
| Outage ledger `NWS_ALERT_LEDGER_FIELDS` (energy_outage_ledger.py :66-69) | Event, NWSCode, Type, Status, Severity, Certainty, Sent, Onset, Expires, Ends, AreasAffected (+ `id`, ura_class/tier, local) | Faithful copy. Missing for later analysis: `references`/VTEC ETN (not available from integration), `Headline` (available, not stored). `_alert_end` (:100) = Ends else Expires: correct. |
| `energy_battery._read_nws_alerts` (:2699-2712) | `state.attributes["Alerts"]` | Correct key spelling/case (matches the recorder). Returns None if the attribute is absent, and the classifier treats that as no alerts. |
| `weather_manager.py`, `energy.py` | `energy.py:9236-9241` only passes the same list to the ledger | n/a |

Flags (wrong-field or missing-fallback): **none found.** Residual hazards:
- **F1 (low).** If `Ends` is null AND `Onset == Expires` (the first Alert of the 10-15 WIY had `Onset == Expires == 04:00`, saved only because `Ends` was present), the window is zero-length, so the alert would never hold. Live pull 2026-10-17: 9 of 238 Update messages had `ends: null`, and among active alerts nulls were Special Weather Statement (2), Typhoon Warning (3), Tropical Storm Warning (2), Typhoon Watch (2), Flood Warning (2), Air Quality Alert, Marine Weather Statement, and 1 Flood Watch. Table products that can hit it: Flood Warning/Watch. For those, `Expires` is a message expiry, not the hazard end, so the fallback may under- or over-hold. This is not wrong-field (nothing better exists without VTEC `eventEndingTime`), but it is the weakest link of the window.
- **F2 (low).** `Urgency` and `Response` (`Prepare`, `Execute`, ...) are never read; Severity-as-attr is by design.
- **F3 (info).** The integration's hourly-ish poll is 1/min (P2d); Update messages are picked up within a minute.

### 1c. Stage E differences (field map)

`git diff develop` of the worktree touches `inclement.py` (selection overlay, schedule), `energy_battery.py`, `energy_outage_ledger.py`. **Field reads are unchanged:** `_hazard_window`, `_is_actual`, `_is_cancel`, `alert_key`, `classifier_input`, `update_alert_memory` logic and `NWS_ALERT_LEDGER_FIELDS` are identical. `match_product` gained a `selection` parameter and now returns a 3-tuple `(row, drift, corroborable)`; the ledger call site was updated to unpack 3 (diff of energy_outage_ledger.py). The classifier adds `AlertRecord.corroborable` and `active_alerts`. No new alert field is consumed.

## 2. PILE-UP (several concurrent alerts)

Mechanism (`classify`, develop :455-550; Stage E same shape):
- Per-message dedup only: `seen_ids` on `alert_id` (:482-492). Every distinct `ID` is a record.
- **Tier** = `_max_tier` over ACTIVE records (`start <= now <= end`) -> highest wins (`_TIER_ORDER` warn 3 > watch 2 > notice 1). A watch cannot mask a warning; a warning is never demoted.
- **expires_at** = `max(end)` over active HOLD (warn/watch) records only (:541). So a long watch sustains the hold after a shorter warning ends: intended (the hazard persists). A notice never extends it.
- **hold_alerts / contributing_events**: all active hold records. Same-product adjacent segments (live example 2026-10-17: two Small Craft Advisory messages sharing VTEC ETN 0093, ids `...56aa67.001.1` and `.002.1`) both count as records, so `contributing_events` lists the event twice. No decision effect found (tier/expires use max), display only.
- **Prepare set** (D-B6): pre-onset non-polygon HOLD records within lead; prepare class = warn if any warn else watch (`prepare_class_of`). Key row = earliest start within that class. Stage E (INV-7(f)) restricts class, key row and T to corroborable records, so an unlisted/widened product cannot set T. Sound.
- **Watch + warning of the same hazard** (e.g. SVA then SVR): both active, tier=warn; the warn dominates, the watch's longer end still sustains the hold. No double charge: the buy path takes ONE key alert.
- **Latch/schedule** are per key alert ID; only the current key may own a schedule (Stage E sweep: `for k in list(sched): if k != key_id: del`). If a second alert becomes the earliest prepare, the key changes and the schedule is re-planned (not double-bought).
- **max_severity / max_certainty** (:526-533): loop uses `>=` over `active` sorted by tier descending, so among equal severity the LAST (lowest-tier) record wins the certainty text, and notice-class records participate. Display only (no consumer outside inclement.py found). Cosmetic.
- **Masking by gated-out events:** an event without a table row only goes to `gated_out_events`; it cannot suppress a matched one.

No tier-masking or double-count defect found. Falsifier tried: could a lower-tier alert win? Only through `max_severity` text, which no decision reads.

## 3. UPDATES (Update / Cancel with new id and `references`)

### 3a. What actually happens on the house (worked example, recorded 10-15/10-16 Wind Advisory)

Four distinct message IDs for one hazard (recorder rows; list length stayed 1, so NWS replaces, never appends):

| Seen from | ID (md5) | Type | Headline | Sent | Onset | Expires | Ends |
|---|---|---|---|---|---|---|---|
| 10-15 11:11:29 | c71a7467 | Alert | ...IN EFFECT FROM 4 AM TO 7 PM CDT FRIDAY | 10-15 11:10 | 10-16 04:00 | **10-16 04:00** | 10-16 19:00 |
| 10-15 23:51:36 | fbdddbec | Update | ...REMAINS IN EFFECT FROM 4 AM... | 10-15 23:50 | 10-16 04:00 | 10-16 19:00 | 10-16 19:00 |
| 10-16 10:27:37 | d39a0907 | Update | ...REMAINS IN EFFECT UNTIL 7 PM CDT THIS EVENING | 10-16 10:26 | **10-16 10:26** (re-stamped = Sent) | 10-16 19:00 | 10-16 19:00 |
| 10-16 18:54:36 | 7be42762 | Update | ...WILL EXPIRE AT 7 PM CDT THIS EVENING | 10-16 18:53 | **10-16 18:53** (re-stamped) | **10-16 20:00** | 10-16 19:00 |
| 10-16 19:00:36 | (none) | state 0 | | | | | |

d39a0907 -> 7be42762 (the pair the operator named): Sent 10:26 -> 18:53; Onset 10:26 -> 18:53; Expires 19:00 -> **20:00** (now later than Ends); Ends unchanged 19:00; Headline "REMAINS IN EFFECT" -> "WILL EXPIRE"; Description changed from "WHEN...Until 7 PM" to "Winds have decreased below advisory thresholds. However, occasional gusts above 30 mph will continue..."; Instruction dropped (None). Severity Moderate / Certainty Likely / Status Actual / NWSCode WIY identical. The `URL` urn:oid hash differs per message. Observation: an "expiring/decreased" Update is still `Type=Update`, `Status=Actual`; URA keeps holding to `Ends` (19:00), and the feed itself dropped it at 19:00:36, not at Expires.

### 3b. How URA links updates: it does not (by design of the available data)

- The integration does not carry `references`, so linking is impossible without fetching the API directly. The `ID` is a hash of the message URN, which changes on each Update. `alert_key` = ID.
- Supersession is therefore delegated to NWS: `alerts/active` is a current-state view; live check 2026-10-17: of 482 active alerts, **0** have a `reference` identifier that is itself still active. Observed in the house sensor: the superseded message disappeared in the same poll that the Update appeared (list length stayed 1 across all three transitions). A second pattern exists (P2a notes 10-09 AQA kept 2-4 same-event messages with different Sent concurrently), which is the case that matters for 3c.
- `update_alert_memory` rule (3) (`left_feed`, develop :394-400) is what discards the superseded ID from memory: old ID absent from a healthy non-empty feed (the new Update makes it non-empty) -> cleared. Rule (2) Cancel clears by event name + window overlap; with no Cancel in the feed it never fires in practice. Rule (2) matches by event name only, so a Cancel for one Severe Thunderstorm Warning would clear every overlapping SVR memory entry (the feed copies still count because feed wins in `classifier_input`; only the outage-insurance memory is affected). Low.
- The hold continues seamlessly across an Update: the new message carries Onset (past or the same future time) and Ends, so `tier`/`expires_at` do not gap. Verified by the 10-15 23:51 transition (state stayed 1; `expires_at` derived from Ends 19:00 in both).

### 3c. Consequences

| Area | Consequence of Update = new independent alert | Severity |
|---|---|---|
| Hold duration | None where NWS drops the old message. If both old and new are in the feed (the AQA pattern), both are active; max(end) wins; no under-hold. Over-hold only to the older message's Ends. | Low |
| **Re-stamped Onset** | An Update issued after the hazard began carries Onset = Sent. Treated as start = Update time: active immediately, correct. For a PRE-onset Update that moves Onset later (delay), the record re-enters the prepare set with a new start -> Stage E re-plans (D-MED-1 check `sched[key][1] != pstart`). Correct. | Low |
| **Stage E latch/schedule (INV-8)** | Keyed by `alert_id`, the message hash. Every Update changes the key: `_apply_prepare` deletes latch and schedule entries whose key is not in the live prepare set (`for k in list(latch): if k not in live: del`). So the **"reached" latch is lost on an Update** and the frozen schedule is re-planned (`schedule_buy_hours`) from current SOC. Effect: if SOC is below target again, the buy can re-fire after an Update that arrives while still pre-onset (the "reached: no re-buy" property is per message, not per event). WIY example: Update at 23:50 was 4 h pre-onset. Not a safety issue (a buy toward the same target), but it contradicts the intent of the latch. | **Medium** (Stage E-relevant) |
| Outage ledger rows | `_seen_alerts` is keyed by `alert_key` (energy_outage_ledger.py :72-81, :261). One `nws_alert` row per message: the WIY produced 4 rows with different `Sent/Onset/Expires`; no field joins them to one event, and the last row's Onset (18:53) is a re-stamp, not the hazard start (04:00). Anyone computing "alert lead time before an outage" from `Onset` of the latest row will get the wrong lead. First-row Onset (or earliest Onset per event name + overlapping window) is the right one. | **Medium** (analysis integrity) |
| Alert memory | Old ID cleared as `left_feed`, new admitted. The ledger/analysis logs a `inclement_memory_cleared ... (left_feed)` row for every Update; this is expected churn, not feed loss. | Low |
| Drift reporting | `match_product` drift (`observed_code`/`mismatch`) is per event+code, unaffected. | none |

## 4. RECOMMENDATIONS (ranked by risk)

1. **(Medium, Stage E, small) Key the Stage E latch/schedule on a stable event key, not the message hash.** Fallback key without `references` available: `(NWSCode or Event, earliest-known T/S bucket)` is fragile; the robust option is to key on `NWSCode|Event` plus overlapping window (the same overlap predicate already in `update_alert_memory` rule 2). Concrete fix: when a new key alert appears whose event+code match a latch/schedule entry that was just deleted (same tick: old key absent, new key present, windows overlap), migrate the entry to the new ID instead of deleting it. This is a few lines in `_apply_prepare` where the discharge loops are. If the fix is judged too delicate for the in-flight review, ship Stage E as is and card the follow-up, because the failure is a possible re-buy toward an unchanged target, not an under-hold.
2. **(Medium, follow-up, probe-gated) Stop depending on message-id supersession: get `references` + VTEC.** The `nws_alerts` integration cannot supply them. Options: (a) a direct api.weather.gov `alerts/active?point=` read in URA (adds a network client and a second source: new infra, needs the prior-art scan and Tier 2 review); (b) a patch/fork of the custom integration (HACS-managed, would be overwritten); (c) keep the current behaviour and rely on NWS removing superseded messages. Evidence supports (c) today (0/482 active alerts had a still-active reference). Marginal-benefit: do (c) now, park (a/b) with the revival trigger "an Update leaves both messages in the feed and the ledger shows an over-hold or double buy". Measure first: count in the recorder how often 2+ same-event messages coexist (P2a saw it for AQA 10-09).
3. **(Low-Medium, follow-up) Ledger event grouping.** Add to the `nws_alert` payload (cheap, no new data source) the `Headline` and a derived `event_group` = first-seen Onset for the same `Event`+`NWSCode` whose windows overlap, or document that analyses must group by `(Event, NWSCode)` and take the earliest `Onset`. The 10-16 WIY shows 4 rows and a re-stamped last Onset. Belongs with the outage-correlation work, not Stage E.
4. **(Low, follow-up) Null-`Ends` + `Onset == Expires` zero-length window (F1).** Guard in `_hazard_window`: if end <= start, use `start + INCLEMENT_ALERT_MAX_HOLD_H` (that knob already exists as the missing-end fallback). A table product that can hit it today: Flood Watch/Warning (the 1 Flood Watch with null `ends` on 2026-10-17). Fail-toward-hold is consistent with the module's doctrine; add a unit test with the 10-15 first-Alert shape minus `Ends`.
5. **(Low, follow-up) Cancel rule (2) name-only match.** Require the overlap test to include a shared `NWSCode` and, if available, a shared `AreasAffected` before clearing; or accept as-is since Cancel is absent from the feed (0/483) and only memory is affected.
6. **(Cosmetic, any time) `max_severity/max_certainty` tie-break** (`>=` makes the last record win) and duplicate `contributing_events` for same-product segments: dedupe by `(Event)` for display and prefer the highest-tier record on severity ties. No consumer found; do not spend review budget.
7. **(Info) Integration fragility:** `eventCode.NationalWeatherService[0]` IndexError is not caught by the integration, so one malformed alert would make the whole poll `UpdateFailed` (sensor unavailable). The D-B3 memory covers this (stale feed clears nothing). No URA change.

## What would change these conclusions

- A live case where an Update leaves BOTH messages in the feed with different Ends (P2a AQA 10-09 pattern): then max(end) over-holds to the older Ends; confirm by recorder scan before acting on rec 2.
- Any `Cancel` appearing in the sensor `Alerts` list: would exercise rule (2); none seen in the 10-09..10-16 recorder window summarised in P2 nor in the live feed today.
- A Flood/other table product with `ends` null on the house sensor: would exercise F1.

Not verified: the Description diff of fbdddbec vs c71a7467 beyond the first 160 chars; whether `Ends` null occurs for SVR/TOR/WSW (the live sample on 2026-10-17 contained no active TOR/SVR/WSW, only one Flood Watch from the six table products I sampled, with `ends` null).
