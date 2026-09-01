# PLANNING — Shared Power-Read Staleness Helper (ENVOY-PRODUCTION-STALE-1)

**Card:** `ENVOY-PRODUCTION-STALE-1` (consolidated per operator 2026-08-31).
**Rev:** 4 (2026-09-01) — plan-review FIX-REQUIRED addressed. Core insight this rev: **gating a READ to `None` is NOT universally safe.** The None-direction (fail-open vs fail-closed) is per-CONSUMER. Several trust consumers currently treat `None` as "no problem" (fail-open); left uncorrected, gating their producer would move safety guards from "wrong-because-frozen" to "silently disarmed". Every migrated producer now carries an explicit per-consumer None-handling contract; safety guards (breaker, drain-protection, load-shed) are pinned fail-CLOSED at the call-site. Rev 3 D-OBS retained, HIGH-4 fixed.
**Tier:** **2-DB** (regression-prone, cross-coordinator ripple: energy_battery → energy_pool → EVSE + DP + NM + billing; shared primitive; folds together six hand-rolled gates whose thresholds MUST be preserved byte-for-byte on the fresh path).
**Mode:** planning only (read-only). Awaits second plan-review pass before build dispatch.

**Falsifiable invariant (state up front — Rev 4):**
> For every trust-decision-consuming power/SOC read in the Energy family, a numeric HA state whose **`last_reported`** stamp (falling back to `last_updated` when the platform did not populate `last_reported`) is older than the site's configured `MAX_AGE_S` MUST be treated as **absent** (helper returns `None`) AND EACH CONSUMER of that value MUST route to a **fail-SAFE** fallback that preserves the SAFETY DIRECTION of the guard it participates in — the drain-pause set is HELD, the breaker guard TRIPS, the load-shed sustained window is NOT reset, the billing tick is SKIPPED, the persisted analytics column is NULL (never `0`). On the fresh path (age ≤ MAX_AGE_S, valid unit, in-range) the returned value MUST be **byte-identical** to today's read.
>
> Why `last_reported`, not `last_updated`: HA advances `last_reported` on every re-publish (even when the value did not change), but only advances `last_updated` on a value change. A healthy sensor pinned at 0 W (solar at night) or a constant-valued sensor would therefore be judged stale under `last_updated`. This is the same reason the existing grid solar-follow gate at `energy_pool.py:4406-4413` (INV-SF-10) uses `last_reported`. Any migrated site is INDIVIDUALLY specified below to preserve its current stamp choice — see D5.
>
> Why "per-consumer fail direction" is on the invariant: v5.17.5 A1 already fixed the stamp problem for one consumer. What killed that isolated fix on the wider surface (identified in Rev-4 plan-review) is that several trust consumers of `battery_power_w` and `net_power_w` are `x is not None and x < THRESH` shapes — where `None` yields `False` and the guard SILENTLY DISARMS. Producer-gating alone is worse than status quo on those sites. This invariant makes that impossible to omit.

---

## Institutional context verified

### Design/rules read
- `CLAUDE.md` — Tier 2-DB triggers; Producer/Consumer rule; "Numbers get knobs" ladder; "Coincidental equality masks a concept split"; "Extend existing, never rebuild"; "Do the robust fix, not band-aid+card".
- `docs/QUALITY_CONTEXT.md` — Bug class **#7 stale data source** (frozen-valid numeric reads defeat consumers that only check unknown/unavailable) — this cycle is a systematic sweep of that class across the Energy read surface. Bug class **#63 coincidental equality masks a concept split** — informs discriminator wording on D2-A (LKG numerically == primary when frozen).
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.5a — reserve verifiable backout knob (MAX_AGE_S=0 fire-axe); establishes the *"missing = go to fallback, never trust a stale value"* doctrine this cycle extends to the READ layer.

### Prior planning / memory pulled
- Memo `reference_ec_reserve_verifiable_backout_knob` — fire-axe precedent.
- Memo `feedback_coincidental_equality_masks_concept_split` — informs why the hand-rolled gates converged on 180s / 300s / 600s **by domain** and MUST NOT be silently unified into one number; also anchors the D2-A discriminator note (LKG value can equal primary numerically → the discriminator MUST be `_soc_source_last`, not the value).
- Memo `feedback_do_robust_fix_not_bandaid_and_card` — supports operator's consolidate ruling.
- Memo `feedback_read_consumers_before_asserting_function` — direct authority for the exhaustive Consumer + None-direction check on every migrated site (the Rev-1..3 doc failed this by omitting `net_power_w`'s biggest safety consumers).
- v5.17.5 A1 review record — introduced `DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S=600` (`energy_battery.py:882-910`); the extra-comment there IS the template for this cycle's per-site guard. NOTE the current site's `except` block explicitly ACCEPTS on missing/naive `last_updated` ("let unit + range checks decide") — a fail-OPEN branch that D5 must preserve, NOT silently flip.
- v4.5.0 unit-consistency sweep — established `_read_power_w` as the single power reader; this cycle mirrors that pattern at the staleness layer.
- Rev 3: `docs/dashboards/ura_v6_v8_solar_aware_ev_and_census_cards.md` — precedent for staging cards via `ha_config_set_dashboard` `python_transform` (never `.storage` hand-edits); the D-OBS tile follows this pattern.

### Producer AND Consumer surveyed (re-verified by grep 2026-09-01, Rev-4 completed)

**Class-name correction (Rev 4).** The owning classes are:
- `class BatteryStrategy` at `energy_battery.py:307` (NOT "EnergyBatteryCoordinator" — no such class exists).
- `class CostTracker` at `energy_billing.py:92` and `class PeakAvoidanceTracker` at `energy_billing.py:457` (NOT "EnergyBillingCoordinator").
- Grep of `EnergyBatteryCoordinator|EnergyBillingCoordinator` across `custom_components/universal_room_automation/` returns two hits in `inclement.py` and `signals.py` — both are unrelated forward-references / typing quirks in other coordinators, not real classes. Every doc reference below uses the correct symbol.

**Helper HOME decision (Rev 4).** Because the helper has THREE consumers across TWO modules (`energy_battery.BatteryStrategy` at 4 sites, `sensor.py` at 1 site, `energy_billing.CostTracker` at 2 sites), a method on `BatteryStrategy` would force `sensor.py` and `energy_billing.py` to reach through a coordinator handle they may not have. Decision: `_state_age_s` is a **module-level function in `energy_battery.py`** (top of file, after imports); `BatteryStrategy` gets thin instance-method wrappers `_read_fresh_power_w` / `_read_fresh_float` that call it internally (they need `self._get_entity(...)` and `self._read_power_w`'s unit normalization); `sensor.py` and `energy_billing.py` import `_state_age_s` directly. Rung 1 knob (module constant) not instance state.

**PRODUCER table — sites this cycle gates:**

| # | Site (producer) | file:line | Current reject | Fallback that engages when helper returns `None` |
|---|---|---|---|---|
| 1 | `_read_power_w("solar_production")` via `solar_production_w` | `energy_battery.py:1572-1596`, called at `:1614` | unknown/unavailable only | `solar_production_w_envelope()` at `:2287` — its own entry check at `:2330` also calls `_read_power_w(...) is not None`; both call sites migrated together (D3). |
| 2 | `_read_power_w("net_power")` via `net_power_w` | `energy_battery.py:1628-1636` | unknown/unavailable only | see expanded Consumer table + per-consumer fail-CLOSED specs (D4). |
| 3 | `battery_power_w` inline | `energy_battery.py:1546-1570` | unknown/unavailable only | drain-protection consumers currently fail-OPEN on `None` — D4-D REQUIRES paired call-site fail-CLOSED at `energy.py:6162` AND `:6318` before the producer gate ships. |
| 4 | PRIMARY `battery_soc` via `_get_state_float(self._get_entity("battery_soc"))` | 4 CALL SITES — see D2 | unknown/unavailable only | three-tier resolver (LKG → cloud) at `:838-921` for site A only; sites B/D need migration to reach the same guarantee; site C is a health predicate (classify explicitly). |

**LKG-stamp arithmetic note (Rev 2 preserved):** the LKG is stamped at READ time — `energy_battery.py:830-832` snapshots `_soc_lkg_at = dt_util.utcnow()` **on every fresh read**, not against the source sensor's `last_reported`. Therefore the aggregate blindness under a frozen primary is **sequential**: up to `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S` (helper does not yet return None) PLUS up to `DEFAULT_SOC_LKG_MAX_AGE_S` (LKG stamp still fresh from the last real read) before the cloud tier is reached. With both at 300 s the worst case is ~600 s of stale-trust before cloud engages, not 300 s. Intentional and DOCUMENTED — do not "fix" by reducing either constant blindly.

---

### CONSUMER × None-direction table (Rev 4 — the load-bearing new section)

Every migrated producer's DOWNSTREAM sites, with the SHIPPED None behavior today (fail-open = safety guard disarms; fail-closed = safety guard engages / conservative fallback) and the REQUIRED behavior after this cycle. **Safety guards MUST be fail-CLOSED.** A row marked "fail-open — change" is where this cycle changes the call-site, not just the producer.

#### `battery_power_w` consumers

| # | Consumer | file:line | Trust vs display | None today | Required post-cycle | Rev-4 mechanism |
|---|---|---|---|---|---|---|
| 1 | EVSE drain gate — plugs | `energy_pool.py:2207-2209` (`is not None and < -100`) | trust (drain pause) | **fail-OPEN** — `discharging=False` → drain pause NEVER fires → EV keeps drawing from battery below floor | fail-CLOSED — HOLD `_paused_by_battery_drain`, do NOT evaluate | D4-D-1: at `energy.py:6162` call site, gate the `determine_battery_drain_actions(...)` call on `self._battery.battery_power_w is not None`; on None, log once + skip (existing `_paused_by_battery_drain` set persists). |
| 2 | EVSE drain gate — smart plugs | `energy_pool.py:3711-3713` (identical shape) | trust (drain pause) | **fail-OPEN** (same shape) | fail-CLOSED — HOLD | D4-D-2: same at `energy.py:6318` (smart_plugs). |
| 3 | `_effective_import_kw` (breaker math) | `energy_battery.py:2627-2633` (`batt_w=None → 0`, does not subtract) | trust (breaker guard math) | **fail-CLOSED already** — treating batt charge as 0 makes effective_import ≥ net, so guard trips MORE easily. Documented at `:2623-2625`. | unchanged | none — preserve. |
| 4 | Envoy restart cache write | `energy.py:2455-2460` (writes raw `.battery_power` prop) | display / restart seed | writes frozen prop | see MEDIUM-7 disposition in D4-F | D4-F. |
| 5 | Write-verifier / forecast reads | `energy_write_verify.py:1794`, `energy_forecast.py:566` | trust (verification, forecasting) | not investigated in Rev-4 scope | out of scope this cycle — CARDED `BATTERY_POWER_W_CONSUMERS_AUDIT_1` | non-goal, documented. |

**Sign-flip note:** `battery_power_w` is signed (positive = charging into battery, negative = discharging out of battery). None handling MUST NOT be a `abs() > THRESH` shape at any new call site — the `is None` short-circuit runs first.

#### `net_power_w` consumers

| # | Consumer | file:line | Trust vs display | None today | Required post-cycle | Rev-4 mechanism |
|---|---|---|---|---|---|---|
| 1 | EVSE grid-cap | `energy.py:6071` (`or 0 / 1000`) | trust (pause/resume EVSE) | **fail-OPEN** — treats grid as 0 kW, resumes paused EVSEs | fail-CLOSED — HOLD `_paused_by_grid_cap` | D4-B (unchanged from Rev 2/3). |
| 2 | Persisted analytics row | `energy.py:3129-3130` (`or 0`) | trust (writes DB) | writes false 0 | NULL propagation | D4-C (unchanged). |
| 3 | Load-shed sustained-window trigger | `energy.py:7381-7387` (`snap = self._battery._effective_import_kw(); if snap is None: return`) | trust (SHED escalation) | **fail-OPEN by early-return** — no shed escalation AND no release; `_sustained_import_readings` deque is frozen (neither appended nor drained) | fail-CLOSED — on None, do NOT return silently; explicitly DRAIN the sustained-window deque (treat as "cannot confirm sustained import" → break the run) and keep the existing shed set intact (releases require a fresh in-window read, same as today's toggle-off branch downstream). | D4-G (NEW Rev-4). |
| 4 | Breaker guard predicate | `energy_battery.py:2648` (`_grid_import_guard_triggered`, `return False` on None snap) | trust (breaker trip → abort fresh charge start / halt grid-charge) | **fail-OPEN** — 12 kW breaker guard cannot trip when net_power reads stale | fail-CLOSED — on None, **return True** (assume tripped), matching the docstring precedent at `_breaker_guard_fail_closed_on_blind:3358` for the FRESH-entry path. Existing `envoy-unavailable branch upstream` comment at `:2639-2641` refers to a full-outage branch; a stale-but-numeric LOCAL sensor bypasses that upstream check (verified: `_degraded_telemetry_source` at `:3358` is None on a value-pinned local CT). | D4-H (NEW Rev-4). Only ships alongside D4-A; if D4-A defers, D4-H MUST defer with it. |
| 5 | Billing accumulate (direct grid) | `energy_billing.py:152-170` (`unknown/unavailable` only) | trust (dollars) | fail-open on frozen-valid CT | fail-CLOSED — skip tick | D4-E (unchanged). |
| 6 | Billing accumulate (fallback) | `energy_billing.py:178-190` | trust (dollars) | fail-open on frozen-valid | fail-CLOSED — skip tick | D4-E (unchanged). |
| 7 | Aggregation reads | `aggregation.py:6289`, `:6319` | trust — pending re-verification during build | not investigated in Rev-4 scope | OUT OF SCOPE this cycle | CARDED `AGGREGATION_NET_POWER_STALE_1` (builder verifies at wire-in; if surface is display, keep raw; if trust, add fail-CLOSED). |
| 8 | Sensor exposure | `sensor.py:8690`, `:11538` | display | display-only | unchanged (display) | none. |

Rev-4 reviewer explicitly cleared the "fail-closed already" claim for the breaker via `_breaker_guard_fail_closed_on_blind` — that helper only compensates when `_degraded_telemetry_source is not None`; a value-pinned LOCAL CT does NOT set that flag, so the compensation does not apply. D4-H is REQUIRED, not redundant.

#### `solar_production_w` consumers

All three trust consumers at `energy.py:3229/:3404/:3557` accept `None` via existing None-safe strategy math (verified during Rev-2 sweep). Envelope entry at `energy_battery.py:2330` is fail-OPEN under D3 producer gate and is addressed by D3-B. Persisted row at `energy.py:3126` is already None-safe. No new fail-direction fixes.

#### `battery_soc` consumers

Resolver (D2-A) collapses the primary/LKG/cloud tiers into one number. Downstream consumers see the tiered result, which is None only when ALL three tiers fail — the existing blind-hold branch handles that. No new fail-direction fixes.

---

### 5th AC-kWh gate (Rev-2 addition, preserved)

`hvac_override.py:3962` gates the AC-kWh read on `age_s > AC_KWH_SENSOR_STALENESS_S` using `last_updated`, and fails **OPEN** on `TypeError` (returns `age_s = 0.0`, admitting the read) — opposite of the CF-8 fail-closed contract used elsewhere. **Non-goal in this cycle** (behavioral change to a different coordinator's read path); **carded separately** (`HVAC-OVERRIDE-KWH-STALE-FAIL-OPEN-1`).

### Consumer-check finding (design-binding, unchanged)

`sensor.ura_energy_envoy_status.stale` is DISPLAY-ONLY. `envoy_available` IS trusted (`energy.py:3753` blind_hold DP; `energy_pool.py:571` EVSE guard; `:2934` NM alert) but is computed from primary SOC + storage_mode. ∴ The fix MUST gate the READ. Extending `envoy_status` for operator-facing staleness surfacing is display-safe by grep (Rev 3, re-verified Rev 4: three self-references only — `sensor.py:13296` docstring, `sensor.py:13308` unique_id, `energy.py:841` comment).

### Grep prior-art results for proposed additions
- `_state_age_s` / `state_age_s` / `read_fresh` / `_read_state_fresh` — **NEW** module-level function in `energy_battery.py` (six site-local re-implementations at `energy_battery.py:891`, `energy_battery.py:1136-1150` (folded per Rev-4 MEDIUM-6), `energy_pool.py:4406`, `energy_pool.py:4695`, `sensor.py:12494`, `hvac_override.py:3956` — the 6th is scope-carded).
- `DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S`, `DEFAULT_NET_POWER_MAX_AGE_S`, `DEFAULT_BATTERY_POWER_MAX_AGE_S`, `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S` — **NEW**. Rung 1 (module constants — safety knobs, review-gated).
- Rev 3: `sensor.ura_energy_coordinator_envoy_status` — **REUSED** (extended, not duplicated). Definition at `sensor.py:13293-13444`.
- Rev 3/4: `solar_age_s`, `net_power_age_s`, `battery_power_age_s`, `primary_soc_age_s`, `stale_sources`, `unconfigured_sources` (Rev-4 split from `stale_sources` per HIGH-4), `fallback_active` — **NEW attributes** on the existing sensor, sourced from the D1 helper.

### Code locations surveyed end-to-end
- `energy_battery.py:307` (`class BatteryStrategy`), `:770-925` (SOC resolver + A1 gate at `:882-910`), `:830-832` (LKG stamp arithmetic), `:1130-1155` (6th gate — cloud-oracle lag with `max(0.0,…)` clamp), `:1530-1636` (power readers), `:2225-2320` (envelope entry checks — both primary-SOC and live-solar), `:2440-2461` (`envoy_available` predicate), `:2620-2646` (`_effective_import_kw` + `_grid_import_guard_triggered`), `:3350-3370` (`_breaker_guard_fail_closed_on_blind` — scope-limited compensator), `:6080-6100` (soc_resolution diagnostics).
- `energy.py:2450-2460` (save_envoy_cache raw writes), `:3115-3140` (persisted analytics), `:3225-3560` (solar strategy consumers), `:6055-6090` (EVSE grid-cap consumer), `:6150-6165` and `:6310-6325` (drain-actions call sites — D4-D fail-CLOSED targets), `:7370-7400` (load-shed sustained window — D4-G target).
- `energy_billing.py:92` (`class CostTracker`), `:144-191` (`_get_net_power` — two branches, D4-E targets), `:457` (`class PeakAvoidanceTracker`).
- `energy_pool.py:565-580`, `:2200-2225`, `:3705-3720` (drain-consumers fail-OPEN today), `:4395-4417` (grid-follow), `:4685-4710` (per-bay solar power).
- `energy_const.py:300-340`, `:960-985`.
- `sensor.py:12480-12515` — AC-kWh display gate (no try/except — MEDIUM-8).
- `sensor.py:13293-13444` — `EnergyEnvoyStatusSensor`.
- `hvac_override.py:3950-3975` — 5th AC-kWh gate (scope-carded).

---

## Deliverables

### D1 — Add the shared helper (single source of truth)

Add a **module-level function** in `energy_battery.py` (top of file, after imports):

```python
def _state_age_s(state, *, stamp: str = "last_reported") -> float | None:
    """Return the age in seconds of `state` measured against `stamp`,
    falling back to `last_updated` if the chosen stamp is absent (a
    platform that never populated `last_reported`). Returns None if
    the state is missing, both stamps are absent, or the chosen stamp
    is naive (fail-closed per CF-8 precedent at energy_pool.py:4402-4409).

    Rev-4 (MEDIUM-6): negative ages clamped to 0.0 to defend against
    clock skew or future-stamped inputs, matching the shipped clamp at
    energy_battery.py:1149 (`ages.append(max(0.0, (now - lu).total_seconds()))`).
    Without the clamp a future-stamped state would read as fresh-by-accident.
    """
```

Plus two thin `BatteryStrategy` instance-method wrappers (they need `self._get_entity` and unit normalization from `_read_power_w`):

- `_read_fresh_power_w(entity_key, max_age_s, *, stamp="last_reported") -> float | None` — supersedes `_read_power_w`: same unit-normalization, plus rejects when `_state_age_s(state, stamp=stamp)` is `None` OR `> max_age_s`. Preserves fresh-path byte-identity.
- `_read_fresh_float(entity_id, max_age_s, *, stamp="last_reported") -> float | None` — same for the non-unit-scaled SOC read.

`sensor.py` and `energy_billing.py` import `_state_age_s` directly from `.domain_coordinators.energy_battery` (relative import — same package).

**Stamp choice per NEW gate (unchanged from Rev 2):**
- Solar production → `last_reported` (constant-0 at night is healthy).
- Net power → `last_reported` (constant during import/export balance).
- Battery power → `last_reported`.
- Primary SOC → `last_reported` (100 % pinned after full charge is healthy).

#### Acceptance
- **Verify:** helper is importable from `energy_battery`; no site calls it yet.
- **Test:** `test_state_age_s_missing_naive_fresh_stale`.
- **Test:** `test_state_age_s_prefers_last_reported_falls_to_last_updated`.
- **Test:** `test_state_age_s_negative_stamp_clamps_to_zero` (Rev-4 MEDIUM-6 anchor — future-dated `last_reported` returns 0.0, NOT a negative number that would compare fresh against every threshold).
- **Test:** `test_read_fresh_constant_valued_sensor_is_fresh`.
- **Test:** `test_read_fresh_power_w_unit_scaling_preserved`.
- **Live:** N/A.

### D2 — Migrate PRIMARY `battery_soc` — ALL FOUR SITES

Same as Rev 3 (A `:828`, B `:2242`, C `:2455` KEEP-raw with justification, D `:6091` migrate). No consumer-direction changes needed — resolver already handles None correctly.

**Const:** `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S: Final = 300` in `energy_const.py`.

**Rev-4 LOW-9 discriminator note (Bug Class #63):** on frozen-primary, the LKG value may numerically equal the primary reading (both were the SAME sample a moment ago). The D2-A acceptance MUST discriminate on `_soc_source_last` (`"envoy"` vs `"lkg"` / `"cloud_fallback"`), NOT on the returned SOC value. A test that only asserts `battery_soc == expected_value` proves NOTHING — a broken gate returns the same number as a working one. Explicit `_soc_source_last == "lkg"` assertions added to D2-A tests.

**Rev-2 D2 surface addition — `primary_age_s` attribute:** unchanged.

#### Acceptance (D2)
- (unchanged from Rev 3)
- **Discriminating (A, Rev-4 anchor):** inject numeric primary with `last_reported = now-400s`, LKG cache holds a numerically identical value stamped 5s ago. `battery_soc` returns that number under BOTH the broken gate and the fixed gate — **the anchor is `_soc_source_last == "lkg"`**, not the number. Test: `test_primary_soc_stale_discriminator_is_source_not_value`.
- (Other D2 tests unchanged.)

### D3 — Migrate `solar_production_w` — BOTH producer AND envelope entry check

Unchanged from Rev 3 (D3-A `:1614`, D3-B `:2330`).

### D4 — Migrate `net_power_w`, inline `battery_power_w`, billing `_get_net_power`, AND paired call-site fail-CLOSED fixes

**D4-A — `energy_battery.py:1636` net_power_w producer.** Migrate to `self._read_fresh_power_w("net_power", DEFAULT_NET_POWER_MAX_AGE_S, stamp="last_reported")`. **New const** `DEFAULT_NET_POWER_MAX_AGE_S: Final = 180`.

**Dependency lock (Rev 4 CRITICAL-2):** D4-A MUST ship in the same commit as D4-B, D4-C, D4-E, D4-G, D4-H. Shipping D4-A without D4-H would MOVE the 12 kW breaker guard from "trips on wrong number" to "cannot trip at all" during stale windows. Reviewer to gate this on a single-diff check.

**D4-B — grid-cap consumer at `energy.py:6071` — fail-SAFE change (unchanged from Rev 2).**

**D4-C — persisted analytics `grid_import_kw` / `solar_export_kw` (`energy.py:3129-3130`) — NULL propagation (unchanged).**

**D4-D — `battery_power_w` inline refactor + PAIRED call-site fail-CLOSED (Rev 4 CRITICAL-1).**

Producer (`energy_battery.py:1546-1570`): route through `_read_fresh_power_w("battery_power", DEFAULT_BATTERY_POWER_MAX_AGE_S, stamp="last_reported")` with sign-flip AT THE CALL SITE. **New const** `DEFAULT_BATTERY_POWER_MAX_AGE_S: Final = 180`. Do NOT change the display-only `battery_power` prop at `:1530`.

**D4-D-1 (paired, MANDATORY): fail-CLOSED at `energy.py:6161-6165` — plug/EVSE drain call.** Today `determine_battery_drain_actions` is called unconditionally; on `battery_power_w = None` the inner `is not None and < -100` yields `False` → drain pause NEVER FIRES → battery drains through the floor into a charging EV. Change:

```python
if self._battery.battery_power_w is None:
    # Rev-4 CRITICAL-1 fail-CLOSED: stale battery_power → HOLD the
    # current _paused_by_battery_drain set, do NOT call determine_*.
    # Mirrors D4-B grid-cap pattern. Releases still occur on the next
    # tick with a fresh read.
    _LOGGER.debug("EVSE drain: battery_power stale — holding pause set")
else:
    drain_actions = self._ev.determine_battery_drain_actions(
        battery_power_w=self._battery.battery_power_w,
        ...
    )
```

**D4-D-2 (paired, MANDATORY): same at `energy.py:6317-6325` — smart-plug drain call.** Identical shape.

**Test:** `test_drain_stale_battery_power_holds_pause_set_evse` and `test_drain_stale_battery_power_holds_pause_set_plugs` — bay/plug in `_paused_by_battery_drain`, `battery_power_w` returns None for 5 consecutive ticks, membership MUST persist; on the 6th tick a fresh read returns and `determine_battery_drain_actions` runs normally.

**Discriminating test — the D4-D core proof:** without D4-D-1/D4-D-2, migrating the producer alone MAKES THE BUG WORSE. Anchor test `test_drain_producer_gate_without_call_site_fail_close_regresses` — mutate `energy.py:6161` to call `determine_battery_drain_actions(battery_power_w=None, …)` unconditionally, then run the drain test with `battery_soc < threshold` and `battery_power_w` stale — MUST fail (pause is not held). Restoring the D4-D-1 gate re-passes. This is the mutation-anchored proof that producer + consumer BOTH move.

**D4-E — billing `_get_net_power` (`energy_billing.CostTracker._get_net_power` at `energy_billing.py:144-191`) — fresh-read migration (unchanged from Rev 2 in intent; class name corrected).** Import `_state_age_s` from `.energy_battery`; call directly against `import_state`/`export_state`/fallback `state`.

**D4-F — Envoy restart cache raw writes at `energy.py:2455-2460` (Rev 4 MEDIUM-7).** Today `save_envoy_cache` writes the RAW `.net_power`, `.solar_production`, `.battery_power` props (which are pre-gate `_get_state_float` reads at `energy_battery.py:1519/1527/1542`), guarded ONLY on `battery_soc is not None` — which after D2-A returns the LKG on staleness, so the outer guard passes but the raw fields are frozen. Choose (in-cycle):

Option 1 (chosen): gate the whole `save_envoy_cache` call on `self._battery._soc_source_last == "envoy"` (add alongside the existing `soc is None` check). Rationale: the cache is the RESTART SEED; poisoning it with frozen power at restart replays the frozen values as "fresh" on next boot until the first real read. Skipping a save when we know the source is stale is the same posture as D4-C NULL propagation. `_soc_source_last` is already computed by D2-A and requires no new state.

**Test:** `test_save_envoy_cache_skips_when_soc_source_last_is_lkg`, `test_save_envoy_cache_skips_when_soc_source_last_is_cloud_fallback`, `test_save_envoy_cache_fresh_path_unchanged`.

**D4-G — Load-shed sustained-window at `energy.py:7381-7387` (Rev 4 CRITICAL-2 sub-fix).** Today the early `return` on `snap is None` leaves `_sustained_import_readings` frozen — the shed neither escalates (correct, we can't measure) NOR releases (correct, we can't measure), BUT the deque is not drained, so on the NEXT fresh read one appended value is compared against a stale sustained window that spans a stale gap → false-persistent "sustained import" trigger the moment telemetry returns. Change:

```python
snap = self._battery._effective_import_kw()
if snap is None:
    # Rev-4: cannot confirm sustained import — DRAIN the trailing
    # window (break the run) so the next fresh read starts a new
    # sustained-import measurement, not a bogus stitched one across
    # the stale gap. Keep the existing shed set intact (releases
    # require an explicit fresh in-window read below).
    self._sustained_import_readings.clear()
    return
```

**Test:** `test_load_shed_sustained_window_drains_on_stale_snap` — pre-populate deque with 4 near-threshold readings; produce a stale snap; deque MUST be empty; next fresh reading MUST NOT trip sustained-import escalation until a fresh run rebuilds the window. Neuter → RED anchor: reverting the `.clear()` line MUST fail this test with a false-escalation.

**D4-H — Breaker guard fail-CLOSED at `energy_battery.py:2635-2646` (Rev 4 CRITICAL-2 sub-fix).** Today `_grid_import_guard_triggered` returns `False` on `snap is None` — the 12 kW guard CANNOT TRIP on stale net_power. The docstring's "envoy-unavailable branch upstream handles that case" is only true for full-outage paths that set `_degraded_telemetry_source`; a value-pinned local CT does NOT. Change:

```python
def _grid_import_guard_triggered(self) -> bool:
    snap = self._effective_import_kw()
    if snap is None:
        # Rev-4 CRITICAL-2 fail-CLOSED: stale net_power → assume the
        # breaker COULD be tripped. Mirrors the FRESH-entry-path
        # posture at _breaker_guard_fail_closed_on_blind:3358.
        # A stale-but-numeric LOCAL CT bypasses the upstream
        # envoy-unavailable branch because _degraded_telemetry_source
        # is not set on value-pinned local reads.
        return True
    return snap[0] > self._arbitrage_grid_import_guard_kw
```

**Test:** `test_breaker_guard_trips_on_stale_net_power` — stale `net_power_w`, guard MUST return True; existing fresh-path tests unchanged.

**Callers of `_grid_import_guard_triggered` re-verified (Rev 4):** the change makes fresh-entry paths ABORT when net_power reads stale (correct — matches the shipped `_breaker_guard_fail_closed_on_blind` for the same reason). No caller assumes False-on-stale as an admit signal.

#### Acceptance (D4)
- **Tests:** `test_net_power_stale_returns_none`, `test_battery_power_w_stale_returns_none_sign_preserved`, `test_battery_power_display_unchanged`, `test_grid_cap_stale_net_holds_pause_set` (D4-B), `test_persisted_row_null_on_stale_net` (D4-C), `test_drain_stale_battery_power_holds_pause_set_{evse,plugs}` (D4-D), `test_drain_producer_gate_without_call_site_fail_close_regresses` (D4-D mutation anchor), `test_billing_stale_*` (D4-E), `test_save_envoy_cache_skips_when_soc_source_last_is_{lkg,cloud_fallback}` (D4-F), `test_load_shed_sustained_window_drains_on_stale_snap` (D4-G), `test_breaker_guard_trips_on_stale_net_power` (D4-H).
- **Neuter→RED:** every one of the 8 sub-deliverables has its own reverse-mutation anchor.
- **Live (D4-A/B):** peak-import counter freezes on next Envoy CT stall > 180 s.
- **Live (D4-C):** row's `grid_import_kw`/`solar_export_kw` NULL (not 0.0) when `net_power_w is None`.
- **Live (D4-D):** during any observed `battery_power_w` stale window ≥ 180 s while an EVSE bay is `_paused_by_battery_drain`, the bay MUST remain paused (recorder cross-tab on EVSE state vs Envoy `battery_power` `last_reported`).
- **Live (D4-E):** `_cost_today`/`_import_kwh_today` ±5 % vs comparable day; direction of drift = trim, not inflate.
- **Live (D4-F):** post-restart, `envoy_cache` file's power fields either fresh (>= last `_soc_source_last == "envoy"` moment) or stale-but-flagged (Rev-4 acceptance: a boot log line stating "envoy_cache last saved with source_last=envoy at <ts>" — no bogus fresh replay).
- **Live (D4-G):** on the next observed Envoy CT stall ≥ 180 s that spans a would-be sustained window, `_sustained_import_readings` is observed to drain (debug log) and no shed escalation fires on the trailing edge.
- **Live (D4-H):** `_grid_import_guard_triggered` observed `True` during a stale window (`sensor.ura_energy_arbitrage_guard_triggered` or equivalent diagnostic); fresh-charge entry is aborted with the existing log line rather than proceeding blind.

### D5 — Fold the SIX hand-rolled gates through the helper (Rev-4 MEDIUM-6: 6 sites, not 4)

**Rev-2 rule preserved:** each folded site preserves its CURRENT stamp verbatim via the `stamp=` arg.

**Sites:**

1. `energy_battery.py:882-910` (cloud-SOC A1) — call `_state_age_s(st, stamp="last_updated")`. Preserve `DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S=600`. **Rev-4 HIGH-3 explicit contract:** today's `except` branch at `:907-910` explicitly ACCEPTS the fallback on missing/naive `last_updated` ("let unit + range checks decide"). The naïve D1-helper mapping (helper → None → reject → fully-blind → D2 de-escalation) would flip this trust-path from fail-OPEN to fail-CLOSED, a scope creep on a v5.17.5-shipped decision. Preserve today's semantics with an EXPLICIT mapping at THIS site:
   ```python
   age = _state_age_s(st, stamp="last_updated")
   if age is None:
       pass  # Rev-4: preserve v5.17.5 fail-OPEN — missing/naive
             # stamp → let unit+range checks decide. Do NOT flip to
             # reject as a side effect of the helper refactor.
   elif age > DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S:
       self._soc_source_last = "fallback_stale_reject"
       return None
   ```
   Add `test_cloud_soc_fold_preserves_fail_open_on_missing_stamp` to lock the semantics. A separate future cycle may propose the flip with its own review.

2. `energy_battery.py:1136-1150` (cloud-oracle lag D2 age tracker, Rev-4 MEDIUM-6 NEW fold) — call `_state_age_s(state, stamp="last_reported")`. The site already uses `last_reported → last_updated` fallback + `max(0.0, …)` clamp; the helper now embodies both. Preserve `_fire_d2_nm` threshold semantics; identical behavior on all in-domain inputs.

3. `energy_pool.py:4695-4708` (EVSE per-bay solar power) — call `_state_age_s(pst, stamp="last_updated")`. Preserve `SOLAR_POWER_FRESH_S=180` and `stale_power` set add; preserve CF-8 fail-closed on naive/missing.

4. `energy_pool.py:4406-4413` (grid-follow, INV-SF-10) — call `_state_age_s(st, stamp="last_reported")`. Preserve `SOLAR_FOLLOW_GRID_FRESH_S=180` and `(None, "stale")` return; preserve CF-8 fail-closed.

5. `sensor.py:12491-12507` (AC-kWh display-only attribute) — call `_state_age_s(state, stamp="last_updated")`. **Rev-4 MEDIUM-8 corrected rationale:** the current site has NO `try/except`. If `last_updated` is naive, the `(aware - naive).total_seconds()` at `:12497-12499` raises `TypeError` which PROPAGATES out of the `extra_state_attributes` property (does NOT fall back to the default attribute dict — HA renders the entity as unavailable-attrs on the exception). The refactor introduces the helper's fail-CLOSED semantics (naive → helper returns None → `stale = True` in the returned dict). **Net behavior change:** pathological input (naive stamp) transitions from "attributes property raises" to "attributes render `stale = True`" — strictly BETTER. Do NOT claim byte-identity on the pathological path; DO claim the new behavior is the intended one. Anchor: `test_ac_kwh_naive_stamp_renders_stale_true_no_exception`.

6. `hvac_override.py:3962` — **NOT folded** in this cycle (5th AC-kWh gate, opposite fail-OPEN contract) — carded `HVAC-OVERRIDE-KWH-STALE-FAIL-OPEN-1`.

#### Acceptance (D5)
- **Test:** per site `test_<site>_helper_call_preserves_threshold` (4 cases: age=threshold-1 fresh; age=threshold+1 stale; missing stamp; naive stamp) hitting the current branch.
- **Test:** `test_cloud_soc_fold_preserves_fail_open_on_missing_stamp` (site 1 HIGH-3 anchor).
- **Test:** `test_cloud_oracle_lag_fold_byte_identical_including_negative_clamp` (site 2 MEDIUM-6 anchor).
- **Test:** `test_ac_kwh_naive_stamp_renders_stale_true_no_exception` (site 5 MEDIUM-8 anchor).
- **Neuter→RED:** per site.
- **Live:** `stale_power` set-add rate and `(None, "stale")` grid-return rate within ±10 % of pre-deploy 24 h baseline. `envoy_available` and `blind_hold_active` bytes-identical.

### D6 — Pre/post row-rate snapshot (Tier 2-DB requirement)

Unchanged from Rev 3 (three pinned `ssh ha sqlite3` snapshots).

---

### D-OBS — Operator-facing staleness surface + Lovelace tile (Rev 3, HIGH-4 fixed in Rev 4)

**Rev-4 HIGH-4 fix — `stale_sources` must not include UNCONFIGURED sources.**

Original Rev-3 rule: `if age is None or > MAX: stale_sources.append(name)`. Problem: `_get_entity(key)` returns None for an unset optional CONF entity (`CONF_ENERGY_NET_POWER_ENTITY` and `CONF_ENERGY_BATTERY_POWER_ENTITY` are optional per `energy.py:990-992`); `hass.states.get(None)` returns None; helper returns None; the source is appended even though the operator never wired it. Result: `envoy_status` state pinned "stale" FOREVER on any install where a source is unset — this breaks the plan's own fresh-path regression criterion.

**Rev-4 corrected computation:**

```python
def _resolve_source_age(key: str) -> tuple[float | None, str]:
    """Return (age_s, status) where status in {'unconfigured','missing','fresh','stale'}."""
    eid = energy._battery._get_entity(key)
    if not eid:
        return (None, "unconfigured")
    st = hass.states.get(eid)
    if st is None:
        return (None, "missing")  # configured but entity vanished — degraded, not stale
    age = _state_age_s(st, stamp="last_reported")
    if age is None:
        return (None, "missing")  # fail-CLOSED for the trust decision, but not "stale" for display
    return (age, "fresh")  # threshold applied by caller

solar_age_s,          solar_status          = _resolve_source_age(CONF_ENERGY_SOLAR_ENTITY)
net_power_age_s,      net_power_status      = _resolve_source_age(CONF_ENERGY_NET_POWER_ENTITY)
battery_power_age_s,  battery_power_status  = _resolve_source_age(CONF_ENERGY_BATTERY_POWER_ENTITY)
primary_soc_age_s,    primary_soc_status    = _resolve_source_age(CONF_ENERGY_BATTERY_SOC_ENTITY)

stale_sources: list[str] = []
unconfigured_sources: list[str] = []
missing_sources: list[str] = []
for name, age, status, max_age in [
    ("solar_production", solar_age_s, solar_status, DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S),
    ("net_power", net_power_age_s, net_power_status, DEFAULT_NET_POWER_MAX_AGE_S),
    ("battery_power", battery_power_age_s, battery_power_status, DEFAULT_BATTERY_POWER_MAX_AGE_S),
    ("primary_soc", primary_soc_age_s, primary_soc_status, DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S),
]:
    if status == "unconfigured":
        unconfigured_sources.append(name)
    elif status == "missing":
        missing_sources.append(name)
    elif age is not None and age > max_age:
        stale_sources.append(name)
```

Only `stale_sources` (not `unconfigured_sources`, not `missing_sources`) drives the state-enum "stale" transition in D-OBS-2. `unconfigured_sources` and `missing_sources` are attributes for operator visibility; they do NOT pin the sensor to "stale".

**Rev-4 LOW-10 reconciliation note.** The existing `envoy_status` `last_available`-age trigger at `sensor.py:13358-13370` (bounded [600, 1800]) can fire "stale" while D-OBS `stale_sources == []` (per-source ages fresh but overall cycle age past bound). This is EXPECTED and CORRECT — they measure different things. Add `stale_reason` attribute (string: `"per_source" | "last_available" | "consumption_anomaly" | "unavailable_count"` or a set) so the tile can tell the operator WHICH trigger fired.

D-OBS-1 attributes final list:
- `solar_age_s`, `net_power_age_s`, `battery_power_age_s`, `primary_soc_age_s` (numeric | None)
- `stale_sources` (list[str] — configured-and-present-and-past-threshold)
- `unconfigured_sources` (list[str] — CONF unset)
- `missing_sources` (list[str] — configured but entity None/no stamp)
- `fallback_active` (bool | "lkg" | "cloud_fallback" | "solar_lkg")
- `stale_reason` (list[str] — which trigger(s) fired the "stale" state)

D-OBS-2 native_value: unchanged from Rev 3 EXCEPT the per-source-stale union branch is gated on the corrected `stale_sources` (unconfigured/missing do NOT trigger); `stale_reason` populated accordingly.

D-OBS-3 tile: unchanged from Rev 3; add `unconfigured_sources` row (icon `mdi:help-circle-outline`, hidden when empty) and `stale_reason` row.

#### D-OBS Acceptance (Rev-4 additions)

- **Regression (HIGH-4 anchor):** `test_envoy_status_unconfigured_net_power_does_not_pin_stale` — construct fixture with `CONF_ENERGY_NET_POWER_ENTITY` unset, all other sources fresh; `state == "online"`, `stale_sources == []`, `unconfigured_sources == ["net_power"]`. Neuter→RED: reverting to the Rev-3 "None-or-> threshold" mapping MUST fail this test.
- **Regression:** `test_envoy_status_missing_entity_reports_missing_not_stale` — configured entity that `hass.states.get` returns None for → `missing_sources` contains it, `stale_sources` does not, state stays as pre-per-source-trigger derivation.
- **Reconciliation (LOW-10):** `test_envoy_status_stale_reason_last_available_only` — force `_envoy_last_available` age past bound with all per-source ages fresh; `state == "stale"`, `stale_sources == []`, `stale_reason == ["last_available"]`.
- (Rev-3 D-OBS tests preserved.)

---

## Non-goals (explicit)

- **No new unconsumed staleness sensor.** Consumer-check ruling: gate the READ.
- **No threshold changes to any existing gate.** `SOLAR_POWER_FRESH_S=180`, `SOLAR_FOLLOW_GRID_FRESH_S=180`, `DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S=600`, `AC_KWH_SENSOR_STALENESS_S` — untouched.
- **No change to `envoy_available` composition.** D2-C explicitly keeps the raw read.
- **No flip of the v5.17.5-shipped cloud-SOC fail-OPEN-on-missing-stamp decision.** D5 site 1 explicitly preserves it; a flip requires its own review.
- **No periodic reload / probe / watchdog.** Passive read-time gate only.
- **No change to display props** (`battery_power` at `:1530`; AC-kWh `native_value`).
- **No unification of the hand-rolled thresholds into one number.**
- **No migration of non-Energy staleness sites** (BLE room-mapping, presence LKG, tracker-stale) — out of scope.
- **`hvac_override.py:3962` NOT folded** — 5th AC-kWh gate; carded.
- **`aggregation.py:6289/6319`, `energy_write_verify.py:1794`, `energy_forecast.py:566` NOT investigated** for fail-direction in this cycle — carded as `AGGREGATION_NET_POWER_STALE_1` and `BATTERY_POWER_W_CONSUMERS_AUDIT_1`.
- **AC-kWh `native_value` staleness gate not added** — attribute-only remains; separately cardable.
- **Rev 3: no parallel staleness sensor**; no NM push on the new per-source stale signal; no `state == "degraded"` enum variant; no PWA tile change.

---

## Tier 2-DB review plan (3 framings + Live)

- **Review A — data integrity / read-layer correctness.** Byte-identity of the fresh path across D2/D3/D4/D5 via mutation-anchored source drills. Verify all four NEW consts land at rung 1. Verify `_state_age_s` `stamp=` arg + `max(0.0, …)` clamp. LKG stamp semantics preserved. **Rev 4:** verify D5 site 1 preserves fail-OPEN semantics (`test_cloud_soc_fold_preserves_fail_open_on_missing_stamp` passes; a naïve helper-only refactor fails it). Verify D-OBS attribute computation uses SAME helper + stamp choice as the gate; `envoy_status.state` fresh-path byte-identical.
- **Review B — signal-chain / cross-coordinator integration + PER-CONSUMER None direction.** For each consumer in the Rev-4 CONSUMER × None-direction table, trace end-to-end that a stale read routes to the SAFETY-preserving fallback (fail-CLOSED for guards). Re-verify D2-B/D and D3-B (Rev-1..2 shipped alongside gated resolver). **Rev 4 required checks:** D4-A NOT shipped without D4-B, D4-C, D4-E, D4-G, D4-H in the same commit (single-diff gate); D4-D producer NOT shipped without D4-D-1 AND D4-D-2 call-site fail-CLOSED (mutation anchor `test_drain_producer_gate_without_call_site_fail_close_regresses`); `_grid_import_guard_triggered` change verified against ALL callers (grep for the symbol; none assume False-on-stale as admit); `_sustained_import_readings.clear()` at D4-G is REACHED (not orphaned) — mutate the `return` to `pass; return` and confirm test still triggers. Re-grep `energy_envoy_status` for zero `.state` decision consumers.
- **Review C — new surface / test authority + helper HOME correctness.** Every new const round-trips via `energy_const.py`; every test drives production code (no INSERT/monkeypatch shortcuts); discriminating tests actually discriminate (Rev-4 anchor: D2-A `_soc_source_last`-not-value assertion; D4-D producer+consumer joint mutation). Verify module-level `_state_age_s` import from `sensor.py` and `energy_billing.py` does not create a circular import (energy_battery has no upward deps on either). **Rev 4:** verify D-OBS tile staged via `ha_config_set_dashboard` (`write_committed:true, post_write_verified:true`); tile entity_id matches LIVE `ha_get_entity` lookup; the `unconfigured_sources` vs `stale_sources` split rendered distinctly (icon/color).
- **Review D — Live Validation, post-restart.** Recorder queries pinned in D6 run pre/post. `soc_resolution.attributes.primary_age_s` observed over 6 h — zero decision-path ticks where `source_last == "envoy"` AND `primary_age_s > 300`. **Rev 4:** during any observed stale window, verify `_paused_by_battery_drain` and `_paused_by_grid_cap` sets are HELD (not emptied); `_grid_import_guard_triggered` observed True in the same window (diagnostic). `envoy_status.stale_sources`, `unconfigured_sources`, `stale_reason` populated correctly on both dashboards. README `Validated <date>` table written back.

---

## Files to change

- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` — module-level `_state_age_s` helper (D1); `BatteryStrategy` wrappers `_read_fresh_power_w`/`_read_fresh_float` (D1); migrate 4 SOC + 2 envelope + 3 power sites (D2/D3/D4-A/D4-D producer); fold A1 gate (D5-1) and cloud-oracle-lag D2 age tracker (D5-2, Rev-4 MEDIUM-6); `_grid_import_guard_triggered` fail-CLOSED (D4-H); `primary_age_s` attribute on soc_resolution sensor surface.
- `custom_components/universal_room_automation/domain_coordinators/energy_pool.py` — fold 2 gates (D5-3, D5-4).
- `custom_components/universal_room_automation/domain_coordinators/energy.py` — D4-B fail-safe grid-cap (`:6071`); D4-C NULL persisted row (`:3129-3130`); D4-D-1/D4-D-2 fail-CLOSED at drain call sites (`:6161`, `:6317`); D4-F cache-save gating (`:2455`); D4-G sustained-window drain (`:7381`).
- `custom_components/universal_room_automation/domain_coordinators/energy_billing.py` — D4-E fresh-read migration for both branches in `CostTracker._get_net_power`; import `_state_age_s` from `.energy_battery`.
- `custom_components/universal_room_automation/sensor.py` — fold 1 display gate (D5-5); import `_state_age_s` from `.domain_coordinators.energy_battery`; expose `primary_age_s` on soc_resolution sensor; D-OBS extend `EnergyEnvoyStatusSensor.extra_state_attributes` with 6 attrs (Rev-4 split incl. `unconfigured_sources`, `missing_sources`, `stale_reason`); extend `native_value` per-source stale union.
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py` — 4 new `DEFAULT_*_MAX_AGE_S` constants with rationale comments.
- `quality/tests/` — new module `test_shared_power_read_staleness.py` covering D1-D5 + D-OBS (all Rev-4 anchor tests).
- **D-OBS (applied at deploy, not built):** `ura-v8` and `ura-v6` Lovelace dashboards via `ha_config_set_dashboard`. No repo file.
- `docs/readmes/README_v<next>.md` — pre-deploy prospective + post-restart validation table (include D-OBS tile-render row on BOTH v6 and v8, PLUS the D4-D drain-held-during-stale window row, PLUS the D4-H breaker-triggered-during-stale window row).

## Risks & mitigations

- **Test-file collision** — worktree isolation + serialised suite runs.
- **`.pyc` staleness during mutation drills** — `PYTHONDONTWRITEBYTECODE=1` + `find … -name __pycache__ -delete` before each drill.
- **Silent threshold drift** — Review A explicit checklist to diff all preserved constants pre/post.
- **Billing regression (D4-E)** — boot-time INFO summary of `_cost_today`/`_import_kwh_today` for first 24 h; Review D compares.
- **Rev-4 partial-ship hazard.** If D4-A ships without D4-D-1/D4-D-2 or without D4-H, the SAFETY DIRECTION of the drain guard AND the breaker guard silently disarm during stale windows. Mitigation: single-diff gate (Review B); the mutation-anchor `test_drain_producer_gate_without_call_site_fail_close_regresses` catches split-shipping.
- **D-OBS state-enum expansion** — grep-verified zero decision consumers today; Review B re-grep at review time; `stale_reason` attribute names the trigger.
- **D-OBS attribute drift** — reconciliation-through-shared-helper invariant + cross-comment on both call sites.
- **D-OBS tile-staleness** — entities card preferred; markdown wrapper requires `entity_id:` watch-list.

## Open questions for operator (not blocking planning)

- `hvac_override.py:3962` (5th AC-kWh gate) — fold in a follow-up cycle or flip fail-OPEN behavior first?
- AC-kWh `native_value` staleness gate — card, or leave the display sensor alone?
- Sequential ~600 s stale-trust horizon for primary SOC — keep (default), or lower `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S` / `DEFAULT_SOC_LKG_MAX_AGE_S`?
- Rev-4 D5 site 1: preserve v5.17.5 fail-OPEN-on-missing-stamp (planned default) or open a follow-up cycle to flip it to fail-CLOSED with review?
- D-OBS: tile section placement per dashboard — builder picks at apply time (default) or operator preference?
- Rev-4 `AGGREGATION_NET_POWER_STALE_1` and `BATTERY_POWER_W_CONSUMERS_AUDIT_1` — schedule immediately after this cycle or backlog?

---

## Rev 4 change summary (2026-09-01)

Applied per adversarial plan-review FIX-REQUIRED (all items verified against source before rewrite):

1. **CRITICAL-1 (D4-D drain-consumer fail-OPEN)** — added D4-D-1 and D4-D-2 paired call-site fail-CLOSED changes at `energy.py:6161` and `:6317`; joint mutation anchor test proves producer + consumer must ship together; explicit CONSUMER × None-direction table row for `battery_power_w`.
2. **CRITICAL-2 (net_power consumer enumeration incomplete)** — CONSUMER × None-direction table added with EIGHT `net_power_w` consumers listed; D4-G (load-shed sustained-window drain at `energy.py:7381`) and D4-H (`_grid_import_guard_triggered` fail-CLOSED at `energy_battery.py:2635-2646`) added as MANDATORY paired fixes; single-diff gate in Review B prevents D4-A shipping alone; unlisted consumers (`aggregation.py`, `energy_write_verify.py`, `energy_forecast.py`) carded as out-of-scope.
3. **HIGH-3 (D5 cloud-SOC fold silently flips fail-OPEN→fail-closed on a trust path)** — D5 site 1 (`energy_battery.py:882-910`) now specifies EXPLICIT mapping `age is None → pass (accept)` preserving v5.17.5 semantics; anchor test `test_cloud_soc_fold_preserves_fail_open_on_missing_stamp`; a future flip requires its own cycle.
4. **HIGH-4 (D-OBS `stale_sources` marks UNCONFIGURED sources stale)** — D-OBS-1 rewritten with `_resolve_source_age → (age, status)` returning one of `{unconfigured, missing, fresh, stale}`; three separate attributes (`stale_sources`, `unconfigured_sources`, `missing_sources`); only `stale_sources` drives the state-enum transition; regression anchor `test_envoy_status_unconfigured_net_power_does_not_pin_stale`.
5. **MEDIUM-5 (class names wrong)** — corrected throughout: `class BatteryStrategy` (`energy_battery.py:307`), `class CostTracker` (`energy_billing.py:92`), `class PeakAvoidanceTracker` (`energy_billing.py:457`); no `EnergyBatteryCoordinator`/`EnergyBillingCoordinator` in the codebase (grep-verified). Helper HOME decided: **module-level `_state_age_s` in `energy_battery.py`** imported by `sensor.py` + `energy_billing.py`; `BatteryStrategy` retains wrappers `_read_fresh_power_w`/`_read_fresh_float` for its own sites.
6. **MEDIUM-6 (6th in-family gate missed + missing negative clamp)** — added D5 site 2 (`energy_battery.py:1136-1150` cloud-oracle lag); pulled the shipped `max(0.0, (now - lu).total_seconds())` negative clamp INTO `_state_age_s` itself with anchor `test_state_age_s_negative_stamp_clamps_to_zero`.
7. **MEDIUM-7 (`save_envoy_cache` raw ungated writes)** — added D4-F: gate the whole call on `self._battery._soc_source_last == "envoy"` (in addition to existing `soc is None` check); reuses D2-A state; three anchor tests.
8. **MEDIUM-8 (D5 sensor.py:12494 rationale factually wrong)** — corrected: current site has NO `try/except`, exception PROPAGATES out of the attributes property; new helper-fail-closed behavior (`stale = True`) is strictly BETTER, not "net observable identical". Anchor test renamed `test_ac_kwh_naive_stamp_renders_stale_true_no_exception`.
9. **LOW-9 (D2-A discriminator)** — added Bug Class #63 note: LKG value can numerically equal primary when frozen; the discriminator MUST be `_soc_source_last`, not the value; anchor `test_primary_soc_stale_discriminator_is_source_not_value`.
10. **LOW-10 (reconciliation reverse case)** — `stale_reason` attribute added to distinguish `"per_source" | "last_available" | "consumption_anomaly" | "unavailable_count"`; anchor `test_envoy_status_stale_reason_last_available_only`.

Invariant re-verification with the per-consumer fail-direction clause: producer-only migration provably regresses two safety guards (drain, breaker) into silently-disarmed mode — the discriminating anchor `test_drain_producer_gate_without_call_site_fail_close_regresses` FAILS the producer-only build and PASSES the paired build. Invariant holds.

---

## Rev 3 addition summary (retained, 2026-09-01)

(Rev-3 summary preserved verbatim from prior revision — D-OBS added as ADDITIVE deliverable extending existing `envoy_status` sensor; Lovelace tile on `ura-v8` + `ura-v6` via `ha_config_set_dashboard`; NO parallel sensor, NO NM push, NO PWA tile change. Rev-4 HIGH-4 fix corrects the `stale_sources` computation; D-OBS-2 union derivation and D-OBS-3 tile shape otherwise unchanged.)

---

## Rev 2 fix summary (retained, 2026-09-01)

(Rev-2 summary preserved from prior revision — `stamp=` arg + `last_reported` fallback; D3-B, D2 4-site expansion, D4-B/C/E, LKG stamp arithmetic correction, 5th AC-kWh gate scope-carded, D5 sensor.py byte-identity claim corrected, D6 pinned queries. Rev-4 supersedes MEDIUM-5, MEDIUM-6, and MEDIUM-8 corrections; other Rev-2 fixes stand.)
