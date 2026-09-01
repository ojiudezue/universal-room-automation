# PLANNING — Shared Power-Read Staleness Helper (ENVOY-PRODUCTION-STALE-1)

**Card:** `ENVOY-PRODUCTION-STALE-1` (consolidated per operator 2026-08-31).
**Rev:** 2 (2026-09-01) — adversarial plan-review fixes applied. Fix summary at the bottom.
**Tier:** **2-DB** (regression-prone, cross-coordinator ripple: energy_battery → energy_pool → EVSE + DP + NM + billing; shared primitive; folds together five hand-rolled gates whose thresholds MUST be preserved byte-for-byte on the fresh path).
**Mode:** planning only (read-only). Awaits second plan-review pass before build dispatch.

**Falsifiable invariant (state up front — Rev 2, `last_reported`):**
> For every trust-decision-consuming power/SOC read in the Energy family, a numeric HA state whose **`last_reported`** stamp (falling back to `last_updated` when the platform did not populate `last_reported`) is older than the site's configured `MAX_AGE_S` MUST be treated as **absent** (helper returns `None`), routing the consumer to its already-built fallback (LKG envelope, cloud fallback, `STALE_POWER` set, `blind_hold_active`). On the fresh path (age ≤ MAX_AGE_S, valid unit, in-range) the returned value MUST be **byte-identical** to today's read.
>
> Why `last_reported`, not `last_updated`: HA advances `last_reported` on every re-publish (even when the value did not change), but only advances `last_updated` on a value change. A healthy sensor pinned at 0 W (solar at night) or a constant-valued sensor would therefore be judged stale under `last_updated`. This is the same reason the existing grid solar-follow gate at `energy_pool.py:4406-4413` (INV-SF-10) uses `last_reported`. Any migrated site is INDIVIDUALLY specified below to preserve its current stamp choice — see D5.

---

## Institutional context verified

### Design/rules read
- `CLAUDE.md` — Tier 2-DB triggers; Producer/Consumer rule; "Numbers get knobs" ladder; "Coincidental equality masks a concept split"; "Extend existing, never rebuild"; "Do the robust fix, not band-aid+card".
- `docs/QUALITY_CONTEXT.md` — Bug class **#7 stale data source** (frozen-valid numeric reads defeat consumers that only check unknown/unavailable) — this cycle is a systematic sweep of that class across the Energy read surface.
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.5a — reserve verifiable backout knob (MAX_AGE_S=0 fire-axe); establishes the *"missing = go to fallback, never trust a stale value"* doctrine this cycle extends to the READ layer.

### Prior planning / memory pulled
- Memo `reference_ec_reserve_verifiable_backout_knob` — fire-axe precedent.
- Memo `feedback_coincidental_equality_masks_concept_split` — informs why the hand-rolled gates converged on 180s / 300s / 600s **by domain** and MUST NOT be silently unified into one number.
- Memo `feedback_do_robust_fix_not_bandaid_and_card` — supports operator's consolidate ruling.
- Memo `feedback_read_consumers_before_asserting_function` — direct authority for the Consumer check on every migrated site (the Rev 1 doc failed this by mis-citing `energy_pool.py:1483`).
- v5.17.5 A1 review record — introduced `DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S=600` (`energy_battery.py:882-910`); the extra-comment there IS the template for this cycle's per-site guard.
- v4.5.0 unit-consistency sweep — established `_read_power_w` as the single power reader; this cycle mirrors that pattern at the staleness layer.

### Producer AND Consumer surveyed (re-verified by grep 2026-09-01)

**PRODUCER table — sites this cycle gates:**

| # | Site (producer) | file:line | Current reject | Fallback that engages when helper returns `None` |
|---|---|---|---|---|
| 1 | `_read_power_w("solar_production")` via `solar_production_w` | `energy_battery.py:1572-1596`, called at `:1614` | unknown/unavailable only | `solar_production_w_envelope()` at `:2287` — but its **own entry check** at `:2330` also calls `_read_power_w(...) is not None`; both call sites MUST migrate together (see D3). |
| 2 | `_read_power_w("net_power")` via `net_power_w` | `energy_battery.py:1628-1636` | unknown/unavailable only | see Consumer table — most consumers use `or 0` fail-open today; D4 changes call-site handling to fail-safe (see D4). |
| 3 | `battery_power_w` inline | `energy_battery.py:1546-1570` | unknown/unavailable only | none in cycle; drain-protection consumer already tolerates None. |
| 4 | PRIMARY `battery_soc` via `_get_state_float(self._get_entity("battery_soc"))` | 4 CALL SITES — see D2 | unknown/unavailable only | three-tier resolver (LKG → cloud) at `:838-921` **for site A only**; sites B/D need migration to reach the same guarantee; site C is a health predicate (classify explicitly). |

**LKG-stamp arithmetic note (Rev 2, correcting the Rev-1 #63 NOTE):** the LKG is stamped at READ time — `energy_battery.py:830-832` snapshots `_soc_lkg_at = dt_util.utcnow()` **on every fresh read**, not against the source sensor's `last_reported`. Therefore the aggregate blindness under a frozen primary is **sequential**: up to `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S` (helper does not yet return None) PLUS up to `DEFAULT_SOC_LKG_MAX_AGE_S` (LKG stamp still fresh from the last real read) before the cloud tier is reached. With both at 300 s the worst case is ~600 s of stale-trust before cloud engages, not 300 s. This is intentional and DOCUMENTED — do not "fix" by reducing either constant blindly; either lower the aggregate (both smaller) or accept the sequential horizon.

**CONSUMER table — every downstream that reads a migrated producer (Rev 2, corrected):**

| Producer | Consumer file:line | Trust or Display | On `None` today |
|---|---|---|---|
| `solar_production_w` | `energy.py:3126` — persisted analytics row | trust (writes to DB) | `solar_prod_kw = None` propagated correctly (already None-safe) |
| `solar_production_w` | `energy.py:3229` | trust (strategy math) | current behavior preserved |
| `solar_production_w` | `energy.py:3404` | trust (strategy math) | current behavior preserved |
| `solar_production_w` | `energy.py:3557` | trust (strategy math) | current behavior preserved |
| `solar_production_w` | `energy_battery.py:2330` (envelope entry check `live is None`) | gate | REQUIRED migration — see D3 |
| `net_power_w` | `energy.py:3129-3130` — persisted analytics `grid_import_kw`, `solar_export_kw` | trust (writes to DB) | `max(net_power_w or 0, 0)/1000` writes **false zero** on None — Rev-2 D6 covers this |
| `net_power_w` | `energy.py:6071` — EVSE grid-import cap | trust (pause/resume) | `(net_power_w or 0)/1000` treats None as 0 kW → **fail-open** (resumes paused EVSEs) — Rev-2 D4 covers |
| `net_power_w` (indirect, via grid entities) | `energy_billing.py:144-175` `_get_net_power` → `accumulate()` `_cost_today` / `_import_kwh_today` | trust (dollars) | reads `sensor.<grid_import>/<grid_export>` directly with unknown/unavailable-only reject; frozen-valid poisons the bill — Rev-2 D4 sub-site |
| PRIMARY `battery_soc` (site A `:828`) | resolver → every battery strategy consumer | trust | resolver already exists (LKG → cloud); helper returning None triggers correct fallback |
| PRIMARY `battery_soc` (site B `:2242`) | `solar_production_w_envelope` entry check | gate | ungated frozen primary suppresses the envelope — **REQUIRED migration D2** |
| PRIMARY `battery_soc` (site C `:2455`) | local Envoy-health predicate `envoy_available` | trust (blind-hold DP, NM, EVSE guard) | frozen primary returns True (Envoy looks healthy when it isn't) — **classify explicitly D2** |
| PRIMARY `battery_soc` (site D `:6091`) | `_evaluate_soc_resolution` diagnostics + Live-criterion source | display + observability | frozen primary yields the tier the Live criterion is meant to detect; migrate D2 |

**5th AC-kWh gate (Rev-2 addition):** `hvac_override.py:3962` gates the AC-kWh read on `age_s > AC_KWH_SENSOR_STALENESS_S` using `last_updated`, and fails **OPEN** on `TypeError` (returns `age_s = 0.0`, admitting the read) — opposite of the CF-8 fail-closed contract used elsewhere. **Non-goal in this cycle** (behavioral change to a different coordinator's read path); **carded separately** (`HVAC-OVERRIDE-KWH-STALE-FAIL-OPEN-1`).

**Consumer-check finding (design-binding):** `sensor.ura_energy_envoy_status.stale` is DISPLAY-ONLY. `envoy_available` IS trusted (`energy.py:3753` blind_hold DP; `energy_pool.py:571` EVSE guard; `:2934` NM alert) but is computed from primary SOC + storage_mode. ∴ The fix MUST gate the READ. Adding another unconsumed staleness sensor would repeat the display-only failure mode.

### Grep prior-art results for proposed additions
- `_state_age_s` / `state_age_s` / `read_fresh` / `_read_state_fresh` — **NEW** (grepped `custom_components/`, no equivalent public helper; five site-local re-implementations at `energy_battery.py:891`, `energy_pool.py:4406`, `:4695`, `sensor.py:12494`, `hvac_override.py:3956` — the 5th is scope-carded, not folded).
- `DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S`, `DEFAULT_NET_POWER_MAX_AGE_S`, `DEFAULT_BATTERY_POWER_MAX_AGE_S`, `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S` — **NEW**. Rung 1 (module constants — safety knobs, review-gated) per "Numbers get knobs".

### Code locations surveyed end-to-end
- `energy_battery.py:770-925` (SOC resolver + A1 gate); `:1530-1636` (power readers + LKG stamp); `:2225-2320` (envelope entry checks — **both** primary-SOC and live-solar); `:2440-2461` (`envoy_available` predicate); `:6080-6100` (soc_resolution diagnostics tick).
- `energy.py:3115-3140` (persisted analytics row); `:3225-3560` (solar strategy consumers); `:6055-6090` (EVSE grid-cap consumer).
- `energy_billing.py:135-190` (`_get_net_power` + accumulate).
- `energy_pool.py:565-580`, `:4395-4417` (grid-follow), `:4685-4710` (per-bay solar power).
- `energy_const.py:300-340`, `:960-985`.
- `sensor.py:12480-12515` — AC-kWh display gate.
- `hvac_override.py:3950-3975` — 5th AC-kWh gate (scope-carded).

---

## Deliverables

### D1 — Add the shared helper (single source of truth)

Add three module-private helpers on `EnergyBatteryCoordinator` (co-located with `_get_state_float` at `energy_battery.py:785`, same coordinator that owns every downstream fallback — no new module, no cross-coordinator import surface):

- `_state_age_s(state, *, stamp: str = "last_reported") -> float | None` — Rev 2: **per-site stamp arg**. Reads `getattr(state, stamp, None)`; if that is `None`, falls back to `getattr(state, "last_updated", None)` (so a platform that never populated `last_reported` degrades to today's behavior rather than always-stale). Returns `(now_utc − chosen_stamp).total_seconds()`, or `None` if state is missing, both stamps are absent, or the chosen stamp is naive (fail-closed per CF-8 precedent at `energy_pool.py:4402-4409`).
- `_read_fresh_power_w(entity_key, max_age_s, *, stamp="last_reported") -> float | None` — supersedes `_read_power_w`: same unit-normalization, plus rejects when `_state_age_s(state, stamp=stamp)` is `None` OR `> max_age_s`. Preserves the exact fresh-path byte-identity.
- `_read_fresh_float(entity_id, max_age_s, *, stamp="last_reported") -> float | None` — same for the non-unit-scaled SOC read.

**Stamp choice per NEW gate** (Rev 2 — see invariant rationale):
- Solar production → `last_reported` (constant-0 at night is healthy; `last_updated` would falsely flag it stale).
- Net power → `last_reported` (net can legitimately sit at a constant during import/export balance).
- Battery power → `last_reported`.
- Primary SOC → `last_reported` (a battery pinned at 100 % after a full charge is healthy; `last_updated` would falsely flag it stale).

**Producer check:** the helper's only inputs are `hass.states.get(...)` and a constant. **Consumer check:** in D1 the helpers have zero consumers (added but not yet wired) — a builder mutation of the fresh-path branch MUST leave the suite green (D1 is neutral); a mutation of the stale-branch MUST fail a D2/D3/D4/D5 test.

#### Acceptance
- **Verify:** helper module imports; no site calls it yet.
- **Test:** `test_state_age_s_missing_naive_fresh_stale` (four cases: None state, naive stamp, fresh, stale).
- **Test:** `test_state_age_s_prefers_last_reported_falls_to_last_updated` — state with `last_reported = now-5s` and `last_updated = now-500s` returns ~5s; state with `last_reported=None` and `last_updated = now-5s` returns ~5s.
- **Test (Rev-2 must):** `test_read_fresh_constant_valued_sensor_is_fresh` — a sensor whose value has not changed for 3600s but whose `last_reported` = now − 5s MUST be treated FRESH (this is the invariant's core discriminator against `last_updated`).
- **Test:** `test_read_fresh_power_w_unit_scaling_preserved` (fresh path byte-identical to `_read_power_w`).
- **Live:** N/A (no wire-in yet).

### D2 — Migrate PRIMARY `battery_soc` — ALL FOUR SITES

**Enumeration (Rev 2, corrected):** `_get_state_float(self._get_entity("battery_soc"))` appears at four sites. All four are addressed here.

**D2-A — `energy_battery.py:828` (resolver primary read).** Migrate to `self._read_fresh_float(self._get_entity("battery_soc"), DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S, stamp="last_reported")`. When helper returns None, the existing three-tier resolver at `:838-921` runs unchanged.

**D2-B — `energy_battery.py:2242` (SOC-envelope twin entry check).** Migrate to `self._read_fresh_float(...)` with the SAME const. This is the sibling of the D3 solar-envelope fix: ungated primary here means a frozen primary suppresses the SOC envelope for the blind-window EVSE guard, defeating the fallback we shipped. Same no-fallback risk as D3.

**D2-C — `energy_battery.py:2455` (`envoy_available` local health predicate).** **Classify:** intentionally KEEP raw `_get_state_float`. Rationale: this predicate answers "is the LOCAL Envoy responding at all?" and MUST NOT be gated on staleness — a frozen-but-present read still proves the local integration is loaded (vs `unavailable` when the Envoy is off the network). A staleness gate here would flip `envoy_available` False and fire the NM alert / blind-hold on every legitimate value-pinned window (night-time production, idle net). **Justification anchored** by the docstring at `:2444-2453` ("LOCAL check that never inherits the cloud-first redirection"). No migration; add a `# NOTE: intentional raw read — see D2-C in PLANNING_shared_power_read_staleness.md` comment.

**D2-D — `energy_battery.py:6091` (soc_resolution diagnostics tick).** Migrate to `self._read_fresh_float(...)` with the SAME const. Rationale: this is the source snapshot the divergence/resolution evaluators (and the D2 Live acceptance criterion) inspect; if it silently reads a frozen primary, the Live check "zero envoy reads with age > 300s" becomes tautologically true (there's no source-age visibility). Migrating this site also makes the diagnostic surface consistent with the trust surface.

**Const:** `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S: Final = 300` in `energy_const.py` next to `DEFAULT_SOC_LKG_MAX_AGE_S:318`. Rev-2 doc-comment: the aggregate stale-trust horizon is **sequential** (PRIMARY_MAX + LKG_MAX) because the LKG is re-stamped at READ time (`:830-832`), so the two constants are NOT a shared boundary — they compose. Two independent horizons kept as two independent knobs.

**Rev-2 D2 surface addition — `primary_age_s` attribute:** add `primary_age_s` (from `_state_age_s(state, stamp="last_reported")`) to the existing `soc_resolution` sensor's `extra_state_attributes` (the sensor is already the D2 Live oracle). This is the DISCRIMINATING observable for the Live criterion — the criterion cannot be evaluated without it.

#### Acceptance (D2)
- **Verify (A):** on stale primary + fresh LKG, `battery_soc` returns the LKG value; `_soc_source_last == "lkg"`.
- **Verify (A):** on stale primary + no LKG + fresh cloud fallback, `battery_soc` returns cloud; `_soc_source_last == "cloud_fallback"`.
- **Verify (B):** on frozen-primary + Envoy blind, `soc_upper_envelope()` returns a non-None envelope tier (today it returns None because :2242 short-circuits).
- **Verify (C):** `envoy_available` returns True on a value-pinned primary (regression guard).
- **Verify (D):** the `soc_resolution` sensor exposes `primary_age_s`; when the source sensor's `last_reported` age > 300s, `primary_age_s > 300` AND `source_last in {"lkg","cloud_fallback"}`.
- **Discriminating:** inject a numeric primary with `last_reported = now − 400s`, sibling entity with `last_reported = now − 5s`. Site-A read returns None; `_soc_source_last` MUST be `lkg` (fresh LKG) or `cloud_fallback` (expired LKG) — NOT `envoy`.
- **Test:** `test_primary_soc_stale_falls_to_lkg`, `test_primary_soc_stale_no_lkg_falls_to_cloud`, `test_primary_soc_fresh_byte_identical`, `test_soc_envelope_engages_when_primary_frozen`, `test_envoy_available_true_on_pinned_primary` (C regression), `test_soc_resolution_exposes_primary_age_s`.
- **Neuter→RED (A):** deleting the `max_age_s` arg on `:828` MUST fail `test_primary_soc_stale_falls_to_lkg`.
- **Neuter→RED (B):** reverting `:2242` MUST fail `test_soc_envelope_engages_when_primary_frozen`.
- **Neuter→RED (D):** reverting `:6091` MUST fail `test_soc_resolution_exposes_primary_age_s` (no age visible).
- **Live:** post-deploy, `soc_resolution.attributes.primary_age_s` observed over 6h — zero ticks where `source_last == "envoy"` AND `primary_age_s > 300`.

### D3 — Migrate `solar_production_w` — BOTH producer AND envelope entry check

**D3-A — `energy_battery.py:1614` (producer path).** Migrate `self._read_power_w("solar_production")` to `self._read_fresh_power_w("solar_production", DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S, stamp="last_reported")`.

**D3-B — `energy_battery.py:2330` (envelope entry check `live = self._read_power_w("solar_production")`).** **REQUIRED migration** (Rev-2 fix — Rev 1 stated this as "verify by construction" and would have left ungated code shipping alongside the gated resolver). Migrate to the same `_read_fresh_power_w(...)` call. Without this, the envelope short-circuits on a frozen-valid live reading (`live is not None → return None`) precisely when we need the envelope MOST — i.e. today's producer bug fixed inside the resolver ONLY, worse than shipping nothing.

**Const:** `DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S: Final = 180` in `energy_const.py` adjacent to `SOLAR_POWER_FRESH_S:974`. Kept as a separate constant so a future producer-side tuning cannot silently shift EVSE bay accounting; document the equality-of-intent with `# NOTE:`.

#### Acceptance
- **Verify (A):** with the Envoy solar sensor frozen at 0 W for > 180s AND Envoy otherwise responsive, LKG at `:1618` does NOT re-stamp (`_solar_prod_lkg_at` unchanged).
- **Verify (B):** with the same frozen-valid solar, `solar_production_w_envelope()` returns a non-None tier (today it returns None because `:2330` reads `live is not None`).
- **Discriminating:** inject frozen-0 solar sensor (age = 200s) while battery SOC sensor shows age = 5s → `solar_production_w` returns None AND `_solar_prod_lkg_w` is unchanged. A fix that failed to gate would re-stamp `_solar_prod_lkg_w = 0.0`.
- **Test:** `test_solar_stale_does_not_poison_lkg`, `test_solar_stale_engages_envelope` (proves D3-B), `test_solar_fresh_byte_identical`.
- **Neuter→RED (A):** revert `:1614` → `test_solar_stale_does_not_poison_lkg` MUST fail.
- **Neuter→RED (B):** revert `:2330` → `test_solar_stale_engages_envelope` MUST fail (envelope short-circuits again).
- **Live:** post-deploy, `_solar_prod_lkg_w` monotonicity check on the persisted blob across an Envoy blind window; NM `blind_hold` alert unchanged (bytes-identical `envoy_available`).

### D4 — Migrate `net_power_w`, inline `battery_power_w`, AND billing `_get_net_power`

**D4-A — `energy_battery.py:1636` net_power_w.** Migrate to `self._read_fresh_power_w("net_power", DEFAULT_NET_POWER_MAX_AGE_S, stamp="last_reported")`. **New const** `DEFAULT_NET_POWER_MAX_AGE_S: Final = 180`.

**D4-B — grid-cap consumer at `energy.py:6071` — fail-SAFE change (Rev-2 must):** today `net_kw = (self._battery.net_power_w or 0) / 1000.0`; on None this treats the grid as 0 kW and the cap-actions helper will resume any bay in `_paused_by_grid_cap`. Change to:
```
if self._battery.net_power_w is None:
    # Stale/absent net_power — HOLD the current _paused_by_grid_cap set,
    # do NOT evaluate. Resume-only paths still run under the toggle-off
    # branch below on the next tick when a fresh read returns.
    pass
else:
    net_kw = self._battery.net_power_w / 1000.0
    grid_cap_actions = self._ev.determine_grid_cap_actions(...)
    ...
```
No changes to `determine_grid_cap_actions` internals; only the call-site is gated.

**Test:** `test_grid_cap_stale_net_holds_pause_set` — bay in `_paused_by_grid_cap`, `net_power_w` returns None for 5 consecutive ticks, bay MUST remain in the set; on the 6th tick a fresh net_power returns and the cap-actions helper runs normally.

**D4-C — persisted analytics `grid_import_kw` / `solar_export_kw` (`energy.py:3129-3130`) — null-propagation change (Rev-2 must, also credited in D6):** today
```
grid_import_kw = max(net_power_w or 0, 0) / 1000.0
solar_export_kw = abs(min(net_power_w or 0, 0)) / 1000.0
```
writes **false zero** to the persisted row on None (drifts every downstream analytics query). Match the sibling `solar_prod_kw` pattern at `:3128`:
```
grid_import_kw = max(net_power_w, 0) / 1000.0 if net_power_w is not None else None
solar_export_kw = abs(min(net_power_w, 0)) / 1000.0 if net_power_w is not None else None
```
Persist as NULL, not 0. Downstream analytics queries already tolerate NULL rows (they SUM/AVG over IS NOT NULL); a false 0 conflates "no data" with "no import".

**D4-D — `battery_power_w` inline refactor (`energy_battery.py:1546-1570`).** Route through `_read_fresh_power_w("battery_power", DEFAULT_BATTERY_POWER_MAX_AGE_S, stamp="last_reported")` with the sign-flip applied AT THE CALL SITE (not in the helper). **New const** `DEFAULT_BATTERY_POWER_MAX_AGE_S: Final = 180`. Do NOT change the display-only `battery_power` prop at `:1530`.

**D4-E — billing `_get_net_power` (`energy_billing.py:144-175`) — Rev-2 must (highest-dollar surface).** The direct-grid-entity branch at `:152-170` reads `sensor.<grid_import>`, `sensor.<grid_export>` and checks only `unknown/unavailable` — a frozen-valid grid CT poisons `_cost_today` / `_import_kwh_today` on every accumulate tick. The fallback branch at `:178-190` reads `self._net_power_entity` directly with the same weakness. Migrate both to a fresh-read pattern:

- Direct-grid branch: for `import_state` and `export_state`, call `self._battery._state_age_s(state, stamp="last_reported")` (or the equivalent helper hoisted to a shared util if `EnergyBillingCoordinator` doesn't own an `EnergyBatteryCoordinator` reference — builder chooses the smaller diff; if hoisted, the helper becomes a module-level function in `energy_battery.py` and re-imported). If EITHER state's age > `DEFAULT_NET_POWER_MAX_AGE_S`, return None (accumulate skips this tick, same as today's unavailable path).
- Fallback branch: same, against `self._net_power_entity`.

**Test:** `test_billing_stale_grid_import_returns_none`, `test_billing_stale_fallback_returns_none`, `test_billing_fresh_byte_identical` (accumulator sums equal to today's within ε).

#### Acceptance (D4)
- **Test:** `test_net_power_stale_returns_none`, `test_battery_power_w_stale_returns_none_sign_preserved`, `test_battery_power_display_unchanged`, `test_grid_cap_stale_net_holds_pause_set` (D4-B), `test_persisted_row_null_on_stale_net` (D4-C), `test_billing_stale_*` (D4-E).
- **Discriminating (D4-B):** without the fail-safe change, `test_grid_cap_stale_net_holds_pause_set` PASSES only under a fix that suppresses the resume; the `or 0` band-aid would fail it (verified by mutation: reverting to `or 0` makes the paused bay resume in the test).
- **Discriminating (D4-C):** row's `grid_import_kw` and `solar_export_kw` columns are NULL (not 0.0) when `net_power_w is None`; distinct observable from the buggy path.
- **Neuter→RED:** per site.
- **Live (D4-A/B):** peak-import counter freezes (does not integrate stale) on the next observed Envoy CT stall > 180s; recorder query on CT `last_reported` vs sensor tick.
- **Live (D4-C):** post-deploy DB spot check — pre-deploy 24h count of rows with `grid_import_kw = 0.0 AND net_power source stale` (via recorder cross-tab) vs post-deploy count — expect a drop to ~0 for the stale sub-population (fresh rows unchanged).
- **Live (D4-E):** `_cost_today` and `_import_kwh_today` sensors — before/after 24h totals within ±5 % on a comparable-weather day (freezing accumulator during stale windows will TRIM total, not inflate; direction of drift is the discriminator).

### D5 — Fold the 4 hand-rolled gates through the helper (de-dup, thresholds AND stamps preserved)

**Rev-2 rule (must-fix #1 corollary):** each folded site preserves its CURRENT stamp verbatim via the `stamp=` arg. Do not "upgrade" a gate to `last_reported` in this cycle.

- `energy_battery.py:891-910` (cloud-SOC A1) — call `_state_age_s(st, stamp="last_updated")`. Cloud fallback entity is a REST-poll cadence; last_updated is what today's arithmetic uses. Keep `DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S=600` and the `fallback_stale_reject` branch identical.
- `energy_pool.py:4695-4708` (EVSE per-bay solar power) — call `_state_age_s(pst, stamp="last_updated")`. Verified at line 4697 today. Preserve `SOLAR_POWER_FRESH_S=180` and the `stale_power` set add; preserve CF-8 fail-closed on naive/missing.
- `energy_pool.py:4406-4413` (grid-follow) — call `_state_age_s(st, stamp="last_reported")`. Verified at line 4407 today (INV-SF-10). Preserve `SOLAR_FOLLOW_GRID_FRESH_S=180` and `(None, "stale")` return; preserve CF-8 fail-closed.
- `sensor.py:12491-12507` (AC-kWh **display-only attribute**) — call `_state_age_s(state, stamp="last_updated")`. Verified at line 12494 today. **Rev-2 correction to the byte-identity claim:** today the site has NO `try/except`, so a naive `last_updated` would raise (silently returning to attributes as `stale = True` default). The refactor introduces the helper's fail-closed semantics (naive → `_state_age_s` returns None → `stale = True`). This is a **behavior change on the pathological input** (naive stamps): new behavior is `stale = True`, old behavior was an exception → default `stale = True`. Net observable to the dashboard: identical `stale = True`. Document explicitly; add `test_ac_kwh_naive_stamp_shows_stale`. **NO** gate on `native_value` in this cycle.

**5th gate NOT folded:** `hvac_override.py:3962` — see non-goals + carded.

#### Acceptance (D5)
- **Test:** for each site, `test_<site>_helper_call_preserves_threshold` (age = threshold − 1 fresh; threshold + 1 stale; missing stamp; naive stamp) — all 4 cases hit the current branch.
- **Test:** `test_ac_kwh_naive_stamp_shows_stale` (Rev-2 addition — explicit behavior anchor for the exception → helper-fail-closed transition).
- **Neuter→RED:** in each site, replace the helper call with a hard-coded `age = 0.0` — the corresponding threshold test MUST fail.
- **Live:** `stale_power` set-add rate and `(None, "stale")` grid-return rate within ±10 % of pre-deploy 24h baseline. NM `envoy_available` and `blind_hold_active` bytes-identical.

### D6 — Pre/post row-rate snapshot (Tier 2-DB requirement)

Pre-deploy capture (Rev 2 — pin the exact queries so the post-deploy comparison is not ambiguous):

```
# 1. _soc_source_last distribution over last 24h
ssh ha 'sqlite3 /config/universal_room_automation/data/universal_room_automation.db \
  "SELECT json_extract(attributes,'"'"'$.source_last'"'"'), COUNT(*) \
   FROM states_meta sm JOIN states s ON s.metadata_id = sm.metadata_id \
   WHERE sm.entity_id = '"'"'sensor.ura_energy_soc_resolution'"'"' \
     AND s.last_updated_ts > strftime('"'"'%s'"'"','"'"'now'"'"') - 86400 \
   GROUP BY 1;"'

# 2. Anomaly rows by (coordinator, severity, type) last 24h
ssh ha 'sqlite3 /config/universal_room_automation/data/universal_room_automation.db \
  "SELECT coordinator, severity, type, COUNT(*) FROM anomaly_events \
   WHERE ts_utc > strftime('"'"'%s'"'"','"'"'now'"'"') - 86400 \
   GROUP BY 1,2,3 ORDER BY 4 DESC;"'

# 3. Rev-2 D4-C: false-zero grid_import_kw rows (drops post-fix)
ssh ha 'sqlite3 /config/universal_room_automation/data/universal_room_automation.db \
  "SELECT strftime('"'"'%Y-%m-%d'"'"', dt_local), \
          SUM(CASE WHEN grid_import_kw = 0.0 THEN 1 ELSE 0 END) AS zeros, \
          SUM(CASE WHEN grid_import_kw IS NULL THEN 1 ELSE 0 END) AS nulls, \
          COUNT(*) AS total \
   FROM ura_energy_snapshots \
   WHERE dt_local > date('"'"'now'"'"','"'"'-1 day'"'"') \
   GROUP BY 1;"'
```

Comparison ±25 % at 24 h post-restart per Tier 2-DB policy, EXCEPT the false-zero column (query 3) which is expected to migrate from `zeros>0/nulls≈0` → `zeros≈live-true-zeros/nulls>0` — the DIRECTIONAL test.

---

## Non-goals (explicit)

- **No new unconsumed staleness sensor.** Consumer-check ruling: gate the READ.
- **No threshold changes to any existing gate.** `SOLAR_POWER_FRESH_S=180`, `SOLAR_FOLLOW_GRID_FRESH_S=180`, `DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S=600`, `AC_KWH_SENSOR_STALENESS_S` — untouched.
- **No change to `envoy_available` composition.** D2-C explicitly keeps the raw read.
- **No periodic reload / probe / watchdog.** Passive read-time gate only.
- **No change to display props** (`battery_power` at `:1530`; AC-kWh `native_value`).
- **No unification of the hand-rolled thresholds into one number.**
- **No migration of non-Energy staleness sites** (BLE room-mapping, presence LKG, tracker-stale) — out of scope.
- **`hvac_override.py:3962` NOT folded in this cycle** — 5th AC-kWh gate; different coordinator, fail-OPEN-on-TypeError contract opposite to helper's fail-closed. **Card:** `HVAC-OVERRIDE-KWH-STALE-FAIL-OPEN-1` (fold + flip to fail-closed; standalone review).
- **AC-kWh `native_value` staleness gate not added** — attribute-only remains; separately cardable if desired.

---

## Tier 2-DB review plan (3 framings + Live)

- **Review A — data integrity / read-layer correctness.** Byte-identity of the fresh path across the migrated reads (D2/D3/D4) via mutation-anchored source drills. Verify all four NEW consts land at rung 1. Verify `_state_age_s` `stamp=` arg propagates correctly (naive-stamp, missing-stamp, fallback-to-last_updated). LKG stamp semantics preserved (no accidental stamp on None).
- **Review B — signal-chain / cross-coordinator integration.** For each consumer (see Consumer table) trace end-to-end that a stale read at the producer routes to the correct fallback with no double-emit, no signal drop, no restart divergence. Explicit re-verification of D2-B/D and D3-B (the ungated-gate-alongside-gated-resolver risk that Rev 1 shipped). Explicit re-verification of D4-B fail-safe (grid-cap resume suppression) and D4-C NULL-vs-0 persistence.
- **Review C — new surface / test authority.** Every new const round-trips via `energy_const.py`; every acceptance test drives production code (no INSERT/monkeypatch shortcuts); the discriminating tests actually discriminate.
- **Review D — Live Validation, post-restart.** Recorder queries pinned in D6 run pre/post. `soc_resolution.attributes.primary_age_s` observed over 6h — zero decision-path ticks where `source_last == "envoy"` AND `primary_age_s > 300`. README `Validated <date>` table written back before cycle close.

---

## Files to change

- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` — add helpers (D1); migrate 4 SOC + 2 envelope + 3 power sites (D2/D3/D4); fold A1 gate (D5); add `primary_age_s` attribute to soc_resolution sensor surface.
- `custom_components/universal_room_automation/domain_coordinators/energy_pool.py` — fold 2 gates (D5).
- `custom_components/universal_room_automation/domain_coordinators/energy.py` — D4-B fail-safe on grid-cap consumer (`:6071`); D4-C NULL propagation on persisted row (`:3129-3130`).
- `custom_components/universal_room_automation/domain_coordinators/energy_billing.py` — D4-E fresh-read migration for both grid-entity and fallback branches.
- `custom_components/universal_room_automation/sensor.py` — fold 1 display gate (D5 arithmetic only); expose `primary_age_s` on soc_resolution sensor.
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py` — 4 new `DEFAULT_*_MAX_AGE_S` constants with rationale comments.
- `quality/tests/` — new module `test_shared_power_read_staleness.py` covering D1-D5 acceptance.
- `docs/readmes/README_v<next>.md` — pre-deploy prospective, post-restart validation table.

## Risks & mitigations

- **Test-file collision** — coordinate with any concurrent Energy cycle via worktree isolation (memo `feedback_worktree_isolation_all_agents`); serialise suite runs (memo `feedback_serialise_suite_runs_across_agents`).
- **`.pyc` staleness during mutation drills** — enforce `PYTHONDONTWRITEBYTECODE=1` + `find … -name __pycache__ -delete` before each drill (memo `feedback_mutation_verification_pycache_staleness`).
- **Silent threshold drift** — Review A explicit checklist to diff all preserved constants pre/post.
- **Billing regression risk (D4-E) — highest-dollar surface.** Add a boot-time INFO log line summarizing `_cost_today` / `_import_kwh_today` for the first 24 h; Review D compares against pre-deploy baseline.

## Open questions for operator (not blocking planning)

- `hvac_override.py:3962` (5th AC-kWh gate) — fold in a follow-up cycle, or flip only its fail-OPEN behavior first? (Carded either way as `HVAC-OVERRIDE-KWH-STALE-FAIL-OPEN-1`.)
- AC-kWh `native_value` staleness gate — card, or leave the display sensor alone?
- If the sequential ~600 s stale-trust horizon for primary SOC is unacceptable, do we (a) lower `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S` to 120 s so aggregate is ~420 s, or (b) also lower `DEFAULT_SOC_LKG_MAX_AGE_S` (broader blast radius)? Rev 2 keeps both at 300 s as the safe default.

---

## Rev 2 fix summary (2026-09-01)

Applied per adversarial plan-review:

1. **CRITICAL #1 (stamp semantics)** — helper signature gains `stamp="last_reported"` with `last_updated` fallback; invariant rewritten around `last_reported`; per-site stamp preserved in D5; new test `test_read_fresh_constant_valued_sensor_is_fresh` added to D1.
2. **CRITICAL #2 (solar 3rd site)** — D3 split into D3-A (`:1614`) and D3-B (`:2330`), the latter REQUIRED with its own Neuter→RED anchor `test_solar_stale_engages_envelope`.
3. **HIGH #3 (primary-SOC 4 sites)** — D2 expanded into D2-A (`:828`), D2-B (`:2242`), D2-C (`:2455`, classified KEEP with justification), D2-D (`:6091`, migrated); `primary_age_s` surfaced on soc_resolution for the Live criterion.
4. **HIGH #4 (net_power fail-open)** — D4-B fail-SAFE change at `energy.py:6071`: None → HOLD `_paused_by_grid_cap`, no evaluation; `test_grid_cap_stale_net_holds_pause_set` added.
5. **HIGH #5 (billing)** — D4-E added; `energy_billing.py:_get_net_power` both branches migrated to fresh-read; false "billing protected" claim removed from Consumer table.
6. **MEDIUM #6 (false-zero analytics)** — D4-C added; `energy.py:3129-3130` switched to None/NULL propagation matching sibling `:3128`; D6 pre/post query pinned.
7. **MEDIUM (consumer table)** — corrected: dropped bogus `energy_pool.py:1483` excess-solar-admit claim; real consumers listed at `energy.py:3126/:3229/:3404/:3557` + envelope `:2330`; `determine_excess_solar_actions:1610` explicitly not a solar reader.
8. **MEDIUM (#63 NOTE)** — corrected: LKG is stamped at READ time (`:830-832`), so primary-frozen + gate is SEQUENTIAL aggregate up to (PRIMARY_MAX + LKG_MAX), not a shared boundary; documented in the LKG-stamp arithmetic note under the Producer table and in D2's const rationale.
9. **MEDIUM (5th AC-kWh gate)** — `hvac_override.py:3962` listed as non-goal with reason (fail-OPEN opposite contract); carded as `HVAC-OVERRIDE-KWH-STALE-FAIL-OPEN-1`.
10. **MEDIUM (D5 byte-identity claim)** — corrected for `sensor.py:12494`: today has no try/except, so helper introduction changes the pathological-input (naive stamp) path from raising to `stale=True`; net observable identical; `test_ac_kwh_naive_stamp_shows_stale` added.
11. **MEDIUM (D6 queries)** — three concrete `ssh ha sqlite3` snapshots pinned; DIRECTIONAL test for the false-zero column added.

Invariant re-verification with `last_reported`: a constant-valued fresh sensor now passes the fresh path (its `last_reported` re-advances each poll); the invariant's "MUST be treated as absent when age > MAX_AGE_S" property is preserved for the trust-decision path; the discriminating test `test_read_fresh_constant_valued_sensor_is_fresh` anchors the change. Invariant holds.
