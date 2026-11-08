# PLANNING — EC inclement leftovers (retired threat list, forecast thresholds, period-name sites, blind envoy_available)

**Status:** Rev 2, 2026-11-08 (plan review 1 `docs/reviews/code-review/ec_inclement_leftovers_plan_review_1.md` @ `61788218`, FIX-PLAN-FIRST 0C/2H/4M/4L; every finding folded, see §10). Not built. Operator approved building items 2, 4, 5. Item 3 is a recommendation only.
**Cards:** EC-INCLEMENT-HARDENING-1 (residual `residual_2026_10_17_legacy_threat_list`; open item "precip confirm thresholds 50 % / 1.0 mm unfitted"), EC-BLIND-DEESCALATE-TOP-RATE-1, EC-STORM-FULLHOLD-DEGRADED-ENVOY-AVAILABLE-1.
**Parent plans:** `PLANNING_ec_storm_and_blind_decisions.md` (Rev 3.3: §6 Stage D, §8 site table, §14 Q1/Q8 rulings), `PLANNING_ec_storm_stage_e.md` (E1.9 deletions, §row 19 thresholds parked), `PLANNING_inclement_hardening.md`.

Every line reference below was re-located on `develop` @ `2377ad92` (v5.106.1). The cards' references are from about v5.103.6x and are stale.

---

## 0. Headline: what the cards say vs what the code says

Three of the four items are partly or fully done already. The plan is mostly the remaining tail.

| Item | Card claim | Current code (verified) | What is left |
|---|---|---|---|
| 2 | `energy_battery.py ~2647-2660` reads/passes the threat list; `config_flow.py ~6030-6037, 6164-6168` imports/parses it | **Gone.** Stage E E1.9 (`8e094e5f`) deleted those readers, the warn-min-severity key/default/options, the options-form fields and their strings. `git grep` finds no reader in `energy_battery.py`, `config_flow.py`, `options_flow.py` or `inclement.py`. | The constant + default list, the one-shot repair check that is their only reader, its repair-issue strings, and a test-only `classify(threat=, warn_min=)` shim. |
| 3 | 50 % / 1.0 mm unfitted | Still unfitted. Scope narrowed on 10-17: convective now uses its own 70 % + storm condition. | Recommendation + a measure-first probe (§D3). |
| 4 | Blind de-escalation keys on literal `"peak"` | **Fixed** in Stage A (`15b7ab39`): `_is_top_rate_edge` (`energy_battery.py:7373-7395`) uses `TOURateEngine.is_top_rate` / `is_top_period` (`energy_tou.py:505-528`); caller `energy_battery.py:6554`. The literal survives only as the no-engine fallback (`:7386`, `:7395`). | Stage D of the parent plan (never built): migrate the "above bottom rate" (H) sites, pin the rest. |
| 5 | Full-hold degraded path returns `envoy_available=True` | **Fixed** in `95ecb743` (Review B B-LOW-2): `energy_battery.py:6835-6838` sets `_res["envoy_available"] = False`; pre-onset sibling at `:6913-6919`. Test `test_ec_stage_b_preonset_precharge.py:1616`. | **One sibling site still hard-codes `True`:** `_get_attainability_hold_current_decision` (`energy_battery.py:5746-5756`). |

The cards should be updated with these findings when this plan is dispositioned (surgical yaml edits only).

---

## 1. Institutional context verified

### 1a. REUSE / NEW per proposed piece

| Piece | Verdict | Evidence |
|---|---|---|
| Top-rate primitive | **REUSE** `TOURateEngine.is_top_rate` / `is_top_period` / `period_rank` / `rate_rank` / `is_bottom_rate` (`energy_tou.py:491-533`) | Shipped Stage A `15b7ab39`. No new primitive is needed. |
| Bottom-rate check for H sites | **REUSE** `is_bottom_rate(now)` (`energy_tou.py:530`) for "now" sites; `period_rank(season, period) != 0` (`:491`) for sites that hold a *future* period name (`hvac_predict.py:2063/2073`, `sensor.py:9430`) | Precedent: `energy_battery._is_bottom_rate` (`:3405-3414`) wraps the engine with a literal fallback when the engine is absent. |
| Literal-site pin test | **REUSE** the AST-allowlist pattern of `test_ec_stage_e_selection.py::test_legacy_plumbing_removed` (`:647-685`) and the governor lint `test_cfg_true_emission_sites_pinned` | Parent plan §6 Stage D names it `TOU_PERIOD_NAME_LITERAL_SITES` / `test_period_literal_sites_pinned`. `git grep` = 0 hits, so it was never built. |
| `envoy_available` derivation | **REUSE** the `_result` rule `bool(self._degraded_telemetry_source is None)` (`energy_battery.py:7895-7897`) | Same derivation the B-LOW-2 fix relies on. |
| Forecast thresholds | **REUSE** `FORECAST_PRECIP_CONFIRM_PCT` / `_MM` (`energy_const.py:1123`, `:1128`) | No new knob is proposed. |
| `above_bottom_rate(tou, season, period)` (Rev 2) | **NEW**, one pure module function in `energy_tou.py` | The engine has `period_rank(season, period)` (`energy_tou.py:491`) but no "rank a GIVEN period, fall back to the literal" helper. `is_bottom_rate(now)` (`:530`) and the battery wrapper `_is_bottom_rate` (`energy_battery.py:3405`) rank the CLOCK period, which is wrong for sites that receive `tou_period` (review H1). |
| `TOU_PERIOD_NAME_LITERAL_SITES` (pin dict) | **NEW** rung-1 dict in `energy_const.py` | Named in parent §6 Stage D, never built (grep = 0). |
| Anything else NEW | **None.** No CONF key, entity, signal or table. | |

### 1b. Greps run (develop @ 2377ad92)

- `git grep -n -iE "power_threat_events|threat_min_severity|warn_min|threat_events|min_severity"` repo-wide (code, tests, strings, translations, skills). Results in §D2 table. `routine_event_min_severity` hits are a different, live NM feature; out of scope.
- `git grep -n "_check_legacy_threat_list|inclement_legacy_threat_list_retired"`: `energy.py:1324` (caller in setup), `:9512-9543` (def), `strings.json:2359`, `translations/en.json:2359`, tests `test_ec_stage_b_classification.py:539-556`, `test_ec_outage_ledger.py:1646-1669`, `test_ec_stage_e_selection.py:672`.
- Item 4 (Rev 2): an AST walk per the §D4.1 rule (every `ast.Constant` equal to `"peak"`/`"mid_peak"`, docstrings excluded) over `custom_components/universal_room_automation/`: **64 occurrences / 37 keys** (§D4.2). Raw `git grep -nE '"(peak|mid_peak)"' -- '*.py'` gives ~60 lines; the difference is docstring/comment text and multi-hit lines. Rev 1's 39 came from a comparison-only grep and missed the `.get(...)` keys, `energy.py:4236`, `energy_battery.py:5294/5296/6991`, the `energy_tou.py` normalizer and the `energy_const.py` tariff keys (review H2).
- `grep -n '"envoy_available"' energy*.py`: `energy_battery.py:5756` (literal True), `:6678` (False, fully-blind), `:6838`, `:6919` (False overrides), `:7895` (derived in `_result`), `:8351` (status); consumers `energy.py:3760` (`_track_envoy_availability`), `:7949` (display), `:14117`.
- `awk` scan for literal `return {` decision dicts in `energy_battery.py:5600-7960`: exactly three (`:5746`, `:6668`, `:7882`).
- `git grep -n "FORECAST_PRECIP_CONFIRM"`: `energy_const.py:1123,1128`; `inclement.py:1795-1824` (`forecast_confirms`).

### 1c. Live config read (Samba mount, `.storage/core.config_entries`, 2026-11-08)

- CM options still carry `inclement_power_threat_events` = the v5.5.0 default list (8 items) and `inclement_warn_min_severity = "Severe"`. Both have been inert since Stage B/E shipped; options-flow load and save have run with them present. That is live proof stored stale keys are harmless.
- `.storage/repairs.issue_registry`: no `inclement_legacy_threat_list_retired` issue.
- `inclement_grid_precharge_on_hold = False` → every forecast-confirmed **buy** leg is dormant live. The thresholds still matter for the **watch hold corroboration and the pre-onset high floor** (§D3).
- Live tariff (`universal_room_automation/tou_rates.json`): summer (Jun–Sep) off 0.0435 / mid 0.0932 / peak 0.1618; shoulder (Mar–May, Oct–Nov) and winter (Dec–Feb) off 0.0435 / mid 0.0864 and **no `peak` period**. Off-peak is the bottom rate in every season.

### 1d. Docs and memory read

- `PLANNING_ec_storm_and_blind_decisions.md`: §6 Stage D, §8 (35-site classification), §9 tiers, §14 Q1 (keep 4 T-change sites named, ruled B) and Q8 (Stage D: "do it, don't park"), §16 (thresholds not fitted).
- `PLANNING_ec_storm_stage_e.md`: E1.9 deletions; table row 283 (`_check_legacy_threat_list` KEEP as "live repair path"; this plan revisits that); row 552 (thresholds parked, trigger 2027-03-31).
- `PLANNING_inclement_hardening.md` (:62, :298, the 43 % live sample).
- `AUDIT_outage_alert_correlation.md`, `AUDIT_nws_alert_history_lakeway.md`, `AUDIT_ec_storm_stage0_probes.md` (P1: PoP not set, single sample).
- `docs/reviews/code-review/ec_stage_bc_review_B.md` (repair path idempotent), `plan_ec_storm_blind_review_1.md` M5 (`off_peak` literals).
- Memory: `project_storm_counsel_doctrine`, `feedback_marginal_benefit_pushback`, `feedback_coincidental_equality_masks_concept_split`, `feedback_finish_the_job_all_pieces`, `feedback_tier2db_for_regression_prone`.
- **`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` read completely (Rev 2, all 725 lines)**, because D4 edits `hvac_predict.py`. The touched attrs `anchor_period` / `anchor_starts_in_minutes` are display-only: returned by `get_intent_attrs` (`hvac_predict.py:2124-2128`) and read only by `sensor.py:13065` (plan review 1, re-checked). No §10 corrections-ledger claim (C1–C38) is touched or re-asserted. The doc has no TOU-anchor content; §11 step 6 (W3 "pre-cool window TOU-derived") is unaffected and not started. No HVAC STATE_OF_PLAY update is needed because no HVAC decision changes. This is not presence work, so the presence docs do not apply.
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` has no threat-list text (grep = 0). **`docs/user-manual/ENERGY_COORDINATOR.md:174`, `:306-307` still document the list and min-severity as live options** (review M1; added to D2).

### 1e. Code surveyed

`energy_battery.py` (`determine_mode` 6375-6990, `_get_attainability_hold_current_decision` 5626-5770, `_run_attain_branch` 5961-6260, `_result` 7820-7900, `_is_top_rate_edge` 7373-7405); `energy.py` (`_track_envoy_availability` 3756-3795, `_check_legacy_threat_list` 9512-9543, `_update_hvac_constraint` / `_update_energy_situation` / `_update_load_shedding` 9590-9830); `energy_tou.py` 487-700; `inclement.py` 1230-1830; `energy_pool.py` 400-410, 1365-1405, 1855-1865, 2765-2775, 3940-3965, 4530-4540; `hvac_predict.py` 2055-2080; `sensor.py` 9415-9435; `energy_billing.py:875`.

---

## 2. Falsifiable invariants

- **INV-L1 (item 2, decision-neutral removal).** For any CM options dict, including one that still carries `inclement_power_threat_events` and/or `inclement_warn_min_severity` with any value, every `InclementDecision` and every `determine_mode` result is identical before and after the removal. Options-flow init and save with those keys present raise nothing.
  *Falsifier:* any reader of either key left behind, or a schema validator that rejects unknown stored keys.
- **INV-P1 (item 4, byte-identical migration).** For ANY `(season, period)` argument pair on the live PEC tariff, and for any non-rankable engine (None, MagicMock, unknown season/period), `above_bottom_rate` equals `period in ("peak","mid_peak")`. Each of the 9 H sites decides only through that helper on the PASSED period (never the clock period). After the build, the `{(file, func, literal): count}` map of `"peak"`/`"mid_peak"` constants (D4.1 rule) equals the pin exactly.
  *Falsifiers:* a site that ranks the clock period instead of its `tou_period` argument (a direct `_update_load_shedding("peak")` call at an off-peak wall clock then stops shedding; review H1); a `MagicMock` rank read as truthy; a future-period site using `get_season(now)` across a season boundary; a new literal or a docstring-only literal mis-counted by the lint.
- **INV-E1 (item 5).** On any `determine_mode` call where `self.envoy_available` is False, the returned dict has `envoy_available is False`. This holds on every return path: `_result`, the fully-blind literal dict, the storm precharge overrides, and the attain HOLD-CURRENT literal dict.
  *Falsifier:* Envoy telemetry-blind + SOC resolved via cloud/LKG + attain latched `charging` + rate window `None` (post-reboot K-tick warm-up). Today `_get_attainability_hold_current_decision` returns `envoy_available: True` (`energy_battery.py:5756`). `_track_envoy_availability` (`energy.py:3760-3768`) then zeroes `_envoy_unavailable_count` and clears `_envoy_degraded` on that tick.

---

## 3. Producer and consumer checks

### `inclement_power_threat_events` / `inclement_warn_min_severity` (item 2)
- **Producer:** none since E1.9. The options form no longer renders either field (`test_legacy_plumbing_removed` asserts this). Stored values are fossil v5.5.0 data.
- **Consumers:** one. `EnergyCoordinator._check_legacy_threat_list` (`energy.py:9512`, called once at setup `:1324`) is display-only and raises a repair issue when the stored list ≠ default. It never feeds a decision. On the live install it returns False on every boot because the stored value equals the default. `INCLEMENT_SEVERITY_ORDER` (`energy_const.py:1191`) is **not** this plumbing: it is live, read by `inclement._severity_rank` → `max_severity` attr (`inclement.py:191-197, :750`). KEEP.

### `FORECAST_PRECIP_CONFIRM_PCT` / `_MM` (item 3)
- **Producer:** rung-1 module constants (`energy_const.py:1123, :1128`), not fitted.
- **Consumer:** `inclement.forecast_confirms` (`inclement.py:1768-1832`) only.
  - `winter_storm` family (Winter Storm Warning/Watch, Ice Storm Warning, Blizzard Warning; `energy_const.py:1174-1177`): `tmin ≤ 32 °F AND (max_pop ≥ 50 OR max_precip_mm_no_pop ≥ 1.0)`. **This is the only user of PCT=50.**
  - `convective` family: `storm condition AND (max_pop ≥ 70 OR max_precip_mm_no_pop ≥ 1.0)`. **MM=1.0 is still shared here**, on no-PoP (Open-Meteo backup) hours.
  - `freeze` family: temperature only. Neither constant applies.
- **Downstream of `confirms`** (via `_forecast_confirmed_ids`, `energy_battery.py:3354`, latched per alert id): (a) the zone buy legs (`inclement.py:1367, 1528, 1610`), dormant live because `inclement_grid_precharge_on_hold = False`; (b) **live:** watch-hold corroboration (`inclement.py:1563-1572`); (c) **live:** the pre-onset high floor for a confirmed watch (`inclement.py:1348-1352`, `:1450-1455`).

### `tou_period` literals (item 4)
- **Producer:** `TOURateEngine.get_current_period` (`energy_tou.py:459`) from `tou_rates.json`. Healthy; three named periods (`_VALID_PERIODS`, `:47`).
- **Consumers:** the 64 constant occurrences (37 keys) in §D4.2; the 9 H sites pass their own `tou_period` (or a future period) and must be ranked as passed.

### `decision["envoy_available"]` (item 5)
- **Producer:** `_result` derives it (`:7895`). Three literal-dict returns bypass `_result` (`:5746` True, `:6668` False) or post-override it (`:6838`, `:6919`).
- **Consumers:** `_track_envoy_availability` (`energy.py:3760`), a **trust decision**: the outage counter, the D7 degraded flag and the "Envoy Offline" NM page at count 3. `energy.py:7949` is display.

---

## 4. Emission / decision-site enumeration

- Item 2: §D2 table (every repo reference).
- Item 4: §D4.2 table, generated by the §D4.1 AST rule (64 occurrences / 37 keys), the same rule the pin test uses.
- Item 5: the six `"envoy_available"` writers listed in §1b. The three literal dicts are the whole bypass surface; `_stamp_grid_buy` passes the dict through unchanged.

---

## 5. Deliverables

### D2 — Remove the retired threat-list tail (item 2)

**Per-symbol verdict:**

| Symbol / reference | Location | Verdict | Evidence |
|---|---|---|---|
| Readers in `energy_battery.py` / `config_flow.py` (card's sites) | — | **Already removed** (E1.9) | grep = 0 |
| `CONF_INCLEMENT_WARN_MIN_SEVERITY`, default, options list | — | **Already removed** (E1.9) | grep = 0; pinned by `test_legacy_plumbing_removed` |
| Options-form strings for both fields | `strings.json`, `translations/en.json` | **Already removed** | asserted at `test_ec_stage_e_selection.py:680-684`; listed as deleted in `test_dpm_cleanup_and_labels.py:474-478` (leave as is) |
| `CONF_INCLEMENT_POWER_THREAT_EVENTS` | `energy_const.py:847` (+ comment `:841-846`) | **REMOVE** | sole reader is the repair check |
| `DEFAULT_INCLEMENT_POWER_THREAT_EVENTS` | `energy_const.py:864-873` (+ comment `:861-862`) | **REMOVE** | read by the repair check and two tests only |
| `EnergyCoordinator._check_legacy_threat_list` + call | `energy.py:9512-9543`, `:1322-1324` | **REMOVE** | Display-only. Fires only when the stored list ≠ default, which happened on no install (live = default; registry empty). New installs can never set the key (form field gone). The repair text tells the operator to use the product selection, which is now documented in the options form itself. |
| Repair issue `inclement_legacy_threat_list_retired` | `strings.json:2359-2362`, `translations/en.json:2359-2362` | **REMOVE** | No producer left |
| Test shim `classify(alerts, threat=None, warn_min=...)` + `del threat, warn_min` | `test_inclement_alert_classifier.py:110-114`; callers `:216-218`, `:229` | **REMOVE kwargs**; keep both tests' assertions (Red Flag gated out; severity never demotes) | test-only plumbing for retired args |
| `test_legacy_threat_list_*` repair tests | `test_ec_stage_b_classification.py:32-33, 535-556` | **DELETE** (they test removed code) | |
| Repair-check stub in ledger test | `test_ec_outage_ledger.py:1646-1669` | **EDIT**: drop the `_check_legacy_threat_list` stub/assertion; keep the rest | |
| Allowlist in `test_legacy_plumbing_removed` | `test_ec_stage_e_selection.py:648-674` | **TIGHTEN**: `allowed = set()`; add `DEFAULT_INCLEMENT_POWER_THREAT_EVENTS` and `_check_legacy_threat_list` to the forbidden names; add `inclement_legacy_threat_list_retired` to the forbidden strings for both string files | Turns the removal into a pin |
| Test import + list build from `DEFAULT_INCLEMENT_POWER_THREAT_EVENTS` | `test_inclement_alert_classifier.py:79` (import), `:216` (`threat = list(DEFAULT_...) + ["Red Flag"]`) | **EDIT**: drop the import (else the whole module fails collection) and the `threat` list; the Red-Flag test becomes a plain `classify([...])` with the same assertions (`tier == "none"`, `"Red Flag Warning" in gated_out_events`) | review M1 |
| User manual rows | `docs/user-manual/ENERGY_COORDINATOR.md:174` ("event-type relevance is the PRIMARY gate ... matching the operator's list"), `:306` (Power-threat events), `:307` (Min severity) | **EDIT**: delete rows 306-307; rewrite :174 to say hold/buy selection comes from the product table + "Alerts that hold the battery" / "Of those, alerts that may buy grid power" | stale user-facing doc (review M1) |
| `docs/readmes/README_v5.5.0.md:10` | release history | **LEAVE AS IS** | READMEs are the dated validation ledger; never rewritten |
| `inclement.py:21` module docstring mention | `inclement.py:18-22` | **EDIT** wording to past tense ("the retired v5.5.0 list") | doc only |
| `INCLEMENT_SEVERITY_ORDER`, `_severity_rank` | `energy_const.py:1191`, `inclement.py:191` | **KEEP** (live, attrs) | `inclement.py:750` |
| Stored option keys in `core.config_entries` | live CM entry | **KEEP, do not purge** | Inert (no reader). Writing options to purge them risks a CM reload (`feedback_parent_entry_reload_watchdog_hazard`) for zero gain. |
| `.claude/skills/ura-energy-strategy-reference/SKILL.md:217` ("Severity gated against `warn_min_severity`") | skill doc | **EDIT**: severity is attrs-only since Stage B D-B2 | stale doc |
| Prior-plan text (`PLANNING_ec_storm_stage_e.md:283` KEEP) | doc | Note supersession in this plan; do not rewrite history | |

**Open uncertainty (state, don't guess):** I have not verified how HA's issue registry treats a previously created non-persistent issue whose integration code no longer creates it. It does not matter live (no such issue exists). If the operator wants belt-and-braces for future installs, the alternative is one `ir.async_delete_issue(..., "inclement_legacy_threat_list_retired")` at setup. Recommendation: **don't add it**. No install has the issue, and the key can no longer be customized.

#### Acceptance criteria
- **Verify:** `git grep -n "POWER_THREAT\|power_threat_events\|_check_legacy_threat_list\|inclement_legacy_threat_list_retired" custom_components/` returns nothing.
- **Verify (INV-L1):** a test builds the CM options with the legacy keys present (default list, a customized list `+["Flood"]`, a string form, `warn_min_severity="Extreme"`), runs `InclementFusion.decide` / `determine_mode` on a fixed alert set, and asserts results equal the same run without the keys. Discriminates: under a leftover reader, the customized-list case diverges. Under a clean removal, all four are equal.
- **Verify:** options-flow `async_step_init` → coordinator_energy renders and saves with the legacy keys in `entry.options` (no `vol.Invalid`, keys untouched in the saved dict).
- **Verify:** `git grep -n "DEFAULT_INCLEMENT_POWER_THREAT_EVENTS\|power_threat" quality/` returns nothing, and the full suite collects (no `ImportError` in `test_inclement_alert_classifier.py`).
- **Test:** `test_legacy_plumbing_removed` (tightened), `test_legacy_inclement_keys_decision_neutral` (new), `test_options_flow_tolerates_legacy_inclement_keys` (new), existing `test_legacy_threat_list_is_ignored_red_flag_stays_gated_out` and `test_severity_never_demotes_table_tier` (import, list build and shim kwargs dropped; assertions kept).
- **Live:** after restart, `sensor.ura_energy_coordinator_battery_strategy` reason/mode/`inclement_*` attrs match the pre-deploy snapshot taken in the same TOU period and alert state; no new `repairs` issue; no `inclement` WARNING/ERROR in the first 10 min of logs; CM options still show the two fossil keys (untouched).

### D3 — Forecast confirm thresholds (item 3): recommendation only

**Which paths still use them (verified):**
- `FORECAST_PRECIP_CONFIRM_PCT = 50`: **winter_storm family only** (Winter Storm Warning/Watch, Ice Storm Warning, Blizzard Warning).
- `FORECAST_PRECIP_CONFIRM_MM = 1.0`: winter_storm **and** convective, on hours whose provider has no PoP (Open-Meteo backup when OWM is down).
- Live effect today: watch-hold corroboration and the pre-onset high floor (80) for a **Winter Storm Watch**. Warnings hold regardless. Buys are dormant (`grid_precharge_on_hold = False`).

**Recommendation:**
1. **Keep PCT at 50 for the winter family. Do not raise it to match convective's 70.** The risk runs the other way. Locally, freeze/ice products are the outage class: Winter Storm Warning 3/9 windows with a documented outage, Ice Storm 1/1, Hard Freeze 1/5; Wind Advisory 0/33 and point-covering SVR 0/32 (`AUDIT_outage_alert_correlation.md:49-60`). A missed confirm on an ice storm costs a low-SOC outage. A false confirm costs a watch floor (or, if buys get enabled, off-peak kWh at $0.0435).
2. **The suspect number is `MM = 1.0` for the winter family, not PCT.** Freezing-rain events accrete ice at liquid-equivalent rates that are often well under 1 mm/h. On an OWM outage the Open-Meteo backup could then fail to confirm a real ice storm. I'm reasoning from meteorology here; this has not been measured, so it is not grounds for a change yet.
3. **Measure first (cheap, read-only, `ura-prober`):** pull archived hourly model forecasts (Open-Meteo Historical Forecast API; **verify its archive depth covers 2023-01** before relying on it) for the house coordinates over the 2023-01-30..02-03 ice storm, the 2026-01-23..26 event, and the 6 non-outage Winter Storm Warning windows in `AUDIT_nws_alert_history_lakeway.md`. Report per window: max hourly precip mm, max PoP if present, min temp. **Go/no-go:** if any outage window fails `mm ≥ 1.0 ∧ t ≤ 32` while passing at a lower mm, propose a separate winter-family MM constant at the highest value that confirms every outage window. That is a rung-1 constant change, flagged for operator OK. If every outage window confirms at 1.0, close the item as "validated, keep".
4. **Evidence that is missing and will not appear on its own:** URA records no hourly forecast or alert history (the DB has no alert/forecast table; only `energy_forecast_log`). The parent plan's "revisit after a season accrues" (`PLANNING_ec_storm_stage_e.md:552`, trigger 2027-03-31) cannot fire because nothing is accruing. Either run the archive probe in step 3 or card a small forecast-outlook logger. Do not wait for 2027-03-31.

No build for D3 in this cycle. No constant change is clearly supported by evidence yet.

### D4 — Period-name literal sites (item 4): finish parent Stage D

**Scope decision.** Neither option (a) nor (b) as posed; a third option applies.
- (a)'s "add one primitive and migrate the blind site" is already shipped (Stage A, `15b7ab39`, `_is_top_rate_edge`).
- (b) "migrate every means-top-rate site" would migrate the four **T-change** sites. The operator ruled those B (keep named) on 2026-10-16 (parent §14 Q1). Each one changes shoulder/winter behavior (HVAC coast/shed, pool speed, excess-solar EVSE at 17-21 for 8 months a year), so each is a policy change, not a fix. Marginal benefit is small: in shoulder/winter the `mid_peak` branch of `determine_mode` (`energy_battery.py:6967+`) already discharges the battery through the top rate, so those loads run on battery unless SOC is exhausted. The spread at stake is $0.086 − $0.0435 per kWh. **Recommend keeping Q1 = B.** Revival trigger per site: grid import during shoulder/winter `mid_peak` above 1 kWh/day on 5+ days in a month (one recorder query), which means the battery is not covering the top rate.
- **This cycle = parent Stage D as ruled (Q8 "do it, don't park"):** route the 9 H sites through ONE pure rate-rank helper, and pin every remaining literal so no new text match lands silently.

**Honest marginal-benefit note.** On the live tariff every H migration is byte-identical: off_peak is the bottom rate in every season, so for a valid period `not off_peak` ≡ `in ("peak","mid_peak")` ≡ rank > 0. D4 buys portability (a second tariff, e.g. a super-off-peak) and the pin. It fixes no live decision. The operator already chose to do it (Q8); this plan keeps it small.

#### D4.1 The site rule (mechanical, AST-based; the table and the pin use the SAME rule)

A **site** is every `ast.Constant` node whose value is exactly `"peak"` or `"mid_peak"` in any `*.py` under `custom_components/universal_room_automation/`, **excluding docstrings**: the `Constant` that is the value of the first statement (an `ast.Expr`) of a `Module`, `ClassDef`, `FunctionDef` or `AsyncFunctionDef` body. Comments are not AST nodes and never count. Each site is keyed by `(relative path, nearest enclosing FunctionDef/AsyncFunctionDef name or "<module>", literal)`; the pin stores the **occurrence count** per key (several occurrences can share a key). Substring checks such as `"Peak" in reason` and `.lower()` reads are covered only when the exact constant appears (e.g. `"mid_peak" in (reason or "").lower()` at `:7877` is a site; `"Peak" in reason` is not).

No exclusion list: tariff-definition constants (`energy_const.py` default-tariff dict keys, `energy_tou.py` normalizer table and `_VALID_PERIODS`) are IN the pin as class **DEF**. A new literal in those files then also needs a reviewed pin edit, at zero extra code.

Reproduction script used for this table (develop @ 2377ad92): walk the AST as above, print key, count, line numbers. **Result: 64 occurrences under 37 keys.**

#### D4.2 Site table (regenerated from D4.1; 64 occurrences / 37 keys)

Classes: **T-fb** = top-rate fallback inside the Stage A primitive; **T-change** = top rate but migrating changes shoulder/winter behavior (kept named, Q1); **H** = "above the bottom rate" (migrate, byte-identical); **N** = the named period on purpose; **DEF** = tariff definition / name normalization.

| Key (file · function · literal) | Count | Lines | Use | Class | Verdict |
|---|---|---|---|---|---|
| energy.py · `_decision_cycle_body` · peak | 1 | 7153 | SOC-at-peak degradation baseline | N | pin |
| energy.py · `_get_displaced_rate` · peak | 2 | 4234, 4235 | displaced-rate lookup: summer peak rate | N | pin |
| energy.py · `_get_displaced_rate` · mid_peak | 2 | 4236, 4237 | displaced-rate lookup: else mid_peak rate | N | pin (note: means "season top rate" by tariff structure; byte-identical today; a `max(import_rate)` rewrite is portability-only, not in scope) |
| energy.py · `_update_energy_situation` · peak / mid_peak | 1 / 1 | 9744 / 9746 | situation "optimizing" (display) | H | **migrate** (one `elif` through the helper) |
| energy.py · `_update_hvac_constraint` · peak | 2 | 9618, 9626 | 9618 = shed at peak + low SOC (**T-change**); 9626 = HVAC coast at peak (N) | T-change + N | pin |
| energy.py · `_update_hvac_constraint` · mid_peak | 2 | 9603, 9631 | summer post-peak mid_peak; mid_peak poor-solar | N | pin |
| energy.py · `_update_load_shedding` · peak | 2 | 9773, 9823 | 9773 = shed only above bottom (H); 9823 = peak import learning history (N) | H + N | **migrate 9773**; pin 9823 (count 2 → 1) |
| energy.py · `_update_load_shedding` · mid_peak | 1 | 9773 | as above | H | **migrate** (count 1 → 0) |
| energy_battery.py · `_evaluate_untrusted_boundary_page` · peak | 1 | 2296 | skip untrusted-SOC page in peak (benign in shoulder: boundary None → no page) | T-change | pin |
| energy_battery.py · `_attain_target_boundary` · mid_peak | 1 | 5287 | mid_peak → walk to next peak | N | pin |
| energy_battery.py · `_attain_target_boundary` · peak | 2 | 5294, 5296 | walk compare + returned period name | N | pin |
| energy_battery.py · `_midpeak_rate_lt_peak` · mid_peak / peak | 1 / 1 | 5352 / 5353 | rate-dict `.get(...)` keys | N | pin |
| energy_battery.py · `_should_attain_peak_buffer` · mid_peak | 1 | 5413 | attain D1b gate | N | pin |
| energy_battery.py · `_adopt_attain_state_from_hardware` · mid_peak | 1 | 5848 | attain D1b gate | N | pin |
| energy_battery.py · `_run_attain_branch` · mid_peak | 4 | 6009, 6091, 6254, 6354 | D1b rate re-check ×2; stage label ×2 | N | pin |
| energy_battery.py · `determine_mode` · peak | 1 | 6946 | peak strategy branch | N | pin |
| energy_battery.py · `determine_mode` · mid_peak | 2 | 6967, 6991 | mid_peak branch; `tou_period="mid_peak"` kwarg into attain | N | pin |
| energy_battery.py · `_is_top_rate_edge` · peak | 4 | 7386 ×2, 7395 ×2 | no-engine / exception fallback of the Stage A primitive | T-fb | pin |
| energy_battery.py · `_result` · mid_peak | 1 | 7877 | phase label from reason text | N (display) | pin |
| energy_billing.py · `<module>` · peak / mid_peak | 1 / 1 | 875 | `_DISPLACED_PERIODS`, consumed only at `energy.py:4634` | H | **migrate** the consumer; delete the tuple |
| energy_const.py · `<module>` · mid_peak | 3 | 24, 44, 59 | `PEC_TOU_RATES` keys | DEF | pin |
| energy_const.py · `<module>` · peak | 1 | 29 | `PEC_TOU_RATES` key | DEF | pin |
| energy_pool.py · `determine_actions` · peak | 3 | 405, 1371, 3944 | 405 pool reduce at peak (**T-change**); 1371 EVSE peak/mid (H); 3944 plug proactive-hold cleanup (H) | T-change + H | **migrate 1371, 3944**; pin 405 (count 3 → 1) |
| energy_pool.py · `determine_actions` · mid_peak | 2 | 1371, 3944 | as above | H | **migrate** (count 2 → 0) |
| energy_pool.py · `determine_excess_solar_actions` · peak | 1 | 1858 | excess-solar EVSE never in peak | T-change | pin |
| energy_pool.py · `determine_fill_priority_actions` · peak / mid_peak | 2 / 2 | 2771, 4534 / 2773, 4536 | fill-priority inert bracket (two classes, same method name) | N | pin |
| energy_tou.py · `<module>` · peak | 4 | 39, 40, 41, 47 | normalizer + `_VALID_PERIODS` | DEF | pin |
| energy_tou.py · `<module>` · mid_peak | 3 | 44, 45, 47 | normalizer + `_VALID_PERIODS` | DEF | pin |
| energy_tou.py · `peak_ahead_before_offpeak` · peak | 1 | 693 | summer bracket walk | N | pin |
| hvac_predict.py · `get_intent_attrs` · peak / mid_peak | 2 / 2 | 2063, 2073 | anchor to next / current high-rate window | H | **migrate** both |
| sensor.py · `_build_situation_attrs` · peak / mid_peak | 1 / 1 | 9430 | next-boundary text (display) | H | **migrate** |

Counts: **H** = 9 sites (`energy.py` 9744/9746, 9773; `energy_pool.py` 1371, 3944; `hvac_predict.py` 2063, 2073; `sensor.py` 9430; billing 875→`energy.py:4634`). **T-change** = 4 (2296, 9618, pool 405, pool 1858). Everything else N / T-fb / DEF, pinned. After the build the pin also carries the helper's own fallback literals (below) and drops the H occurrences, net 64 − 15 + 2 = **51 occurrences**. The builder regenerates the exact final table with the D4.1 script and commits it as the pin tuple; any delta from these numbers is stated in the build notes.

**`"off_peak"` literals:** about 29 sites, out of scope per parent §8 (byte-identical on every known tariff). **Revival trigger:** a second tariff whose lowest-rate period isn't named `off_peak`. The pin covers `peak` / `mid_peak` only, as ruled. The H helper does NOT touch the `off_peak` branches next to migrated sites (e.g. `hvac_predict.py:2069`, `energy_pool.py:1400`, `:3962`).

#### D4.3 The one helper (NEW) and the migration rule

`energy_tou.py` module-level pure function (no `self`, no I/O, no clock):

```python
def above_bottom_rate(tou, season: str | None, period: str | None) -> bool:
    """True iff `period` ranks above the season's lowest distinct import rate.
    Ranks the PASSED period (never re-derives it from the clock). Falls back to
    the legacy literal when the engine/season/period cannot be ranked."""
    try:
        rank = tou.period_rank(season, period) if (tou is not None and season) else None
    except Exception:  # noqa: BLE001
        rank = None
    if isinstance(rank, int) and not isinstance(rank, bool):
        return rank > 0
    return period in ("peak", "mid_peak")   # legacy fallback (pinned)
```

- **Why NEW (§1a updated):** the engine has `period_rank(season, period)` but nothing that ranks a GIVEN period with a literal fallback. `is_bottom_rate(now)` ranks the CLOCK period and must not be used at sites that receive `tou_period` (review H1).
- **`isinstance(rank, int)` guard:** a `MagicMock` engine (e.g. `quality/tests/test_v4_6_9_energy_recent_decisions.py:173`, `coord._tou = MagicMock()`) returns a non-int → literal fallback → byte-identical to today. The builder confirms that suite and the direct `_update_load_shedding("peak"/"off_peak")` callers (`test_energy_load_shedding_correctness.py`, `test_low_cleanup.py`, others found by grep) stay green unchanged.
- **Season per site (review M2):**
  - "now" sites with a passed `tou_period` (`_update_energy_situation`, `_update_load_shedding`, `energy_pool.py:1371`, `:3944`): `season = tou.get_season(now)` with the site's existing `now` (or `dt_util.now()` where the site has none), `period = tou_period`.
  - Future-period sites `hvac_predict.py:2063` and `sensor.py:9430`: `get_next_transition` returns `{next_period, hours_until, transition_hour}`, no datetime, and its wrap branch uses the NEXT day's season (`energy_tou.py:594-622`). Use `season = tou.get_season(now + timedelta(hours=hours_until))`; `hours_until is None` → `season=None` → literal fallback.
  - Current-period site `hvac_predict.py:2073`: `season = tou.get_season(now)`, `period = tou.get_current_period()` (as today).
  - Billing (review L2): `_apply_arbitrage_tick(self, tick, period, season, now)` (`energy.py:4595`) already has both. `energy.py:4634` becomes `if above_bottom_rate(self._tou, season, period) and served_kwh > 0:`; `_DISPLACED_PERIODS` (`energy_billing.py:875`) and its import (`energy.py:4613`) are deleted (grep shows no other reader).
- **`energy.py:9744/9746`:** collapse to one `elif above_bottom_rate(...)` → `"optimizing"` (both branches set the same value today).

#### Acceptance criteria
- **Verify (INV-P1, helper):** ONE full-year sweep of `above_bottom_rate` on the live `tou_rates.json` fixture: every hour 2026-01-01 00:00 → 2026-12-31 23:00 America/Chicago (both DST days), with `season = get_season(t)` and `period = get_current_period(t)`, asserts `above_bottom_rate(...) == (period in ("peak","mid_peak"))`. Plus the future-season form: for every hour, `season = get_season(t + hours_until)` against `next_period` from `get_next_transition(t)`, which must equal the literal on PEC. Equality on PEC cannot tell `get_season(now)` from `get_season(now + hours_until)` (every PEC season ranks `peak`/`mid_peak` above bottom), so the season choice gets its own discriminator: a synthetic two-season tariff where season B ranks `off_peak` above a `super_off_peak` bottom, with the season boundary at midnight. At 21:00 on the last day of season A, `next_period = "off_peak"` with the transition in season B; the correct form returns True and the `get_season(now)` form returns False (in A, `off_peak` is the bottom).
- **Verify (rank, not name):** a synthetic tariff whose bottom period is `super_off_peak` and whose `off_peak` is mid-rank makes `above_bottom_rate(tou, s, "off_peak")` True and `(tou, s, "super_off_peak")` False. The literal says the opposite for `off_peak`. At `hvac_predict.py:2063`: next period `off_peak` (mid-rank) → `anchor_period = "off_peak"`; next period `super_off_peak` → helper False → the unchanged `elif next_period == "off_peak"` (`:2069`) is also False → `anchor_period` stays `None`. That is expected and documented, since the `off_peak` literals are out of scope.
- **Verify (fallback):** engine None, `MagicMock` engine, unknown period, `season=None` → the literal result, for each of `"peak"`, `"mid_peak"`, `"off_peak"`, `None`.
- **Verify (routing, per site; review M3):** one behavioral test per H site driving the real method with a stub engine where `period_rank` returns 0 for the passed period (helper → False) while the period name is `"peak"`. Under the migration the site acts "bottom"; under the literal it would act "above bottom". These are the Review-C mutation anchors: reverting any one site to its literal must turn its test RED.
- **Verify (pin):** `test_period_literal_sites_pinned` walks the AST per D4.1 and asserts the `{key: count}` map equals the rung-1 dict `TOU_PERIOD_NAME_LITERAL_SITES` in `energy_const.py` (each entry annotated with its class). An added literal fails (key missing or count up); a removed one fails (stale pin). Docstring occurrences are ignored, and a self-test proves it (a docstring containing `"peak"` does not count; a Compare does).
- **Test:** `test_above_bottom_rate_full_year_sweep_matches_literal`, `test_above_bottom_rate_future_season_sweep`, `test_above_bottom_rate_ranks_not_names_synthetic_tariff`, `test_above_bottom_rate_fallbacks`, `test_<site>_routes_through_above_bottom_rate` ×9, `test_period_literal_sites_pinned`, `test_period_literal_pin_ignores_docstrings`.
- **Live (no-regression only; review L3):** D4 cannot be discriminated live on PEC (byte-identical by design). At the next 17:00 shoulder boundary after deploy, `sensor.ura_energy_coordinator_battery_strategy` (state + `tou_top_rate`), the energy-situation sensor, EVSE/pool `ura_activity_log` actions and the HVAC intent attrs `anchor_period` / `anchor_starts_in_minutes` match the same boundary the previous day (one `ssh ha sqlite3` read of `ura_activity_log` for 16:55-17:10 both days). The README write-back labels this row "no regression", not "migration proven". Proof of the migration lives in the suite.

### D5 — Close the last literal `envoy_available: True` (item 5)

**Finding.** The card's site (full-hold degraded precharge) was fixed in `95ecb743`: `energy_battery.py:6835-6838`. Its pre-onset sibling is at `:6913-6919`. The remaining defect has the same shape at `_get_attainability_hold_current_decision` (`energy_battery.py:5626-5770`). It returns a literal dict with `"envoy_available": True` (`:5756`). It is reachable on a degraded tick: `determine_mode` passes the fully-blind gate when SOC resolves via fallback (`:6700-6708`), then `_run_attain_branch` (`:6988`, `:7215`) → `rate is None` → `:6248`. The reboot-recovery caller `_maybe_run_reboot_recovery` (`:5909`) is reachable the same way.

**Effect.** On each such tick, `_track_envoy_availability` (`energy.py:3760-3768`) resets `_envoy_unavailable_count` to 0, clears `_envoy_degraded` / `_since`, and stamps `_envoy_last_available`, all while the Envoy is blind. The "Envoy Offline" NM page (fires at count == 3, `:3779`) is delayed. If HOLD-CURRENT repeats every tick, the page never fires. Whether the rate window refills from fallback SOC (bounding this to K ticks) or stays None while blind is **unverified**; the builder confirms from `_observed_net_charge_rate_per_hour` and tests both.

**Fix.** At `:5756`, replace `True` with `bool(getattr(self, "_degraded_telemetry_source", None) is None)`, the `_result` rule (`:7895-7897`). At the point HOLD-CURRENT is reached, `_degraded_telemetry_source` has been set by `:6704`, and nothing between clears it (the only clears are `:6700` entry-reset and the two restored-in-`finally` storm sites). No other change: the dict stays action-free.

**Whole-surface pin (Rev 2, review M4).** The consumer reads `decision.get("envoy_available", True)` (`energy.py:3760`, also `:7949`), so a decision dict that OMITS the key also reads "available", which is the same defect. The test AST-scans `energy_battery.py` for every `ast.Dict` literal whose constant keys include both `"mode"` and `"actions"` (the decision shape; today exactly `:5746`, `:6668`, `:7882`; the `get_status` dict at `:8334` has no `"actions"` and is out). Each must contain an `"envoy_available"` key whose value is NOT `Constant(True)`. A self-test proves the predicate fires on a fixture dict missing the key and on one with literal `True`. Changing the consumer default is out of scope: it would page on any keyless dict.

#### Acceptance criteria
- **Verify (INV-E1):** degraded tick (Envoy-blind, SOC via `cloud_fallback`, attain latched `charging`, rate window empty) → `determine_mode(...)["envoy_available"] is False`, and `actions == []` (HOLD-CURRENT unchanged). Then feed three such decisions through `_track_envoy_availability`: the count reaches 3 and the "Envoy Offline" NM alert is scheduled once. Discriminates: pre-fix, the count stays 0 and no page fires. A fix that instead suppresses HOLD-CURRENT would change `actions` and fail the first assertion.
- **Verify:** the same path with a healthy Envoy still returns `envoy_available is True` (no false outage on the normal post-reboot warm-up).
- **Test:** `test_attain_hold_current_degraded_reports_envoy_unavailable`, `test_attain_hold_current_healthy_reports_envoy_available`, `test_degraded_hold_current_counts_toward_envoy_offline_page`, `test_decision_dicts_carry_non_literal_envoy_available`. Mutation (Review C): revert `:5756` to `True` → the first and third tests go RED.
- **Live:** not organically triggerable on demand (needs blind Envoy + reboot mid-attain). Live check = no regression: `sensor.ura_energy_coordinator_battery_strategy` attr `envoy_available` true and Envoy outage count 0 after restart with a healthy Envoy. The degraded case is proven in-suite. Say so in the README table.

---

## 6. Numbers get knobs

No new behavioral number. Existing ones touched or assessed:

| Number | Knob / rung | Why this rung |
|---|---|---|
| `FORECAST_PRECIP_CONFIRM_PCT` 50 | rung 1, `energy_const.py:1123` | Safety-adjacent hold gate. Change only by reviewed, evidence-backed edit. No change this cycle. |
| `FORECAST_PRECIP_CONFIRM_MM` 1.0 | rung 1, `:1128` | Same. A split winter-family constant is the candidate D3 outcome, operator OK required. |
| `TOU_PERIOD_NAME_LITERAL_SITES` | rung 1 tuple, `energy_const.py` (new **pin list**, not a behavior knob) | Review-gated by design: adding a literal must be a reviewed decision. |
| Envoy offline page at count 3 | existing literal at `energy.py:3779` | Unchanged and out of scope. Noted: not on the knob ladder (pre-existing). |

Kill switches: none needed. D2 and D5 are removals/corrections; D4 is byte-identical with literal fallback.

---

## 7. Non-goals

- Migrating the 4 **T-change** sites (Q1 = B stands; revival trigger above).
- Migrating the ~29 `"off_peak"` literals (parent §8 exclusion; revival trigger above).
- Purging fossil keys from stored options (inert; reload hazard).
- Changing either forecast threshold, or building a forecast logger, in this cycle (D3 is a probe + recommendation; the logger is a card if the probe is skipped).
- Any change to `_is_top_rate_edge` or the Stage A blind state machine.
- Touching `routine_event_min_severity` (unrelated, live NM feature that shares a substring).
- Adding the `(degraded telemetry: <src>)` reason suffix to the HOLD-CURRENT dict (review L1). It is display-only. That dict bypasses `_result`, so no phase-from-reason parse reads it, and reason strings are pinned by existing attain tests. Recorded as a known cosmetic sibling; not built.
- Changing `_get_displaced_rate` (`energy.py:4229-4238`) to a `max(import_rate)` form: N-pinned, portability only.
- Changing the `get_next_transition` contract to return a datetime (the future-season rule works from `hours_until`).

---

## 8. Tier classification

| Item | Tier | Trigger / reason |
|---|---|---|
| D2 (threat-list tail) | **1** on its own | Removal of a display-only repair path plus dead constants; no decision path reads them (INV-L1 test proves it). |
| D3 | none (no build) | Probe = `ura-prober`, read-only. |
| D4 (Stage D) | **2-DB** (3 framing-disjoint reviews) | Standing policy for regression-prone strategy logic: it touches load-shed, EVSE, pool and HVAC-intent decision sites across 5 files. **Not Tier 3:** no value is threaded through a reserve/charge state machine, no `energy_battery.py` decision site migrates (all battery literals are N / T-change, pin only), and byte-identity is proven by an exhaustive hourly sweep rather than by reasoning. |
| D5 (envoy_available) | **1** on its own | One field on an action-free dict; consumer is the outage counter/page. `energy_battery.py` is high-caution, so a mutation drill is required anyway. |

**Cycle:** one branch, one PATCH ship. The cycle runs at **Tier 2-DB** (highest item governs). Suggested framings: **A** = local correctness (sweep arithmetic, season-at-dt, fallback paths, D5 derivation); **B** = cross-coordinator + no-op path (EVSE/pool/load-shed/HVAC-intent outputs byte-identical; options-flow load with fossil keys; `_track_envoy_availability` counter/D7 semantics); **C** = test authority via real per-site mutation (`ura-reviewer-mutation`): revert each of the 9 H sites to its literal (or to `is_bottom_rate(now)`, the H1 failure shape), make the helper ignore the `isinstance` guard, swap a future-period site to `get_season(now)`, revert the D5 line, and drop the `envoy_available` key from the HOLD-CURRENT dict. Each must turn a named test RED, and the pin must fail on an injected literal and on a removed one. Plan review: one adversarial plan review before build (Tier 2 rule), which re-runs the §D4 grep independently.

**Builder:** `ura-builder`, in a worktree under `.claude/worktrees/`. Pre-deploy snapshot: strategy-sensor attrs + one day of `ura_activity_log` EVSE/pool rows for the 16:55-17:10 window. Deploy risk rank (operator travel rule): **LOW**. D4 is byte-identical, D2 is dead code, D5 corrects a counter input.

---

## 9. Card disposition proposals (apply at cycle close)

- **EC-BLIND-DEESCALATE-TOP-RATE-1:** the named defect is done (Stage A `15b7ab39`). The widened scope = this D4. Close on D4 ship; T-change sites stay on the card's Q1 note with the revival trigger.
- **EC-STORM-FULLHOLD-DEGRADED-ENVOY-AVAILABLE-1:** the named site is done (`95ecb743`). The residual sibling = D5. Close on D5 ship.
- **EC-INCLEMENT-HARDENING-1:** legacy-threat residual closes on D2 ship. The threshold item becomes the D3 probe (`ura-prober`) with the go/no-go above. Its parked 2027-03-31 trigger is replaced, because no history accrues.

---

## 10. Rev 2 changelog (plan review 1 disposition)

| ID | Finding | Disposition |
|---|---|---|
| H1 | the `is_bottom_rate(now)` rule ignores the passed `tou_period` | FIXED: one helper `above_bottom_rate(tou, season, period)` ranks the PASSED period, with `isinstance(rank, int)` guard and literal fallback (§D4.3). The MagicMock mock at `test_v4_6_9_energy_recent_decisions.py:173` falls back to the literal → unchanged. |
| H2 | pin predicate vs table mismatch | FIXED: one AST rule (§D4.1: every non-docstring `ast.Constant` `"peak"`/`"mid_peak"`, keyed `(file, func, literal)` with count, DEF entries included rather than excluded); table regenerated from it (§D4.2: 64 / 37); pin test uses the same rule. |
| M1 | D2 missed user manual + test import | FIXED: `docs/user-manual/ENERGY_COORDINATOR.md:174/306-307` and `test_inclement_alert_classifier.py:79/216` added to the D2 table; `README_v5.5.0.md:10` left as history. |
| M2 | future-period season under-specified | FIXED: `get_season(now + timedelta(hours=hours_until))` for `hvac_predict.py:2063` and `sensor.py:9430`; `now` for `:2073`; synthetic `super_off_peak` expectation at `:2069` stated. |
| M3 | 9 per-site sweeps unbuildable | FIXED: one helper swept once (plus future-season form and synthetic tariff), 9 routing tests as Review-C mutation anchors; §1a now lists the helper and the pin dict as NEW. |
| M4 | D5 pin too narrow | FIXED: every `mode`+`actions` dict literal must carry `envoy_available`, not literal True; self-test included. |
| L1 | HOLD-CURRENT reason suffix | Non-goal (§7), reason stated. |
| L2 | billing "migrate or pin" option | FIXED: migrate the consumer `energy.py:4634` with its own `season`/`period`; delete `_DISPLACED_PERIODS`. |
| L3 | D4 Live can't discriminate | Labeled "no regression only"; proof is in-suite. |
| L4 | HVAC doc read not cited | FIXED: §1d cites the full read and the display-only finding; no §10 claim affected. |
