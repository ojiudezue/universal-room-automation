# PLANNING — EC inclement leftovers (retired threat list, forecast thresholds, period-name sites, blind envoy_available)

**Status:** Plan, 2026-11-08. Not built. Operator approved building items 2, 4, 5. Item 3 is a recommendation only.
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
| Anything NEW | **None.** No CONF key, entity, signal, helper or table is added. | |

### 1b. Greps run (develop @ 2377ad92)

- `git grep -n -iE "power_threat_events|threat_min_severity|warn_min|threat_events|min_severity"` repo-wide (code, tests, strings, translations, skills). Results in §D2 table. `routine_event_min_severity` hits are a different, live NM feature; out of scope.
- `git grep -n "_check_legacy_threat_list|inclement_legacy_threat_list_retired"`: `energy.py:1324` (caller in setup), `:9512-9543` (def), `strings.json:2359`, `translations/en.json:2359`, tests `test_ec_stage_b_classification.py:539-556`, `test_ec_outage_ledger.py:1646-1669`, `test_ec_stage_e_selection.py:672`.
- `git grep -nE '"(peak|mid_peak)"'` with comparison operators, all `*.py`: 39 hits (§D4 table). `"off_peak"` literals counted separately (§D4 note).
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
- Not HVAC or presence work, so the two STATE_OF_PLAY docs do not apply. `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` has no threat-list text (grep = 0).

### 1e. Code surveyed

`energy_battery.py` (`determine_mode` 6375-6990, `_get_attainability_hold_current_decision` 5626-5770, `_run_attain_branch` 5961-6260, `_result` 7820-7900, `_is_top_rate_edge` 7373-7405); `energy.py` (`_track_envoy_availability` 3756-3795, `_check_legacy_threat_list` 9512-9543, `_update_hvac_constraint` / `_update_energy_situation` / `_update_load_shedding` 9590-9830); `energy_tou.py` 487-700; `inclement.py` 1230-1830; `energy_pool.py` 400-410, 1365-1405, 1855-1865, 2765-2775, 3940-3965, 4530-4540; `hvac_predict.py` 2055-2080; `sensor.py` 9415-9435; `energy_billing.py:875`.

---

## 2. Falsifiable invariants

- **INV-L1 (item 2, decision-neutral removal).** For any CM options dict, including one that still carries `inclement_power_threat_events` and/or `inclement_warn_min_severity` with any value, every `InclementDecision` and every `determine_mode` result is identical before and after the removal. Options-flow init and save with those keys present raise nothing.
  *Falsifier:* any reader of either key left behind, or a schema validator that rejects unknown stored keys.
- **INV-P1 (item 4, byte-identical migration).** For every hour of a full tz-aware year (DST days included) on the live PEC tariff, each migrated H site returns the same value as its literal predecessor. After the build, no new comparison of a TOU period variable against `"peak"` / `"mid_peak"` can land outside the pinned allowlist without a test failing.
  *Falsifier:* one hour where `not is_bottom_rate(now)` and `tou_period in ("peak","mid_peak")` disagree (for example a season-boundary hour where `get_season` and `get_current_period` read different months); an unpinned literal that passes the lint.
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
- **Consumers:** the 39 sites in §D4.

### `decision["envoy_available"]` (item 5)
- **Producer:** `_result` derives it (`:7895`). Three literal-dict returns bypass `_result` (`:5746` True, `:6668` False) or post-override it (`:6838`, `:6919`).
- **Consumers:** `_track_envoy_availability` (`energy.py:3760`), a **trust decision**: the outage counter, the D7 degraded flag and the "Envoy Offline" NM page at count 3. `energy.py:7949` is display.

---

## 4. Emission / decision-site enumeration

- Item 2: §D2 table (every repo reference).
- Item 4: §D4 table (39 `peak`/`mid_peak` sites + `energy_billing.py:875`).
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
- **Test:** `test_legacy_plumbing_removed` (tightened), `test_legacy_inclement_keys_decision_neutral` (new), `test_options_flow_tolerates_legacy_inclement_keys` (new), existing `test_legacy_threat_list_is_ignored_red_flag_stays_gated_out` and `test_severity_never_demotes_table_tier` (shim kwargs dropped).
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
- (b) "migrate every means-top-rate site" would migrate the four **T-change** sites. The operator ruled those B (keep named) on 2026-10-16 (parent §14 Q1). Each one changes shoulder/winter behavior (HVAC coast, load-shed, pool speed, excess-solar EVSE at 17-21 for 8 months a year), so each is a policy change, not a fix. Marginal benefit is small: in shoulder/winter the `mid_peak` branch of `determine_mode` (`energy_battery.py:6967+`) already discharges the battery through the top rate, so those loads run on battery unless SOC is exhausted. The spread at stake is $0.086 − $0.0435 per kWh. **Recommend keeping Q1 = B.** Revival trigger per site: observed grid import during shoulder/winter `mid_peak` above 1 kWh/day on 5+ days in a month (query `energy_*` history), which means the battery is not covering the top rate.
- **This cycle = parent Stage D as ruled (Q8 "do it, don't park"):** migrate the H sites to the rate primitive, and pin every remaining literal with a classification so no new text match lands silently.

**Honest marginal-benefit note.** On the live tariff, every H migration is byte-identical: off_peak is the bottom rate in every season, so `not off_peak` ≡ `in ("peak","mid_peak")` ≡ `not is_bottom_rate`. D4 buys portability (a second tariff, e.g. a super-off-peak) and the pin. It fixes no live decision. The operator already chose to do it (Q8); this plan keeps it small.

**Site table (re-located; 39 comparison sites + 1 tuple constant):**

Classes as parent §8: **T** = top rate (done), **T-change** = top rate but migration changes shoulder/winter behavior (kept named, Q1), **H** = "above the bottom rate" (migrate, byte-identical), **N** = the named period on purpose (pin).

| # | Site (current) | Use | Class | Verdict |
|---|---|---|---|---|
| 1 | `energy_battery.py:2296` | skip untrusted-SOC page during peak | T-change | keep, pin (benign in shoulder: `_attain_target_boundary` returns None → no page) |
| 2–3 | `:5287`, `:5294` | mid_peak walk to next `peak` (summer bracket) | N | pin |
| 4–5 | `:5352`, `:5353` | rate-dict keys in `_midpeak_rate_lt_peak` | N | pin |
| 6–9 | `:5413`, `:5848`, `:6009`, `:6091` | attain mid_peak gated by `_midpeak_rate_lt_peak` | N | pin |
| 10–11 | `:6254`, `:6354` | stage label | N | pin |
| 12–13 | `:6946`, `:6967` | peak / mid_peak strategy branches (season-aware by design) | N | pin |
| 14–15 | `:7386`, `:7395` | `_is_top_rate_edge` no-engine fallback | T (fallback) | pin |
| 16 | `:7877` | `_result` phase label from reason text | N (display) | pin |
| 17 | `energy.py:4234` | season-data shape check | N | pin |
| 18 | `:7153` | SOC-at-peak degradation baseline | N | pin |
| 19 | `:9603` | summer post-peak mid_peak | N | pin |
| 20 | `:9618` | HVAC shed at peak + low SOC + active shedding | T-change | keep, pin |
| 21–22 | `:9626`, `:9631` | HVAC coast at peak; mid_peak poor-solar | N | pin |
| 23–24 | `:9744`, `:9746` | energy situation (display) | H | **migrate** |
| 25 | `:9773` | load shed only above bottom rate | H | **migrate** |
| 26 | `:9823` | peak import learning history | N | pin |
| 27 | `energy_pool.py:405` | pool speed reduce at peak | T-change | keep, pin |
| 28 | `:1371` | EVSE peak/mid handling | H | **migrate** |
| 29 | `:1858` | excess-solar EVSE never during peak | T-change | keep, pin |
| 30–31 | `:2771`, `:2773` | fill-priority inert (bracket) | N | pin |
| 32 | `:3944` | proactive-hold cleanup | H | **migrate** |
| 33–34 | `:4534`, `:4536` | fill-priority inert (bracket) | N | pin |
| 35 | `energy_tou.py:693` | `peak_ahead_before_offpeak` walk | N | pin |
| 36–37 | `hvac_predict.py:2063`, `:2073` | anchor to next / current high-rate window | H | **migrate** (`period_rank(get_season(dt), p) not in (None, 0)`, dt = transition time / now) |
| 38 | `sensor.py:9430` | next-boundary text (display) | H | **migrate** (same as 36) |
| 39 | `energy_billing.py:875` `_DISPLACED_PERIODS` | displaced periods for peak-avoidance | H | **migrate** to a rank check at the interval's own time, or pin with a comment if the call site has no timestamp (builder states which, with file:line) |

Totals: H 9 (migrate), T-change 4 (keep, Q1), N/T-fallback 26 (pin). The parent's 35 grew to 39 + 1 because Stage A added the 2 fallback literals and the line drift exposed `energy.py:4234` and `energy_battery.py:5352-5353` (dict-key reads the parent counted as part of their helper).

**`"off_peak"` literals:** about 29 sites. They stay out of scope per parent §8 (byte-identical on every known tariff). **Revival trigger:** a second tariff whose lowest-rate period isn't named `off_peak`. The pin covers `peak` / `mid_peak` only, as ruled.

**Migration rule (each H site):** use `is_bottom_rate(now)` for "now" sites and `period_rank(season_at(dt), period)` for future-period sites. Each keeps the **literal as the no-engine / exception fallback** (the `_is_bottom_rate` precedent, `energy_battery.py:3405-3414`). `None` rank (unknown period) → fallback literal, never "not bottom" by default.

#### Acceptance criteria
- **Verify (INV-P1):** for each of the 9 H sites, a full-year hourly sweep (2026-01-01..12-31 America/Chicago, both DST days, plus the 00:00 hour of every season-boundary month) on the live `tou_rates.json` fixture asserts migrated == literal. Discriminates: a wrong season source (e.g. `get_season()` without `dt` at a future boundary) diverges at the 05-31→06-01 and 09-30→10-01 21:00 transitions. A correct migration is equal everywhere.
- **Verify:** a synthetic two-season tariff whose bottom period is named `super_off_peak` and whose `off_peak` is mid-rank makes the migrated H sites return "above bottom" during `off_peak`. The literal would say otherwise. This proves the migration does something.
- **Verify (pin):** `test_period_literal_sites_pinned`: AST scan of `custom_components/` for `Compare` nodes (and `in`-tuples / tuple constants) that contain `"peak"` / `"mid_peak"`, keyed by (file, enclosing function, literal). The set must equal the rung-1 tuple `TOU_PERIOD_NAME_LITERAL_SITES` in `energy_const.py`, and each entry carries its class (N / T-change / T-fallback). Adding an unlisted literal fails; removing a listed one fails (stale pin).
- **Test:** `test_period_literal_sites_pinned`, `test_h_site_hour_sweep_identical[<site>]` ×9, `test_h_sites_follow_rank_not_name_on_synthetic_tariff`, `test_h_site_fallback_without_tou_engine`.
- **Live:** at the next 17:00 shoulder boundary after deploy, `sensor.ura_energy_coordinator_battery_strategy` (state + `tou_top_rate`), the energy-situation sensor, EVSE/pool `ura_activity_log` actions and the HVAC intent attrs `anchor_period` / `anchor_starts_in_minutes` match the same boundary the previous day (one `ssh ha sqlite3` read of `ura_activity_log` for 16:55-17:10 both days).

### D5 — Close the last literal `envoy_available: True` (item 5)

**Finding.** The card's site (full-hold degraded precharge) was fixed in `95ecb743`: `energy_battery.py:6835-6838`. Its pre-onset sibling is at `:6913-6919`. The remaining defect has the same shape at `_get_attainability_hold_current_decision` (`energy_battery.py:5626-5770`). It returns a literal dict with `"envoy_available": True` (`:5756`). It is reachable on a degraded tick: `determine_mode` passes the fully-blind gate when SOC resolves via fallback (`:6700-6708`), then `_run_attain_branch` (`:6988`, `:7215`) → `rate is None` → `:6248`. The reboot-recovery caller `_maybe_run_reboot_recovery` (`:5909`) is reachable the same way.

**Effect.** On each such tick, `_track_envoy_availability` (`energy.py:3760-3768`) resets `_envoy_unavailable_count` to 0, clears `_envoy_degraded` / `_since`, and stamps `_envoy_last_available`, all while the Envoy is blind. The "Envoy Offline" NM page (fires at count == 3, `:3779`) is delayed. If HOLD-CURRENT repeats every tick, the page never fires. Whether the rate window refills from fallback SOC (bounding this to K ticks) or stays None while blind is **unverified**; the builder confirms from `_observed_net_charge_rate_per_hour` and tests both.

**Fix.** At `:5756`, replace `True` with `bool(getattr(self, "_degraded_telemetry_source", None) is None)`, the `_result` rule (`:7895-7897`). At the point HOLD-CURRENT is reached, `_degraded_telemetry_source` has been set by `:6704`, and nothing between clears it (the only clears are `:6700` entry-reset and the two restored-in-`finally` storm sites). No other change: the dict stays action-free.

**Whole-surface pin.** A test that AST-scans `energy_battery.py` for dict literals with key `"envoy_available"` whose value is the constant `True` must find none. This closes the class: a future literal return can't reintroduce it.

#### Acceptance criteria
- **Verify (INV-E1):** degraded tick (Envoy-blind, SOC via `cloud_fallback`, attain latched `charging`, rate window empty) → `determine_mode(...)["envoy_available"] is False`, and `actions == []` (HOLD-CURRENT unchanged). Then feed three such decisions through `_track_envoy_availability`: the count reaches 3 and the "Envoy Offline" NM alert is scheduled once. Discriminates: pre-fix, the count stays 0 and no page fires. A fix that instead suppresses HOLD-CURRENT would change `actions` and fail the first assertion.
- **Verify:** the same path with a healthy Envoy still returns `envoy_available is True` (no false outage on the normal post-reboot warm-up).
- **Test:** `test_attain_hold_current_degraded_reports_envoy_unavailable`, `test_attain_hold_current_healthy_reports_envoy_available`, `test_degraded_hold_current_counts_toward_envoy_offline_page`, `test_no_literal_true_envoy_available_in_battery`. Mutation (Review C): revert `:5756` to `True` → the first and third tests go RED.
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

---

## 8. Tier classification

| Item | Tier | Trigger / reason |
|---|---|---|
| D2 (threat-list tail) | **1** on its own | Removal of a display-only repair path plus dead constants; no decision path reads them (INV-L1 test proves it). |
| D3 | none (no build) | Probe = `ura-prober`, read-only. |
| D4 (Stage D) | **2-DB** (3 framing-disjoint reviews) | Standing policy for regression-prone strategy logic: it touches load-shed, EVSE, pool and HVAC-intent decision sites across 5 files. **Not Tier 3:** no value is threaded through a reserve/charge state machine, no `energy_battery.py` decision site migrates (all battery literals are N / T-change, pin only), and byte-identity is proven by an exhaustive hourly sweep rather than by reasoning. |
| D5 (envoy_available) | **1** on its own | One field on an action-free dict; consumer is the outage counter/page. `energy_battery.py` is high-caution, so a mutation drill is required anyway. |

**Cycle:** one branch, one PATCH ship. The cycle runs at **Tier 2-DB** (highest item governs). Suggested framings: **A** = local correctness (sweep arithmetic, season-at-dt, fallback paths, D5 derivation); **B** = cross-coordinator + no-op path (EVSE/pool/load-shed/HVAC-intent outputs byte-identical; options-flow load with fossil keys; `_track_envoy_availability` counter/D7 semantics); **C** = test authority via real per-site mutation (`ura-reviewer-mutation`): revert each of the 9 H sites, the D5 line, and the repair-check removal (re-add a reader). Each must turn a named test RED, and the pin must fail on an injected literal. Plan review: one adversarial plan review before build (Tier 2 rule), which re-runs the §D4 grep independently.

**Builder:** `ura-builder`, in a worktree under `.claude/worktrees/`. Pre-deploy snapshot: strategy-sensor attrs + one day of `ura_activity_log` EVSE/pool rows for the 16:55-17:10 window. Deploy risk rank (operator travel rule): **LOW**. D4 is byte-identical, D2 is dead code, D5 corrects a counter input.

---

## 9. Card disposition proposals (apply at cycle close)

- **EC-BLIND-DEESCALATE-TOP-RATE-1:** the named defect is done (Stage A `15b7ab39`). The widened scope = this D4. Close on D4 ship; T-change sites stay on the card's Q1 note with the revival trigger.
- **EC-STORM-FULLHOLD-DEGRADED-ENVOY-AVAILABLE-1:** the named site is done (`95ecb743`). The residual sibling = D5. Close on D5 ship.
- **EC-INCLEMENT-HARDENING-1:** legacy-threat residual closes on D2 ship. The threshold item becomes the D3 probe (`ura-prober`) with the go/no-go above. Its parked 2027-03-31 trigger is replaced, because no history accrues.
