# PLANNING — Shared Power-Read Staleness Helper (ENVOY-PRODUCTION-STALE-1)

**Card:** `ENVOY-PRODUCTION-STALE-1` (consolidated per operator 2026-08-31).
**Rev:** 5 (2026-09-01) — §BUILD-READY. Rev-5 confirm-review = SHIP. Two plan-text defects fixed in-place (MEDIUM-1 contradictory pause-direction wording; MEDIUM-2 unimplementable "hoist" instruction) + two minor clarifications (site A fall-through vs literal `else`; site B is SOLE compensator, no upstream `_breaker_guard_fail_closed_on_blind`). Neither text fix changes the shipped design; both prevent a builder coin-flip on a safety axis.

Rev-5 corrections applied to the four Rev-4 findings (all verified against source before rewrite; all confirmed genuinely resolved with no new fail-OPEN):

> - **Rev-5 CRIT-A** — Rev-4 D4-H patched DEAD code (`_grid_import_guard_triggered` at `energy_battery.py:2635-2646` has ZERO callers; grep-verified only the def + stale comment refs at `:519` and `:4829`). The LIVE 12 kW breaker guard is THREE inline sites: `energy_battery.py:3150-3197`, `:4523-4547`, `:4680-4703` — each shaped `if snap is not None and snap[0] > self._arbitrage_grid_import_guard_kw:` (the exact fail-OPEN shape after D4-A). D4-H re-scoped; dead helper disposed per supersession rules.
> - **Rev-5 CRIT-B** — same three sites' streak-reset paths (`energy_battery.py:3196` — fall-through, not literal `else`; `:4547` — literal `else`; `:4703` — literal `else`) silently WIPE an accumulated trip streak on a one-tick stale gap. D4-H specifies HOLD-not-reset on `snap is None`.
> - **Rev-5 HIGH-C** — Rev-4 D4-D-1/D4-D-2 over-scoped: skipping the entire `determine_battery_drain_actions(...)` call would also skip its RELEASES (force-charge at `energy_pool.py:2147-2150` EVSE and `:3723-3726` plugs; `must_start_by_min` L1 hard release at `energy.py:6329-6331` — "the ONLY hard release the operator's L1 charger gets"). Rev-5 splits pause-evaluation from release-evaluation via a `battery_power_unknown=True` flag; the release arms are already reachable because `battery_discharging` is False under a None read.
> - **Rev-5 MED-D** — Rev-4 D-OBS `_resolve_source_age` pseudocode used CONF_* constants but `_get_entity(key)` at `energy_battery.py:719` expects SHORT names per the key_map at `energy.py:986-996` (`"net_power"`, `"battery_power"`, `"solar_production"`, `"battery_soc"`). Fixed to short names.

Rev 3 D-OBS retained (with MED-D fix); Rev 4 producer/consumer table retained (with the streak-wipe row added and D4-H re-scoped).

**Tier:** **2-DB** (regression-prone, cross-coordinator ripple: energy_battery → energy_pool → EVSE + DP + NM + billing; shared primitive; folds together six hand-rolled gates whose thresholds MUST be preserved byte-for-byte on the fresh path).
**Mode:** §BUILD-READY. Build may dispatch.

**Falsifiable invariant (state up front — Rev 5):**
> For every trust-decision-consuming power/SOC read in the Energy family, a numeric HA state whose **`last_reported`** stamp (falling back to `last_updated` when the platform did not populate `last_reported`) is older than the site's configured `MAX_AGE_S` MUST be treated as **absent** (helper returns `None`) AND EACH CONSUMER of that value MUST route to a **fail-SAFE** fallback that preserves the SAFETY DIRECTION of the guard it participates in — the drain-pause set is HELD **while releases still evaluate**, the breaker guard TRIPS **and its consecutive-trip streak HOLDS**, the load-shed sustained window is drained (no stitched-run false escalation), the billing tick is SKIPPED, the persisted analytics column is NULL (never `0`). On the fresh path (age ≤ MAX_AGE_S, valid unit, in-range) the returned value MUST be **byte-identical** to today's read.
>
> Why `last_reported`, not `last_updated`: HA advances `last_reported` on every re-publish (even when the value did not change), but only advances `last_updated` on a value change. A healthy sensor pinned at 0 W (solar at night) or a constant-valued sensor would therefore be judged stale under `last_updated`. Same reason the existing grid solar-follow gate at `energy_pool.py:4406-4413` (INV-SF-10) uses `last_reported`. Any migrated site is INDIVIDUALLY specified below to preserve its current stamp choice — see D5.
>
> Rev-5 refinement of the per-consumer clause: **safety-guard side-effects (pause SETS and streak COUNTERS) MUST be treated as separate axes from the guard's Boolean output.** Producer-only gating that inadvertently WIPES a pause set (Rev-4 HIGH-C) or WIPES a streak counter (Rev-4 CRIT-B) silently disarms the guard just as much as returning False. **A blind CT MUST NOT ARM a new pause either — only HOLD an existing one** — because arming on a blind CT would fight the release path (force-charge, must_start_by) and risk stranding the operator's L1 EV overnight. The invariant covers all three axes: Boolean, pause-set membership, streak counter.

---

## Institutional context verified

### Design/rules read
- `CLAUDE.md` — Tier 2-DB triggers; Producer/Consumer rule; "Numbers get knobs" ladder; "Coincidental equality masks a concept split"; "Extend existing, never rebuild"; "Do the robust fix, not band-aid+card"; **"Post-Ship Supersession & Consumer-Gap Audit"** (applied to `_grid_import_guard_triggered` in D4-H).
- `docs/QUALITY_CONTEXT.md` — Bug class **#7 stale data source** + **#63 coincidental equality masks a concept split**.
- `docs/Coordinator/ENERGY_COORDINATOR_MANUAL.md` §2.5a — reserve verifiable backout knob (MAX_AGE_S=0 fire-axe).

### Prior planning / memory pulled
- Memo `reference_ec_reserve_verifiable_backout_knob` — fire-axe precedent.
- Memo `feedback_coincidental_equality_masks_concept_split` — LKG numeric == primary when frozen; D2-A discriminator MUST be `_soc_source_last`, not value.
- Memo `feedback_do_robust_fix_not_bandaid_and_card`.
- Memo `feedback_read_consumers_before_asserting_function` — the load-bearing memory this whole cycle's Consumer × None-direction table honors.
- v5.17.5 A1 review record — `DEFAULT_SOC_CLOUD_FALLBACK_MAX_AGE_S=600` (`energy_battery.py:882-910`); the `except` branch at `:907-910` explicitly ACCEPTS on missing/naive `last_updated` ("let unit + range checks decide") — a fail-OPEN branch D5 preserves.
- v4.5.0 unit-consistency sweep — `_read_power_w` template.
- Rev 3: `docs/dashboards/ura_v6_v8_solar_aware_ev_and_census_cards.md`.

### Producer AND Consumer surveyed (re-verified by grep 2026-09-01, Rev-5 line numbers corrected)

**Class-name correction (Rev 4 preserved).** `class BatteryStrategy` at `energy_battery.py:307`; `class CostTracker` at `energy_billing.py:92`; `class PeakAvoidanceTracker` at `energy_billing.py:457`. No `EnergyBatteryCoordinator`/`EnergyBillingCoordinator` classes exist.

**Helper HOME decision (Rev 4 preserved).** `_state_age_s` is a **module-level function in `energy_battery.py`** (top of file, after imports); `BatteryStrategy` gets thin instance-method wrappers `_read_fresh_power_w` / `_read_fresh_float`; `sensor.py` and `energy_billing.py` import `_state_age_s` directly.

**PRODUCER table — sites this cycle gates:**

| # | Site (producer) | file:line | Current reject | Fallback that engages when helper returns `None` |
|---|---|---|---|---|
| 1 | `_read_power_w("solar_production")` via `solar_production_w` | `energy_battery.py:1572-1596`, called at `:1614` | unknown/unavailable only | `solar_production_w_envelope()` at `:2287` — entry check at `:2330` also gated (D3). |
| 2 | `_read_power_w("net_power")` via `net_power_w` | `energy_battery.py:1628-1636` | unknown/unavailable only | expanded Consumer table + per-consumer fail-CLOSED specs (D4). |
| 3 | `battery_power_w` inline | `energy_battery.py:1546-1570` | unknown/unavailable only | drain-protection consumers currently fail-OPEN on `None`; D4-D REQUIRES paired call-site **pause/release split** at `energy.py:6161` AND `:6317` before the producer gate ships. |
| 4 | PRIMARY `battery_soc` via `_get_state_float(self._get_entity("battery_soc"))` | 4 CALL SITES — D2 | unknown/unavailable only | three-tier resolver (LKG → cloud) at `:838-921` for site A only; sites B/D migrated; site C classified. |

**LKG-stamp arithmetic note (Rev 2 preserved).** LKG re-stamped at READ time (`:830-832`); aggregate blindness under a frozen primary is **sequential**: up to `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S` + up to `DEFAULT_SOC_LKG_MAX_AGE_S` before cloud engages.

---

### CONSUMER × None-direction table (Rev 5, MEDIUM-1 wording fix applied)

Every migrated producer's DOWNSTREAM sites, with SHIPPED None behavior today (fail-open = safety guard disarms; fail-closed = safety guard engages / conservative fallback) and REQUIRED post-cycle behavior. **Safety guards MUST be fail-CLOSED, side-effects included** — Boolean output, pause-set membership, AND streak counter.

#### `battery_power_w` consumers

| # | Consumer | file:line | Trust vs display | None today | Required post-cycle | Rev-5 mechanism |
|---|---|---|---|---|---|---|
| 1 | EVSE drain gate — plugs | `energy_pool.py:2207-2209` (`is not None and < -100`) | trust (drain pause) | **fail-OPEN** — `discharging=False` → drain pause never fires | **HOLD existing pauses; do NOT arm new ones under unknown** (deliberate — arming on a blind CT contradicts the release path and risks stranding). Releases (force-charge, must_start_by) STILL evaluate. | D4-D-1: pass `battery_power_unknown=True` to `determine_battery_drain_actions`; force-charge release at `:2147-2150` still evaluates; pause-add condition inside the function gated on `not battery_power_unknown`. |
| 2 | EVSE drain gate — smart plugs | `energy_pool.py:3711-3713` (identical shape) | trust (drain pause) | **fail-OPEN** | same — HOLD existing, do NOT arm new, releases EVALUATE | D4-D-2: mirror at `energy.py:6317`; force-charge release at `energy_pool.py:3723-3726` still evaluates; `must_start_by_min` L1 release at `energy.py:6329-6331` still evaluates. |
| 3 | `_effective_import_kw` (breaker math) | `energy_battery.py:2600-2633` (`batt_w=None → 0`, does not subtract) | trust (breaker guard math) | **fail-CLOSED already** — treating batt charge as 0 makes effective_import ≥ net, guard trips MORE easily. Documented at `:2623-2625`. | unchanged | none — preserve. |
| 4 | Envoy restart cache write | `energy.py:2455-2460` (writes raw `.battery_power` prop) | display / restart seed | writes frozen prop | gate on `_soc_source_last == "envoy"` | D4-F. |
| 5 | Write-verifier / forecast reads | `energy_write_verify.py:1794`, `energy_forecast.py:566` | trust | not investigated | out of scope — CARDED `BATTERY_POWER_W_CONSUMERS_AUDIT_1` | non-goal. |

**Sign-flip note:** `battery_power_w` is signed. `is None` short-circuit runs before any threshold comparison.

**One-voice pause-direction contract (MEDIUM-1 corrective, load-bearing):** the table above, the D4-D-0 spec below, and the D4-D acceptance tests all say the SAME thing: under `battery_power_unknown=True`, **existing membership in `_paused_by_battery_drain` is preserved (HOLD)** AND **no new pause is added (do NOT arm)** AND **all release branches evaluate normally**. Any wording elsewhere in this doc that reads as "arm a pause on unknown" is a defect — treat this bullet as authoritative.

#### `net_power_w` consumers

| # | Consumer | file:line | Trust vs display | None today | Required post-cycle | Rev-5 mechanism |
|---|---|---|---|---|---|---|
| 1 | EVSE grid-cap | `energy.py:6071` (`or 0 / 1000`) | trust (pause/resume EVSE) | **fail-OPEN** — grid ≈ 0 kW, resumes paused EVSEs | fail-CLOSED — HOLD `_paused_by_grid_cap` | D4-B. |
| 2 | Persisted analytics row | `energy.py:3129-3130` (`or 0`) | trust (writes DB) | writes false 0 | NULL propagation | D4-C. |
| 3 | Load-shed sustained-window | `energy.py:7381-7387` (`snap is None: return`) | trust (SHED escalation) | **fail-OPEN by early-return + deque frozen** → stitched-run false escalation on trailing edge | fail-CLOSED — `_sustained_import_readings.clear()` + return; keep existing shed set intact | D4-G. |
| 4 | Breaker guard inline site A — `_reevaluate_arbitrage` CHARGE-phase | `energy_battery.py:3150-3197` | trust (breaker trip → chunk lock) | **fail-OPEN**: `if snap is not None and snap[0] > cap` → None falls through to `:3196` (both inner branches return, so `:3196` is reached by FALL-THROUGH not by a literal `else`); guard does NOT trip AND `_arbitrage_guard_consecutive_trips = 0` (wipes streak) | fail-CLOSED — treat None as "assume over-cap" (increment streak, honor `ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK`); do NOT reset the streak on None | D4-H-1 (Rev-5). |
| 5 | Breaker guard inline site B — attainability `_get_attain_action_charging` | `energy_battery.py:4523-4547` | trust | **fail-OPEN + streak wipe** (`else` at `:4547` resets streak). **No upstream `_breaker_guard_fail_closed_on_blind` compensator at this site** (unlike site C at `:4676`) — D4-H-2 is the SOLE compensator here; do not assume symmetry with site C. | fail-CLOSED — same | D4-H-2. |
| 6 | Breaker guard inline site C — attainability `_get_attain_action_entry` | `energy_battery.py:4680-4703` | trust | **fail-OPEN + streak wipe** (`else` at `:4703` resets streak). Upstream `_breaker_guard_fail_closed_on_blind("attain_entry")` at `:4676` covers `_degraded_telemetry_source` ONLY — a value-pinned local CT bypasses it, so this site's inline check is the last line of defense on the LOCAL-stale path. | fail-CLOSED — same | D4-H-3. |
| 7 | Streak-wipe cross-site invariant | `_arbitrage_guard_consecutive_trips` reset at `:3196` (fall-through), `:4547` (`else`), `:4703` (`else`) | trust (2-tick lock latch) | one-tick stale gap alternating with over-import → streak never reaches 2 → guard never locks the chunk | on `snap is None`, HOLD the streak (do NOT reset); only reset on a genuine under-cap fresh read | D4-H covers all three (single change per site). |
| 8 | Billing accumulate (direct grid) | `energy_billing.py:152-170` | trust (dollars) | fail-open on frozen-valid CT | fail-CLOSED — skip tick | D4-E. |
| 9 | Billing accumulate (fallback) | `energy_billing.py:178-190` | trust (dollars) | fail-open on frozen-valid | fail-CLOSED — skip tick | D4-E. |
| 10 | Aggregation reads | `aggregation.py:6289`, `:6319` | trust — pending re-verification | out of scope | CARDED `AGGREGATION_NET_POWER_STALE_1` | non-goal. |
| 11 | Sensor exposure | `sensor.py:8690`, `:11538` | display | display-only | unchanged | none. |

**Rev-5 CRIT-A supersession disposition of `_grid_import_guard_triggered` (`energy_battery.py:2635-2646`):** grep across `custom_components/` returned three hits — the def itself, `:519` (stale comment referencing "`_grid_import_guard_triggered()` + 3 inline sites"), `:4829` (stale comment inside `_breaker_guard_fail_closed_on_blind`). ZERO real callers. Triage:

- **DELETE** candidate — dead AND buggy (returns False on the very None case the LIVE guards must trip on) AND a footgun. Deletion posture: DELETE **after** D4-H ships and post-restart live-validation confirms the three inline sites are fail-CLOSED (per CLAUDE.md "only delete after new path is live-validated"). Rev-5 does NOT delete pre-ship; deletion PR follows Live Validation.
- The `:519` and `:4829` stale comments are updated in-cycle to reference the inline sites only (dead-comment cleanup, safe in-cycle).

#### `solar_production_w` consumers

Trust consumers at `energy.py:3229/:3404/:3557` accept `None` via existing None-safe strategy math. Envelope entry at `energy_battery.py:2330` addressed by D3-B. Persisted row at `energy.py:3126` already None-safe.

#### `battery_soc` consumers

Resolver (D2-A) collapses tiers; downstream sees the tiered result (None only when ALL tiers fail — existing blind-hold branch handles).

---

### 5th AC-kWh gate (Rev-2 preserved)

`hvac_override.py:3962` — non-goal; carded `HVAC-OVERRIDE-KWH-STALE-FAIL-OPEN-1`.

### Consumer-check finding (unchanged)

`sensor.ura_energy_envoy_status.stale` DISPLAY-ONLY (grep Rev 4 re-verified: three self-references only). Extending is display-safe.

### Grep prior-art results for proposed additions
- `_state_age_s` / `state_age_s` / `read_fresh` / `_read_state_fresh` — **NEW** module-level function in `energy_battery.py`.
- `DEFAULT_SOLAR_PRODUCTION_MAX_AGE_S`, `DEFAULT_NET_POWER_MAX_AGE_S`, `DEFAULT_BATTERY_POWER_MAX_AGE_S`, `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S` — **NEW**, rung 1.
- `battery_power_unknown` kwarg on `determine_battery_drain_actions` — **NEW** (Rev-5). Two call sites (`energy.py:6161`, `:6317`); no prior art; default False (fresh-path byte-identity).
- Rev-3/4: `sensor.ura_energy_coordinator_envoy_status` — **REUSED** (extended).
- Rev-3/4: `solar_age_s`, `net_power_age_s`, `battery_power_age_s`, `primary_soc_age_s`, `stale_sources`, `unconfigured_sources`, `missing_sources`, `stale_reason`, `fallback_active` — **NEW attributes**.

### Code locations surveyed end-to-end (Rev-5 line numbers)
- `energy_battery.py:307` (`class BatteryStrategy`), `:719-735` (`_get_entity` — short-name key), `:770-925` (SOC resolver + A1 gate at `:882-910`, `except` at `:907-910`), `:830-832` (LKG stamp), `:1130-1155` (6th gate — cloud-oracle lag with `max(0.0,…)` clamp at `:1149`), `:1530-1636` (power readers), `:2225-2320` (envelope entry checks), `:2440-2461` (`envoy_available`), `:2600-2633` (`_effective_import_kw`), **`:2635-2646` (`_grid_import_guard_triggered` — DEAD, disposition per D4-H)**, `:3150-3197` (LIVE breaker guard site A + streak-wipe-by-fall-through at `:3196`), `:3365-3370` (`_breaker_guard_fail_closed_on_blind` — scope-limited compensator, applies to site C only), `:4144` (streak reset — separate context, out of scope), `:4523-4547` (LIVE breaker guard site B + streak-wipe-in-`else` at `:4547`; NO upstream compensator), `:4680-4703` (LIVE breaker guard site C + streak-wipe-in-`else` at `:4703`; upstream compensator at `:4676`), `:6080-6100` (soc_resolution diagnostics).
- `energy.py:986-996` (key_map — SHORT names, MED-D corrective), `:2450-2460` (save_envoy_cache — D4-F), `:3115-3140` (persisted analytics), `:3225-3560` (solar strategy), `:6055-6090` (EVSE grid-cap — D4-B), `:6150-6165` and `:6310-6335` (drain-actions call sites — D4-D targets; `:6329-6331` `must_start_by_min` L1 release), `:7370-7400` (load-shed — D4-G).
- `energy_billing.py:92` (`class CostTracker`), `:144-191` (`_get_net_power` — D4-E), `:457` (`class PeakAvoidanceTracker`).
- `energy_pool.py:2140-2225` (EVSE drain — force-charge release at `:2147-2150`; pause-add condition on `battery_discharging` at `:2228-2243`), `:3705-3735` (plug drain — force-charge release at `:3723-3726`), `:3797` (plug variant pause-add condition on `battery_discharging`), `:3815` (`battery_ok = not battery_discharging`), `:4395-4417` (grid-follow), `:4685-4710` (per-bay solar power).
- `energy_const.py:300-340`, `:960-985`.
- `sensor.py:12480-12515` — AC-kWh display gate.
- `sensor.py:13293-13444` — `EnergyEnvoyStatusSensor`.

---

## Deliverables

### D1 — Add the shared helper (single source of truth)

Add a **module-level function** in `energy_battery.py` (top of file, after imports):

```python
def _state_age_s(state, *, stamp: str = "last_reported") -> float | None:
    """Return the age in seconds of `state` measured against `stamp`,
    falling back to `last_updated` if the chosen stamp is absent.
    Returns None if state is missing, both stamps absent, or the chosen
    stamp is naive (fail-closed per CF-8 precedent at
    energy_pool.py:4402-4409).

    Rev-4 (MEDIUM-6): negative ages clamped to 0.0 to defend against
    clock skew or future-stamped inputs, matching the shipped clamp at
    energy_battery.py:1149.
    """
```

Plus two thin `BatteryStrategy` instance-method wrappers:

- `_read_fresh_power_w(entity_key, max_age_s, *, stamp="last_reported") -> float | None`
- `_read_fresh_float(entity_id, max_age_s, *, stamp="last_reported") -> float | None`

`sensor.py` and `energy_billing.py` import `_state_age_s` directly from `.domain_coordinators.energy_battery`.

**Stamp choice per NEW gate:** solar / net / battery_power / primary_soc → `last_reported`.

#### Acceptance
- **Verify:** helper importable; no site calls it yet.
- **Test:** `test_state_age_s_missing_naive_fresh_stale`.
- **Test:** `test_state_age_s_prefers_last_reported_falls_to_last_updated`.
- **Test:** `test_state_age_s_negative_stamp_clamps_to_zero`.
- **Test:** `test_read_fresh_constant_valued_sensor_is_fresh`.
- **Test:** `test_read_fresh_power_w_unit_scaling_preserved`.

### D2 — Migrate PRIMARY `battery_soc` — ALL FOUR SITES

Unchanged from Rev 4 (A `:828`, B `:2242`, C `:2455` KEEP-raw, D `:6091` migrate).

**Const:** `DEFAULT_BATTERY_SOC_PRIMARY_MAX_AGE_S: Final = 300`.

**Bug Class #63 discriminator:** D2-A tests anchor on `_soc_source_last`, not value. `test_primary_soc_stale_discriminator_is_source_not_value`.

**`primary_age_s` attribute** on `soc_resolution` sensor — Rev-2 preserved.

#### Acceptance (D2)
- (Rev-3 tests preserved + Rev-4 discriminator anchor.)
- **Live:** `soc_resolution.primary_age_s` 6h — zero ticks `source_last == "envoy"` AND `primary_age_s > 300`.

### D3 — Migrate `solar_production_w` — BOTH producer AND envelope entry check

Unchanged from Rev 3 (D3-A `:1614`, D3-B `:2330`).

### D4 — Migrate `net_power_w`, inline `battery_power_w`, billing `_get_net_power`, PAIRED call-site fixes

**D4-A — `energy_battery.py:1636` net_power_w producer.** Migrate to `self._read_fresh_power_w("net_power", DEFAULT_NET_POWER_MAX_AGE_S, stamp="last_reported")`. **New const** `DEFAULT_NET_POWER_MAX_AGE_S: Final = 180`.

**Single-diff gate:** D4-A MUST ship in the same commit as D4-B, D4-C, D4-E, D4-G, **and all three sub-sites of D4-H** (`energy_battery.py:3150-3197`, `:4523-4547`, `:4680-4703`). Reviewer B enforces via single-diff check.

**D4-B — grid-cap consumer at `energy.py:6071` — fail-SAFE HOLD `_paused_by_grid_cap` (unchanged from Rev 2/3/4).**

**D4-C — persisted analytics `grid_import_kw` / `solar_export_kw` (`energy.py:3129-3130`) — NULL propagation (unchanged).**

**D4-D — `battery_power_w` inline refactor + PAIRED call-site pause/RELEASE split (Rev-5).**

Producer (`energy_battery.py:1546-1570`): route through `_read_fresh_power_w("battery_power", DEFAULT_BATTERY_POWER_MAX_AGE_S, stamp="last_reported")` with sign-flip at the call site. **New const** `DEFAULT_BATTERY_POWER_MAX_AGE_S: Final = 180`. Display prop at `:1530` unchanged.

**D4-D-0 (Rev-5, MEDIUM-2 corrective): extend `determine_battery_drain_actions` signature** in `energy_pool.py` (both EVSE variant and plug variant). Add ONE kwarg:

```python
def determine_battery_drain_actions(
    self,
    *,
    battery_power_w: float | None,
    battery_soc: float | None,
    soc_threshold: int,
    reserve_soc: int | None,
    force_charge_active: bool,
    solar_replenishing: bool,
    is_offpeak: bool,
    dp_forcing: bool = False,
    now_local=None,
    must_start_by_min: int | None = None,
    battery_power_unknown: bool = False,   # NEW Rev-5
) -> list[dict]:
    """... battery_power_unknown=True means the CT read was rejected as
    stale. Under this flag: RELEASE branches (force_charge, must_start_by,
    DP-forcing) evaluate normally; PAUSE-add conditions are gated
    (existing memberships HOLD; no NEW pause is armed). Default False
    preserves fresh-path byte-identity."""
```

**No structural hoisting** required. In the plug variant `battery_discharging` is computed at `energy_pool.py:3711` **above** the entity loop, and the `must_start_by_min` release path sits in the `elif` arm that depends on `battery_discharging` transitively via `battery_ok = not battery_discharging` at `:3815` — release arms are already reachable under a None read because the current shape yields `battery_discharging = False`, which is precisely why HIGH-C verified as resolved in outcome. The Rev-5 change is surgical:

- **Gate ONLY the pause-add conditions on `not battery_power_unknown`:**
  - EVSE variant: `energy_pool.py:2228-2243` (the block that adds `evse_id` to `_paused_by_battery_drain`) — extend the guarding predicate with `and not battery_power_unknown`.
  - Plug variant: `energy_pool.py:3797` (the corresponding pause-add block) — extend the guarding predicate with `and not battery_power_unknown`.

That is the entire structural change. Release arms are untouched. The force-charge release at `:2147-2150` / `:3723-3726` and the `must_start_by_min` L1 hard release evaluate exactly as they do today, because `battery_discharging` becomes False under a None read and the release paths already handle that case.

**D4-D-1: call site at `energy.py:6161` — EVSE drain call.**

```python
_bp = self._battery.battery_power_w
drain_actions = self._ev.determine_battery_drain_actions(
    battery_power_w=_bp,
    battery_soc=self._battery.battery_soc,
    soc_threshold=self._ev_battery_drain_soc,
    ...
    battery_power_unknown=(_bp is None),   # NEW Rev-5
)
```

**D4-D-2: call site at `energy.py:6317` — smart-plug drain call.** Mirror; `must_start_by_min=self._dp_must_start_by_min` is already passed and MUST still be honored under `battery_power_unknown=True` (the operator's L1 3am release).

**Tests (Rev-5):**
- `test_drain_stale_battery_power_holds_pause_set_evse` — bay in `_paused_by_battery_drain`, `battery_power_w = None` for 5 ticks, membership persists.
- `test_drain_stale_battery_power_holds_pause_set_plugs` — mirror for plugs.
- `test_drain_stale_battery_power_does_not_arm_new_pause` (MEDIUM-1 wording anchor) — bay NOT in `_paused_by_battery_drain`, `battery_power_w = None`, SOC below threshold, off-peak → membership REMAINS empty (no new arm). Confirms the "HOLD, do NOT arm" contract distinct from a fail-CLOSED-arm interpretation.
- `test_drain_stale_battery_power_still_honors_force_charge_release` — plug in `_paused_by_battery_drain`, `battery_power_w = None`, `force_charge_active = True` → membership CLEARED despite stale CT.
- `test_drain_stale_battery_power_still_honors_must_start_by` — L1 socket in `_paused_by_battery_drain`, `battery_power_w = None` for 6 hours, wall-clock crosses `must_start_by_min` → membership CLEARED despite persistently dead CT. **Anti-strand test.**
- `test_drain_producer_gate_without_call_site_unknown_flag_regresses` (mutation anchor) — mutate D4-D-1 to omit `battery_power_unknown=(_bp is None)`; pause-hold test fails.
- `test_drain_over_scoped_skip_regresses_release` (mutation anchor) — mutate D4-D-1 to a Rev-4-shape `if _bp is None: return` guard around the whole call; `must_start_by` test fails. Confirms the pause/release SPLIT is load-bearing.

**D4-E — billing `CostTracker._get_net_power` at `energy_billing.py:144-191` — fresh-read migration for both branches (unchanged from Rev 4).** Import `_state_age_s` from `.energy_battery`.

**D4-F — Envoy restart cache write gating at `energy.py:2455-2460` (Rev-4 preserved).** Gate on `_soc_source_last == "envoy"`.

**D4-G — Load-shed sustained-window drain at `energy.py:7381-7387` (Rev-4 preserved).** `_sustained_import_readings.clear()` + return on stale snap.

**D4-H — Breaker guard fail-CLOSED at THREE inline sites (Rev-5).**

The Rev-4 target (`_grid_import_guard_triggered` at `:2635-2646`) is DEAD (see supersession disposition above). The LIVE sites are all shaped:

```python
snap = self._effective_import_kw()
if snap is not None and snap[0] > self._arbitrage_grid_import_guard_kw:
    ... increment self._arbitrage_guard_consecutive_trips ...
    ... if >= ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK: LOCK ...
# (streak reset lives at the end of the block — via literal `else`
#  at sites B/C, or via FALL-THROUGH at site A because both inner
#  branches return.)
self._arbitrage_guard_consecutive_trips = 0
```

Rev-5 canonical change (applied at all three sites, site-appropriate return values inserted):

```python
snap = self._effective_import_kw()
if snap is None:
    # Rev-5 CRIT-A/B fail-CLOSED: stale net_power (post-D4-A) →
    # treat as "assume over-cap" AND do NOT reset the streak.
    # A value-pinned local CT bypasses _breaker_guard_fail_closed_on_blind
    # (which only compensates when _degraded_telemetry_source is set;
    # a stale-but-numeric local read does not set that flag), so the
    # inline site is the last line of defense for the 12kW panel guard.
    self._arbitrage_guard_consecutive_trips += 1
    if self._arbitrage_guard_consecutive_trips >= ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK:
        from homeassistant.util import dt as dt_util
        self._arbitrage_chunk_completed = True
        self._arbitrage_guard_aborted_at = dt_util.now().isoformat()
        self._arbitrage_guard_aborted_kw = None   # sentinel: locked on stale
        _LOGGER.warning(
            "Arbitrage grid-import guard: net_power STALE — assuming "
            "over-cap; %d consecutive stale/over-cap ticks. Chunk locked.",
            self._arbitrage_guard_consecutive_trips,
        )
        return <site-appropriate locked value>
    _LOGGER.info(
        "Arbitrage grid-import guard: net_power STALE — treating as trip "
        "%d/%d; deferring one tick.",
        self._arbitrage_guard_consecutive_trips,
        ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK,
    )
    return <site-appropriate defer-one-tick value>
elif snap[0] > self._arbitrage_grid_import_guard_kw:
    ... existing over-cap branch UNCHANGED ...
else:
    # Genuine under-cap fresh read — safe to reset the streak.
    self._arbitrage_guard_consecutive_trips = 0
    ... existing under-cap continuation UNCHANGED ...
```

**D4-H-1** applies at `energy_battery.py:3150-3197` (arbitrage CHARGE-phase). **Builder note (Rev-5 clarification):** today's streak-reset at `:3196` is reached by FALL-THROUGH — the `if snap is not None and snap[0] > cap` block's inner branches both `return` (defer returns `ARBITRAGE_PHASE_CHARGE`, lock returns `ARBITRAGE_PHASE_WAIT`), so `:3196` is a bare statement after the `if`. Do NOT insert a literal `else` expecting symmetry with sites B/C. The Rev-5 replacement re-shapes the control flow into an explicit `if snap is None: ... elif snap[0] > cap: ... else: ...` with the streak-reset in the final `else` branch. Site-appropriate values: defer-one-tick returns `ARBITRAGE_PHASE_CHARGE`, locked returns `ARBITRAGE_PHASE_WAIT`.

**D4-H-2** applies at `energy_battery.py:4523-4547` (attainability `_get_attain_action_charging`). Streak-reset today is a literal `else` at `:4547`. **Builder note (Rev-5 clarification):** site B has **NO upstream `_breaker_guard_fail_closed_on_blind` compensator** — that helper protects site C at `:4676` (via `"attain_entry"` call) and is not present anywhere upstream of site B. D4-H-2 is the SOLE local-stale compensator at this site; do not assume symmetry with site C's belt-and-suspenders posture. Site-appropriate values: defer-one-tick continues (no early return); locked sets `self._attain_state = "inactive"` and returns `None`.

**D4-H-3** applies at `energy_battery.py:4680-4703` (attainability `_get_attain_action_entry`). Streak-reset today is a literal `else` at `:4703`. The upstream `_breaker_guard_fail_closed_on_blind("attain_entry")` at `:4676` remains as the DEGRADED-telemetry compensator; D4-H-3 is the LOCAL-stale compensator (disjoint conditions, both required). Site-appropriate values: defer-one-tick continues; locked returns `None`.

**`_arbitrage_guard_aborted_kw = None` sentinel:** locked-on-stale vs locked-on-measured-overdraw distinguishable in the diagnostic; add a Rev-5 note in the arbitrage-status sensor's docstring; no new sensor.

**Tests (D4-H, per-site):**
- `test_breaker_guard_charge_phase_trips_on_stale_net_power` (D4-H-1)
- `test_breaker_guard_attain_charging_trips_on_stale_net_power` (D4-H-2)
- `test_breaker_guard_attain_entry_trips_on_stale_net_power` (D4-H-3)
- `test_breaker_guard_streak_holds_on_alternating_stale_and_over_cap` (cross-site invariant anchor) — sequence: over-cap, stale, over-cap → streak reaches 2 → LOCK. Under pre-fix code (streak wipe on stale) the same sequence NEVER locks.
- `test_breaker_guard_streak_resets_on_genuine_under_cap` (regression) — sequence: over-cap, fresh under-cap → streak reset. Fresh-path behavior unchanged.
- **Neuter→RED per site (mutation anchors):** revert the `if snap is None:` branch to `pass` at ANY ONE of the three sites → the corresponding site test fails; the other two still pass.
- **Fresh-path byte-identity tests** (`test_breaker_guard_<site>_fresh_over_cap_unchanged`, `test_breaker_guard_<site>_fresh_under_cap_unchanged`) — existing over-cap and under-cap branches byte-identical when `snap is not None`.

**Dead helper cleanup (in-cycle):** update the stale comments at `energy_battery.py:519` and `:4829` to reference the three inline sites only. DO NOT delete the def in this cycle; deletion PR follows Live Validation.

#### Acceptance (D4)
- **Tests:** all above per-sub-deliverable.
- **Neuter→RED:** every sub-deliverable has its own reverse-mutation anchor; D4-D has THREE (pause-hold, no-new-arm, release-still-fires); D4-H has THREE per-site (plus the cross-site streak-hold anchor).
- **Live (D4-A/B):** peak-import counter freezes on next Envoy CT stall > 180s.
- **Live (D4-C):** row's `grid_import_kw`/`solar_export_kw` NULL (not 0.0) when `net_power_w is None`.
- **Live (D4-D):** during any observed `battery_power_w` stale window ≥ 180s while a bay is `_paused_by_battery_drain`, membership persists (recorder cross-tab). During any observed stale window that crosses 03:00 with an L1 plug in the set, membership CLEARS at 03:00 (release still evaluated). During any observed stale window where a bay is NOT in the set, no new arm occurs.
- **Live (D4-E):** `_cost_today`/`_import_kwh_today` ±5% vs comparable day; direction = trim.
- **Live (D4-F):** post-restart `envoy_cache` fields either fresh or stale-but-flagged.
- **Live (D4-G):** `_sustained_import_readings` observed to drain on stall; no shed escalation on trailing edge.
- **Live (D4-H):** during any observed net_power stale window while an arbitrage CHARGE chunk is running, `_arbitrage_guard_consecutive_trips` observed to INCREMENT (not reset); if the stall persists past 2 ticks the chunk locks with `_arbitrage_guard_aborted_kw = None` sentinel. Post-Live: file the follow-up PR to DELETE `_grid_import_guard_triggered` per supersession triage.

### D5 — Fold the SIX hand-rolled gates through the helper

Unchanged from Rev 4:

1. `energy_battery.py:882-910` (cloud-SOC A1) — `stamp="last_updated"`; EXPLICIT `age is None → pass (accept)` preserving v5.17.5 fail-OPEN. Anchor `test_cloud_soc_fold_preserves_fail_open_on_missing_stamp`.
2. `energy_battery.py:1136-1150` (cloud-oracle lag D2 tracker) — `stamp="last_reported"`; helper embodies the `max(0.0, …)` clamp at `:1149`.
3. `energy_pool.py:4695-4708` (EVSE per-bay solar) — `stamp="last_updated"`.
4. `energy_pool.py:4406-4413` (grid-follow INV-SF-10) — `stamp="last_reported"`.
5. `sensor.py:12491-12507` (AC-kWh display) — `stamp="last_updated"`; MEDIUM-8 corrected rationale (exception PROPAGATES today → new `stale=True` behavior is strictly BETTER). Anchor `test_ac_kwh_naive_stamp_renders_stale_true_no_exception`.
6. `hvac_override.py:3962` — NOT folded; carded.

### D6 — Pre/post row-rate snapshot

Unchanged from Rev 3 (three pinned `ssh ha sqlite3` queries).

---

### D-OBS — Operator-facing staleness surface + Lovelace tile (Rev-5 MED-D applied)

**Rev-5 MED-D corrected `_resolve_source_age` — uses SHORT names per `energy.py:986-996` key_map:**

```python
def _resolve_source_age(short_key: str) -> tuple[float | None, str]:
    """Return (age_s, status) where status in {'unconfigured','missing','fresh','stale'}.
    short_key is the SHORT name used by BatteryStrategy._get_entity — one of
    'net_power' | 'battery_power' | 'solar_production' | 'battery_soc' —
    NOT the CONF_ENERGY_*_ENTITY constant."""
    eid = energy._battery._get_entity(short_key)
    if not eid:
        return (None, "unconfigured")
    st = hass.states.get(eid)
    if st is None:
        return (None, "missing")
    age = _state_age_s(st, stamp="last_reported")
    if age is None:
        return (None, "missing")
    return (age, "fresh")   # threshold applied by caller

solar_age_s,          solar_status          = _resolve_source_age("solar_production")
net_power_age_s,      net_power_status      = _resolve_source_age("net_power")
battery_power_age_s,  battery_power_status  = _resolve_source_age("battery_power")
primary_soc_age_s,    primary_soc_status    = _resolve_source_age("battery_soc")
```

The classification loop (`stale_sources`, `unconfigured_sources`, `missing_sources`) unchanged from Rev 4. Only `stale_sources` drives the state-enum "stale" transition in D-OBS-2.

**Rev-5 MED-D regression anchor:** `test_envoy_status_short_key_resolution`. `stale_reason` attribute (Rev-4 LOW-10) preserved.

D-OBS-1 attributes: `solar_age_s`, `net_power_age_s`, `battery_power_age_s`, `primary_soc_age_s`, `stale_sources`, `unconfigured_sources`, `missing_sources`, `fallback_active`, `stale_reason`.

D-OBS-2 (`native_value`): unchanged from Rev 3 (union with existing triggers; only `stale_sources` drives the new "stale" branch).

D-OBS-3 (tile): unchanged from Rev 3 (with Rev-4 rows for `unconfigured_sources`, `stale_reason`).

#### D-OBS Acceptance

- `test_envoy_status_unconfigured_net_power_does_not_pin_stale` (HIGH-4 anchor).
- `test_envoy_status_missing_entity_reports_missing_not_stale`.
- `test_envoy_status_stale_reason_last_available_only` (LOW-10).
- `test_envoy_status_short_key_resolution` (Rev-5 MED-D anchor).
- (Rev-3 D-OBS tests preserved.)
- **Live:** attributes populated on both dashboards; `stale_sources == []` on healthy Envoy; per-source ages < each `MAX_AGE_S`.

---

## Non-goals (explicit)

- No new unconsumed staleness sensor.
- No threshold changes to any existing gate.
- No change to `envoy_available` composition.
- No flip of v5.17.5-shipped cloud-SOC fail-OPEN-on-missing-stamp decision.
- No periodic reload / probe / watchdog.
- No change to display props (`battery_power` at `:1530`; AC-kWh `native_value`).
- No unification of hand-rolled thresholds.
- No migration of non-Energy staleness sites (BLE, presence LKG, tracker-stale).
- `hvac_override.py:3962` NOT folded — carded.
- `aggregation.py:6289/6319`, `energy_write_verify.py:1794`, `energy_forecast.py:566` NOT investigated — carded.
- AC-kWh `native_value` staleness gate not added — carded.
- No parallel staleness sensor; no NM push; no `state == "degraded"` enum variant; no PWA tile change.
- **Rev-5: no deletion of `_grid_import_guard_triggered` pre-ship.** Deletion PR follows Live Validation of D4-H. Rev-5 IN-CYCLE update: stale comments at `:519` and `:4829` corrected.
- **Rev-5: no structural hoisting inside `determine_battery_drain_actions`.** The pause/release split is achieved by gating ONLY the pause-add conditions at `energy_pool.py:3797` and `:2228-2243` on `not battery_power_unknown`; release arms are already reachable under a None read because `battery_discharging` becomes False. Do not restructure the live `if`/`elif` chain.
- **Rev-5: no arming of new drain pauses under `battery_power_unknown=True`.** Existing memberships HOLD; releases evaluate; no new arm. Arming would fight the release path and risk stranding the operator's L1 EV overnight.

---

## Tier 2-DB review plan (3 framings + Live) — Rev-5

- **Review A — data integrity / read-layer correctness.** Byte-identity fresh path; helper `stamp=` + clamp; LKG stamp; verify D4-H fresh-path byte-identity at all three sites.
- **Review B — signal-chain / cross-coordinator integration + PER-CONSUMER None direction.** Trace each consumer. Single-diff gate: D4-A NOT shipped without D4-B/C/E/G/H-1/H-2/H-3 in the same commit; D4-D producer NOT shipped without D4-D-1 AND D4-D-2 AND the `battery_power_unknown` kwarg. Re-grep `_grid_import_guard_triggered` still zero callers. Confirm the pause/release split shape: pause-add conditions at `energy_pool.py:3797` and `:2228-2243` gated on `not battery_power_unknown`; release arms structurally untouched. Confirm `_arbitrage_guard_consecutive_trips = 0` appears ONLY in the genuine-under-cap branch at all three D4-H sites — mutation drill per site.
- **Review C — new surface / test authority + helper HOME correctness.** Const round-trip; tests drive production; discriminating tests actually discriminate. Verify D-OBS `_resolve_source_age` uses SHORT keys; verify `test_envoy_status_short_key_resolution` genuinely fails under a CONF_*-arg mutation. Verify `test_drain_stale_battery_power_does_not_arm_new_pause` and `test_drain_stale_battery_power_still_honors_must_start_by` both anchored on the single kwarg.
- **Review D — Live Validation, post-restart.** D6 queries pre/post. `soc_resolution.primary_age_s` 6h. During net_power stale windows, `_arbitrage_guard_consecutive_trips` INCREMENTS; on ≥2 stale/over-cap ticks, chunk locks with `_arbitrage_guard_aborted_kw = None` sentinel. During battery_power stale windows spanning 03:00 with L1 paused, release fires. `envoy_status.stale_sources`, `unconfigured_sources`, `stale_reason` populated. README `Validated <date>` table written back. Post-Live: file supersession PR to DELETE `_grid_import_guard_triggered`.

---

## Files to change

- `custom_components/universal_room_automation/domain_coordinators/energy_battery.py` — module-level `_state_age_s` (D1); `BatteryStrategy` wrappers (D1); migrate 4 SOC + 2 envelope + 3 power sites (D2/D3/D4-A/D4-D producer); fold A1 gate (D5-1) and cloud-oracle-lag D2 tracker (D5-2); **fail-CLOSED + streak-hold at three inline breaker-guard sites (D4-H-1/2/3)**; stale-comment cleanup at `:519` and `:4829`; `primary_age_s` attribute on soc_resolution.
- `custom_components/universal_room_automation/domain_coordinators/energy_pool.py` — fold 2 gates (D5-3, D5-4); **add `battery_power_unknown: bool = False` kwarg to both `determine_battery_drain_actions` variants (D4-D-0); gate ONLY the pause-add conditions at `:3797` (plug variant) and `:2228-2243` (EVSE variant) on `not battery_power_unknown`. No structural hoisting; release arms untouched (already reachable because `battery_discharging` is False under a None read).**
- `custom_components/universal_room_automation/domain_coordinators/energy.py` — D4-B fail-safe grid-cap (`:6071`); D4-C NULL persisted row (`:3129-3130`); D4-D-1/D4-D-2 pass `battery_power_unknown=(_bp is None)` at `:6161` and `:6317`; D4-F cache-save gating (`:2455`); D4-G sustained-window drain (`:7381`).
- `custom_components/universal_room_automation/domain_coordinators/energy_billing.py` — D4-E fresh-read migration for both branches in `CostTracker._get_net_power`; import `_state_age_s`.
- `custom_components/universal_room_automation/sensor.py` — fold 1 display gate (D5-5); import `_state_age_s`; expose `primary_age_s`; D-OBS extend attrs + `native_value`; `_resolve_source_age` uses SHORT keys.
- `custom_components/universal_room_automation/domain_coordinators/energy_const.py` — 4 new `DEFAULT_*_MAX_AGE_S` consts.
- `quality/tests/` — new `test_shared_power_read_staleness.py` covering D1-D5 + D-OBS (all Rev-4 + Rev-5 anchor tests).
- D-OBS tile via `ha_config_set_dashboard` (deploy-time, not build).
- `docs/readmes/README_v<next>.md` — Rev-5 Live table rows.
- **Follow-up PR (post-Live, out of this cycle's diff):** delete `_grid_import_guard_triggered` at `energy_battery.py:2635-2646`.

## Risks & mitigations

- **Test-file collision** — worktree isolation + serialised suite runs.
- **`.pyc` staleness during mutation drills** — `PYTHONDONTWRITEBYTECODE=1` + cache clear before each drill.
- **Silent threshold drift** — Review A explicit checklist.
- **Billing regression (D4-E)** — boot-time INFO summary for first 24h; Review D compares.
- **Rev-4 → Rev-5 partial-ship hazards:**
  - D4-A without D4-H-1/H-2/H-3 in same commit → 12kW breaker guard silently disarmed on any stale-net window (fail-OPEN + streak wipe compounded).
  - D4-D producer without the `battery_power_unknown` kwarg + call-site plumbing → drain guard disarmed OR (Rev-4-shape whole-call skip) EV stranded overnight when CT dies.
  Mitigation: single-diff gate (Review B); mutation-anchor tests for both split-shipping shapes.
- **Contradictory pause-direction (MEDIUM-1 preventive)** — a builder reading "fail-CLOSED for PAUSES" could arm a new pause under unknown. Mitigation: authoritative one-voice contract bullet under the `battery_power_w` table; explicit test `test_drain_stale_battery_power_does_not_arm_new_pause`; non-goal bullet forbidding new arms under unknown.
- **Restructure temptation (MEDIUM-2 preventive)** — a builder reading Rev-4-style "hoist release branches" could rewrite the live `if`/`elif` chain in Tier-3 energy code. Mitigation: explicit "no structural hoisting" non-goal; files-to-change spec names the two exact gate points (`energy_pool.py:3797` and `:2228-2243`); D4-D-0 explains why the release arms are already reachable (`battery_discharging = False` under None).
- **Dead-helper reintroduction risk.** A concurrent cycle could wire `_grid_import_guard_triggered` before D4-H ships. Mitigation: Review B re-greps at review time; stale comments corrected in-cycle.
- **Site B lone-compensator risk** — a builder assuming site C's `_breaker_guard_fail_closed_on_blind` symmetry could weaken D4-H-2. Mitigation: consumer-table row 5 and D4-H-2 spec explicitly note site B has NO upstream compensator.
- **Site A `else`-vs-fall-through risk** — a builder inserting a literal `else` at site A expecting symmetry with sites B/C could produce dead code or unreachable branches. Mitigation: D4-H-1 spec explicitly notes site A's streak-reset today is a fall-through, and the Rev-5 replacement re-shapes it into a proper `if / elif / else` chain.
- **D-OBS attribute drift** — reconciliation-through-shared-helper invariant.
- **D-OBS tile-staleness** — entities card preferred; markdown wrapper requires `entity_id:` watch-list.
- **`_arbitrage_guard_aborted_kw = None` sentinel** — dashboards / diagnostics that display this value must tolerate None; grep for consumers before build.

## Open questions for operator (not blocking build)

- `hvac_override.py:3962` (5th AC-kWh gate) — fold in follow-up or flip fail-OPEN first?
- AC-kWh `native_value` staleness gate — card, or leave?
- Sequential ~600s stale-trust horizon for primary SOC — keep or lower?
- D5 site 1: preserve v5.17.5 fail-OPEN-on-missing-stamp (planned default) or open a follow-up to flip?
- D-OBS: tile section placement per dashboard — builder picks (default) or operator preference?
- `_arbitrage_guard_aborted_kw = None` sentinel vs. distinct `aborted_cause` attribute — preference?
- Deletion PR for `_grid_import_guard_triggered` — file same day as Live Validation success, or fold into next cycle?
- Follow-up cards `AGGREGATION_NET_POWER_STALE_1` and `BATTERY_POWER_W_CONSUMERS_AUDIT_1` — schedule after this cycle or backlog?

---

## §BUILD-READY

Plan-review confirm-review 2026-09-01 = SHIP. All four Rev-4 findings genuinely resolved with no new fail-OPEN; two plan-text defects (MEDIUM-1 pause-direction wording, MEDIUM-2 unimplementable hoist instruction) fixed in-place; two minor clarifications (site A fall-through, site B lone-compensator) folded. Design unchanged from the SHIP verdict. Build may dispatch under Tier 2-DB (3 framings + Live), single-diff gate on D4-A ↔ D4-B/C/E/G/H-1/H-2/H-3 and D4-D producer ↔ D4-D-0/D4-D-1/D4-D-2 enforced by Review B.

---

## Rev 5 change summary (2026-09-01)

Applied per adversarial plan-review FIX-REQUIRED on Rev 4, plus confirm-review plan-text corrections:

1. **Rev-5 CRIT-A (D4-H patched dead code)** — grep-confirmed `_grid_import_guard_triggered` at `energy_battery.py:2635-2646` has ZERO callers. D4-H re-scoped to three LIVE inline sites at `:3150-3197`, `:4523-4547`, `:4680-4703`. Rev-5 spec: on `snap is None`, treat as "assume over-cap"; increment streak; honor `ARBITRAGE_GUARD_CONSECUTIVE_TRIPS_TO_LOCK`; lock with `_arbitrage_guard_aborted_kw = None` sentinel. Dead helper triaged per supersession rules; deletion PR follows Live Validation.
2. **Rev-5 CRIT-B (streak-wipe on stale gap)** — reset moved into the genuine-under-cap branch ONLY; stale branch INCREMENTS. Cross-site anchor `test_breaker_guard_streak_holds_on_alternating_stale_and_over_cap`.
3. **Rev-5 HIGH-C (D4-D over-scoped)** — `battery_power_unknown: bool = False` kwarg on both `determine_battery_drain_actions` variants; pause-add conditions gated on `not battery_power_unknown`; release arms unchanged (reachable because `battery_discharging = False` under None). Anti-strand tests `test_drain_stale_battery_power_still_honors_force_charge_release` and `test_drain_stale_battery_power_still_honors_must_start_by`.
4. **Rev-5 MED-D (D-OBS pseudocode wrong key)** — `_resolve_source_age` uses SHORT keys per key_map at `energy.py:986-996`; anchor `test_envoy_status_short_key_resolution`.
5. **Rev-5 MEDIUM-1 (confirm-review, wording)** — pause-direction language unified across consumer-table row 1, D4-D-0 spec, and non-goals: **HOLD existing pauses; do NOT arm new ones under unknown**. Explicit "arming on a blind CT would fight the release path and risk stranding" rationale on the invariant, the consumer table's one-voice contract bullet, and the non-goals. New anchor test `test_drain_stale_battery_power_does_not_arm_new_pause` discriminates HOLD-only from fail-CLOSED-arm.
6. **Rev-5 MEDIUM-2 (confirm-review, implementability)** — struck the "hoist release branches before any `battery_discharging` check" instruction; replaced with the surgical "gate ONLY the pause-add conditions at `energy_pool.py:3797` and `:2228-2243` on `not battery_power_unknown`" instruction. D4-D-0 explains why the release arms are already reachable under a None read (`battery_discharging = False` via `battery_ok = not battery_discharging` at `:3815`). Files-to-change spec names both gate points.
7. **Rev-5 clarification #1 (confirm-review)** — D4-H-1 spec notes site A's streak-reset at `:3196` is reached by FALL-THROUGH (both inner branches return), not a literal `else`; the replacement re-shapes into an explicit `if / elif / else`. Do NOT insert a literal `else` expecting symmetry with sites B/C.
8. **Rev-5 clarification #2 (confirm-review)** — D4-H-2 spec notes site B has **NO upstream `_breaker_guard_fail_closed_on_blind` compensator** (unlike site C, whose compensator is at `:4676`). D4-H-2 is the SOLE local-stale compensator at site B; do not assume symmetry with site C's belt-and-suspenders posture.
9. **LOW-5 line drift corrected throughout** (Rev 5): `_effective_import_kw` def `:2600`; `_grid_import_guard_triggered` `:2635-2646` (dead); `_breaker_guard_fail_closed_on_blind` `:3365`; EVSE drain call site `:6161`; streak-reset lines confirmed `:3196` (fall-through), `:4547` (`else`), `:4703` (`else`); force-charge releases confirmed `:2147-2150` and `:3723-3726`; `must_start_by_min` L1 release confirmed `:6329-6331`; plug variant pause-add condition `:3797`, EVSE variant `:2228-2243`; `battery_ok = not battery_discharging` at `:3815`.

Rev-4 verified CLEAR carried forward without change: CRITICAL-1 consumer coverage for `battery_power_w`; HIGH-3 cloud-SOC preserve-accept; HIGH-4 unconfigured/missing split (MED-D fixes the pseudocode key); MED-5 class names + no import cycle; MED-6 6th gate + `max(0.0, …)` clamp; D4-G load-shed sustained-window drain; net_power consumer enumeration otherwise complete (CRIT-B adds streak-wipe row); envoy_status display-only ruling.

Invariant re-verification with the Rev-5 clauses (pause-set membership as separate axis, streak counter as separate axis, HOLD-not-arm on blind CT, do-not-restructure release arms): the discriminating anchors (`test_drain_over_scoped_skip_regresses_release`, `test_drain_stale_battery_power_does_not_arm_new_pause`, `test_breaker_guard_streak_holds_on_alternating_stale_and_over_cap`) all FAIL the Rev-4-shape build and PASS the Rev-5 build. Invariant holds.

---

## Rev 4 change summary (retained, 2026-09-01)

(Rev-4 summary preserved verbatim — CRITICAL-1 paired drain call-site changes at `energy.py:6161`/`:6317`; CRITICAL-2 initial net_power consumer enumeration + D4-G load-shed drain; HIGH-3 D5 site 1 explicit accept mapping; HIGH-4 `_resolve_source_age` split (Rev-5 MED-D fixes the pseudocode key); MED-5 class names; MED-6 6th gate + clamp in helper; MED-7 D4-F save_envoy_cache gating; MED-8 sensor.py:12494 rationale corrected; LOW-9 discriminator; LOW-10 stale_reason. Rev-5 supersedes Rev-4 D4-D shape, D4-H target, and D-OBS pseudocode key.)

---

## Rev 3 addition summary (retained)

(D-OBS added as ADDITIVE deliverable; extends existing `envoy_status` sensor; Lovelace tile on `ura-v8` + `ura-v6`; NO parallel sensor, NO NM push, NO PWA tile change. Rev-4 HIGH-4 corrected the classification; Rev-5 MED-D corrects the pseudocode's `_get_entity` key form.)

---

## Rev 2 fix summary (retained)

(`stamp=` arg + `last_reported` fallback; D3-B; D2 4-site expansion; D4-B/C/E; LKG stamp arithmetic; 5th AC-kWh gate scope-carded; D5 sensor.py byte-identity claim corrected; D6 pinned queries. Rev-4 supersedes MED-5, MED-6, MED-8; Rev-5 supersedes D4-D shape, D4-H target, D-OBS pseudocode. Other Rev-2 fixes stand.)
